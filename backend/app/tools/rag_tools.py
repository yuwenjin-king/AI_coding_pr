"""Knowledge retrieval tools backed by the Phase 3 RAG store."""

from __future__ import annotations

from app.knowledge.rag import get_rag
from app.tools.registry import ToolResult, registry

_MAX_TEXT = 1500


def _format(hits: list[dict]) -> str:
    if not hits:
        return "no matches (knowledge base may be empty — run python -m app.knowledge.ingest)"
    lines = []
    for i, hit in enumerate(hits, 1):
        text = (hit.get("text") or "").strip()
        if len(text) > _MAX_TEXT:
            text = text[:_MAX_TEXT] + "…"
        lines.append(
            f"[{i}] {hit.get('ref')} · {hit.get('title')} "
            f"(score={hit.get('score'):.2f}, source={hit.get('source')})\n{text}"
        )
    return "\n\n".join(lines)


def _search(args: dict, source: str, name: str) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(name, False, "query required")
    hits = get_rag().retrieve(query, source=source)
    return ToolResult(name, True, _format(hits))


def _tool_search_document(args: dict) -> ToolResult:
    return _search(args, "document", "search_document")


def _tool_search_ticket(args: dict) -> ToolResult:
    return _search(args, "ticket", "search_ticket")


def register_rag_tools() -> None:
    registry.register(
        "search_document",
        "Search the knowledge base (architecture docs, coding standards, postmortems).",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        _tool_search_document,
        phase=3,
    )
    registry.register(
        "search_ticket",
        "Search historical tickets (similar bugs and past requirements).",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        _tool_search_ticket,
        phase=3,
    )
