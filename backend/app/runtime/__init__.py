"""Run status machine + checkpoint hooks (Phase 2/6)."""

from enum import Enum


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    needs_review = "needs_review"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
