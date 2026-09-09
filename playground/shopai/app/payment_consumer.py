"""In-process Kafka-like payment event consumer.

BUG-1024 fix:
Use event_id-based deduplication instead of skipping on redelivered flag.
mark_paid() is inherently idempotent (setting status to "PAID" repeatedly
has no side effect), so we should always apply the transition for valid events.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.order_service import store


@dataclass
class PaymentSucceeded:
    event_id: str
    order_id: str
    redelivered: bool = False


class PaymentConsumer:
    def __init__(self) -> None:
        self._processed_events: set[str] = set()

    def handle(self, event: PaymentSucceeded) -> None:
        if event.event_id in self._processed_events:
            return
        self._processed_events.add(event.event_id)
        order = store.get(event.order_id)
        if order is None:
            return
        store.mark_paid(event.order_id)


consumer = PaymentConsumer()
