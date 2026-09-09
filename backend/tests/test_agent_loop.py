"""Agent loop behavior with a scripted LLM."""

import pytest

from app.runtime.agent_loop import AgentLoopError, run_agent_loop
from tests.fakes import FakeGateway, fake_message, fake_tool_call


def _msgs():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
    ]


def test_loop_runs_tool_then_finishes():
    gw = FakeGateway([
        fake_message(None, [fake_tool_call("c1", "list_dir", "{}")]),
        fake_message(None, [fake_tool_call("c2", "run_test", "{}")]),
        fake_message("最终报告：AI Confidence 90"),
    ])
    events = []
    report = run_agent_loop(messages=_msgs(), tools=None, max_steps=6, on_event=events.append, llm=gw)

    assert report == "最终报告：AI Confidence 90"
    kinds = [(e["type"], e.get("name")) for e in events]
    assert kinds == [
        ("llm", None),
        ("tool", "list_dir"),
        ("llm", None),
        ("tool", "run_test"),
        ("llm", None),
    ]
    tool_event = events[3]  # the run_test observation
    assert tool_event["ok"] is True
    assert tool_event["arguments"] == {}
    assert "passed" in tool_event["output"]  # real pytest ran in the playground
    # the model saw both observations before its final answer
    assert gw.requests[2]["messages"] == ["system", "user", "assistant", "tool", "assistant", "tool"]


def test_loop_uses_provided_tools_schema():
    gw = FakeGateway([fake_message("done")])
    tools = [{"type": "function", "function": {"name": "x"}}]
    run_agent_loop(messages=_msgs(), tools=tools, max_steps=2, llm=gw)
    assert gw.requests[0]["tools"] == tools


def test_tool_failure_is_observation_not_crash():
    gw = FakeGateway([
        fake_message(None, [fake_tool_call("c1", "read_file", '{"path": "../../etc/passwd"}')]),
        fake_message("报告"),
    ])
    events = []
    run_agent_loop(messages=_msgs(), max_steps=4, on_event=events.append, llm=gw)
    tool_event = events[1]
    assert tool_event["ok"] is False
    assert "escapes sandbox" in tool_event["output"]


def test_max_steps_raises():
    gw = FakeGateway([
        fake_message(None, [fake_tool_call(f"c{i}", "list_dir", "{}")]) for i in range(5)
    ])
    with pytest.raises(AgentLoopError, match="max steps"):
        run_agent_loop(messages=_msgs(), max_steps=3, llm=gw)
