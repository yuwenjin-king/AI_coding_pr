"""Requirement Agent (Phase 5): turn a ticket into structured acceptance criteria.

Single LLM call with a JSON contract — no tools needed. Output feeds the
Coding Agent prompt and is appended to the run report.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.llm import gateway
from app.models import AgentRun, Ticket

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 CodePilot Requirement Agent。把工单拆解为结构化需求。
只输出一个 JSON 对象（不要 Markdown 代码块），字段：
{
  "understanding": "需求理解（1-3 句）",
  "acceptance_criteria": ["可验证的验收标准", ...],
  "modules": ["涉及的模块/文件", ...],
  "risks": ["风险与边界情况", ...],
  "test_plan": ["需要补充的测试", ...]
}
"""


def run_requirement_agent(db: Session, run: AgentRun, ticket: Ticket) -> dict[str, Any] | None:
    """Returns the parsed requirement dict (best effort; None on failure)."""
    user = (
        f"工单 {ticket.code} ({ticket.type})\n标题: {ticket.title}\n\n{ticket.description}\n\n"
        f"仓库结构参考: playground/shopai（app/order_service.py 订单状态机、"
        f"app/payment_consumer.py 支付消费、tests/）"
    )
    try:
        message, _meta = gateway.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        )
    except Exception as exc:  # noqa: BLE001 — requirement stage is best-effort
        logger.warning("requirement agent failed: %s", exc)
        return None

    content = (message.content or "").strip()
    # tolerate ```json fences``` from the model
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("requirement agent returned non-JSON, keeping raw text")
        return {"understanding": content, "acceptance_criteria": [], "modules": [], "risks": [], "test_plan": []}
    return parsed


def requirement_markdown(req: dict[str, Any]) -> str:
    lines = ["## Requirement Agent 产出", f"**需求理解**：{req.get('understanding', '')}", ""]
    for key, title in [
        ("acceptance_criteria", "验收标准"),
        ("modules", "涉及模块"),
        ("risks", "风险"),
        ("test_plan", "测试计划"),
    ]:
        items = req.get(key) or []
        if items:
            lines.append(f"**{title}**：")
            lines.extend(f"- {i}" for i in items)
            lines.append("")
    return "\n".join(lines)
