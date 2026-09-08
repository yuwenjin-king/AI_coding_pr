from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "mysql+pymysql://codepilot:codepilot@127.0.0.1:3306/codepilot"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    shopai_root: str = "playground/shopai"
    agent_max_steps: int = 16
    agent_phase: int = 2
    test_timeout_seconds: int = 180
    sse_poll_seconds: float = 1.0
    project_root: str = str(ROOT)

    @property
    def shopai_path(self) -> Path:
        p = Path(self.shopai_root)
        if not p.is_absolute():
            p = ROOT / p
        return p.resolve()


settings = Settings()
