"""管理员：访客与行为（用户探真）。每个访客的 IP、中文归属地、设备、来源、访问轨迹；游客与登录用户都在内。"""

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db, utcnow
from ..models import Event, Item, User, Visitor
from ..services import geo, visits

router = APIRouter(prefix="/api/admin/analytics", tags=["admin"], dependencies=[Depends(require_admin)])

VIEWS = ("page_view", "item_view")


def _user_brief(u: User | None) -> dict | None:
    return {"id": u.id, "nickname": u.nickname, "email": u.email or u.username, "avatar": u.avatar, "role": u.role} if u else None


def _where(ip: str, stored: str) -> str:
    # 境外地名的中文译名可能是后来才翻译好的，展示时以实时查询为准
    return geo.lookup(ip) or stored


def _visitor_out(v: Visitor, users: dict) -> dict:
    return {"vid": v.id, "user": _user_brief(users.get(v.user_id)), "first_seen": v.first_seen, "last_seen": v.last_seen,
            "first_ip": v.first_ip, "first_geo": _where(v.first_ip, v.first_geo), "ip": v.last_ip,
            "geo": _where(v.last_ip, v.last_geo), "device": v.device, "referrer": v.referrer, "landing": v.landing,
            "visits": v.visits, "events": v.events, "converted_at": v.converted_at}


def _event_out(e: Event, users: dict, items: dict) -> dict:
    props = e.props or {}
    iid = props.get("item_id")
    it = items.get(iid) if isinstance(iid, int) else None
    return {"id": e.id, "vid": e.vid, "user": _user_brief(users.get(e.user_id)), "name": e.name, "label": visits.label(e.name),
            "category": e.category, "props": props, "item": {"id": it.id, "name": it.name} if it else None,
            "page": e.page, "ip": e.ip, "geo": _where(e.ip, e.geo), "created_at": e.created_at}


def _lookups(db: Session, events: list[Event]) -> tuple[dict, dict]:
    uids = {e.user_id for e in events if e.user_id}
    iids = {(e.props or {}).get("item_id") for e in events}
    iids = {i for i in iids if isinstance(i, int)}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(uids)))} if uids else {}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(iids)))} if iids else {}
    return users, items


def _region(where: str) -> str:
    """「中国 广东省 深圳市 电信」→「广东省」；境外 → 国家名。"""
    parts = where.split()
    if not parts:
        return "未知"
    if parts[0] == "中国" and len(parts) > 1:
        return parts[1]
    return parts[0]


@router.get("/overview")
def overview(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    today = visits.today_cn()
    series = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        s, e = visits.day_bounds(d)
        rng = (Event.created_at >= s, Event.created_at < e)
        series.append({
            "day": d.isoformat(),
            "pv": db.scalar(select(func.count()).select_from(Event).where(*rng, Event.name.in_(VIEWS))) or 0,
            "uv": db.scalar(select(func.count(distinct(Event.vid))).where(*rng)) or 0,
            "new": db.scalar(select(func.count()).select_from(Visitor).where(Visitor.first_seen >= s, Visitor.first_seen < e)) or 0,
        })
    start, _ = visits.day_bounds(today - timedelta(days=days - 1))
    t0, t1 = visits.day_bounds(today)
    in_range = Event.created_at >= start

    def counts(name: str, key: str, n: int = 10) -> list:
        c = Counter()
        for props in db.scalars(select(Event.props).where(in_range, Event.name == name).order_by(Event.id.desc()).limit(20000)):
            v = (props or {}).get(key)
            if v not in (None, ""):
                c[v] += 1
        return c.most_common(n)

    top_items = counts("item_view", "item_id")
    ids = [k for k, _ in top_items if isinstance(k, int)]
    names = {i.id: i.name for i in db.scalars(select(Item).where(Item.id.in_(ids)))} if ids else {}
    visitors = db.execute(select(Visitor.last_ip, Visitor.last_geo, Visitor.device, Visitor.user_id)
                          .where(Visitor.last_seen >= start)).all()
    regions, devices = Counter(), Counter()
    for ip, g, dev, _ in visitors:
        regions[_region(_where(ip, g))] += 1
        devices[dev.split(" · ")[0] if dev else "未知"] += 1
    by_name = dict(db.execute(select(Event.name, func.count()).where(in_range).group_by(Event.name)).all())
    today_rng = (Event.created_at >= t0, Event.created_at < t1)
    return {
        "days": days,
        "today": {
            "uv": db.scalar(select(func.count(distinct(Event.vid))).where(*today_rng)) or 0,
            "pv": db.scalar(select(func.count()).select_from(Event).where(*today_rng, Event.name.in_(VIEWS))) or 0,
            "new": db.scalar(select(func.count()).select_from(Visitor).where(Visitor.first_seen >= t0)) or 0,
            "users": db.scalar(select(func.count(distinct(Event.user_id))).where(*today_rng, Event.user_id.is_not(None))) or 0,
            "online": db.scalar(select(func.count()).select_from(Visitor).where(Visitor.last_seen >= utcnow() - timedelta(minutes=5))) or 0,
        },
        "range": {
            "visitors": len(visitors),
            "logged_in": sum(1 for v in visitors if v[3]),
            "conversions": db.scalar(select(func.count()).select_from(Visitor).where(Visitor.converted_at >= start)) or 0,
            "events": sum(by_name.values()),
        },
        "series": series,
        "events": sorted(({"name": k, "label": visits.label(k), "count": v} for k, v in by_name.items()), key=lambda x: -x["count"]),
        "top_pages": [{"page": k, "count": v} for k, v in counts("page_view", "path")],
        "top_searches": [{"q": k, "count": v} for k, v in counts("search", "q")],
        "top_items": [{"id": k, "name": names.get(k, f"#{k}"), "count": v} for k, v in top_items],
        "regions": [{"name": k, "count": v} for k, v in regions.most_common(12)],
        "devices": [{"name": k, "count": v} for k, v in devices.most_common(8)],
    }


@router.get("/visitors")
def visitors(kind: str = "", q: str = "", page: int = Query(1, ge=1), size: int = Query(30, le=100), db: Session = Depends(get_db)):
    conds = []
    if kind == "guest":
        conds.append(Visitor.user_id.is_(None))
    elif kind == "user":
        conds.append(Visitor.user_id.is_not(None))
    elif kind == "converted":
        conds.append(Visitor.converted_at.is_not(None))
    for w in q.split():
        like = f"%{w}%"
        uids = select(User.id).where(or_(User.nickname.ilike(like), User.email.ilike(like)))
        conds.append(or_(Visitor.last_ip.ilike(like), Visitor.first_ip.ilike(like), Visitor.last_geo.ilike(like),
                         Visitor.first_geo.ilike(like), Visitor.device.ilike(like), Visitor.id == w, Visitor.user_id.in_(uids)))
    base = select(Visitor).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(Visitor.last_seen.desc()).offset((page - 1) * size).limit(size)).all()
    uids = {v.user_id for v in rows if v.user_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(uids)))} if uids else {}
    online_since = utcnow() - timedelta(minutes=5)
    return {"total": total, "items": [{**_visitor_out(v, users), "online": v.last_seen >= online_since} for v in rows]}


@router.get("/visitors/{vid}")
def visitor_detail(vid: str, page: int = Query(1, ge=1), size: int = Query(50, le=200), db: Session = Depends(get_db)):
    v = db.get(Visitor, vid)
    if v is None:
        raise HTTPException(404, "访客不存在")
    users = {v.user_id: db.get(User, v.user_id)} if v.user_id else {}
    total = db.scalar(select(func.count()).select_from(Event).where(Event.vid == vid))
    events = db.scalars(select(Event).where(Event.vid == vid).order_by(Event.id.desc()).offset((page - 1) * size).limit(size)).all()
    eu, items = _lookups(db, events)
    users.update(eu)
    ips = db.execute(select(Event.ip, func.count(), func.max(Event.created_at)).where(Event.vid == vid)
                     .group_by(Event.ip).order_by(func.max(Event.created_at).desc()).limit(20)).all()
    # 同一账号在其他浏览器 / 设备上的访客记录
    others = []
    if v.user_id:
        others = [_visitor_out(o, users) for o in db.scalars(select(Visitor).where(Visitor.user_id == v.user_id, Visitor.id != vid)
                                                             .order_by(Visitor.last_seen.desc()).limit(10))]
    return {"visitor": _visitor_out(v, users), "total": total, "events": [_event_out(e, users, items) for e in events],
            "ips": [{"ip": ip, "geo": geo.lookup(ip), "count": n, "last": last} for ip, n, last in ips], "other_devices": others}


@router.get("/events")
def events(name: str = "", vid: str = "", user_id: int | None = None, q: str = "", after: int = 0,
           page: int = Query(1, ge=1), size: int = Query(50, le=200), db: Session = Depends(get_db)):
    conds = []
    if name:
        conds.append(Event.name == name)
    if vid:
        conds.append(Event.vid == vid)
    if user_id:
        conds.append(Event.user_id == user_id)
    if after:
        conds.append(Event.id > after)
    for w in q.split():
        conds.append(or_(Event.ip.ilike(f"%{w}%"), Event.geo.ilike(f"%{w}%"), Event.page.ilike(f"%{w}%")))
    base = select(Event).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(Event.id.desc()).offset((page - 1) * size).limit(size)).all()
    users, items = _lookups(db, rows)
    return {"total": total, "names": {k: v[1] for k, v in visits.EVENTS.items()},
            "items": [_event_out(e, users, items) for e in rows]}
