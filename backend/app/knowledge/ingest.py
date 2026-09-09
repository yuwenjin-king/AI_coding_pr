"""Ingest pipeline: knowledge/seed/*.md + DB tickets → embeddings → Qdrant.

Run manually:  python -m app.knowledge.ingest
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import ROOT, settings
from app.knowledge.rag import RagDoc, RagStore, build_file_docs, build_ticket_doc
from app.models import Ticket

logger = logging.getLogger(__name__)

SEED_DIR = ROOT / "knowledge" / "seed"


def collect_seed_docs() -> list[RagDoc]:
    docs: list[RagDoc] = []
    if SEED_DIR.is_dir():
        for path in sorted(SEED_DIR.glob("*.md")):
            content = path.read_text(encoding="utf-8", errors="replace")
            docs.extend(build_file_docs(path.name, content))
    return docs


def collect_ticket_docs(db: Session) -> list[RagDoc]:
    docs: list[RagDoc] = []
    for ticket in db.query(Ticket).all():
        docs.append(
            build_ticket_doc(ticket.code, ticket.type, ticket.title, ticket.description)
        )
    return docs


def ingest_all(db: Session, store: RagStore | None = None) -> dict:
    store = store or RagStore()
    docs = collect_seed_docs() + collect_ticket_docs(db)
    store.reset()
    count = store.upsert(docs)
    logger.info("ingested %s chunks (from %s docs)", count, len(docs))
    return {"chunks": count, "sources": len(docs)}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        print(ingest_all(db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
