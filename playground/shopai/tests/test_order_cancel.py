"""Tests for order cancellation (REQ-1025)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.order_service import OrderItem, inventory, store
from app.payment_consumer import PaymentSucceeded, consumer

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    store.clear()
    inventory.clear()
    consumer._processed_events.clear()
    yield
    store.clear()
    inventory.clear()
    consumer._processed_events.clear()


# --- Unit tests: OrderStore.cancel_order ---


def test_cancel_pending_order_changes_status():
    """Cancel on a pending order should transition to 'cancelled'."""
    store.create("o1")
    result = store.cancel_order("o1")
    assert result.status == "cancelled"


def test_cancel_paid_order_raises_error():
    """Cancel on an already paid order should raise ValueError."""
    store.create("o2")
    store.mark_paid("o2")
    with pytest.raises(ValueError, match="Only pending orders can be cancelled"):
        store.cancel_order("o2")


def test_cancel_already_cancelled_order_raises_error():
    """Cancel on an already cancelled order should raise ValueError."""
    store.create("o3")
    store.cancel_order("o3")
    with pytest.raises(ValueError, match="Only pending orders can be cancelled"):
        store.cancel_order("o3")


def test_cancel_nonexistent_order_raises_keyerror():
    """Cancel on a non-existent order should raise KeyError."""
    with pytest.raises(KeyError):
        store.cancel_order("nonexistent")


def test_cancel_restores_inventory():
    """Cancelling a pending order should restore reserved inventory."""
    product_id = "p1"
    inventory.set_stock(product_id, 100)
    items = [OrderItem(product_id=product_id, quantity=5)]
    store.create("o4", items=items)
    # Stock should be reduced by 5
    assert inventory._stock[product_id] == 95
    store.cancel_order("o4")
    # Stock should be restored to original
    assert inventory._stock[product_id] == 100


def test_cancel_multiple_items_restores_all():
    """Cancelling an order with multiple items restores all inventory."""
    p1, p2 = "p1", "p2"
    inventory.set_stock(p1, 50)
    inventory.set_stock(p2, 30)
    items = [
        OrderItem(product_id=p1, quantity=10),
        OrderItem(product_id=p2, quantity=8),
    ]
    store.create("o5", items=items)
    assert inventory._stock[p1] == 40
    assert inventory._stock[p2] == 22
    store.cancel_order("o5")
    assert inventory._stock[p1] == 50
    assert inventory._stock[p2] == 30


# --- Integration tests: API endpoint ---


def test_api_cancel_pending_order():
    """POST /orders/{id}/cancel on pending order returns 200."""
    store.create("o6")
    resp = client.post("/orders/o6/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"


def test_api_cancel_paid_order_returns_400():
    """POST /orders/{id}/cancel on paid order returns 400."""
    store.create("o7")
    store.mark_paid("o7")
    resp = client.post("/orders/o7/cancel")
    assert resp.status_code == 400


def test_api_cancel_already_cancelled_returns_400():
    """POST /orders/{id}/cancel on already cancelled order returns 400."""
    store.create("o8")
    client.post("/orders/o8/cancel")
    resp = client.post("/orders/o8/cancel")
    assert resp.status_code == 400


def test_api_cancel_nonexistent_returns_404():
    """POST /orders/{id}/cancel on nonexistent order returns 404."""
    resp = client.post("/orders/nonexistent/cancel")
    assert resp.status_code == 404


def test_api_cancel_with_inventory_restoration():
    """Cancel via API restores inventory correctly."""
    product_id = "p3"
    inventory.set_stock(product_id, 200)
    items = [OrderItem(product_id=product_id, quantity=10)]
    store.create("o9", items=items)
    assert inventory._stock[product_id] == 190
    resp = client.post("/orders/o9/cancel")
    assert resp.status_code == 200
    assert inventory._stock[product_id] == 200


def test_cancel_then_pay_is_prevented():
    """After cancel, paying the order should not change status back."""
    store.create("o10")
    store.cancel_order("o10")
    # Even if payment event arrives after cancel, status stays cancelled
    consumer.handle(PaymentSucceeded(event_id="e10", order_id="o10"))
    assert store.get("o10").status == "cancelled"
