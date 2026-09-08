"""Git observation tools (read-only). Phase 4 will add branch/commit/write."""

from __future__ import annotations

import subprocess

from app.config import settings
from app.tools.registry import ToolResult, registry

_GIT_TIMEOUT = 15
_MAX_OUTPUT = 8000


def _git(args: list[str], tool_name: str) -> ToolResult:
    try:
        proc = subprocess.run(
            ["git", "-C", str(settings.shopai_path), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except FileNotFoundError:
        return ToolResult(tool_name, False, "git binary not found")
    except subprocess.TimeoutExpired:
        return ToolResult(tool_name, False, f"git {' '.join(args)} timed out")
    output = (proc.stdout + proc.stderr).strip()
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n...[truncated]"
    return ToolResult(tool_name, proc.returncode == 0, output or "(no output)")


def _tool_git_status(args: dict) -> ToolResult:
    return _git(["status", "--porcelain=v1", "-b"], "git_status")


def _tool_git_diff(args: dict) -> ToolResult:
    git_args = ["diff"]
    if args.get("stat"):
        git_args.append("--stat")
    if args.get("path"):
        git_args.extend(["--", str(args["path"])])
    return _git(git_args, "git_diff")


def _tool_git_log(args: dict) -> ToolResult:
    n = min(int(args.get("n") or 10), 50)
    git_args = ["log", "--oneline", f"-{n}"]
    if args.get("path"):
        git_args.extend(["--", str(args["path"])])
    return _git(git_args, "git_log")


def register_git_tools() -> None:
    registry.register(
        "git_status",
        "Show working tree status (branch + changed files) of the ShopAI repo.",
        {"type": "object", "properties": {}},
        _tool_git_status,
        phase=2,
    )
    registry.register(
        "git_diff",
        "Show unstaged changes of the ShopAI repo. Set stat=true for a summary.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Limit diff to one path"},
                "stat": {"type": "boolean", "description": "Return diffstat only"},
            },
        },
        _tool_git_diff,
        phase=2,
    )
    registry.register(
        "git_log",
        "Show recent commits of the ShopAI repo.",
        {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of commits, default 10, max 50"},
                "path": {"type": "string", "description": "Limit to one path"},
            },
        },
        _tool_git_log,
        phase=2,
    )
