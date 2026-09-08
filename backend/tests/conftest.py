"""Shared fixtures: in-memory sqlite so tests never touch MySQL."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register tables on Base
from app.database import Base


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def project_and_ticket(db_session):
    from app.models import Project, Ticket

    project = Project(name="ShopAI-test", repo_path="/tmp/shopai-test")
    db_session.add(project)
    db_session.flush()
    ticket = Ticket(
        project_id=project.id,
        code="T-001",
        type="BUG",
        title="test ticket",
        description="测试工单",
        status="open",
    )
    db_session.add(ticket)
    db_session.commit()
    return ticket
