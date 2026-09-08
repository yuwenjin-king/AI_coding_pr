from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.llm import gateway
from app.models import AgentRun, Ticket
from app.runtime import RunStatus
from app.runtime.agent_loop import run_agent_loop
from app.tools import registry


DEFAULT_PLAN = [
    "理解工单与复现条件",
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
2. 不要尝试 write_file、git_commit、deploy_service 等写操作。
3. 先探索再下结论，至少阅读订单与支付相关源码；下结论前用 run_test 验证现有测试的表现（注意 xfail 标记的用例）。
4. 最终用中文 Markdown 输出，必须包含：
   - 问题理解
   - Root Cause（具体到文件与逻辑）
   - 建议修改的文件
   - 修复方案（步骤）
   - 建议补充的测试
   - AI Confidence（0-100 的整数）
不要编造没有读到的代码。
"""


def run_task_agent(db: Session, run_id: int) -> None:
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
    run.plan_json = json.dumps(DEFAULT_PLAN, ensure_ascii=False)
    trace: list[dict[str, Any]] = []
    db.commit()

    def persist(event: dict[str, Any]) -> None:
        trace.append(event)
        run.trace_json = json.dumps(trace, ensure_ascii=False)
        db.commit()

    user = (
        f"工单 {ticket.code} ({ticket.type})\n"
        f"标题: {ticket.title}\n\n"
        f"{ticket.description}\n\n"
        f"目标仓库: {settings.shopai_path}\n"
        "请调查并给出方案，不要修改文件。"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    tools = registry.schemas_for_phase(phase=settings.agent_phase)

    try:
        report = run_agent_loop(
            messages=messages,
            tools=tools,
            max_steps=settings.agent_max_steps,
            on_event=persist,
        )
        run.report_md = report
        run.status = RunStatus.succeeded.value
        db.commit()
    except Exception as exc:  # noqa: BLE001 — persist agent failure
        run.status = RunStatus.failed.value
        run.error = str(exc)
        db.commit()
    finally:
        run.trace_json = json.dumps(trace, ensure_ascii=False)
        db.commit()
