"""Tool layer: phase gating, sandbox escapes, real git/run_test execution."""

from app.tools import registry


def test_phase1_exposes_only_readonly():
    names = registry.names(phase=1)
    assert set(names) == {"list_dir", "read_file", "search_code"}


def test_phase2_adds_git_and_test_tools():
    names = registry.names(phase=2)
    assert {"git_status", "git_diff", "git_log", "run_test"} <= set(names)


def test_phase4_adds_write_tools():
    names = registry.names(phase=4)
    assert {"write_file", "create_branch", "git_commit"} <= set(names)
    assert "deploy_service" not in names  # phase 6


def test_schemas_match_names():
    schemas = registry.schemas_for_phase(phase=2)
    assert {s["function"]["name"] for s in schemas} == set(registry.names(phase=2))


def test_path_escape_is_blocked():
    result = registry.call("read_file", {"path": "../../etc/passwd"})
    assert not result.ok
    assert "escapes sandbox" in result.output


def test_search_code_finds_payment_logic():
    result = registry.call("search_code", {"query": "mark_paid"})
    assert result.ok
    assert "order_service.py" in result.output


def test_run_test_reports_xfail():
    result = registry.call("run_test", {})
    assert result.ok
    assert "exit=0" in result.output
    assert "passed" in result.output  # real pytest ran; count depends on playground state


def test_git_log_and_status():
    log = registry.call("git_log", {"n": 3})
    assert log.ok and log.output.strip()
    status = registry.call("git_status", {})
    assert status.ok and "## " in status.output


def test_write_tools_still_blocked_when_called():
    result = registry.call("write_file", {"path": "app/main.py"})
    assert result.blocked and not result.ok


def test_tool_exception_becomes_observation(monkeypatch):
    def boom(_args):
        raise RuntimeError("subprocess exploded")

    monkeypatch.setitem(registry._tools, "run_test", type(registry._tools["run_test"])(
        "run_test", "", {}, boom, 2, True,
    ))
    result = registry.call("run_test", {})
    assert not result.ok
    assert "tool error" in result.output
