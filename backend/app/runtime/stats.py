"""Run-level observability: aggregate per-run stats from trace events.

The agent loop already tags every `llm` event with `meta` (latency + token
usage from the provider). `stats_from_trace` folds a whole trace into one
small dict persisted as `agent_runs.stats_json` and shown in the UI.
"""

from __future__ import annotations

from typing import Any


def new_stats() -> dict[str, int]:
    return {
        "steps": 0,
        "llm_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "llm_latency_ms": 0,
        "tool_calls": 0,
        "tool_failures": 0,
        "tool_blocked": 0,
    }


def apply_event(stats: dict[str, int], event: dict[str, Any]) -> None:
    """Fold one trace event into `stats` (mutates). Unknown types are ignored."""
    etype = event.get("type")
    if etype == "llm":
        stats["llm_calls"] += 1
        stats["steps"] = max(stats["steps"], int(event.get("step") or 0))
        meta = event.get("meta") or {}
        stats["llm_latency_ms"] += int(meta.get("latency_ms") or 0)
        usage = meta.get("usage") or {}
        stats["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        stats["completion_tokens"] += int(usage.get("completion_tokens") or 0)
    elif etype == "tool":
        stats["tool_calls"] += 1
        if event.get("blocked"):
            stats["tool_blocked"] += 1
        elif not event.get("ok"):
            stats["tool_failures"] += 1


def stats_from_trace(trace: list[dict[str, Any]]) -> dict[str, int]:
    stats = new_stats()
    for event in trace:
        apply_event(stats, event)
    return stats
