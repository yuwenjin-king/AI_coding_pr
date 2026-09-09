import pytest

from app.order_service import store
from app.payment_consumer import PaymentSucceeded, consumer


@pytest.fixture(autouse=True)
def _reset_store():
    store.clear()
    consumer._processed_events.clear()
    yield
    store.clear()
    consumer._processed_events.clear()


def test_happy_path_marks_paid():
    store.create("o1")
    consumer.handle(PaymentSucceeded(event_id="e1", order_id="o1", redelivered=False))
    assert store.get("o1").status == "PAID"


def test_redelivery_should_still_mark_paid():
    """BUG-1024 regression: redelivered events must still mark the order as paid."""
    store.create("o2")
    consumer.handle(PaymentSucceeded(event_id="e2", order_id="o2", redelivered=True))
    assert store.get("o2").status == "PAID"


def test_duplicate_event_id_is_ignored():
    """Idempotency: same event_id delivered twice should only process once."""
    store.create("o3")
    consumer.handle(PaymentSucceeded(event_id="e3", order_id="o3", redelivered=False))
    consumer.handle(PaymentSucceeded(event_id="e3", order_id="o3", redelivered=False))
    assert store.get("o3").status == "PAID"
