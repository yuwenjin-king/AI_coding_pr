# ShopAI 订单状态机

- pending：已下单未支付
- PAID：支付成功
- cancelled：用户取消（尚未实现，见 REQ-1025）

支付成功事件 `PaymentSucceeded` 由 Kafka 风格消费者处理，调用 `OrderStore.mark_paid`。
