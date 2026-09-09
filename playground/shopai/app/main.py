from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.order_service import store
from app.payment_consumer import PaymentSucceeded, consumer

app = FastAPI(title="ShopAI")


class CreateOrderBody(BaseModel):
    order_id: str


class PayBody(BaseModel):
    order_id: str
    event_id: str
    simulate_first_delivery_failure: bool = False


@app.post("/orders")
def create_order(body: CreateOrderBody):
    return store.create(body.order_id)


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = store.get(order_id)
    if not order:
        raise HTTPException(404, "order not found")
    return order


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    """Cancel an order. Only pending orders can be cancelled."""
    try:
        return store.cancel_order(order_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, "order not found")


@app.post("/payments/callback")
def payment_callback(body: PayBody):
    """Payment gateway webhook. Publishes PaymentSucceeded to the consumer."""
    order = store.get(body.order_id)
    if not order:
        raise HTTPException(404, "order not found")
    first = PaymentSucceeded(
        event_id=body.event_id,
        order_id=body.order_id,
        redelivered=False,
    )
    if body.simulate_first_delivery_failure:
        # Broker retries; consumer sees redelivered=True
        consumer.handle(
            PaymentSucceeded(
                event_id=body.event_id,
                order_id=body.order_id,
                redelivered=True,
            )
        )
    else:
        consumer.handle(first)
    return store.get(body.order_id)
