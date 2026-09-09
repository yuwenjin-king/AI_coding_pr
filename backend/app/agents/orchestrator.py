"""Orchestrator: run lifecycle and mode routing.

Phase <=3: every run is analysis-only, straight to Task Agent.
Phase >=4: BUG tickets run in coding mode inside an isolated git worktree;
after the agent loop the system commits, runs tests, captures the diff and
moves the run to needs_review for Human-in-the-loop approve/reject.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.agents.task_agent import run_task_agent
from app.config import settings
from app.models import AgentRun, Ticket
from app.runtime import RunStatus
from app.runtime.workspace import Workspace, WorkspaceError, set_current_shopai_path

logger = logging.getLogger(__name__)


def _coding_mode(ticket: Ticket) -> bool:
    return settings.agent_phase >= 4 and ticket.type == "BUG"


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
    else:
        run_task_agent(db, run_id)


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

    set_current_shopai_path(shopai)
    try:
        run_task_agent(db, run.id, mode="coding")
        db.refresh(run)
        if run.status != RunStatus.succeeded.value:
            ws.remove()
            run.workspace = None
            db.commit()
            return
        _finalize_coding_run(db, run, ws, ticket)
    finally:
        set_current_shopai_path(None)


def _finalize_coding_run(db: Session, run: AgentRun, ws: Workspace, ticket: Ticket) -> None:
    """Commit the agent's changes, verify tests, capture diff, hand over to HITL."""
    db.refresh(run)
    committed = ws.commit_all(f"agent: fix {ticket.code} ({ticket.title})")
    diff = ws.diff()

    from app.tools import registry

    test = registry.call("run_test", {})
    run.test_summary = test.output[-4000:]
    run.diff_md = diff[:200_000]

    if not committed or not diff.strip():
        run.status = RunStatus.failed.value
        run.error = "agent made no changes in the workspace"
        ws.remove()
        run.workspace = None
        db.commit()
        return

    if not test.ok:
        run.status = RunStatus.failed.value
        run.error = f"tests still failing after fix:\n{test.output[-2000:]}"
        ws.remove()
        run.workspace = None
        db.commit()
        return

    run.status = RunStatus.needs_review.value
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
