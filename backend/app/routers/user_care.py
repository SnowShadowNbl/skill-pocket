"""v3.3.57 后台批次 4c：给单个用户发站内消息、以用户视角只读查看、站内消息已读率。

- 发消息需要 send_message 能力（超级管理员、管理员、客服），每个管理员每天最多 DAILY_LIMIT 条。
- 以用户视角查看需要 view_as_user 能力：先开一个 15 分钟的只读会话（必填原因，写日志），之后按分区读取，每次读取也记一条日志。
  只读接口不返回邮箱、令牌、验证码等敏感信息。
"""

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..auth import client_ip, require_admin
from ..config import settings
from ..db import get_db, utcnow
from ..models import (Category, CategorySubscription, Comment, CompareRun, FavDimension, Favorite, FavFolder,
                      FavoriteFolderLink, Item, Notification, User)
from ..services import activity, notify, permissions, users

router = APIRouter(prefix="/api/admin", tags=["admin-user-care"], dependencies=[Depends(require_admin)])

DAILY_LIMIT = 50
VIEW_TTL = 15 * 60
_ser = URLSafeTimedSerializer(settings.secret_key, salt="view-as-user")
KIND_LABELS = {"admin_message": "管理员消息", "feedback_reply": "反馈回复", "new_items": "订阅上新", "release": "新版本发布",
               "system": "系统提醒", "announcement": "公告"}
SECTIONS = {"pocket": "口袋", "subscriptions": "订阅", "notifications": "消息", "comments": "使用日志 / 评论", "compares": "对比"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _need(me: User, cap: str, what: str):
    if cap not in permissions.capabilities(me.role):
        _err(403, "no_permission", f"当前角色（{permissions.ROLE_LABELS.get(me.role, me.role)}）不能{what}")


def _user(db: Session, uid: int) -> User:
    u = db.get(User, uid)
    if u is None:
        _err(404, "not_found", "用户不存在")
    return u


# ---------------------------------------------------------------- 单发站内消息
class MessageIn(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=500)
    reason: str = Field("", max_length=300)
    link: str = Field("", max_length=300)


def _fill(text: str, u: User) -> str:
    return text.replace("{nickname}", u.nickname or "你").replace("{id}", str(u.id))


@router.post("/users/{user_id}/messages")
def send_message(user_id: int, body: MessageIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    _need(me, "send_message", "给用户发消息")
    u = _user(db, user_id)
    if u.status in ("deleted", "merged"):
        _err(400, "bad_target", "这个账号已注销或已合并，不能发消息")
    if len(body.reason.strip()) < 2:
        _err(400, "reason_required", "请填写原因")
    if body.link and not body.link.startswith("/"):
        _err(400, "bad_link", "链接只能是站内路径，例如 /items/12")
    day = utcnow() - timedelta(days=1)
    sent = db.scalar(select(func.count()).select_from(Notification).where(Notification.sender_id == me.id, Notification.created_at >= day)) or 0
    if sent >= DAILY_LIMIT:
        _err(429, "rate_limited", f"每个管理员 24 小时内最多发 {DAILY_LIMIT} 条消息")
    n = Notification(user_id=u.id, kind="admin_message", title=_fill(body.title.strip(), u)[:200], body=_fill(body.text.strip(), u)[:500],
                     link=body.link.strip(), sender_id=me.id)
    db.add(n)
    db.commit()
    activity.record("user_message", f"给用户发消息：{users.label(u)}「{n.title}」", user=me, target_type="user", target_id=u.id,
                    ip=client_ip(request), reason=body.reason.strip(), after={"title": n.title, "text": n.body[:200]}, target_label=users.label(u))
    return _msg_out(db, n, {me.id: me})


def _msg_out(db: Session, n: Notification, who: dict) -> dict:
    s = who.get(n.sender_id) or (db.get(User, n.sender_id) if n.sender_id else None)
    return {"id": n.id, "kind": n.kind, "kind_label": KIND_LABELS.get(n.kind, n.kind), "title": n.title, "text": n.body, "link": n.link,
            "by": {"id": s.id, "label": users.label(s)} if s else None, "at": n.created_at, "read_at": n.read_at}


@router.get("/users/{user_id}/messages")
def list_messages(user_id: int, kind: str = Query("admin_message", pattern="^(admin_message|all)$"), page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    _user(db, user_id)
    stmt = select(Notification).where(Notification.user_id == user_id)
    if kind != "all":
        stmt = stmt.where(Notification.kind == kind)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.sender_id for r in rows if r.sender_id} or {-1})))}
    return {"total": total, "page": page, "page_size": page_size, "daily_limit": DAILY_LIMIT, "items": [_msg_out(db, n, who) for n in rows]}


@router.get("/messages/stats")
def message_stats(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """已读率：按消息类型统计发送数和已读数。注意用户点「全部已读」也算已读，已读率偏高。"""
    since = utcnow() - timedelta(days=days)
    rows = db.execute(select(Notification.kind, Notification.read_at).where(Notification.created_at >= since)).all()
    sent, read = Counter(), Counter()
    for k, r in rows:
        sent[k] += 1
        if r is not None:
            read[k] += 1
    total_s, total_r = sum(sent.values()), sum(read.values())
    rate = lambda r, s: round(r / s, 3) if s else None  # noqa: E731
    return {"days": days, "sent": total_s, "read": total_r, "read_rate": rate(total_r, total_s),
            "by_type": [{"type": k, "label": KIND_LABELS.get(k, k), "sent": v, "read": read[k], "read_rate": rate(read[k], v)}
                        for k, v in sent.most_common()]}


# ---------------------------------------------------------------- 以用户视角只读查看
class ViewIn(BaseModel):
    reason: str = Field("", max_length=300)


@router.post("/users/{user_id}/view-sessions")
def open_view(user_id: int, body: ViewIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    _need(me, "view_as_user", "以用户视角查看")
    u = _user(db, user_id)
    if len(body.reason.strip()) < 4:
        _err(400, "reason_required", "请填写原因（至少 4 个字）")
    sid = _ser.dumps({"a": me.id, "u": u.id})
    activity.record("view_as_user", f"以用户视角查看：{users.label(u)}", user=me, target_type="user", target_id=u.id, ip=client_ip(request),
                    reason=body.reason.strip(), target_label=users.label(u))
    return {"session_id": sid, "expires_at": utcnow() + timedelta(seconds=VIEW_TTL), "expires_in": VIEW_TTL, "sections": SECTIONS}


def _check_view(me: User, uid: int, sid: str) -> None:
    _need(me, "view_as_user", "以用户视角查看")
    try:
        d = _ser.loads(sid, max_age=VIEW_TTL)
    except SignatureExpired:
        _err(403, "view_expired", "只读查看已过期，请重新开始")
    except BadSignature:
        _err(403, "view_expired", "只读查看无效，请重新开始")
    if d.get("a") != me.id or d.get("u") != uid:
        _err(403, "view_expired", "只读查看和当前用户不匹配，请重新开始")


def _card(it: Item | None) -> dict | None:
    if it is None:
        return None
    return {"id": it.id, "name": it.name, "summary": it.summary, "status": it.status,
            "repo": it.repo.full_name if it.repo else "", "cover_url": f"/media/{it.cover_path}" if it.cover_path else None}


@router.get("/users/{user_id}/view/{section}")
def view_section(user_id: int, section: str, request: Request, session_id: str = Query(...), page: int = Query(1, ge=1),
                 db: Session = Depends(get_db), me: User = Depends(require_admin)):
    if section not in SECTIONS:
        _err(404, "unknown_section", "没有这个分区")
    _check_view(me, user_id, session_id)
    u = _user(db, user_id)
    size = 30
    if section == "pocket":
        favs = db.scalars(select(Favorite).where(Favorite.owner_id == u.id).order_by(Favorite.created_at.desc())).all()
        items = {i.id: i for i in db.scalars(select(Item).options(joinedload(Item.repo)).where(Item.id.in_([f.item_id for f in favs] or [-1]))).unique()}
        links: dict[int, list[int]] = {}
        for fid, folder in db.execute(select(FavoriteFolderLink.favorite_id, FavoriteFolderLink.folder_id)
                                      .where(FavoriteFolderLink.favorite_id.in_([f.id for f in favs] or [-1]))).all():
            links.setdefault(fid, []).append(folder)
        dims = db.scalars(select(FavDimension).where(FavDimension.owner_id == u.id).order_by(FavDimension.sort)).all()
        data = {"total": len(favs),
                "dimensions": [{"id": d.id, "name": d.name, "folders": [{"id": f.id, "name": f.name, "emoji": f.emoji or "",
                                                                         "shared": bool(f.share_token)} for f in d.folders]} for d in dims],
                "items": [{"item": _card(items.get(f.item_id)), "note": f.note, "folder_ids": links.get(f.id, []), "at": f.created_at}
                          for f in favs[(page - 1) * size: page * size]]}
    elif section == "subscriptions":
        rows = db.execute(select(CategorySubscription, Category).join(Category, Category.id == CategorySubscription.category_id)
                          .where(CategorySubscription.user_id == u.id)).all()
        data = {"total": len(rows), "items": [{"name": c.name, "is_parent": c.parent_id is None, "since": s.created_at,
                                               "last_notified_at": s.last_notified_at} for s, c in rows]}
    elif section == "notifications":
        stmt = select(Notification).where(Notification.user_id == u.id)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.order_by(Notification.id.desc()).offset((page - 1) * size).limit(size)).all()
        data = {"total": total, "unread": db.scalar(select(func.count()).select_from(Notification).where(
            Notification.user_id == u.id, Notification.read_at.is_(None))) or 0, "items": [_msg_out(db, n, {}) for n in rows]}
    elif section == "comments":
        stmt = select(Comment).where(Comment.user_id == u.id)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.options(joinedload(Comment.item)).order_by(Comment.id.desc()).offset((page - 1) * size).limit(size)).all()
        data = {"total": total, "items": [{"id": c.id, "item": {"id": c.item_id, "name": c.item.name if c.item else ""}, "content": c.content,
                                           "rating": c.rating, "status": c.status, "at": c.created_at} for c in rows]}
    else:
        stmt = select(CompareRun).where(CompareRun.user_id == u.id)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.order_by(CompareRun.id.desc()).offset((page - 1) * size).limit(size)).all()
        data = {"total": total, "items": [{"id": r.id, "names": [s.get("name", "") for s in (r.subjects or [])], "status": r.status,
                                           "at": r.created_at} for r in rows]}
    activity.record("view_as_user", f"只读查看 {users.label(u)} 的{SECTIONS[section]}", user=me, target_type="user", target_id=u.id,
                    ip=client_ip(request), target_label=users.label(u), detail={"section": section})
    return {"section": section, "section_label": SECTIONS[section], "user": {"id": u.id, "label": users.label(u), "nickname": u.nickname,
                                                                             "avatar": u.avatar}, "page": page, **data}
