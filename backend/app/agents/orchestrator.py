"""Orchestrator placeholder. Phase 1 always routes to the single Task Agent."""

from sqlalchemy.orm import Session

from app.agents.task_agent import run_task_agent


def dispatch(db: Session, run_id: int) -> None:
    run_task_agent(db, run_id)
