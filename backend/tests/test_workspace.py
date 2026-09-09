"""Phase 4: workspace isolation, write_file gating, coding run lifecycle, HITL."""

import json
import subprocess
from pathlib import Path

import pytest

from app.models import AgentRun, Project, Ticket
from app.runtime import RunStatus
from tests.fakes import FakeGateway, fake_message, fake_tool_call

REAL_SHOPAI = Path(__file__).resolve().parents[2] / "playground" / "shopai"


def _run(cmd, cwd):
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture()
def tmp_repo(tmp_path, monkeypatch):
    """A throwaway git repo that mirrors playground/shopai, isolated from the user's repo."""
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
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "add", "-A"], repo)
    _run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "t"], repo)

    monkeypatch.setattr("app.config.settings.shopai_root", str(shopai))
    monkeypatch.setattr("app.config.settings.agent_workspace_root", str(tmp_path / "ws"))
    yield repo
    subprocess.run(
        ["git", "worktree", "prune"], cwd=str(repo), capture_output=True, text=True
    )


@pytest.fixture()
def bug_ticket(db_session):
    project = Project(name="P-ws", repo_path="x")
    db_session.add(project)
    db_session.flush()
    ticket = Ticket(
        project_id=project.id,
        code="BUG-9001",
        type="BUG",
        title="fix me",
        description="重复投递未标记 PAID",
        status="open",
    )
    db_session.add(ticket)
    db_session.commit()
    return ticket


FIXED_CONSUMER = '''from dataclasses import dataclass

from app.order_service import store


@dataclass
class PaymentSucceeded:
    event_id: str
    order_id: str
    redelivered: bool = False


class PaymentConsumer:
    def handle(self, event):
        order = store.get(event.order_id)
        if order is None:
            return
        if order.status != "PAID":
            store.mark_paid(event.order_id)


consumer = PaymentConsumer()
'''


def _coding_gateway():
    """Scripted agent: fix the consumer, drop the xfail marker, then report."""
    return FakeGateway([
        fake_message(None, [fake_tool_call("c1", "read_file", '{"path": "app/payment_consumer.py"}')]),
        fake_message(None, [fake_tool_call(
            "c2", "write_file",
            json.dumps({"path": "app/payment_consumer.py", "content": FIXED_CONSUMER}),
        )]),
        fake_message(None, [fake_tool_call(
            "c3", "write_file",
            json.dumps({
                "path": "tests/test_payment_status.py",
                "content": (
                    "import pytest\n\n"
                    "from app.order_service import store\n"
                    "from app.payment_consumer import PaymentSucceeded, consumer\n\n\n"
                    "@pytest.fixture(autouse=True)\n"
                    "def _reset_store():\n"
                    "    store.clear()\n"
                    "    yield\n"
                    "    store.clear()\n\n\n"
                    "def test_happy_path_marks_paid():\n"
                    "    store.create('o1')\n"
                    "    consumer.handle(PaymentSucceeded(event_id='e1', order_id='o1', redelivered=False))\n"
                    "    assert store.get('o1').status == 'PAID'\n\n\n"
                    "def test_redelivery_should_still_mark_paid():\n"
                    "    store.create('o2')\n"
                    "    consumer.handle(PaymentSucceeded(event_id='e2', order_id='o2', redelivered=True))\n"
                    "    assert store.get('o2').status == 'PAID'\n"
                ),
            }),
        )]),
        fake_message(None, [fake_tool_call("c4", "run_test", "{}")]),
        fake_message("# Root Cause\n重投递被当重复消费\nAI Confidence: 90"),
    ])


def test_write_file_gated_and_scoped(tmp_repo, monkeypatch):
    from app.tools import registry
    from app.runtime.workspace import Workspace, set_current_shopai_path

    # phase 3 default → blocked
    assert registry.call("write_file", {"path": "a.py", "content": "x"}).blocked

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    ws = Workspace(1, "BUG-9001")
    shopai = ws.create()
    set_current_shopai_path(shopai)
    try:
        result = registry.call("write_file", {"path": "app/new_file.py", "content": "X = 1\n"})
        assert result.ok
        assert (shopai / "app" / "new_file.py").read_text() == "X = 1\n"

        # escaping and bad suffix rejected inside workspace
        assert not registry.call("write_file", {"path": "../evil.py", "content": "x"}).ok
        assert not registry.call("write_file", {"path": "app/run.sh", "content": "x"}).ok

        # main checkout untouched
        assert not (REAL_SHOPAI / "app" / "new_file.py").exists()
    finally:
        ws.remove()


def test_coding_run_lifecycle_to_needs_review(db_session, bug_ticket, tmp_repo, monkeypatch):
    from app.agents.orchestrator import dispatch

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway())

    run = AgentRun(ticket_id=bug_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()

    dispatch(db_session, run.id)

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.needs_review.value
    assert refreshed.mode == "coding"
    assert refreshed.branch == f"agent/BUG-9001-run{run.id}"
    assert "payment_consumer.py" in refreshed.diff_md
    assert "2 passed" in refreshed.test_summary  # xfail gone, both green
    assert Path(refreshed.workspace).exists()

    # main checkout still untouched
    assert "redelivered" in (REAL_SHOPAI / "app" / "payment_consumer.py").read_text()


def test_hitl_approve_merges(db_session, bug_ticket, tmp_repo, monkeypatch):
    from app.agents.orchestrator import approve_run, dispatch

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway())

    run = AgentRun(ticket_id=bug_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    dispatch(db_session, run.id)

    db_session.expire_all()
    run = db_session.get(AgentRun, run.id)
    ok, message = approve_run(db_session, run)
    assert ok, message

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.succeeded.value
    assert refreshed.workspace is None
    db_session.refresh(bug_ticket)
    assert bug_ticket.status == "resolved"
    # fix landed in the tmp repo's main branch: the buggy early-return is gone
    merged = (tmp_repo / "playground" / "shopai" / "app" / "payment_consumer.py").read_text()
    assert "if event.redelivered" not in merged
    assert 'order.status != "PAID"' in merged
    worktrees = _run(["git", "worktree", "list"], tmp_repo)
    assert str(run.id) not in worktrees or "agent-workspaces" not in worktrees


def test_hitl_reject_discards(db_session, bug_ticket, tmp_repo, monkeypatch):
    from app.agents.orchestrator import dispatch, reject_run

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway())

    run = AgentRun(ticket_id=bug_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    dispatch(db_session, run.id)

    db_session.expire_all()
    run = db_session.get(AgentRun, run.id)
    assert run.status == RunStatus.needs_review.value
    ws_path = Path(run.workspace)
    ok, _ = reject_run(db_session, run)
    assert ok
    assert not ws_path.exists()
    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == RunStatus.cancelled.value
    # main branch of tmp repo has no merge commit
    log = _run(["git", "log", "--oneline"], tmp_repo)
    assert "merge" not in log
