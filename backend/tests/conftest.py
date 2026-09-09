"""Shared fixtures: in-memory sqlite so tests never touch MySQL."""

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register tables on Base
from app.database import Base

REAL_SHOPAI = Path(__file__).resolve().parents[2] / "playground" / "shopai"


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


def _run_git(cmd, cwd):
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture()
def tmp_repo(tmp_path, monkeypatch):
    """A throwaway git repo mirroring playground/shopai, isolated from the user's repo."""
    repo = tmp_path / "project"
    shopai = repo / "playground" / "shopai"
    shopai.mkdir(parents=True)
    for src in REAL_SHOPAI.rglob("*"):
        if not src.is_file():
            continue
        if any(part in {".pytest_cache", "__pycache__"} or part.startswith(".") for part in src.parts):
            continue
        dst = shopai / src.relative_to(REAL_SHOPAI)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"))
    _run_git(["git", "init", "-b", "main"], repo)
    _run_git(["git", "add", "-A"], repo)
    _run_git(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"], repo)
    _run_git(["git", "config", "user.email", "t@t"], repo)
    _run_git(["git", "config", "user.name", "t"], repo)

    monkeypatch.setattr("app.config.settings.shopai_root", str(shopai))
    monkeypatch.setattr("app.config.settings.agent_workspace_root", str(tmp_path / "ws"))
    yield repo
    subprocess.run(["git", "worktree", "prune"], cwd=str(repo), capture_output=True, text=True)


def _make_ticket(db_session, code: str, type_: str, title: str, description: str):
    from app.models import Project, Ticket

    project = Project(name=f"P-{code}", repo_path="x")
    db_session.add(project)
    db_session.flush()
    ticket = Ticket(
        project_id=project.id,
        code=code,
        type=type_,
        title=title,
        description=description,
        status="open",
    )
    db_session.add(ticket)
    db_session.commit()
    return ticket


@pytest.fixture()
def bug_ticket(db_session):
    return _make_ticket(db_session, "BUG-9001", "BUG", "fix me", "重复投递未标记 PAID")


@pytest.fixture()
def req_ticket(db_session):
    return _make_ticket(
        db_session,
        "REQ-9002",
        "REQ",
        "增加取消订单功能",
        "只能取消待支付订单；支付完成后不能取消；取消后恢复库存。",
    )
