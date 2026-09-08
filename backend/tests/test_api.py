"""HTTP API + SSE without touching MySQL or a real LLM."""

import json

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import AgentRun
from app.runtime import RunStatus


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_tickets_crud(db_session, project_and_ticket):
    client = _client(db_session)
    try:
        listed = client.get("/api/tickets")
        assert listed.status_code == 200
        assert listed.json()[0]["code"] == "T-001"

        created = client.post(
            "/api/tickets",
            json={
                "code": "T-002",
                "type": "REQ",
                "title": "新需求",
                "description": "描述",
                "project_id": project_and_ticket.project_id,
            },
        )
        assert created.status_code == 200
        assert created.json()["status"] == "open"

        detail = client.get(f"/api/tickets/{project_and_ticket.id}")
        assert detail.status_code == 200
        assert detail.json()["runs"] == []
    finally:
        app.dependency_overrides.clear()


def test_sse_emits_snapshot_then_done(db_session, project_and_ticket, monkeypatch):
    run = AgentRun(
        ticket_id=project_and_ticket.id,
        status=RunStatus.succeeded.value,
        report_md="done-report",
        trace_json=json.dumps([{"step": 1, "type": "llm", "content": "hi"}]),
    )
    db_session.add(run)
    db_session.commit()

    monkeypatch.setattr("app.api._stream_session", lambda: db_session)
    client = _client(db_session)
    try:
        with client.stream("GET", f"/api/runs/{run.id}/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(resp.iter_text())
        assert "data:" in body
        assert "done-report" in body
        assert "event: done" in body
        payload_line = next(line for line in body.splitlines() if line.startswith("data: {"))
        snapshot = json.loads(payload_line[len("data: "):])
        assert snapshot["status"] == "succeeded"
        assert json.loads(snapshot["trace_json"])[0]["type"] == "llm"
    finally:
        app.dependency_overrides.clear()


def test_sse_unknown_run(db_session, monkeypatch):
    monkeypatch.setattr("app.api._stream_session", lambda: db_session)
    client = _client(db_session)
    try:
        resp = client.get("/api/runs/424242/events")
        assert resp.status_code == 200  # SSE opens, then signals the error event
        assert "event: error" in resp.text
    finally:
        app.dependency_overrides.clear()
