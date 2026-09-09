"""Phase 5: requirement/review agent contracts and the rework loop (FakeLLM)."""

import json

from app.models import AgentRun
from app.runtime import RunStatus
from tests.fakes import FakeGateway, fake_message, fake_tool_call
from tests.test_workspace import FIXED_CONSUMER, _coding_gateway, _run  # noqa: F401


REQUIREMENT_JSON = json.dumps(
    {
        "understanding": "订单列表增加取消功能",
        "acceptance_criteria": ["待支付订单可取消", "已支付订单不可取消", "取消后恢复库存"],
        "modules": ["app/order_service.py"],
        "risks": ["并发取消与支付竞态"],
        "test_plan": ["test_cancel_pending", "test_cancel_paid_rejected"],
    },
    ensure_ascii=False,
)


def test_requirement_agent_parses_json(db_session, project_and_ticket, monkeypatch):
    from app.agents.requirement_agent import run_requirement_agent
    from app.models import AgentRun

    run = AgentRun(ticket_id=project_and_ticket.id, status="running")
    db_session.add(run)
    db_session.commit()

    gw = FakeGateway([fake_message(REQUIREMENT_JSON)])
    monkeypatch.setattr("app.agents.requirement_agent.gateway", gw)
    req = run_requirement_agent(db_session, run, project_and_ticket)

    assert req["acceptance_criteria"][0] == "待支付订单可取消"
    user_msg = gw.requests[0]["raw"][1]["content"]
    assert project_and_ticket.code in user_msg


def test_requirement_agent_tolerates_code_fence(db_session, project_and_ticket, monkeypatch):
    from app.agents.requirement_agent import run_requirement_agent
    from app.models import AgentRun

    run = AgentRun(ticket_id=project_and_ticket.id, status="running")
    db_session.add(run)
    db_session.commit()

    fenced = f"```json\n{REQUIREMENT_JSON}\n```"
    monkeypatch.setattr("app.agents.requirement_agent.gateway", FakeGateway([fake_message(fenced)]))
    req = run_requirement_agent(db_session, run, project_and_ticket)
    assert req["understanding"] == "订单列表增加取消功能"


def test_review_agent_defaults_on_garbage(monkeypatch):
    from app.agents.review_agent import run_review_agent

    monkeypatch.setattr(
        "app.agents.review_agent.gateway",
        FakeGateway([fake_message("模型抽风了，不是 JSON")]),
    )
    review = run_review_agent(
        ticket_code="BUG-1", ticket_title="t", ticket_description="d", diff="diff", test_output="ok"
    )
    assert review["verdict"] == "approve"


def test_req_pipeline_with_rework(db_session, req_ticket, tmp_repo, monkeypatch):
    """REQ 工单：Requirement 产出 → Coding 实现 → Review request_changes → 返工 → needs_review。"""
    from app.agents.orchestrator import dispatch

    monkeypatch.setattr("app.config.settings.agent_phase", 5)

    # Requirement Agent: 一次调用
    monkeypatch.setattr(
        "app.agents.requirement_agent.gateway", FakeGateway([fake_message(REQUIREMENT_JSON)])
    )
    # Coding Agent: 首轮（读 + 写 + 测 + 报告）+ 返工轮（测 + 报告）
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway(rounds=2))
    # Review Agent: request_changes 触发一轮返工（返工后不再复审，人工是最终门）
    review_gw = FakeGateway([
        fake_message(json.dumps({
            "verdict": "request_changes",
            "comments": [{"severity": "major", "file": "app/payment_consumer.py", "comment": "缺少幂等保护"}],
            "summary": "需要返工",
        })),
    ])
    monkeypatch.setattr("app.agents.review_agent.gateway", review_gw)

    run = AgentRun(ticket_id=req_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()

    dispatch(db_session, run.id)

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.needs_review.value
    assert "Requirement Agent 产出" in (refreshed.report_md or "")
    assert "验收标准" in (refreshed.report_md or "")
    assert "Review Agent" in (refreshed.report_md or "")
    assert "返工" in (refreshed.report_md or "")
    assert "2 passed" in refreshed.test_summary

    trace = json.loads(refreshed.trace_json)
    agent_events = [e for e in trace if e.get("type") == "agent"]
    assert [e["name"] for e in agent_events][:2] == ["requirement", "review"]
    # review ran once (rework is verified by re-run tests, human is the final gate)
    assert review_gw.requests and len(review_gw.requests) == 1


def test_bug_pipeline_review_approve_no_rework(db_session, bug_ticket, tmp_repo, monkeypatch):
    from app.agents.orchestrator import dispatch

    monkeypatch.setattr("app.config.settings.agent_phase", 5)
    monkeypatch.setattr("app.runtime.agent_loop.gateway", _coding_gateway())
    monkeypatch.setattr(
        "app.agents.review_agent.gateway",
        FakeGateway([fake_message(json.dumps({"verdict": "approve", "comments": [], "summary": "OK"}))]),
    )

    run = AgentRun(ticket_id=bug_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()
    dispatch(db_session, run.id)

    db_session.expire_all()
    refreshed = db_session.get(AgentRun, run.id)
    assert refreshed.status == RunStatus.needs_review.value
    assert "Review Agent" in refreshed.report_md
    # coding gateway script consumed exactly once (no rework)
    trace = json.loads(refreshed.trace_json)
    assert [e["name"] for e in trace if e.get("type") == "agent"] == ["review"]
