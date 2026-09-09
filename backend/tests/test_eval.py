"""Phase 6: eval scorer pure logic (no network)."""

from types import SimpleNamespace

from app.eval.scenarios import DEFAULT_SCENARIOS, Scenario
from app.eval.scorer import score_run, summarize


def _run(**kw):
    base = {"status": "needs_review", "report_md": "# Root Cause\nx", "diff_md": "", "test_summary": ""}
    base.update(kw)
    return SimpleNamespace(**base)


def test_score_run_all_pass():
    scenario = Scenario(
        ticket_code="T-1", name="t", min_phase=4,
        expect_diff_files=["payment_consumer.py"],
        expect_report_contains=["Root Cause"],
        expect_tests_contains="2 passed",
    )
    run = _run(diff_md="diff --git a/app/payment_consumer.py", test_summary="2 passed in 0.1s")
    results = score_run(scenario, run)
    assert all(c.passed for c in results), [c.detail for c in results]


def test_score_run_reports_failures():
    scenario = Scenario(ticket_code="T-1", name="t", min_phase=4, expect_status=["needs_review"], expect_diff_files=["order_service.py"])
    run = _run(status="failed", diff_md="unrelated")
    results = score_run(scenario, run)
    statuses = {c.name: c.passed for c in results}
    assert statuses["终态状态"] is False
    # diff expectations only scored for runs actually up for review
    assert not any("Diff" in c.name for c in results)

    run_review = _run(status="needs_review", diff_md="unrelated")
    statuses = {c.name: c.passed for c in score_run(scenario, run_review)}
    assert statuses["终态状态"] is True
    assert statuses["Diff 包含 'order_service.py'"] is False


def test_analysis_scenario_skips_diff_checks():
    scenario = next(s for s in DEFAULT_SCENARIOS if s.ticket_code == "BUG-1026")
    run = _run(status="succeeded", report_md="参考 BUG-387 的经验")
    results = score_run(scenario, run)
    assert all(c.passed for c in results)
    assert not any("Diff" in c.name for c in results)  # no diff expectations for analysis


def test_summarize_rates():
    scenario = Scenario(ticket_code="T-1", name="t", min_phase=1)
    good = score_run(scenario, _run())
    bad = score_run(scenario, _run(status="failed"))
    summary = summarize({"good": good, "bad": bad})
    assert summary["scenarios_total"] == 2
    assert summary["scenarios_passed"] == 1
    assert summary["scenario_pass_rate"] == 0.5
