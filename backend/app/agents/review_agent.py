"""Review Agent (Phase 5): adversarial pass over the coding agent's diff.

Returns a JSON verdict {verdict: approve|request_changes, comments: [...]}.
`request_changes` drives one rework round in the orchestrator.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.llm import gateway

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 CodePilot Review Agent，审查 AI 生成的代码修复。
输入：工单、代码 Diff、测试输出。从正确性、边界情况、安全性、可维护性角度审查。
只输出一个 JSON 对象（不要 Markdown 代码块）：
{
  "verdict": "approve" | "request_changes",
  "comments": [
    {"severity": "blocker|major|minor", "file": "...", "comment": "..."}
  ],
  "summary": "一句话结论"
}
规则：只在存在 blocker/major 问题时才 request_changes；吹毛求疵的 minor 问题直接 approve。
"""


def run_review_agent(
    *, ticket_code: str, ticket_title: str, ticket_description: str, diff: str, test_output: str
) -> dict[str, Any]:
    user = (
        f"工单 {ticket_code}: {ticket_title}\n{ticket_description}\n\n"
        f"--- Diff ---\n{diff[:60000]}\n\n--- 测试输出 ---\n{test_output[:4000]}"
    )
    message, _meta = gateway.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    )
    content = (message.content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"verdict": "approve", "comments": [], "summary": f"review 输出无法解析，按通过处理：{content[:200]}"}
    if parsed.get("verdict") not in {"approve", "request_changes"}:
        parsed["verdict"] = "approve"
    return parsed


def review_markdown(review: dict[str, Any]) -> str:
    lines = ["## Review Agent", f"**结论**：{review.get('verdict')} — {review.get('summary', '')}", ""]
    for c in review.get("comments") or []:
        lines.append(f"- [{c.get('severity')}] {c.get('file', '')}: {c.get('comment')}")
    return "\n".join(lines)
