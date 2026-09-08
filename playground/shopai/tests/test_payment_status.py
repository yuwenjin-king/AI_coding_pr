import pytest

from app.order_service import store
from app.payment_consumer import PaymentSucceeded, consumer


@pytest.fixture(autouse=True)
def _reset_store():
    store.clear()
    yield
    store.clear()


def test_happy_path_marks_paid():
    store.create("o1")
    consumer.handle(PaymentSucceeded(event_id="e1", order_id="o1", redelivered=False))
    assert store.get("o1").status == "PAID"


@pytest.mark.xfail(reason="BUG-1024: redelivery skips mark_paid", strict=True)
def test_redelivery_should_still_mark_paid():
    store.create("o2")
    consumer.handle(PaymentSucceeded(event_id="e2", order_id="o2", redelivered=True))
    assert store.get("o2").status == "PAID"
