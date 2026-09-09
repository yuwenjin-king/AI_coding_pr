"""Run the playground test suite as an observation tool."""

from __future__ import annotations

import subprocess
import sys

from app.config import settings
from app.runtime.workspace import current_shopai_path
from app.tools.registry import ToolResult, registry

_MAX_OUTPUT = 10000


def _tool_run_test(args: dict) -> ToolResult:
    target = str(args.get("path") or "tests")
    keyword = str(args.get("keyword") or "").strip()
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", target]
    if keyword:
        cmd.extend(["-k", keyword])
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(current_shopai_path()),
            capture_output=True,
            text=True,
            timeout=settings.test_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ToolResult("run_test", False, f"pytest timed out after {settings.test_timeout_seconds}s")
    output = (proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")).strip()
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n...[truncated]"
    summary = f"$ {' '.join(cmd)}\nexit={proc.returncode}\n{output or '(no output)'}"
    return ToolResult("run_test", proc.returncode == 0, summary)


def register_testing_tools() -> None:
    registry.register(
        "run_test",
        "Run pytest in the ShopAI repo (playground). Returns exit code and output. "
        "Use it to verify current test status (e.g. known xfail cases).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Test path, default 'tests'"},
                "keyword": {"type": "string", "description": "-k expression filter"},
            },
        },
        _tool_run_test,
        phase=2,
    )
