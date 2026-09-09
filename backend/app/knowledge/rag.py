"""Phase 3 RAG: chunk → embed (LLM gateway) → Qdrant → retrieve.

Chunking and document building are pure functions (unit-testable without a
vector DB); the store wraps qdrant-client and degrades to "no results" when
Qdrant is down so the agent never crashes on missing infrastructure.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.config import settings
from app.llm import gateway

logger = logging.getLogger(__name__)

CHUNK_TARGET_CHARS = 700
CHUNK_MAX_CHARS = 1200


@dataclass
class RagDoc:
    """One retrievable chunk."""

    id: str
    source: str  # document | ticket
    ref: str  # file name or ticket code
    title: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


def chunk_markdown(text: str, *, title: str = "") -> list[str]:
    """Split markdown into heading-aware chunks within size bounds."""
    sections: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in text.splitlines():
        if re.match(r"^#{1,3}\s", line) and current:
            sections.append("\n".join(current).strip())
            current, current_size = [], 0
        current.append(line)
        current_size += len(line) + 1
        if current_size >= CHUNK_MAX_CHARS:
            sections.append("\n".join(current).strip())
            current, current_size = [], 0
    if current:
        sections.append("\n".join(current).strip())

    chunks: list[str] = []
    for section in filter(None, sections):
        header = f"{title}\n" if title else ""
        if len(section) <= CHUNK_MAX_CHARS:
            chunks.append(header + section)
            continue
        # over-long section (e.g. code block): hard-split around the target size
        for i in range(0, len(section), CHUNK_TARGET_CHARS):
            part = section[i : i + CHUNK_TARGET_CHARS]
            chunks.append(header + part)
    return [c for c in chunks if len(c.strip()) > 20]


def build_file_docs(rel_name: str, content: str) -> list[RagDoc]:
    title = rel_name
    docs = []
    for i, chunk in enumerate(chunk_markdown(content, title=title)):
        docs.append(
            RagDoc(
                id=f"doc:{rel_name}:{i}",
                source="document",
                ref=rel_name,
                title=title,
                text=chunk,
            )
        )
    return docs


def build_ticket_doc(code: str, type_: str, title: str, description: str) -> RagDoc:
    text = f"[{type_}] {code} {title}\n\n{description}"
    return RagDoc(id=f"ticket:{code}", source="ticket", ref=code, title=title, text=text)


class RagStore:
    """Qdrant-backed store. `embed_fn` / `client` injectable for tests."""

    def __init__(
        self,
        *,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
        client: Any = None,
        collection: str | None = None,
    ) -> None:
        self._embed_fn = embed_fn or (lambda texts: gateway.embed(texts))
        self._client = client
        self._collection = collection or settings.qdrant_collection
        self._ready = False

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=settings.qdrant_url, timeout=5)
        return self._client

    def _ensure_collection(self, dim: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self._ready:
            if not self.client.collection_exists(self._collection):
                self.client.create_collection(
                    collection_name=self._collection,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
            self._ready = True

    def upsert(self, docs: list[RagDoc]) -> int:
        if not docs:
            return 0
        vectors = self._embed_fn([d.text for d in docs])
        self._ensure_collection(dim=len(vectors[0]))
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=doc.id,
                vector=vec,
                payload={
                    "source": doc.source,
                    "ref": doc.ref,
                    "title": doc.title,
                    "text": doc.text,
                    **doc.meta,
                },
            )
            for doc, vec in zip(docs, vectors)
        ]
        self.client.upsert(collection_name=self._collection, points=points)
        return len(points)

    def retrieve(
        self, query: str, *, top_k: int | None = None, source: str | None = None
    ) -> list[dict[str, Any]]:
        """Return [{source, ref, title, text, score}]; empty list on any infrastructure failure."""
        try:
            vector = self._embed_fn([query])[0]
            self._ensure_collection(dim=len(vector))
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = None
            if source:
                query_filter = Filter(
                    must=[FieldCondition(key="source", match=MatchValue(value=source))]
                )
            hits = self.client.query_points(
                collection_name=self._collection,
                query=vector,
                limit=top_k or settings.rag_top_k,
                query_filter=query_filter,
            ).points
            return [
                {
                    "source": h.payload.get("source"),
                    "ref": h.payload.get("ref"),
                    "title": h.payload.get("title"),
                    "text": h.payload.get("text"),
                    "score": h.score,
                }
                for h in hits
            ]
        except Exception as exc:  # noqa: BLE001 — RAG is best-effort
            logger.warning("RAG retrieve failed: %s", exc)
            return []

    def reset(self) -> None:
        try:
            if self.client.collection_exists(self._collection):
                self.client.delete_collection(self._collection)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG reset failed: %s", exc)
        self._ready = False


_store: RagStore | None = None


def get_rag() -> RagStore:
    global _store
    if _store is None:
        _store = RagStore()
    return _store


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    return get_rag().retrieve(query, top_k=top_k)
