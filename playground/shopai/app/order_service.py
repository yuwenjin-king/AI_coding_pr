"""ShopAI order domain.

States: pending -> PAID | cancelled
"""

from dataclasses import dataclass, field


@dataclass
class OrderItem:
    product_id: str
    quantity: int


@dataclass
class Order:
    id: str
    status: str = "pending"
    paid: bool = False
    items: list[OrderItem] = field(default_factory=list)


class InventoryStore:
    """Simple in-process inventory store."""

    def __init__(self) -> None:
        self._stock: dict[str, int] = {}

    def set_stock(self, product_id: str, quantity: int) -> None:
        self._stock[product_id] = quantity

    def reserve(self, product_id: str, quantity: int) -> bool:
        current = self._stock.get(product_id, 0)
        if current < quantity:
            return False
        self._stock[product_id] = current - quantity
        return True

    def restore(self, product_id: str, quantity: int) -> None:
        current = self._stock.get(product_id, 0)
        self._stock[product_id] = current + quantity

    def clear(self) -> None:
        self._stock.clear()


class OrderStore:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def create(self, order_id: str, items: list[OrderItem] | None = None) -> Order:
        order = Order(id=order_id, items=items or [])
        self._orders[order_id] = order
        # Reserve inventory for each item
        for item in order.items:
            inventory.reserve(item.product_id, item.quantity)
        return order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def mark_paid(self, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status != "pending":
            return order
        order.status = "PAID"
        order.paid = True
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status != "pending":
            raise ValueError("Only pending orders can be cancelled")
        order.status = "cancelled"
        # Restore inventory for each item
        for item in order.items:
            inventory.restore(item.product_id, item.quantity)
        return order

    def clear(self) -> None:
        self._orders.clear()


store = OrderStore()
inventory = InventoryStore()
