"""v3.3 好用度（口碑）：每位用户只算最近一次打分（已公开的评论），平均后缓存在条目上。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Comment, Item


def recompute(db: Session, item_id: int) -> None:
    rows = db.execute(
        select(Comment.user_id, Comment.rating).where(Comment.item_id == item_id, Comment.status == "visible",
                                                      Comment.rating.is_not(None), Comment.user_id.is_not(None))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
    ).all()
    latest: dict[int, int] = {}
    for uid, r in rows:
        latest.setdefault(uid, r)
    item = db.get(Item, item_id)
    if item is None:
        return
    item.rating_count = len(latest)
    item.rating_avg = (sum(latest.values()) / len(latest)) if latest else None
    db.commit()
