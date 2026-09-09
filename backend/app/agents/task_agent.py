from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.knowledge.memory import memory_context, save_memory
from app.llm import gateway
from app.models import AgentRun, Ticket
from app.runtime import RunStatus
from app.runtime.agent_loop import run_agent_loop
from app.runtime.stats import apply_event, stats_from_trace
from app.tools import registry


DEFAULT_PLAN = [
    "理解工单与复现条件",
    "检索知识库与历史工单（RAG）",
    "列出 ShopAI 仓库结构",
    "搜索订单状态机与支付回调",
    "阅读关键文件",
    "查看 git 历史与当前测试状态（run_test）",
    "给出根因与修复建议（不改代码）",
]

SYSTEM_PROMPT = """你是 CodePilot Task Agent，处理软件研发工单。
规则：
1. 只分析 playground/shopai 代码，使用只读与观测工具：
   list_dir / read_file / search_code（读代码）
   git_status / git_diff / git_log（版本历史）
   run_test（执行靶场测试，验证当前测试状态）
   search_document / search_ticket（知识库与历史工单检索）
2. 不要尝试 write_file、git_commit、deploy_service 等写操作。
3. 先探索再下结论，至少阅读订单与支付相关源码；下结论前用 run_test 验证现有测试的表现（注意 xfail 标记的用例）。
4. 历史工单或知识库经验与当前问题相关时，在报告中引用其编号（如 BUG-387）。
5. 最终用中文 Markdown 输出，必须包含：
   - 问题理解
   - Root Cause（具体到文件与逻辑）
   - 建议修改的文件
   - 修复方案（步骤）
   - 建议补充的测试
   - AI Confidence（0-100 的整数）
不要编造没有读到的代码。
"""


def _knowledge_context(ticket: Ticket) -> str:
    """Auto-inject top RAG hits for the ticket; empty string when RAG is off/unavailable."""
    if settings.agent_phase < 3 or not settings.rag_auto_inject:
        return ""
    from app.knowledge.rag import get_rag

    query = f"{ticket.title}\n{ticket.description[:500]}"
    hits = get_rag().retrieve(query, top_k=3)
    if not hits:
        return ""
    lines = ["以下是与本工单可能相关的知识库/历史工单检索结果（供参考，仍需自行验证）："]
    for hit in hits:
        snippet = (hit.get("text") or "").strip()[:600]
        lines.append(f"- [{hit.get('ref')}] {hit.get('title')} (score={hit.get('score'):.2f})\n  {snippet}")
    return "\n".join(lines)


CODING_PLAN = [
    "理解工单与复现条件",
    "检索知识库与历史工单（RAG）",
    "定位根因（读代码 + git 历史 + 现有测试）",
    "在隔离工作区修复代码（write_file）",
    "移除已修复 bug 的 xfail 标记并补充回归测试",
    "run_test 反复验证直到全绿",
    "输出修复报告，等待人工审批",
]

CODING_SYSTEM_PROMPT = """你是 CodePilot Coding Agent，在隔离的 git worktree 工作区中修复工单。
规则：
1. 工作区就是当前仓库（普通相对路径读写），所有修改只会进入 agent 分支，审批通过前不影响主分支。
2. 可用工具：list_dir / read_file / search_code / git_status / git_diff / git_log / run_test /
   search_document / search_ticket / write_file。
3. 修复流程：
   a. 先定位根因（读代码、查历史、跑 run_test 确认现状，注意 xfail 标记的用例）；
   b. 用 write_file 修复缺陷代码——做最小、正确的修改，保持既有代码风格；
   c. 若测试因对应 bug 已修复而标记 xfail，请移除该标记使其真正执行；
   d. 为修复的 bug 补充至少一个回归测试用例；
   e. run_test 直到全部通过；失败就分析输出、继续修改（自主迭代，不要放弃）；
   f. 不要动与工单无关的文件。
4. 最终用中文 Markdown 输出，必须包含：
   - Root Cause（具体到文件与逻辑）
   - 修改内容（每个文件改了什么、为什么）
   - 测试结果（引用 run_test 的最终输出摘要）
   - AI Confidence（0-100 的整数）
不要编造没有读到的代码和没有执行过的测试结果。
"""


def run_task_agent(db: Session, run_id: int, *, mode: str = "analysis", extra_context: str | None = None) -> None:
    run = db.get(AgentRun, run_id)
    if not run:
        return
    ticket = db.get(Ticket, run.ticket_id)
    if not ticket:
        run.status = RunStatus.failed.value
        run.error = "ticket not found"
        db.commit()
        return

    run.status = RunStatus.running.value
    run.mode = mode
    plan = CODING_PLAN if mode == "coding" else DEFAULT_PLAN
    system_prompt = CODING_SYSTEM_PROMPT if mode == "coding" else SYSTEM_PROMPT
    max_steps = settings.agent_max_steps + 12 if mode == "coding" else settings.agent_max_steps
    run.plan_json = json.dumps(plan, ensure_ascii=False)
    trace: list[dict[str, Any]] = []
    if run.trace_json:  # multi-agent stages / rework rounds append, never clobber
        try:
            trace = json.loads(run.trace_json)
        except json.JSONDecodeError:
            trace = []
    stats = stats_from_trace(trace)
    db.commit()

    def persist(event: dict[str, Any]) -> None:
        trace.append(event)
        apply_event(stats, event)
        run.trace_json = json.dumps(trace, ensure_ascii=False)
        run.stats_json = json.dumps(stats)
        db.commit()

    user = (
        f"工单 {ticket.code} ({ticket.type})\n"
        f"标题: {ticket.title}\n\n"
        f"{ticket.description}\n\n"
        f"目标仓库: {settings.shopai_path}\n"
    )
    knowledge = _knowledge_context(ticket)
    if knowledge:
        user += f"\n{knowledge}\n"
    memories = memory_context(db, ticket)
    if memories:
        user += f"\n{memories}\n"
    if extra_context:
        user += f"\n{extra_context}\n"
    if mode == "coding":
        user += "\n请在隔离工作区完成修复并让测试全绿。"
    else:
        user += "\n请调查并给出方案，不要修改文件。"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]
    tools = registry.schemas_for_phase(phase=settings.agent_phase)

    try:
        report = run_agent_loop(
            messages=messages,
            tools=tools,
            max_steps=max_steps,
            on_event=persist,
        )
        run.report_md = report
        run.status = RunStatus.succeeded.value
        db.commit()
        if mode == "analysis":
            save_memory(db, ticket, run)  # coding runs save on HITL approve instead
    except Exception as exc:  # noqa: BLE001 — persist agent failure
        run.status = RunStatus.failed.value
        run.error = str(exc)
        db.commit()
    finally:
        run.trace_json = json.dumps(trace, ensure_ascii=False)
        db.commit()
