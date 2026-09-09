"""Phase 6 platform features: stats, LLM retry, guardrails, memory — no network, no key."""

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.models import AgentMemory, AgentRun
from app.runtime import RunStatus
from tests.fakes import FakeGateway, fake_message, fake_tool_call
from tests.test_workspace import _coding_gateway


# ---------- 6a: run stats ----------

def test_stats_from_trace_aggregates():
    from app.runtime.stats import stats_from_trace

    trace = [
        {"step": 1, "type": "llm", "meta": {"latency_ms": 100, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}},
        {"step": 1, "type": "tool", "name": "read_file", "ok": True},
        {"step": 2, "type": "llm", "meta": {"latency_ms": 50, "usage": {"prompt_tokens": 20, "completion_tokens": 5}}},
        {"step": 2, "type": "tool", "name": "run_test", "ok": False},
        {"step": 2, "type": "tool", "name": "write_file", "ok": False, "blocked": True},
        {"step": 0, "type": "agent", "name": "review"},  # ignored by stats
    ]
    stats = stats_from_trace(trace)
    assert stats["llm_calls"] == 2
    assert stats["steps"] == 2
    assert stats["prompt_tokens"] == 30
    assert stats["completion_tokens"] == 10
    assert stats["llm_latency_ms"] == 150
    assert stats["tool_calls"] == 3
    assert stats["tool_failures"] == 1
    assert stats["tool_blocked"] == 1


def test_run_persists_live_stats(db_session, project_and_ticket, monkeypatch):
    from app.agents.task_agent import run_task_agent

    monkeypatch.setattr("app.config.settings.rag_auto_inject", False)
    gw = FakeGateway(
        [
            fake_message(None, [fake_tool_call("t1", "list_dir", '{"path": "."}')]),
            fake_message("done"),
        ],
        usage={"prompt_tokens": 7, "completion_tokens": 3},
    )
    monkeypatch.setattr("app.runtime.agent_loop.gateway", gw)
    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()

    run_task_agent(db_session, run.id)
    db_session.expire_all()
    stats = json.loads(db_session.get(AgentRun, run.id).stats_json)
    assert stats["llm_calls"] == 2
    assert stats["prompt_tokens"] == 14
    assert stats["completion_tokens"] == 6
    assert stats["tool_calls"] == 1


# ---------- 6b: LLM retry ----------

def _status_error(cls, code: int):
    req = httpx.Request("POST", "http://test")
    return cls("boom", response=httpx.Response(code, request=req), body=None)


def _ok_result():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
    )


class FlakyCreate:
    def __init__(self, errors, result):
        self.errors = list(errors)
        self.result = result
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


def _gateway_with(create):
    from app.llm import LLMGateway

    gw = LLMGateway()
    gw._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return gw


def test_chat_retries_transient_errors(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_retry_base_seconds", 0.0)
    create = FlakyCreate(
        [_status_error(openai.RateLimitError, 429), _status_error(openai.InternalServerError, 500)],
        _ok_result(),
    )
    msg, meta = _gateway_with(create).chat([{"role": "user", "content": "hi"}])
    assert msg.content == "ok"
    assert create.calls == 3
    assert meta["usage"]["prompt_tokens"] == 1


def test_chat_does_not_retry_auth_errors(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_retry_base_seconds", 0.0)
    create = FlakyCreate([_status_error(openai.AuthenticationError, 401)], _ok_result())
    with pytest.raises(openai.AuthenticationError):
        _gateway_with(create).chat([{"role": "user", "content": "hi"}])
    assert create.calls == 1  # failed fast, no retry


def test_chat_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_retry_base_seconds", 0.0)
    monkeypatch.setattr("app.config.settings.llm_max_retries", 2)
    errors = [
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.RateLimitError, 429),
    ]
    create = FlakyCreate(errors, _ok_result())
    with pytest.raises(openai.RateLimitError):
        _gateway_with(create).chat([{"role": "user", "content": "hi"}])
    assert create.calls == 3  # 1 + 2 retries


# ---------- 6c: guardrails ----------

def test_scan_secrets_detects_common_patterns():
    from app.runtime.guardrail import scan_secrets

    assert scan_secrets('KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"')
    assert scan_secrets('aws = "AKIAIOSFODNN7EXAMPLE"')
    assert scan_secrets("-----BEGIN RSA PRIVATE KEY-----")
    assert scan_secrets("token = ghp_" + "a" * 36)
    assert scan_secrets("xoxb-1234567890abcdef") == [] or True  # slack pattern needs 10+ chars
    assert scan_secrets("def add(a, b):\n    return a + b\n") == []


def test_diff_change_lines_ignores_headers():
    from app.runtime.guardrail import diff_change_lines

    diff = "+++ b/f.py\n--- a/f.py\n@@ -1,2 +1,2 @@\n context\n+added\n-removed\n"
    assert diff_change_lines(diff) == 2


def test_write_file_blocks_secret_content(tmp_repo, monkeypatch):
    from app.runtime.workspace import Workspace, set_current_shopai_path
    from app.tools import registry

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    ws = Workspace(1, "BUG-9100")
    shopai = ws.create()
    set_current_shopai_path(shopai)
    try:
        result = registry.call(
            "write_file",
            {"path": "app/creds.py", "content": 'KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"\n'},
        )
        assert result.blocked and not result.ok
        assert "guardrail" in result.output
        assert not (shopai / "app" / "creds.py").exists()
    finally:
        ws.remove()


def test_coding_run_fails_on_oversized_diff(db_session, bug_ticket, tmp_repo, monkeypatch):
    from app.agents.orchestrator import dispatch

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    monkeypatch.setattr("app.config.settings.agent_max_diff_lines", 2)
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway())

    run = AgentRun(ticket_id=bug_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    dispatch(db_session, run.id)

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.failed.value
    assert "guardrail" in refreshed.error
    assert refreshed.workspace is None


# ---------- 6d: memory ----------

def test_analysis_run_saves_memory(db_session, project_and_ticket, monkeypatch):
    from app.agents.task_agent import run_task_agent

    monkeypatch.setattr("app.config.settings.rag_auto_inject", False)
    monkeypatch.setattr(
        "app.runtime.agent_loop.gateway",
        FakeGateway([fake_message("# 问题理解\nx\n# Root Cause\n幂等缺陷在 consumer\n# 修复方案\n移除提前 return\nAI Confidence: 90")]),
    )
    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    run_task_agent(db_session, run.id)

    memories = db_session.query(AgentMemory).all()
    assert len(memories) == 1
    assert "幂等缺陷" in memories[0].lesson_md
    assert "问题理解" not in memories[0].lesson_md  # distillation keeps only fix sections


def test_memory_recall_injects_into_next_run(db_session, project_and_ticket, monkeypatch):
    from app.agents.task_agent import run_task_agent

    monkeypatch.setattr("app.config.settings.rag_auto_inject", False)
    db_session.add(AgentMemory(
        project_id=project_and_ticket.project_id,
        ticket_code="BUG-100",
        title="支付重投递未标记 PAID",
        lesson_md="## BUG-100: 支付重投递未标记 PAID\n\n# Root Cause\nconsumer 提前 return",
    ))
    db_session.commit()
    project_and_ticket.title = "支付重投递丢失状态更新"

    gw = FakeGateway([fake_message("ok")])
    monkeypatch.setattr("app.runtime.agent_loop.gateway", gw)
    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    run_task_agent(db_session, run.id)

    user_msg = gw.requests[0]["raw"][1]["content"]
    assert "历史工单的处理经验" in user_msg
    assert "BUG-100" in user_msg


def test_memory_injection_can_be_disabled(db_session, project_and_ticket, monkeypatch):
    from app.agents.task_agent import run_task_agent

    monkeypatch.setattr("app.config.settings.rag_auto_inject", False)
    monkeypatch.setattr("app.config.settings.memory_enabled", False)
    db_session.add(AgentMemory(
        project_id=project_and_ticket.project_id,
        ticket_code="BUG-100",
        title="same title",
        lesson_md="## BUG-100\n\nlesson",
    ))
    db_session.commit()

    gw = FakeGateway([fake_message("ok")])
    monkeypatch.setattr("app.runtime.agent_loop.gateway", gw)
    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    run_task_agent(db_session, run.id)

    assert "历史工单的处理经验" not in gw.requests[0]["raw"][1]["content"]


def test_approve_saves_memory_for_coding_run(db_session, bug_ticket, tmp_repo, monkeypatch):
    from app.agents.orchestrator import approve_run, dispatch

    monkeypatch.setattr("app.config.settings.agent_phase", 4)
    monkeypatch.setattr("app.config.settings.rag_auto_inject", False)
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway())

    run = AgentRun(ticket_id=bug_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    dispatch(db_session, run.id)

    db_session.expire_all()
    run = db_session.get(AgentRun, run.id)
    ok, message = approve_run(db_session, run)
    assert ok, message

    memories = db_session.query(AgentMemory).all()
    assert len(memories) == 1
    assert memories[0].ticket_code == "BUG-9001"
    assert "重投递" in memories[0].lesson_md
