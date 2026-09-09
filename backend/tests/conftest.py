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

# The playground's BUG-1024 defect is FIXED on main (agent fix merged via HITL),
# but coding-run fixtures need the bug present so scripted fixes produce a diff.
# This is the original defective consumer restored from git history (7d64048).
BUGGY_CONSUMER = '''"""In-process Kafka-like payment event consumer.

BUG-1024:
Payment gateway may fail the first delivery after charging the user.
The broker redelivers the PaymentSucceeded event. This consumer treats
*any* redelivery as a duplicate and returns early — so the order stays
pending even though money was taken.

This surfaces as ~1% of orders in production (first-attempt processing
errors + retry).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.order_service import store


@dataclass
class PaymentSucceeded:
    event_id: str
    order_id: str
    redelivered: bool = False


class PaymentConsumer:
    def handle(self, event: PaymentSucceeded) -> None:
        # Incorrect idempotency: skip all retries instead of making
        # mark_paid idempotent and always applying the state transition.
        if event.redelivered:
            return
        order = store.get(event.order_id)
        if order is None:
            return
        store.mark_paid(event.order_id)


consumer = PaymentConsumer()
'''

# Original pre-fix test file (xfail marker present) — pairs with BUGGY_CONSUMER.
BUGGY_TESTS = '''import pytest

from app.order_service import store
from app.payment_consumer import PaymentSucceeded, consumer


@pytest.fixture(autouse=True)
def _reset_store():
    store.clear()
    yield
    store.clear()


def test_happy_path_marks_paid():
    store.create("o1")
    consumer.handle(PaymentSucceeded(event_id="e1", order_id="o1", redelivered=False))
    assert store.get("o1").status == "PAID"


@pytest.mark.xfail(reason="BUG-1024: redelivery skips mark_paid", strict=True)
def test_redelivery_should_still_mark_paid():
    store.create("o2")
    consumer.handle(PaymentSucceeded(event_id="e2", order_id="o2", redelivered=True))
    assert store.get("o2").status == "PAID"
'''


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
    # Pin the playground to its pre-E2E state: BUG-1024 unfixed, and only the
    # original test file present — later agent merges (cancel-order, inventory
    # tests) assume fixes these scripted runs never make.
    (shopai / "app" / "payment_consumer.py").write_text(BUGGY_CONSUMER, encoding="utf-8")
    (shopai / "tests" / "test_payment_status.py").write_text(BUGGY_TESTS, encoding="utf-8")
    for extra in (shopai / "tests").glob("test_*.py"):
        if extra.name != "test_payment_status.py":
            extra.unlink()
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
