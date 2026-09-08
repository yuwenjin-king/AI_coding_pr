"""In-process Kafka-like payment event consumer.

BUG-1024:
Payment gateway may fail the first delivery after charging the user.
The broker redelivers the PaymentSucceeded event. This consumer treats
*any* redelivery as a duplicate and returns early — so the order stays
pending even though money was taken.

This surfaces as ~1% of orders in production (first-attempt processing
errors + retry).
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
    def handle(self, event: PaymentSucceeded) -> None:
        # Incorrect idempotency: skip all retries instead of making
        # mark_paid idempotent and always applying the state transition.
        if event.redelivered:
            return
        order = store.get(event.order_id)
        if order is None:
            return
        store.mark_paid(event.order_id)


consumer = PaymentConsumer()
