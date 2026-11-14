"""v3.3.62 后台批次 5c：封面缩略图 / 动图队列（P27）与客户端版本统计（P36）。

缩略图、动图不入库，状态按文件判断：
- done 已生成（文件比原图新）/ queued 在后台队列里 / missing 没有文件也不在队列里（还没生成或生成失败）
- no_anim（只有动图）：记过「没有动画或渲染失败」的标记，不会再自动生成
动图只有 .svg 封面才有。
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..config import settings
from ..db import get_db, utcnow
from ..models import AuthSession, Event, Item, User
from ..services import activity, anim
from ..services.client import CHANNELS

router = APIRouter(prefix="/api/admin", tags=["admin-media"], dependencies=[Depends(require_admin)])
STATUS = {"done": "已生成", "queued": "排队中", "missing": "缺失", "no_anim": "没有动画"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < 2:
        _err(400, "reason_required", "请填写原因")
    return r


def _fresh(dst: Path, src: Path) -> bool:
    return dst.is_file() and src.is_file() and dst.stat().st_mtime >= src.stat().st_mtime


def _state(cover: str, queued: set[str]) -> dict:
    root = settings.media_dir
    src = root / cover
    t = root / "thumb" / f"{cover}.jpg"
    thumb = "done" if _fresh(t, src) else "queued" if cover in queued else "missing"
    out = {"thumb": thumb, "thumb_at": t.stat().st_mtime if t.is_file() else None, "anim": None, "anim_at": None,
           "thumb_bytes": t.stat().st_size if t.is_file() else 0, "anim_bytes": 0}
    if cover.endswith(".svg"):
        a = root / "anim" / f"{cover}.webp"
        none = a.with_suffix(a.suffix + ".none")
        out["anim"] = ("done" if _fresh(a, src) else "no_anim" if _fresh(none, src) else "queued" if cover in queued else "missing")
        out["anim_at"] = a.stat().st_mtime if a.is_file() else None
        out["anim_bytes"] = a.stat().st_size if a.is_file() else 0
    return out


def _covers(db: Session) -> list[tuple[int, str, str]]:
    return db.execute(select(Item.id, Item.name, Item.cover_path).where(Item.status == "published", Item.cover_path != "")
                      .order_by(Item.id.desc())).all()


def _queued() -> set[str]:
    with anim._cv:
        return set(anim._queued)


@router.get("/cover-queue")
def queue_overview(db: Session = Depends(get_db)):
    q = _queued()
    th, an = defaultdict(int), defaultdict(int)
    tb = ab = 0
    seen: set[str] = set()
    for _, _, cover in _covers(db):
        if cover in seen:
            continue
        seen.add(cover)
        s = _state(cover, q)
        th[s["thumb"]] += 1
        tb += s["thumb_bytes"]
        if s["anim"]:
            an[s["anim"]] += 1
            ab += s["anim_bytes"]
    w = anim._worker
    return {"thumb": {k: th.get(k, 0) for k in ("done", "queued", "missing")},
            "anim": {k: an.get(k, 0) for k in ("done", "queued", "missing", "no_anim")},
            "queue_length": anim.pending(), "worker_alive": bool(w and w.is_alive()), "covers": len(seen),
            "storage": {"thumb_bytes": tb, "anim_bytes": ab}, "statuses": STATUS}


@router.get("/cover-queue/items")
def queue_items(kind: str = Query("thumb", pattern="^(thumb|anim)$"), status: str = Query("missing", pattern="^(done|queued|missing|no_anim)$"),
                page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    q = _queued()
    rows = []
    for iid, name, cover in _covers(db):
        s = _state(cover, q)
        st = s[kind]
        if st == status:
            at = s[f"{kind}_at"]
            rows.append({"item": {"id": iid, "name": name}, "cover_path": cover, "kind": kind, "status": st, "status_label": STATUS[st],
                         "updated_at": datetime.fromtimestamp(at, tz=timezone.utc) if at else None})
    start = (page - 1) * page_size
    return {"total": len(rows), "page": page, "page_size": page_size, "items": rows[start:start + page_size]}


def _drop(cover: str, kind: str) -> None:
    root = settings.media_dir
    paths = []
    if kind in ("thumb", "all"):
        paths.append(root / "thumb" / f"{cover}.jpg")
    if kind in ("anim", "all") and cover.endswith(".svg"):
        a = root / "anim" / f"{cover}.webp"
        paths += [a, a.with_suffix(a.suffix + ".none")]
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


class RegenIn(BaseModel):
    kind: str = Field("all", pattern="^(thumb|anim|all)$")
    reason: str = Field("", max_length=300)


@router.post("/items/{item_id}/regenerate-cover")
def regenerate(item_id: int, body: RegenIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    reason = _reason(body.reason)
    it = db.get(Item, item_id)
    if it is None or not it.cover_path:
        _err(404, "not_found", "条目不存在或没有封面")
    if body.kind == "anim" and not it.cover_path.endswith(".svg"):
        _err(400, "no_anim", "只有 SVG 封面才有动图")
    _drop(it.cover_path, body.kind)
    anim.enqueue(it.cover_path, front=True)
    activity.record("cover_regen", f"重新生成「{it.name}」的{'缩略图' if body.kind == 'thumb' else '动图' if body.kind == 'anim' else '缩略图和动图'}",
                    user=me, target_type="item", target_id=it.id, ip=client_ip(request), reason=reason, target_label=it.name)
    return {"ok": True, "queued": True, "queue_length": anim.pending()}


class RetryIn(BaseModel):
    kind: str = Field("all", pattern="^(thumb|anim|all)$")
    reason: str = Field("", max_length=300)
    include_no_anim: bool = False


@router.post("/cover-queue/retry-failed")
def retry_failed(body: RetryIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """把缺失的（kind=anim 且 include_no_anim 时连「没有动画」的也）重新排队。"""
    reason = _reason(body.reason)
    q = _queued()
    todo = []
    for _, _, cover in dict.fromkeys(_covers(db)):
        s = _state(cover, q)
        need = (body.kind in ("thumb", "all") and s["thumb"] == "missing") or (
            body.kind in ("anim", "all") and (s["anim"] == "missing" or (body.include_no_anim and s["anim"] == "no_anim")))
        if need and cover not in todo:
            if body.include_no_anim and s["anim"] == "no_anim":
                _drop(cover, "anim")
            todo.append(cover)
    for c in todo:
        anim.enqueue(c)
    activity.record("cover_regen", f"重新排队生成缩略图 / 动图：{len(todo)} 张封面", user=me, ip=client_ip(request), reason=reason,
                    detail={"kind": body.kind, "count": len(todo)})
    return {"ok": True, "queued": len(todo), "queue_length": anim.pending()}


# ---------------------------------------------------------------- P36 客户端版本
@router.get("/client-versions")
def client_versions(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    """按端和版本统计最近 days 天的登录会话：用户数、会话数、最近活跃；事件按端统计（事件没记版本）。"""
    since = utcnow() - timedelta(days=days)
    rows = db.execute(select(AuthSession.client, AuthSession.client_version, AuthSession.user_id, AuthSession.last_seen_at)
                      .where(AuthSession.created_at >= since)).all()
    agg: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"users": set(), "sessions": 0, "last_seen": None}))
    for c, v, uid, seen in rows:
        a = agg[c or ""][v or ""]
        a["users"].add(uid)
        a["sessions"] += 1
        if seen and (a["last_seen"] is None or seen > a["last_seen"]):
            a["last_seen"] = seen
    events = dict(db.execute(select(Event.client, func.count()).where(Event.created_at >= since).group_by(Event.client)).all())
    current = dict(db.execute(select(User.last_client_version, func.count()).where(User.last_client_version != "")
                              .group_by(User.last_client_version)).all())
    from .observability import errors_by_version

    errs = errors_by_version(db, since)  # v3.3.66 客户端报错上报
    out = []
    for c in ("web-pc", "web-mobile", "miniprogram", ""):
        vers = agg.get(c, {})
        out.append({"client": c or "unknown", "label": CHANNELS.get(c, "未知"), "events": events.get(c, 0),
                    "versions": sorted(({"version": v or "未知", "raw": v or "unknown", "users": len(a["users"]), "sessions": a["sessions"],
                                         "events": None, "errors": errs.get((c, v), 0), "last_seen": a["last_seen"], "current_users": current.get(v, 0) if v else None}
                                        for v, a in vers.items()), key=lambda x: (-x["users"], x["version"]))})
    return {"days": days, "by_client": out}
