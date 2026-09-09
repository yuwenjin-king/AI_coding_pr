"""Generic ReAct loop: LLM → tool calls → observations → … → final answer.

The loop is transport/persistence agnostic — it emits trace events through
`on_event` and lets callers (task agent now, sub-agents in Phase 5) decide
how to persist them.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.llm import gateway
from app.tools import registry

TOOL_OUTPUT_FOR_MODEL = 8000
TOOL_OUTPUT_FOR_TRACE = 4000
ARGS_FOR_TRACE = 200  # write_file echoes full file content — keep traces bounded


class AgentLoopError(RuntimeError):
    """Loop could not reach a final answer."""


def run_agent_loop(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_steps: int,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    llm=None,
) -> str:
    """Drive the tool-calling loop until the model answers without tool calls.

    Returns the final assistant text. Raises AgentLoopError when `max_steps`
    is exhausted, or whatever the LLM gateway raises on transport errors.
    """

    def emit(event: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event)

    if llm is None:
        llm = gateway

    for step in range(1, max_steps + 1):
        message, meta = llm.chat(messages, tools=tools)
        tool_calls = message.tool_calls or []
        emit(
            {
                "step": step,
                "type": "llm",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": (tc.function.arguments or "")[:ARGS_FOR_TRACE],
                    }
                    for tc in tool_calls
                ],
                "meta": meta,
            }
        )
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        if not tool_calls:
            return message.content or ""

        for tc in tool_calls:
            result = registry.call(tc.function.name, tc.function.arguments)
            try:
                args_echo = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args_echo = {"raw": tc.function.arguments}
            args_echo = {
                k: v if not isinstance(v, str) or len(v) <= ARGS_FOR_TRACE else v[:ARGS_FOR_TRACE] + "…"
                for k, v in args_echo.items()
            }
            emit(
                {
                    "step": step,
                    "type": "tool",
                    "name": result.name,
                    "arguments": args_echo,
                    "ok": result.ok,
                    "blocked": result.blocked,
                    "output": result.output[:TOOL_OUTPUT_FOR_TRACE],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.output[:TOOL_OUTPUT_FOR_MODEL],
                }
            )

    raise AgentLoopError(f"exceeded max steps ({max_steps}) without a final report")
