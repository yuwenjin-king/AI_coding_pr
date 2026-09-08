"""Task agent end-to-end against sqlite + FakeGateway."""

import json

from app.agents.task_agent import run_task_agent
from app.models import AgentRun
from app.runtime import RunStatus
from tests.fakes import FakeGateway, fake_message, fake_tool_call


def test_task_agent_persists_report_and_trace(db_session, project_and_ticket, monkeypatch):
    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()

    gw = FakeGateway([
        fake_message(None, [fake_tool_call("c1", "git_log", '{"n": 3}')]),
        fake_message(None, [fake_tool_call("c2", "run_test", "{}")]),
        fake_message("# 问题理解\n...\n# Root Cause\npayment_consumer.py 幂等判断错误\nAI Confidence: 88"),
    ])
    monkeypatch.setattr("app.runtime.agent_loop.gateway", gw)
    run_task_agent(db_session, run.id)

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.succeeded.value
    assert "Root Cause" in refreshed.report_md
    trace = json.loads(refreshed.trace_json)
    names = [e.get("name") for e in trace if e["type"] == "tool"]
    assert names == ["git_log", "run_test"]
    assert refreshed.plan_json  # default plan persisted


def test_task_agent_failure_is_recorded(db_session, project_and_ticket, monkeypatch):
    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()

    class ExplodingGateway:
        def chat(self, *_a, **_k):
            raise RuntimeError("api key invalid")

    monkeypatch.setattr("app.runtime.agent_loop.gateway", ExplodingGateway())
    run_task_agent(db_session, run.id)

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.failed.value
    assert "api key invalid" in refreshed.error


def test_task_agent_missing_ticket(db_session):
    run_task_agent(db_session, 99999)  # no crash, nothing to do
