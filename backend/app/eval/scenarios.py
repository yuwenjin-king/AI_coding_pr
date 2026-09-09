"""Evaluation scenarios: fixed ticket set with machine-checkable expectations.

Used by `python -m app.eval.run_eval` against a live backend (real LLM key
required). The scorer is pure logic and unit-tested with fabricated runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scenario:
    ticket_code: str
    name: str
    min_phase: int  # scenario only makes sense at this AGENT_PHASE or above
    # terminal status(es) that count as the scenario's expected outcome — a list
    # because mode depends on phase (BUG tickets analyse at 3, code at 4+).
    expect_status: list[str] = field(default_factory=lambda: ["needs_review"])
    expect_diff_files: list[str] = field(default_factory=list)  # substrings of diff_md
    expect_report_contains: list[str] = field(default_factory=list)  # substrings of report_md
    expect_tests_contains: str | None = None  # substring of test_summary


DEFAULT_SCENARIOS: list[Scenario] = [
    Scenario(
        ticket_code="BUG-1024",
        name="BUG 修复闭环：重投递未标记 PAID",
        min_phase=4,
        expect_status=["needs_review"],
        expect_diff_files=["payment_consumer.py", "test_payment_status.py"],
        expect_report_contains=["Root Cause"],
        expect_tests_contains="passed",
    ),
    Scenario(
        ticket_code="BUG-1026",
        name="RAG 检索引用：库存扣减参考 BUG-387",
        min_phase=3,
        # phase 3 分析 → succeeded；phase 4+ 走 coding → needs_review
        expect_status=["succeeded", "needs_review"],
        expect_report_contains=["BUG-387"],
    ),
    Scenario(
        ticket_code="REQ-1025",
        name="多 Agent 需求交付：取消订单功能",
        min_phase=5,
        expect_status=["needs_review"],
        expect_diff_files=["order"],
        expect_report_contains=["Review Agent"],
        expect_tests_contains="passed",
    ),
]
