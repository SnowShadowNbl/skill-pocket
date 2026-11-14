"""用户探真：游客编号、行为事件、IP 中文归属地。

- 游客编号（vid）由浏览器生成并保存，每个请求带在 X-Visitor-Id 头里；登录时把这个浏览器关联到账号，
  以前以游客身份来过、这次刚注册的，记一次「游客 → 注册」转化。
- 事件明细保留 180 天；每天凌晨汇总成 event_daily（次数、人数）长期保留。
- 归属地用离线 ip2region 库（services/geo.py），查询不经过第三方。
"""

import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..models import Event, EventDaily, User, Visitor
from . import geo
from .client import client_of

log = logging.getLogger(__name__)
CN = ZoneInfo("Asia/Shanghai")
RETENTION_DAYS = 180
VID_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")

# 事件名 → (类别, 中文名)。前端只能上报这里列出的事件
EVENTS = {
    "page_view": ("view", "浏览页面"),
    "item_view": ("view", "查看详情"),
    "search": ("search", "搜索"),
    "filter": ("search", "筛选"),
    "copy_prompt": ("action", "复制安装指令"),
    "share": ("action", "分享"),
    "outbound": ("action", "打开 GitHub"),
    "favorite": ("action", "收藏"),
    "unfavorite": ("action", "取消收藏"),
    "login_open": ("account", "打开登录框"),
    "login": ("account", "登录"),
    "register": ("account", "注册"),
    "logout": ("account", "退出登录"),
    "add_open": ("action", "打开新增 Skill"),
    "feedback_open": ("action", "打开反馈"),
    "compare_mode": ("action", "打开对比模式"),
    "compare_add": ("action", "加入对比"),
    "compare": ("action", "开始对比"),
    "error": ("error", "前端报错"),
}
CLIENT_EVENTS = set(EVENTS) - {"login", "register"}


def label(name: str) -> str:
    return EVENTS.get(name, ("", name))[1]


def device_of(ua: str) -> str:
    os_ = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("HarmonyOS", "鸿蒙"), ("Android", "Android"),
                                ("Windows", "Windows"), ("Mac OS", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if k in ua), "未知系统")
    br = next((n for k, n in (("MicroMessenger", "微信"), ("QQ/", "QQ"), ("DingTalk", "钉钉"), ("Lark", "飞书"), ("Edg/", "Edge"),
                               ("Chrome/", "Chrome"), ("Firefox/", "Firefox"), ("Safari/", "Safari")) if k in ua), "浏览器")
    bot = any(k in ua.lower() for k in ("bot", "spider", "crawler", "headless", "curl/", "python-"))
    return f"{os_} · {br}" + (" · 爬虫" if bot else "")


def vid_of(request: Request) -> str:
    v = (request.headers.get("x-visitor-id") or "").strip()
    return v if VID_RE.match(v) else ""


def _ip(request: Request) -> str:
    from ..auth import client_ip

    return client_ip(request)[:64]


# ---------------------------------------------------------------- 写入

_rate: dict[str, list[float]] = defaultdict(list)


def rate_ok(key: str, limit: int = 120, window: int = 60) -> bool:
    """每个 IP 每分钟最多上报 limit 批，防刷。"""
    now = time.time()
    hits = [t for t in _rate[key] if now - t < window]
    ok = len(hits) < limit
    if ok:
        hits.append(now)
    _rate[key] = hits
    if len(_rate) > 5000:
        for k in [k for k, v in _rate.items() if not v or now - v[-1] > window]:
            _rate.pop(k, None)
    return ok


def touch_visitor(db: Session, vid: str, request: Request, user: User | None, *, referrer: str = "", landing: str = "",
                  n_events: int = 0) -> Visitor:
    now = utcnow()
    ip = _ip(request)
    where = geo.lookup(ip)
    v = db.get(Visitor, vid)
    if v is None:
        v = Visitor(id=vid, first_seen=now, last_seen=now, first_ip=ip, last_ip=ip, first_geo=where, last_geo=where,
                    device=device_of(request.headers.get("user-agent", ""))[:60], referrer=referrer[:300],
                    landing=landing[:300], visits=1, events=0, user_id=user.id if user else None)
        db.add(v)
    else:
        if now - v.last_seen > timedelta(minutes=30):
            v.visits += 1  # 隔 30 分钟以上算一次新访问
        v.last_seen, v.last_ip = now, ip
        if where:
            v.last_geo = where
        if user is not None and v.user_id is None:
            v.user_id = user.id
    v.events = (v.events or 0) + n_events
    return v


def ingest(db: Session, request: Request, user: User | None, vid: str, events: list[dict], *, referrer: str = "",
           landing: str = "") -> int:
    """前端批量上报。只收已知事件，props 截断，单批最多 50 条。"""
    ip = _ip(request)
    where = geo.lookup(ip)
    client = client_of(request)[0]
    rows = []
    for e in events[:50]:
        name = str(e.get("name") or "")
        if name not in CLIENT_EVENTS:
            continue
        props = e.get("props") if isinstance(e.get("props"), dict) else {}
        props = {str(k)[:30]: (v[:200] if isinstance(v, str) else v) for k, v in list(props.items())[:12]
                 if isinstance(v, (str, int, float, bool)) or v is None}
        rows.append(Event(vid=vid, user_id=user.id if user else None, name=name, category=EVENTS[name][0], props=props,
                          page=str(e.get("page") or "")[:300], ip=ip, geo=where[:80], client=client))
    touch_visitor(db, vid, request, user, referrer=referrer, landing=landing, n_events=len(rows))
    db.add_all(rows)
    db.commit()
    return len(rows)


def server_event(request: Request, name: str, user: User | None, props: dict | None = None) -> None:
    """服务端发生的事件（登录、注册），用独立会话写，失败不影响主流程。"""
    vid = vid_of(request)
    if not vid:
        return
    try:
        with SessionLocal() as db:
            ip = _ip(request)
            db.add(Event(vid=vid, user_id=user.id if user else None, name=name, category=EVENTS[name][0],
                         props=props or {}, page="", ip=ip, geo=geo.lookup(ip)[:80], client=client_of(request)[0]))
            v = touch_visitor(db, vid, request, user, n_events=1)
            if user is not None:
                v.user_id = user.id
                if name == "register" and v.converted_at is None and v.first_seen < utcnow() - timedelta(seconds=5):
                    v.converted_at = utcnow()
            db.commit()
    except Exception:
        log.exception("write server event failed")


# ---------------------------------------------------------------- 汇总与清理

def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=CN)
    return start, start + timedelta(days=1)


def today_cn() -> date:
    return datetime.now(CN).date()


def rollup(days: int = 3) -> int:
    """把最近几天（北京时间，不含今天）的事件汇总到 event_daily，可重复执行。"""
    n = 0
    with SessionLocal() as db:
        for i in range(1, days + 1):
            d = today_cn() - timedelta(days=i)
            s, e = day_bounds(d)
            rows = db.execute(select(Event.name, func.count(), func.count(distinct(Event.vid)))
                              .where(Event.created_at >= s, Event.created_at < e).group_by(Event.name)).all()
            pv = db.execute(select(func.count(distinct(Event.vid))).where(Event.created_at >= s, Event.created_at < e)).scalar() or 0
            db.execute(delete(EventDaily).where(EventDaily.day == d))
            for name, cnt, uv in rows:
                db.add(EventDaily(day=d, name=name, count=cnt, uv=uv))
            if rows:
                db.add(EventDaily(day=d, name="_visitors", count=pv, uv=pv))
            n += len(rows)
        db.commit()
    return n


def purge_old() -> int:
    with SessionLocal() as db:
        from .ops import retention

        days = retention(db)["events_days"]  # v3.3.64 保留天数可在后台调整
        n = db.execute(delete(Event).where(Event.created_at < utcnow() - timedelta(days=days))).rowcount
        db.commit()
        return n
