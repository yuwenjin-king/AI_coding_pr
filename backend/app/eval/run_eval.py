"""Regression eval CLI: run the fixed scenario set against a live backend.

Usage:
    cd backend && .venv/bin/python -m app.eval.run_eval [--base-url http://127.0.0.1:8000]

Requires a real LLM key (that is the point). Tickets are matched by code from
the seeded workbench; each scenario starts a fresh run and polls to a terminal
status, then scores it and prints a Markdown report.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

from app.eval.scenarios import DEFAULT_SCENARIOS
from app.eval.scorer import score_run, summarize

TERMINAL = {"succeeded", "failed", "cancelled", "needs_review"}


def _request(base_url: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base_url}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _run_scenario(base_url: str, ticket_id: int, poll_seconds: float, timeout_s: int) -> dict:
    run = _request(base_url, f"/api/tickets/{ticket_id}/runs", method="POST")
    run_id = run["id"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        run = _request(base_url, f"/api/runs/{run_id}")
        if run["status"] in TERMINAL:
            # needs_review can bounce back to running (review/rework still in
            # flight) — only accept a terminal status once the run stops moving
            snapshot = json.dumps(run, sort_keys=True)
            time.sleep(max(poll_seconds, 8))
            again = _request(base_url, f"/api/runs/{run_id}")
            if json.dumps(again, sort_keys=True) == snapshot:
                return again
            run = again
        time.sleep(poll_seconds)
    return {**run, "status": "timeout"}


def main() -> int:
    parser = argparse.ArgumentParser(description="CodePilot regression eval")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=900, help="per-run seconds")
    parser.add_argument("--out", default="eval_report.json")
    parser.add_argument("--phase", type=int, default=None, help="override AGENT_PHASE check source")
    parser.add_argument(
        "--only", action="append", default=None,
        help="run only these ticket codes (repeatable), e.g. --only BUG-1026",
    )
    args = parser.parse_args()

    health = _request(args.base_url, "/api/health")
    phase = args.phase if args.phase is not None else health.get("phase", 0)
    print(f"backend: {args.base_url} · AGENT_PHASE={phase}")

    tickets = _request(args.base_url, "/api/tickets")
    by_code = {t["code"]: t["id"] for t in tickets}

    all_results: dict[str, list] = {}
    for scenario in DEFAULT_SCENARIOS:
        if args.only and scenario.ticket_code not in args.only:
            continue
        if phase < scenario.min_phase:
            print(f"\n### 跳过 {scenario.ticket_code}（需要 Phase ≥ {scenario.min_phase}）")
            continue
        ticket_id = by_code.get(scenario.ticket_code)
        if ticket_id is None:
            print(f"\n### 跳过 {scenario.ticket_code}（工单不存在，先跑 seed）")
            continue

        print(f"\n### {scenario.ticket_code} · {scenario.name} …", flush=True)
        started = time.time()
        try:
            run = _run_scenario(args.base_url, ticket_id, args.poll_seconds, args.timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  运行失败：{exc}")
            continue
        elapsed = int(time.time() - started)

        results = score_run(scenario, type("RunView", (), run)())
        all_results[f"{scenario.ticket_code} {scenario.name}"] = results
        stats = json.loads(run.get("stats_json") or "{}")
        print(f"  状态 {run['status']} · {elapsed}s · LLM {stats.get('llm_calls', '?')} 次 · "
              f"tokens {stats.get('prompt_tokens', '?')}+{stats.get('completion_tokens', '?')}")
        for r in results:
            mark = "✅" if r.passed else "❌"
            print(f"  {mark} {r.name}: {r.detail}")

    summary = summarize(all_results)
    print("\n## 汇总")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "summary": summary,
                "results": {
                    k: [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in v]
                    for k, v in all_results.items()
                },
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    print(f"报告已写入 {args.out}")
    return 0 if summary["scenario_pass_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
