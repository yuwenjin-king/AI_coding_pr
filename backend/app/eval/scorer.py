"""Pure scoring logic: a run snapshot against a Scenario's expectations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.eval.scenarios import Scenario


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def score_run(scenario: Scenario, run: Any) -> list[CheckResult]:
    """`run` is any object with status/report_md/diff_md/test_summary attributes."""
    results: list[CheckResult] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append(CheckResult(name, ok, detail))

    status = getattr(run, "status", None)
    check(
        "终态状态",
        status in scenario.expect_status,
        f"期望 {'/'.join(scenario.expect_status)}，实际 {status}",
    )

    report = getattr(run, "report_md", None) or ""
    for needle in scenario.expect_report_contains:
        check(f"报告包含 {needle!r}", needle in report, "命中" if needle in report else "未命中")

    if status == "needs_review":  # diff/test expectations only apply to coding runs up for review
        diff = getattr(run, "diff_md", None) or ""
        for fragment in scenario.expect_diff_files:
            hit = fragment in diff
            check(f"Diff 包含 {fragment!r}", hit, "命中" if hit else "未命中")
        tests = getattr(run, "test_summary", None) or ""
        if scenario.expect_tests_contains:
            hit = scenario.expect_tests_contains in tests
            check(
                f"测试输出包含 {scenario.expect_tests_contains!r}",
                hit,
                (tests.splitlines()[-1] if tests else "(空)")[:120],
            )
    return results


def summarize(all_results: dict[str, list[CheckResult]]) -> dict[str, Any]:
    total = sum(len(r) for r in all_results.values())
    passed = sum(1 for r in all_results.values() for c in r if c.passed)
    scenarios_passed = sum(1 for r in all_results.values() if all(c.passed for c in r))
    return {
        "checks_total": total,
        "checks_passed": passed,
        "check_pass_rate": round(passed / total, 3) if total else None,
        "scenarios_total": len(all_results),
        "scenarios_passed": scenarios_passed,
        "scenario_pass_rate": round(scenarios_passed / len(all_results), 3) if all_results else None,
    }
