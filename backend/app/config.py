from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "mysql+pymysql://codepilot:codepilot@127.0.0.1:3306/codepilot"

    # LLM_* is canonical; OPENAI_* kept as fallback alias for old setups.
    llm_api_key: str = Field(default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"))
    llm_base_url: str = Field(default="", validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"))
    llm_model: str = Field(default="", validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"))
    embedding_model: str = Field(default="text-embedding-v4", validation_alias=AliasChoices("EMBEDDING_MODEL"))

    shopai_root: str = "playground/shopai"
    agent_max_steps: int = 16
    agent_phase: int = 3
    test_timeout_seconds: int = 180
    sse_poll_seconds: float = 1.0
    project_root: str = str(ROOT)

    # RAG (Phase 3)
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "codepilot_knowledge"
    rag_top_k: int = 5
    rag_auto_inject: bool = True

    # Coding agent (Phase 4)
    agent_workspace_root: str = ".agent-workspaces"

    @property
    def shopai_path(self) -> Path:
        p = Path(self.shopai_root)
        if not p.is_absolute():
            p = ROOT / p
        return p.resolve()

    @property
    def openai_api_key(self) -> str:
        return self.llm_api_key

    @property
    def openai_model(self) -> str:
        return self.llm_model or "gpt-4o-mini"

    @property
    def openai_base_url(self) -> str:
        """Explicit base URL wins; otherwise infer provider from model name."""
        if self.llm_base_url:
            return self.llm_base_url
        if self.openai_model.lower().startswith("qwen"):
            return DASHSCOPE_BASE_URL
        return OPENAI_BASE_URL


settings = Settings()
