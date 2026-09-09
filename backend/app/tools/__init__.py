"""Tool layer. Every tool declares the phase that unlocks it (see registry.py)."""

from __future__ import annotations

from app.config import settings
from app.tools.registry import ToolDef, ToolResult, ToolRegistry, registry
from app.tools.files import register_file_tools
from app.tools.git_tools import register_git_tools
from app.tools.testing import register_testing_tools
from app.tools.rag_tools import register_rag_tools

__all__ = ["ToolDef", "ToolResult", "ToolRegistry", "registry"]


def _blocked(name: str, unlock_phase: int):
    def _fn(args: dict) -> ToolResult:
        return ToolResult(
            name=name,
            ok=False,
            blocked=True,
            output=(
                f"`{name}` 在 Phase {unlock_phase} 才开放，当前 AGENT_PHASE={settings.agent_phase}，"
                "只允许分析与观测。"
            ),
        )

    return _fn


def _register_placeholders() -> None:
    placeholder_path_params = {"type": "object", "properties": {"path": {"type": "string"}}}
    for name, desc, phase, readonly in [
        ("create_branch", "Create an isolated git branch/worktree (system-managed).", 4, False),
        ("git_commit", "Commit changes on the agent branch (system-managed).", 4, False),
        ("create_pull_request", "Create a pull request.", 4, False),
        ("deploy_service", "Deploy service (requires HITL approval).", 6, False),
    ]:
        registry.register(
            name,
            f"{desc} Placeholder — returns a blocked notice until unlocked.",
            placeholder_path_params,
            _blocked(name, phase),
            phase=phase,
            readonly=readonly,
        )


def register_default_tools() -> None:
    if registry._tools:
        return
    register_file_tools()
    register_git_tools()
    register_testing_tools()
    register_rag_tools()
    _register_placeholders()


register_default_tools()
