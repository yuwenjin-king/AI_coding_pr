from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings
from app.database import Base, engine, SessionLocal
from app.seed import seed_if_empty

app = FastAPI(title="CodePilot Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _ensure_schema(engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def _ensure_schema(engine) -> None:
    """Hand-rolled mini-migration: add columns introduced after first deploy."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("agent_runs")}
    migrations = {
        "mode": "VARCHAR(16) DEFAULT 'analysis'",
        "branch": "VARCHAR(128)",
        "workspace": "VARCHAR(512)",
        "diff_md": "TEXT",
        "test_summary": "TEXT",
        "stats_json": "TEXT",
    }
    with engine.begin() as conn:
        for column, ddl in migrations.items():
            if column not in columns:
                conn.execute(text(f"ALTER TABLE agent_runs ADD COLUMN {column} {ddl}"))


@app.get("/api/health")
def health():
    return {"ok": True, "phase": settings.agent_phase}
