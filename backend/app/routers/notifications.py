"""v3.3 站内消息与分类订阅。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db, utcnow
from ..models import Category, CategorySubscription, Notification, User

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications")
def list_notifications(db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = db.scalars(select(Notification).where(Notification.user_id == me.id).order_by(Notification.id.desc()).limit(30)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == me.id, Notification.read_at.is_(None)))
    return {"unread": unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
                                          "read": n.read_at is not None, "created_at": n.created_at} for n in rows]}


def _unread(db: Session, uid: int) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == uid, Notification.read_at.is_(None)))


@router.post("/notifications/read")
def read_all(db: Session = Depends(get_db), me: User = Depends(current_user)):
    """全部已读。"""
    db.execute(update(Notification).where(Notification.user_id == me.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"ok": True, "unread": 0}


@router.post("/notifications/{note_id}/read")
def read_one(note_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """v3.3.20 单条已读：点哪条，只去掉哪条的提醒点。只能标自己的消息；已经读过的不改时间。"""
    n = db.get(Notification, note_id)
    if n is None or n.user_id != me.id:
        raise HTTPException(404, "消息不存在")
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return {"ok": True, "unread": _unread(db, me.id)}


@router.get("/subscriptions")
def my_subscriptions(db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = db.execute(select(Category.code, Category.name).join(CategorySubscription, CategorySubscription.category_id == Category.id)
                      .where(CategorySubscription.user_id == me.id)).all()
    return [{"code": c, "name": n} for c, n in rows]


def _cat(db: Session, code: str) -> Category:
    c = db.scalar(select(Category).where(Category.code == code))
    if c is None:
        raise HTTPException(404, "分类不存在")
    return c


@router.post("/subscriptions/{code}")
def subscribe(code: str, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = _cat(db, code)
    if not db.scalar(select(CategorySubscription).where(CategorySubscription.user_id == me.id, CategorySubscription.category_id == c.id)):
        db.add(CategorySubscription(user_id=me.id, category_id=c.id, last_notified_at=utcnow()))
        try:
            db.commit()
        except IntegrityError:  # v3.3.8 连点时两个请求同时到达：唯一约束挡住第二个，当作已订阅
            db.rollback()
    return {"ok": True, "subscribed": True}


@router.delete("/subscriptions/{code}")
def unsubscribe(code: str, db: Session = Depends(get_db), me: User = Depends(current_user)):
    c = _cat(db, code)
    s = db.scalar(select(CategorySubscription).where(CategorySubscription.user_id == me.id, CategorySubscription.category_id == c.id))
    if s:
        db.delete(s)
        db.commit()
    return {"ok": True, "subscribed": False}
