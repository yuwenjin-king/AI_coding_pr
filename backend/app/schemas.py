from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    code: str
    type: str = "BUG"
    title: str
    description: str
    project_id: int | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    code: str
    type: str
    title: str
    description: str
    status: str
    created_at: datetime


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    status: str
    mode: str = "analysis"
    plan_json: str | None = None
    report_md: str | None = None
    trace_json: str | None = None
    branch: str | None = None
    workspace: str | None = None
    diff_md: str | None = None
    test_summary: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class TicketDetail(TicketOut):
    runs: list[AgentRunOut] = Field(default_factory=list)


class HitlDecision(BaseModel):
    decision: str  # approve | reject
    comment: str | None = None
