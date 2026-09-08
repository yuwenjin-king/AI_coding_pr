"""Human-in-the-loop gate. Phase 1: always require approval before any write/deploy."""

from enum import Enum


class HitlStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


def can_write(*, hitl_status: str | None) -> bool:
    return False  # Phase 1: never write


def can_deploy(*, hitl_status: str | None) -> bool:
    return hitl_status == HitlStatus.approved.value
