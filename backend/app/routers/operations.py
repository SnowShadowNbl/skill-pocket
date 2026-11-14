"""v3.3.71 后台批次 7b：用户标签（U04）、小范围公告（P29）、首页运营位（P9）、分类订阅人数（P39）。

- 标签只在后台可见，用来筛选用户、圈定公告对象。
- 公告：按「全部用户 / 标签 / 注册渠道」圈人（标签与渠道同时选时取交集），先预览人数再发送；以站内消息送达（kind=announcement），
  已读率按公告统计。只发给正常状态的普通用户，一次最多 MAX_RECIPIENTS 人。
- 首页运营位：公告横幅（可设时间段）、搜索框轮播提示词、新手引导开关；GET /api/home-config 公开给网页端读取。
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..db import get_db, utcnow
from ..models import Announcement, AppMeta, Category, CategorySubscription, Notification, Tag, User, UserTag
from ..services import activity, users
from ..services.client import CHANNELS

public = APIRouter(prefix="/api", tags=["home-config"])
router = APIRouter(prefix="/api/admin", tags=["admin-operations"], dependencies=[Depends(require_admin)])
MAX_RECIPIENTS = 5000
CN = ZoneInfo("Asia/Shanghai")
COLORS = ("blue", "green", "orange", "red", "purple", "gray")


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < 2:
        _err(400, "reason_required", "请填写原因")
    return r


def _who(db: Session, uid):
    if not uid:
        return None
    u = db.get(User, uid)
    return {"id": uid, "label": users.label(u) if u else f"用户 #{uid}"}


# ================================================================ 用户标签
def _tag_out(t: Tag, n: int | None = None) -> dict:
    return {"id": t.id, "name": t.name, "color": t.color, "description": t.description, "users": n, "created_at": t.created_at}


@router.get("/tags")
def list_tags(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(UserTag.tag_id, func.count()).group_by(UserTag.tag_id)).all())
    return {"colors": COLORS, "items": [_tag_out(t, counts.get(t.id, 0)) for t in db.scalars(select(Tag).order_by(Tag.id))]}


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    color: str = "blue"
    description: str = Field("", max_length=200)


class TagPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=30)
    color: str | None = None
    description: str | None = Field(None, max_length=200)


@router.post("/tags")
def create_tag(body: TagIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    name = body.name.strip()
    if body.color not in COLORS:
        _err(400, "bad_color", "颜色不对")
    if db.scalar(select(Tag.id).where(func.lower(Tag.name) == name.lower())):
        _err(400, "duplicate", "已经有这个标签")
    t = Tag(name=name, color=body.color, description=body.description.strip(), created_by=me.id)
    db.add(t)
    db.commit()
    activity.record("tag", f"新建标签「{name}」", user=me, ip=client_ip(request), target_type="tag", target_id=t.id)
    return _tag_out(t, 0)


@router.put("/tags/{tag_id}")
def update_tag(tag_id: int, body: TagPatch, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = db.get(Tag, tag_id)
    if t is None:
        _err(404, "not_found", "标签不存在")
    if body.name is not None:
        name = body.name.strip()
        if db.scalar(select(Tag.id).where(func.lower(Tag.name) == name.lower(), Tag.id != t.id)):
            _err(400, "duplicate", "已经有这个标签")
        t.name = name
    if body.color is not None:
        if body.color not in COLORS:
            _err(400, "bad_color", "颜色不对")
        t.color = body.color
    if body.description is not None:
        t.description = body.description.strip()
    db.commit()
    return _tag_out(t, db.scalar(select(func.count()).select_from(UserTag).where(UserTag.tag_id == t.id)))


class ReasonIn(BaseModel):
    reason: str = Field("", max_length=300)


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int, request: Request, body: ReasonIn | None = None, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    reason = _reason((body or ReasonIn()).reason)
    t = db.get(Tag, tag_id)
    if t is None:
        _err(404, "not_found", "标签不存在")
    n = db.scalar(select(func.count()).select_from(UserTag).where(UserTag.tag_id == t.id)) or 0
    name = t.name
    db.execute(delete(UserTag).where(UserTag.tag_id == t.id))
    db.delete(t)
    db.commit()
    activity.record("tag", f"删除标签「{name}」（{n} 个用户）", user=me, ip=client_ip(request), reason=reason, target_type="tag", target_id=tag_id)
    return {"ok": True}


def user_tags(db: Session, user_ids) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    rows = db.execute(select(UserTag.user_id, Tag).join(Tag, Tag.id == UserTag.tag_id).where(UserTag.user_id.in_(list(user_ids) or [-1]))
                      .order_by(Tag.id)).all()
    for uid, t in rows:
        out.setdefault(uid, []).append({"id": t.id, "name": t.name, "color": t.color})
    return out


class UserTagsIn(BaseModel):
    tag_ids: list[int] = Field(max_length=20)


@router.put("/users/{user_id}/tags")
def set_user_tags(user_id: int, body: UserTagsIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        _err(404, "not_found", "用户不存在")
    want = set(body.tag_ids)
    valid = set(db.scalars(select(Tag.id).where(Tag.id.in_(want or {-1}))))
    if want - valid:
        _err(400, "bad_tag", "有标签不存在", tag_ids=sorted(want - valid))
    have = set(db.scalars(select(UserTag.tag_id).where(UserTag.user_id == u.id)))
    for tid in want - have:
        db.add(UserTag(user_id=u.id, tag_id=tid, created_by=me.id))
    if have - want:
        db.execute(delete(UserTag).where(UserTag.user_id == u.id, UserTag.tag_id.in_(have - want)))
    db.commit()
    names = {t.id: t.name for t in db.scalars(select(Tag).where(Tag.id.in_(want | have or {-1})))}
    if want != have:
        activity.record("user_tags", f"修改用户标签：{users.label(u)}", user=me, target_type="user", target_id=u.id, ip=client_ip(request),
                        before={"tags": "、".join(names[i] for i in sorted(have)) or "（无）"},
                        after={"tags": "、".join(names[i] for i in sorted(want)) or "（无）"}, target_label=users.label(u))
    return {"user_id": u.id, "tags": user_tags(db, [u.id]).get(u.id, [])}


# ================================================================ 小范围公告
class Audience(BaseModel):
    all: bool = False
    tag_ids: list[int] = []
    channels: list[str] = []


class AnnIn(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=500)
    link: str = Field("", max_length=300)
    audience: Audience = Audience()


def _audience_ids(db: Session, a: dict) -> list[int]:
    stmt = select(User.id).where(User.role == "user", User.status == "active")
    if not a.get("all"):
        tags, chans = a.get("tag_ids") or [], a.get("channels") or []
        if not tags and not chans:
            return []
        if tags:
            stmt = stmt.where(User.id.in_(select(UserTag.user_id).where(UserTag.tag_id.in_(tags))))
        if chans:
            stmt = stmt.where(User.signup_channel.in_(["" if c == "unknown" else c for c in chans]))
    return list(db.scalars(stmt.order_by(User.id)))


def _ann_out(db: Session, a: Announcement) -> dict:
    read = None
    if a.status == "sent":
        read = db.scalar(select(func.count()).select_from(Notification).where(Notification.announcement_id == a.id, Notification.read_at.is_not(None))) or 0
    tags = {t.id: t.name for t in db.scalars(select(Tag).where(Tag.id.in_((a.audience or {}).get("tag_ids") or [-1])))}
    au = a.audience or {}
    return {"id": a.id, "title": a.title, "text": a.text, "link": a.link, "status": a.status, "status_label": "已发送" if a.status == "sent" else "草稿",
            "audience": au, "audience_label": "全部用户" if au.get("all") else "、".join(
                [f"标签「{tags.get(i, i)}」" for i in au.get("tag_ids") or []] + [CHANNELS.get("" if c == "unknown" else c, c) for c in au.get("channels") or []]),
            "recipients": a.recipients, "read": read, "read_rate": round(read / a.recipients, 3) if a.recipients and read is not None else None,
            "created_by": _who(db, a.created_by), "created_at": a.created_at, "sent_by": _who(db, a.sent_by), "sent_at": a.sent_at}


def _check_link(link: str) -> str:
    link = (link or "").strip()
    if link and not link.startswith("/"):
        _err(400, "bad_link", "链接只能是站内路径，例如 /items/12")
    return link


@router.get("/announcements")
def list_ann(status: str = Query("", pattern="^(|draft|sent)$"), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             db: Session = Depends(get_db)):
    stmt = select(Announcement)
    if status:
        stmt = stmt.where(Announcement.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Announcement.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "max_recipients": MAX_RECIPIENTS, "items": [_ann_out(db, a) for a in rows]}


@router.post("/announcements")
def create_ann(body: AnnIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    a = Announcement(title=body.title.strip(), text=body.text.strip(), link=_check_link(body.link), audience=body.audience.model_dump(),
                     status="draft", created_by=me.id)
    db.add(a)
    db.commit()
    return _ann_out(db, a)


def _draft(db: Session, ann_id: int) -> Announcement:
    a = db.get(Announcement, ann_id)
    if a is None:
        _err(404, "not_found", "公告不存在")
    if a.status != "draft":
        _err(409, "already_handled", "这条公告已经发送过了", status=a.status, handled_by=_who(db, a.sent_by), handled_at=a.sent_at)
    return a


@router.put("/announcements/{ann_id}")
def update_ann(ann_id: int, body: AnnIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    a = _draft(db, ann_id)
    a.title, a.text, a.link, a.audience = body.title.strip(), body.text.strip(), _check_link(body.link), body.audience.model_dump()
    db.commit()
    return _ann_out(db, a)


@router.delete("/announcements/{ann_id}")
def delete_ann(ann_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    a = _draft(db, ann_id)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.post("/announcements/{ann_id}/preview")
def preview_ann(ann_id: int, db: Session = Depends(get_db)):
    a = db.get(Announcement, ann_id)
    if a is None:
        _err(404, "not_found", "公告不存在")
    ids = _audience_ids(db, a.audience or {})
    sample = [{"id": u.id, "label": users.label(u)} for u in db.scalars(select(User).where(User.id.in_(ids[:10] or [-1])))]
    return {"count": len(ids), "over_limit": len(ids) > MAX_RECIPIENTS, "max_recipients": MAX_RECIPIENTS, "sample": sample,
            "notification": {"kind": "announcement", "title": a.title, "body": a.text, "link": a.link}}


class SendIn(BaseModel):
    reason: str = Field("", max_length=300)
    expected_count: int | None = None


@router.post("/announcements/{ann_id}/send")
def send_ann(ann_id: int, body: SendIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    reason = _reason(body.reason)
    a = _draft(db, ann_id)
    ids = _audience_ids(db, a.audience or {})
    if not ids:
        _err(400, "empty_audience", "没有符合条件的用户")
    if len(ids) > MAX_RECIPIENTS:
        _err(400, "too_many", f"一次最多发给 {MAX_RECIPIENTS} 人，请缩小范围")
    if body.expected_count is not None and body.expected_count != len(ids):
        _err(409, "count_changed", f"符合条件的人数已变化（现在 {len(ids)} 人，预览时 {body.expected_count} 人），请重新预览")
    now = utcnow()
    db.add_all([Notification(user_id=uid, kind="announcement", title=a.title, body=a.text, link=a.link, sender_id=me.id, announcement_id=a.id,
                             created_at=now) for uid in ids])
    a.status, a.recipients, a.sent_by, a.sent_at = "sent", len(ids), me.id, now
    db.commit()
    activity.record("announcement", f"发送公告「{a.title}」给 {len(ids)} 人", user=me, ip=client_ip(request), reason=reason,
                    target_type="announcement", target_id=a.id, detail={"audience": a.audience})
    return _ann_out(db, a)


# ================================================================ 首页运营位
HOME_DEFAULT = {"banner": {"enabled": False, "text": "", "link": "", "level": "info", "starts_at": None, "ends_at": None, "id": 0},
                "search_placeholders": [], "onboarding_enabled": True}


def home_config(db: Session) -> dict:
    m = db.get(AppMeta, "home_config")
    try:
        v = json.loads(m.value) if m and m.value else {}
    except ValueError:
        v = {}
    out = json.loads(json.dumps(HOME_DEFAULT))
    out["banner"].update(v.get("banner") or {})
    out["search_placeholders"] = v.get("search_placeholders") or []
    out["onboarding_enabled"] = v.get("onboarding_enabled", True)
    return out


def _as_utc(v) -> datetime | None:
    """v3.3.72 统一成带时区的 UTC：不带时区的按北京时间理解（和推荐位一致）。"""
    if v in (None, ""):
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    if d.tzinfo is None:
        d = d.replace(tzinfo=CN)
    return d.astimezone(timezone.utc)


def _banner_live(b: dict) -> bool:
    if not b.get("enabled") or not b.get("text"):
        return False
    now = utcnow()
    try:
        s, e = _as_utc(b.get("starts_at")), _as_utc(b.get("ends_at"))
    except (ValueError, TypeError):  # 坏数据：不显示，也不能拖垮首页
        return False
    if s and s > now:
        return False
    if e and e <= now:
        return False
    return True


@public.get("/home-config")
def public_home(db: Session = Depends(get_db)):
    try:
        c = home_config(db)
    except Exception:  # noqa: BLE001  首页配置出错时按默认处理，绝不让首页报错
        return {"banner": None, "search_placeholders": [], "onboarding_enabled": True}
    b = c["banner"]
    return {"banner": {k: b[k] for k in ("id", "text", "link", "level")} if _banner_live(b) else None,
            "search_placeholders": c["search_placeholders"], "onboarding_enabled": c["onboarding_enabled"]}


@router.get("/home-config")
def get_home(db: Session = Depends(get_db)):
    c = home_config(db)
    return {**c, "banner_live": _banner_live(c["banner"])}


class BannerIn(BaseModel):
    enabled: bool = False
    text: str = Field("", max_length=80)
    link: str = Field("", max_length=300)
    level: str = Field("info", pattern="^(info|warn|success)$")
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HomeIn(BaseModel):
    banner: BannerIn | None = None
    search_placeholders: list[str] | None = Field(None, max_length=10)
    onboarding_enabled: bool | None = None
    reason: str = Field("", max_length=300)


@router.put("/home-config")
def put_home(body: HomeIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    reason = _reason(body.reason)
    cur = home_config(db)
    before = json.loads(json.dumps(cur))
    if body.banner is not None:
        b = body.banner.model_dump()
        if b["enabled"] and not b["text"].strip():
            _err(400, "empty_banner", "请填写横幅文字")
        b["link"] = _check_link(b["link"])
        s, e = _as_utc(b["starts_at"]), _as_utc(b["ends_at"])
        if s and e and e <= s:
            _err(400, "bad_range", "结束时间要晚于开始时间")
        b["starts_at"] = s.isoformat() if s else None  # 存 UTC（带时区）
        b["ends_at"] = e.isoformat() if e else None
        b["text"] = b["text"].strip()
        changed = any(b[k] != cur["banner"].get(k) for k in ("text", "link", "level", "enabled"))
        b["id"] = (cur["banner"].get("id") or 0) + (1 if changed else 0)  # 内容变了换新 id，用户关掉过的横幅会重新出现
        cur["banner"] = b
    if body.search_placeholders is not None:
        cur["search_placeholders"] = [x.strip()[:30] for x in body.search_placeholders if x.strip()]
    if body.onboarding_enabled is not None:
        cur["onboarding_enabled"] = body.onboarding_enabled
    db.merge(AppMeta(key="home_config", value=json.dumps(cur, ensure_ascii=False)))
    db.commit()
    diff = {k for k in cur if cur[k] != before[k]}
    activity.record("home_config", "修改首页运营位：" + "、".join({"banner": "公告横幅", "search_placeholders": "搜索框提示词",
                                                             "onboarding_enabled": "新手引导"}[k] for k in sorted(diff)) if diff else "修改首页运营位（无变化）",
                    user=me, ip=client_ip(request), reason=reason, target_type="maintenance", target_label="home_config",
                    before={k: before[k] for k in diff} or None, after={k: cur[k] for k in diff} or None)
    return {**cur, "banner_live": _banner_live(cur["banner"])}


# ================================================================ 分类订阅人数
@router.get("/subscriptions/stats")
def subscription_stats(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(CategorySubscription.category_id, func.count()).group_by(CategorySubscription.category_id)).all())
    users_n = db.scalar(select(func.count(func.distinct(CategorySubscription.user_id)))) or 0
    cats = db.scalars(select(Category).where(Category.id.in_(list(counts) or [-1]))).all()
    return {"subscribers": users_n, "subscriptions": sum(counts.values()),
            "items": sorted(({"category": {"id": c.id, "name": c.name, "parent": c.parent.name if c.parent else None, "is_parent": c.parent_id is None},
                              "subscribers": counts[c.id]} for c in cats), key=lambda x: -x["subscribers"])}
