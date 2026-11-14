"""v3.3.48 推荐位排期：置顶在 [pin_starts_at, pin_ends_at) 内才生效（为空表示不限）。"""

from datetime import datetime

from sqlalchemy import and_, case, or_

from ..db import utcnow
from ..models import Item

STATES = {"active": "生效中", "scheduled": "未开始", "expired": "已结束", "none": "未置顶"}


def effective_weight(now: datetime | None = None):
    """首页排序用的 SQL 表达式：生效中的置顶取权重，否则 0。"""
    now = now or utcnow()
    live = and_(Item.pin_weight > 0, or_(Item.pin_starts_at.is_(None), Item.pin_starts_at <= now),
                or_(Item.pin_ends_at.is_(None), Item.pin_ends_at > now))
    return case((live, Item.pin_weight), else_=0)


def state(it: Item, now: datetime | None = None) -> str:
    if not it.pin_weight:
        return "none"
    now = now or utcnow()
    if it.pin_starts_at and it.pin_starts_at > now:
        return "scheduled"
    if it.pin_ends_at and it.pin_ends_at <= now:
        return "expired"
    return "active"


def out(it: Item) -> dict:
    st = state(it)
    return {"weight": it.pin_weight or 0, "starts_at": it.pin_starts_at, "ends_at": it.pin_ends_at, "state": st,
            "state_label": STATES[st]}
