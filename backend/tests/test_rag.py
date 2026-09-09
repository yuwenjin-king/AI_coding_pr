"""RAG layer: chunking, doc building, retrieval tools, auto-injection (no network)."""

from app.knowledge.ingest import collect_seed_docs
from app.knowledge.rag import build_file_docs, build_ticket_doc, chunk_markdown


class FakeRagStore:
    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def retrieve(self, query, top_k=None, source=None):
        self.queries.append({"query": query, "source": source})
        return self.hits


def test_chunk_markdown_splits_on_headings():
    text = "# Title\nintro\n\n## A\n" + "a-content " * 30 + "\n\n## B\nb-content"
    chunks = chunk_markdown(text, title="file.md")
    assert len(chunks) >= 2
    assert chunks[0].startswith("file.md\n")
    assert any("## A" in c for c in chunks)


def test_chunk_markdown_caps_chunk_size():
    text = "# T\n" + "x" * 5000
    chunks = chunk_markdown(text)
    assert all(len(c) <= 1300 for c in chunks)
    assert sum(len(c) for c in chunks) >= 4900


def test_build_file_and_ticket_docs():
    docs = build_file_docs("BUG-387.md", "# 库存问题\n" + "Redis 与 MySQL 库存并发不一致的详细复盘内容。" * 3)
    assert docs[0].source == "document"
    assert docs[0].ref == "BUG-387.md"

    ticket = build_ticket_doc("BUG-1026", "BUG", "库存扣减偶发失败", "描述")
    assert ticket.id == "ticket:BUG-1026"
    assert "BUG-1026" in ticket.text


def test_collect_seed_docs_reads_repo_seeds():
    docs = collect_seed_docs()
    refs = {d.ref for d in docs}
    assert "BUG-387.md" in refs
    assert "coding-standards.md" in refs
    assert all(d.source == "document" for d in docs)


def test_search_ticket_tool_formats_hits(monkeypatch):
    from app.tools import registry

    fake = FakeRagStore([
        {"source": "ticket", "ref": "BUG-387", "title": "库存扣减", "text": "Redis/MySQL 不一致", "score": 0.87},
    ])
    monkeypatch.setattr("app.tools.rag_tools.get_rag", lambda: fake)
    result = registry.call("search_ticket", {"query": "库存 扣减 失败"})
    assert result.ok
    assert "BUG-387" in result.output
    assert "score=0.87" in result.output
    assert fake.queries[0]["source"] == "ticket"


def test_search_document_empty_kb_hint(monkeypatch):
    from app.tools import registry

    monkeypatch.setattr("app.tools.rag_tools.get_rag", lambda: FakeRagStore([]))
    result = registry.call("search_document", {"query": "架构"})
    assert result.ok
    assert "no matches" in result.output


def test_task_agent_auto_injects_knowledge(db_session, project_and_ticket, monkeypatch):
    import json

    from app.agents.task_agent import run_task_agent
    from app.models import AgentRun
    from app.runtime import RunStatus
    from tests.fakes import FakeGateway, fake_message

    fake = FakeRagStore([
        {"source": "ticket", "ref": "BUG-387", "title": "库存扣减偶发失败", "text": "Redis 与 MySQL 并发不一致", "score": 0.9},
    ])
    monkeypatch.setattr("app.knowledge.rag.get_rag", lambda: fake)

    run = AgentRun(ticket_id=project_and_ticket.id, status=RunStatus.queued.value)
    db_session.add(run)
    db_session.commit()

    gw = FakeGateway([fake_message("# Root Cause\nx\nAI Confidence: 80")])
    monkeypatch.setattr("app.runtime.agent_loop.gateway", gw)
    run_task_agent(db_session, run.id)

    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == RunStatus.succeeded.value
    user_msg = gw.requests[0]["raw"][1]["content"]
    assert "BUG-387" in user_msg
    assert "知识库" in user_msg
    assert json.loads(db_session.get(AgentRun, run.id).plan_json)  # plan still persisted
