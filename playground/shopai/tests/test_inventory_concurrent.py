"""Regression tests for BUG-1026: concurrent inventory reserve race condition."""

import threading
import pytest

from app.order_service import OrderItem, inventory


@pytest.fixture(autouse=True)
def _reset():
    inventory.clear()
    yield
    inventory.clear()


def test_concurrent_reserve_same_product():
    """BUG-1026 regression: multiple threads reserving same stock must not oversell."""
    product_id = "p_bug1026"
    inventory.set_stock(product_id, 10)

    results = []
    errors = []

    def try_reserve():
        try:
            ok = inventory.reserve(product_id, 1)
            results.append(ok)
        except Exception as e:
            errors.append(e)

    # Launch 20 threads all trying to reserve 1 unit each (stock is only 10)
    threads = [threading.Thread(target=try_reserve) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Unexpected errors: {errors}"
    # Exactly 10 should succeed, 10 should fail
    assert sum(results) == 10, f"Expected 10 successful reserves, got {sum(results)}"
    # Remaining stock should be 0
    assert inventory._stock[product_id] == 0, \
        f"Stock should be 0 after 10 successful reserves, got {inventory._stock[product_id]}"


def test_concurrent_reserve_different_products():
    """Concurrent reserve on different products should work independently."""
    p1, p2 = "p_a", "p_b"
    inventory.set_stock(p1, 5)
    inventory.set_stock(p2, 3)

    results_p1 = []
    results_p2 = []

    def reserve_p1():
        results_p1.append(inventory.reserve(p1, 1))

    def reserve_p2():
        results_p2.append(inventory.reserve(p2, 1))

    threads = (
        [threading.Thread(target=reserve_p1) for _ in range(10)] +
        [threading.Thread(target=reserve_p2) for _ in range(8)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results_p1) == 5, f"p1: expected 5 successes, got {sum(results_p1)}"
    assert sum(results_p2) == 3, f"p2: expected 3 successes, got {sum(results_p2)}"
    assert inventory._stock[p1] == 0
    assert inventory._stock[p2] == 0


def test_concurrent_restore_same_product():
    """BUG-1026 regression: concurrent restore must also be atomic."""
    product_id = "p_restore"
    inventory.set_stock(product_id, 10)

    def try_restore():
        inventory.restore(product_id, 1)

    # 5 threads each restoring 1 unit
    threads = [threading.Thread(target=try_restore) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert inventory._stock[product_id] == 15, \
        f"Expected stock 15 after 5 restores, got {inventory._stock[product_id]}"


def test_concurrent_mixed_reserve_and_restore():
    """Mixed concurrent reserve and restore operations."""
    product_id = "p_mixed"
    inventory.set_stock(product_id, 10)

    results_reserve = []

    def do_reserve():
        results_reserve.append(inventory.reserve(product_id, 1))

    def do_restore():
        inventory.restore(product_id, 1)

    # 8 reserves and 3 restores concurrently
    threads = (
        [threading.Thread(target=do_reserve) for _ in range(8)] +
        [threading.Thread(target=do_restore) for _ in range(3)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Net change: -8 + 3 = -5, so stock should be 5
    assert inventory._stock[product_id] == 5, \
        f"Expected stock 5, got {inventory._stock[product_id]}"
    assert sum(results_reserve) == 8, \
        f"Expected 8 successful reserves, got {sum(results_reserve)}"
