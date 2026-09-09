from __future__ import annotations

import time
from typing import Any

from openai import OpenAI

from app.config import settings

# DashScope compatible-mode caps /embeddings at 10 inputs per request.
EMBED_BATCH_SIZE = 10


class LLMGateway:
    """OpenAI-compatible chat + embedding gateway (OpenAI / DashScope / DeepSeek)."""

    def __init__(self) -> None:
        self.model = settings.openai_model
        self._client = OpenAI(
            api_key=settings.llm_api_key or "missing-key",
            base_url=settings.openai_base_url,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        resp = self._client.chat.completions.create(**kwargs)
        meta = {
            "model": self.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "usage": {
                "prompt_tokens": getattr(resp.usage, "prompt_tokens", None) if resp.usage else None,
                "completion_tokens": getattr(resp.usage, "completion_tokens", None) if resp.usage
                else None,
            },
        }
        return resp.choices[0].message, meta

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in provider-safe batches; returns vectors in input order."""
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            resp = self._client.embeddings.create(model=settings.embedding_model, input=batch)
            vectors.extend(d.embedding for d in resp.data)
        return vectors


gateway = LLMGateway()
