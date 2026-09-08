"""Tool registry with phase-based gating.

Tools register with a `phase` number; the agent only sees tools whose
phase <= settings.agent_phase, so bumping AGENT_PHASE forward (or back)
enables (or rolls back) capabilities without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: str
    blocked: bool = False


ToolFn = Callable[[dict[str, Any]], ToolResult]


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn
    phase: int
    readonly: bool

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        fn: ToolFn,
        *,
        phase: int = 1,
        readonly: bool = True,
    ) -> None:
        self._tools[name] = ToolDef(name, description, parameters, fn, phase, readonly)

    def names(self, *, phase: int) -> list[str]:
        return sorted(t.name for t in self._tools.values() if t.phase <= phase)

    def schemas_for_phase(self, *, phase: int) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values() if t.phase <= phase]

    def call(self, name: str, arguments: dict[str, Any] | str) -> ToolResult:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(name=name, ok=False, output=f"unknown tool: {name}")
        try:
            return tool.fn(arguments if isinstance(arguments, dict) else {})
        except Exception as exc:  # noqa: BLE001 — tool failures become observations
            return ToolResult(name=name, ok=False, output=f"tool error: {exc}")


registry = ToolRegistry()
