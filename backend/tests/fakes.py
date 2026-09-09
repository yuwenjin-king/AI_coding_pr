"""Scripted LLM gateway for tests — no network, no API key."""

from types import SimpleNamespace


def fake_tool_call(id_: str, name: str, arguments: str):
    return SimpleNamespace(
        id=id_,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def fake_message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class FakeGateway:
    """Returns queued responses in order; records every request."""

    def __init__(self, responses, usage: dict | None = None):
        self.responses = list(responses)
        self.requests = []
        self.usage = usage

    def chat(self, messages, tools=None, tool_choice=None):
        self.requests.append(
            {"messages": [m["role"] for m in messages], "tools": tools, "raw": [dict(m) for m in messages]}
        )
        if not self.responses:
            raise AssertionError("FakeGateway exhausted")
        return (
            self.responses.pop(0),
            {"model": "fake", "latency_ms": 1, "usage": dict(self.usage) if self.usage else None},
        )
