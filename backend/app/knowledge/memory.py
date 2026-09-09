"""Cross-run Memory: distill lessons from finished runs, recall them for new tickets.

Distillation is rule-based (section extraction from the run report) so it works
without an extra LLM call; recall is keyword-overlap scoring plus recency —
good enough at single-project scale, swappable for RAG later.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AgentMemory, AgentRun, Ticket

LESSON_MAX_CHARS = 1200
_LESSON_SECTION_HINTS = ("root cause", "根因", "修改内容", "修复方案", "测试结果")


def _distill(report_md: str) -> str:
    """Keep the Root Cause / fix / test sections of a report; fall back to its head."""
    if not report_md:
        return ""
    lines = report_md.splitlines()
    kept: list[str] = []
    keeping = False
    for line in lines:
        is_header = line.lstrip().startswith("#")
        if is_header:
            keeping = any(h in line.lower() for h in _LESSON_SECTION_HINTS)
        if keeping:
            kept.append(line)
    lesson = "\n".join(kept).strip()
    if not lesson:
        lesson = report_md.strip()
    if len(lesson) > LESSON_MAX_CHARS:
        lesson = lesson[:LESSON_MAX_CHARS] + "\n…(截断)"
    return lesson


def save_memory(db: Session, ticket: Ticket, run: AgentRun) -> AgentMemory | None:
    """Distill a finished run's report into a memory row. Returns None if nothing to keep."""
    lesson = _distill(run.report_md or "")
    if not lesson:
        return None
    memory = AgentMemory(
        project_id=ticket.project_id,
        ticket_code=ticket.code,
        title=ticket.title,
        lesson_md=f"## {ticket.code}: {ticket.title}\n\n{lesson}",
    )
    db.add(memory)
    db.commit()
    return memory


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z一-鿿]{2,}", text.lower())}


def recall_memories(db: Session, ticket: Ticket, limit: int | None = None) -> list[AgentMemory]:
    """Most relevant past lessons for this ticket: keyword overlap first, then recency."""
    limit = limit or settings.memory_inject_limit
    rows = (
        db.query(AgentMemory)
        .filter(AgentMemory.project_id == ticket.project_id)
        .order_by(AgentMemory.id.desc())
        .all()
    )
    wanted = _keywords(f"{ticket.title} {ticket.description[:300]}")
    def score(row: AgentMemory) -> int:
        return len(wanted & _keywords(f"{row.ticket_code} {row.title} {row.lesson_md}"))
    scored = sorted(rows, key=lambda r: (score(r), r.id), reverse=True)
    relevant = [r for r in scored if score(r) > 0]
    return (relevant or scored)[:limit]


def memory_context(db: Session, ticket: Ticket) -> str:
    """Format recalled lessons for injection into the agent's user message."""
    if not settings.memory_enabled:
        return ""
    memories = recall_memories(db, ticket)
    if not memories:
        return ""
    lines = ["以下是本项目历史工单的处理经验（供参考，仍需验证是否适用于当前问题）："]
    for m in memories:
        snippet = m.lesson_md.strip()[:600]
        lines.append(f"- [经验 {m.ticket_code}]\n  {snippet}")
    return "\n".join(lines)
