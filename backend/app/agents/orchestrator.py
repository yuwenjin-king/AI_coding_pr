"""Orchestrator: run lifecycle and mode routing.

Phase <=3: every run is analysis-only, straight to Task Agent.
Phase >=4: BUG tickets run in coding mode inside an isolated git worktree;
after the agent loop the system commits, runs tests, captures the diff and
moves the run to needs_review for Human-in-the-loop approve/reject.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.agents.requirement_agent import requirement_markdown, run_requirement_agent
from app.agents.review_agent import review_markdown, run_review_agent
from app.agents.task_agent import run_task_agent
from app.config import settings
from app.knowledge.memory import save_memory
from app.models import AgentRun, Ticket
from app.runtime import RunStatus
from app.runtime.guardrail import diff_change_lines
from app.runtime.workspace import Workspace, WorkspaceError, set_current_shopai_path

logger = logging.getLogger(__name__)


def _coding_mode(ticket: Ticket) -> bool:
    return settings.agent_phase >= 4 and ticket.type == "BUG"


def _multi_agent() -> bool:
    return settings.agent_phase >= 5


def dispatch(db: Session, run_id: int) -> None:
    run = db.get(AgentRun, run_id)
    if not run:
        return
    ticket = db.get(Ticket, run.ticket_id)
    if not ticket:
        run.status = RunStatus.failed.value
        run.error = "ticket not found"
        db.commit()
        return

    if _coding_mode(ticket):
        _run_coding(db, run, ticket)
    elif _multi_agent() and ticket.type == "REQ":
        _run_coding(db, run, ticket)
    else:
        run_task_agent(db, run_id)


def _append_trace(db: Session, run: AgentRun, trace_json: str | None, event: dict) -> str:
    import json as _json

    trace = _json.loads(trace_json) if trace_json else []
    trace.append(event)
    trace_json = _json.dumps(trace, ensure_ascii=False)
    run.trace_json = trace_json
    db.commit()
    return trace_json


def _run_coding(db: Session, run: AgentRun, ticket: Ticket) -> None:
    ws = Workspace(run.id, ticket.code)
    try:
        shopai = ws.create()
    except WorkspaceError as exc:
        run.status = RunStatus.failed.value
        run.error = f"workspace setup failed: {exc}"
        db.commit()
        return

    run.branch = ws.branch
    run.workspace = str(ws.path)
    db.commit()

    # Requirement Agent (Phase 5, REQ tickets): structured acceptance criteria
    extra_context = None
    if _multi_agent() and ticket.type == "REQ":
        req = run_requirement_agent(db, run, ticket)
        if req:
            extra_context = requirement_markdown(req)
            _append_trace(
                db, run, run.trace_json,
                {"step": 0, "type": "agent", "name": "requirement", "output": extra_context[:2000]},
            )
            run.report_md = extra_context
            db.commit()

    set_current_shopai_path(shopai)
    try:
        run_task_agent(db, run.id, mode="coding", extra_context=extra_context)
        db.refresh(run)
        if run.status != RunStatus.succeeded.value:
            ws.remove()
            run.workspace = None
            db.commit()
            return
        if extra_context and run.report_md:
            # keep the Requirement Agent section on top of the coding report
            run.report_md = extra_context + "\n\n---\n\n" + run.report_md
            db.commit()
        if not _finalize_coding_run(db, run, ws, ticket):
            return
        if _multi_agent():
            _review_stage(db, run, ws, ticket)
    finally:
        set_current_shopai_path(None)


def _finalize_coding_run(db: Session, run: AgentRun, ws: Workspace, ticket: Ticket) -> bool:
    """Commit the agent's changes, verify tests, capture diff. False = run already failed.

    An empty commit is fine on rework rounds (agent may only have re-verified);
    what matters is the cumulative diff against the base commit.
    """
    db.refresh(run)
    ws.commit_all(f"agent: fix {ticket.code} ({ticket.title})")
    diff = ws.diff()

    from app.tools import registry

    test = registry.call("run_test", {})
    run.test_summary = test.output[-4000:]
    run.diff_md = diff[:200_000]

    if not diff.strip():
        run.status = RunStatus.failed.value
        run.error = "agent made no changes in the workspace"
        ws.remove()
        run.workspace = None
        db.commit()
        return False

    changed_lines = diff_change_lines(diff)
    if changed_lines > settings.agent_max_diff_lines:
        run.status = RunStatus.failed.value
        run.error = (
            f"guardrail: diff {changed_lines} 行超过上限 {settings.agent_max_diff_lines}，"
            "疑似大范围重写；工作区已丢弃，请缩小修改范围后重试"
        )
        ws.remove()
        run.workspace = None
        db.commit()
        return False

    if not test.ok:
        run.status = RunStatus.failed.value
        run.error = f"tests still failing after fix:\n{test.output[-2000:]}"
        ws.remove()
        run.workspace = None
        db.commit()
        return False

    run.status = RunStatus.needs_review.value
    db.commit()
    return True


def _review_stage(db: Session, run: AgentRun, ws: Workspace, ticket: Ticket) -> None:
    """Review Agent over diff+tests; request_changes drives exactly one rework round."""
    review = run_review_agent(
        ticket_code=ticket.code,
        ticket_title=ticket.title,
        ticket_description=ticket.description,
        diff=run.diff_md or "",
        test_output=run.test_summary or "",
    )
    _append_trace(
        db, run, run.trace_json,
        {"step": 0, "type": "agent", "name": "review", "output": review_markdown(review)[:2000]},
    )
    run.report_md = (run.report_md or "") + "\n\n" + review_markdown(review)
    db.commit()

    if review.get("verdict") != "request_changes":
        return

    # Rework round: feed review comments back to the coding agent, then re-verify.
    feedback = "## Review Agent 返工意见（请逐条处理）\n" + review_markdown(review)
    prev_report = run.report_md or ""
    set_current_shopai_path(ws.shopai_path)
    try:
        run_task_agent(db, run.id, mode="coding", extra_context=feedback)
        db.refresh(run)
        if run.status != RunStatus.succeeded.value:
            return  # keep failure state; workspace left for inspection
        if not _finalize_coding_run(db, run, ws, ticket):
            return
    finally:
        set_current_shopai_path(None)
    run.report_md = prev_report + "\n\n---\n### 返工后\n" + (run.report_md or "")
    db.commit()



def approve_run(db: Session, run: AgentRun) -> tuple[bool, str]:
    """HITL approve: merge the agent branch back, then clean up the worktree."""
    if run.status != RunStatus.needs_review.value:
        return False, f"run is {run.status}, not needs_review"
    ticket = db.get(Ticket, run.ticket_id)
    ws = Workspace(run.id, ticket.code) if ticket else None
    if ws is None:
        return False, "ticket not found"
    try:
        ws.merge_into_main()
    except WorkspaceError as exc:
        return False, str(exc)
    ws.remove()
    run.status = RunStatus.succeeded.value
    if ticket:
        ticket.status = "resolved"
        save_memory(db, ticket, run)  # human-validated fix becomes reusable experience
    run.workspace = None
    db.commit()
    return True, f"merged {run.branch} into main"


def reject_run(db: Session, run: AgentRun) -> tuple[bool, str]:
    """HITL reject: discard the worktree and branch, close the run as cancelled."""
    if run.status != RunStatus.needs_review.value:
        return False, f"run is {run.status}, not needs_review"
    ticket = db.get(Ticket, run.ticket_id)
    if ticket:
        Workspace(run.id, ticket.code).remove()
    run.status = RunStatus.cancelled.value
    if ticket:
        ticket.status = "open"
    run.workspace = None
    db.commit()
    return True, f"discarded {run.branch}"
