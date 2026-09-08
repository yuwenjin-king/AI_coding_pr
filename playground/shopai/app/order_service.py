"""ShopAI order domain.

States: pending -> PAID | cancelled
"""

from dataclasses import dataclass, field


@dataclass
class Order:
    id: str
    status: str = "pending"
    paid: bool = False


class OrderStore:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def create(self, order_id: str) -> Order:
        order = Order(id=order_id)
        self._orders[order_id] = order
        return order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def mark_paid(self, order_id: str) -> Order:
        order = self._orders[order_id]
        order.status = "PAID"
        order.paid = True
        return order

    def clear(self) -> None:
        self._orders.clear()


store = OrderStore()
