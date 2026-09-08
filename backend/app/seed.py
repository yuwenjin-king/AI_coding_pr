from app.config import settings
from app.models import Project, Ticket


SEED_TICKETS = [
    {
        "code": "BUG-1024",
        "type": "BUG",
        "title": "支付成功后订单状态未更新",
        "description": (
            "用户反馈：订单支付成功之后，偶尔订单状态还是 pending。\n"
            "环境：生产环境（ShopAI 靶场复现）\n"
            "影响：大约 1% 的订单\n"
            "现象：支付网关已扣款成功，订单仍为 pending，未变成 PAID。\n"
            "请分析订单状态机、支付回调与消息消费逻辑。"
        ),
        "status": "open",
    },
    {
        "code": "REQ-1025",
        "type": "REQ",
        "title": "增加取消订单功能",
        "description": (
            "需求：订单列表增加「取消订单」功能。\n"
            "约束：\n"
            "- 用户只能取消待支付订单\n"
            "- 支付完成后不能取消\n"
            "- 取消后需要恢复库存"
        ),
        "status": "open",
    },
    {
        "code": "BUG-1026",
        "type": "BUG",
        "title": "库存扣减偶发失败",
        "description": (
            "下单时库存扣减偶发失败。历史类似问题见知识库 BUG-387"
            "（Redis 库存与 MySQL 并发不一致）。"
        ),
        "status": "open",
    },
]


def seed_if_empty(db) -> None:
    project = db.query(Project).filter_by(name="ShopAI").one_or_none()
    if project is None:
        project = Project(name="ShopAI", repo_path=str(settings.shopai_path))
        db.add(project)
        db.flush()
    for item in SEED_TICKETS:
        if db.query(Ticket).filter_by(code=item["code"]).one_or_none():
            continue
        db.add(Ticket(project_id=project.id, **item))
    db.commit()
