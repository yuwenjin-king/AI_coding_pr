"""Guardrails: keep the agent from committing secrets or oversized changes.

Used by write_file (content scan before it touches disk) and by the coding
finalizer (diff size budget before a run can reach needs_review).
"""

from __future__ import annotations

import re

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI/DashScope style API key (sk-…)"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id (AKIA…)"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "GitHub token (ghp_…)"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token (xox…)"),
]


def scan_secrets(text: str, max_hits: int = 3) -> list[str]:
    """Descriptions of secret-looking patterns found in `text` (capped)."""
    hits: list[str] = []
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(text):
            hits.append(label)
            if len(hits) >= max_hits:
                break
    return hits


def diff_change_lines(diff: str) -> int:
    """Count actual changed lines (+/-) in a unified diff, headers excluded."""
    count = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            count += 1
    return count
