from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.agents.orchestrator import dispatch
from app.config import settings
from app.database import SessionLocal, get_db
from app.models import AgentRun, Project, Ticket
from app.runtime import RunStatus
from app.schemas import AgentRunOut, HitlDecision, TicketCreate, TicketDetail, TicketOut

router = APIRouter()

_TERMINAL_STATUSES = {
    RunStatus.succeeded.value,
    RunStatus.failed.value,
    RunStatus.cancelled.value,
}


def _run_in_thread(run_id: int) -> None:
    db = SessionLocal()
    try:
        dispatch(db, run_id)
    finally:
        db.close()


@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(db: Session = Depends(get_db)):
    return db.query(Ticket).order_by(Ticket.id.desc()).all()


@router.post("/tickets", response_model=TicketOut)
def create_ticket(body: TicketCreate, db: Session = Depends(get_db)):
    project_id = body.project_id
    if project_id is None:
        project = db.query(Project).first()
        if not project:
            raise HTTPException(400, "no project")
        project_id = project.id
    ticket = Ticket(
        project_id=project_id,
        code=body.code,
        type=body.type,
        title=body.title,
        description=body.description,
        status="open",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = (
        db.query(Ticket)
        .options(joinedload(Ticket.runs))
        .filter(Ticket.id == ticket_id)
        .one_or_none()
    )
    if not ticket:
        raise HTTPException(404, "ticket not found")
    return ticket


@router.post("/tickets/{ticket_id}/runs", response_model=AgentRunOut)
def start_run(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "ticket not found")
    run = AgentRun(ticket_id=ticket.id, status=RunStatus.queued.value)
    db.add(run)
    db.commit()
    db.refresh(run)
    threading.Thread(target=_run_in_thread, args=(run.id,), daemon=True).start()
    return run


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


def _stream_session() -> Session:
    """Session factory for the SSE poller; separate so tests can swap it out."""
    return SessionLocal()


@router.get("/runs/{run_id}/events")
async def run_events(run_id: int):
    """Server-sent events: push the run snapshot whenever it changes, close on terminal status."""

    async def gen():
        last_sig: str | None = None
        while True:
            db = _stream_session()
            try:
                run = db.get(AgentRun, run_id)
                if not run:
                    yield 'event: error\ndata: {"message": "run not found"}\n\n'
                    return
                sig = (
                    f"{run.status}|{len(run.trace_json or '')}|{run.report_md or ''}"
                    f"|{run.error or ''}|{len(run.diff_md or '')}"
                )
                if sig != last_sig:
                    last_sig = sig
                    yield f"data: {AgentRunOut.model_validate(run).model_dump_json()}\n\n"
                if run.status in _TERMINAL_STATUSES:
                    yield "event: done\ndata: {}\n\n"
                    return
            finally:
                db.close()
            await asyncio.sleep(settings.sse_poll_seconds)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/hitl", response_model=AgentRunOut)
def hitl_decide(run_id: int, body: HitlDecision, db: Session = Depends(get_db)):
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    if body.decision not in {"approve", "reject"}:
        raise HTTPException(400, "decision must be approve or reject")

    if run.status == RunStatus.needs_review.value:
        from app.agents.orchestrator import approve_run, reject_run

        action = approve_run if body.decision == "approve" else reject_run
        ok, message = action(db, run)
        if not ok:
            raise HTTPException(409, message)
    else:
        note = f"HITL {body.decision}: {body.comment or ''}".strip()
        run.report_md = (run.report_md or "") + f"\n\n---\n{note}\n"
        db.commit()

    db.refresh(run)
    return run
