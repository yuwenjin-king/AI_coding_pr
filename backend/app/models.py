from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Long agent traces overflow MySQL TEXT (65KB) on real multi-agent runs;
# MEDIUMTEXT (16MB) on MySQL, plain TEXT elsewhere (sqlite has no limit).
LongText = Text().with_variant(MEDIUMTEXT(), "mysql")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    repo_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="project")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(32))  # BUG | REQ
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="tickets")
    runs: Mapped[list["AgentRun"]] = relationship(back_populates="ticket")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    mode: Mapped[str] = mapped_column(String(16), default="analysis")
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_md: Mapped[str | None] = mapped_column(LongText, nullable=True)
    trace_json: Mapped[str | None] = mapped_column(LongText, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workspace: Mapped[str | None] = mapped_column(String(512), nullable=True)
    diff_md: Mapped[str | None] = mapped_column(LongText, nullable=True)
    test_summary: Mapped[str | None] = mapped_column(LongText, nullable=True)
    stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="runs")


class AgentMemory(Base):
    """Cross-run experience distilled from finished runs (Phase 6 Memory)."""

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    ticket_code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    lesson_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
