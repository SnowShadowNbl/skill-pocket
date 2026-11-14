"""v3.3.66 后台批次 6c：接口健康、客户端报错上报（P12）、版本与部署记录（P30）。

- POST /api/client-errors：网页 / 小程序上报报错（不需要登录；按 IP 限频）。同一指纹合并计数。
- GET /api/admin/api-health：按小时汇总的接口请求（services/apistats）。
- GET /api/admin/client-errors(/summary)：报错列表与汇总。
- GET /api/admin/releases：更新日志里的每个版本，加上发布前后各 24 小时的接口 5xx 比例和客户端报错数。
"""

import hashlib
import re
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import client_ip, current_user_optional, require_admin
from ..db import get_db, utcnow
from ..models import ApiStat, ChangelogEntry, ClientError, User
from ..services import apistats, users
from ..services.client import CHANNELS, client_of

public = APIRouter(prefix="/api", tags=["client-errors"])
router = APIRouter(prefix="/api/admin", tags=["admin-observability"], dependencies=[Depends(require_admin)])
CN = ZoneInfo("Asia/Shanghai")
KINDS = {"js_error": "脚本错误", "api_fail": "接口失败", "miniapp_error": "小程序错误", "promise": "未处理的异步错误"}
_rate: dict[str, deque] = defaultdict(deque)
RATE_PER_MIN = 30


# ================================================================ 上报
class ErrorIn(BaseModel):
    kind: str = Field("js_error", pattern="^(js_error|api_fail|miniapp_error|promise)$")
    message: str = Field(min_length=1, max_length=2000)
    stack: str = Field("", max_length=8000)
    page: str = Field("", max_length=500)
    version: str = Field("", max_length=40)


def _norm(msg: str) -> str:
    """指纹用：去掉数字和长串，免得同一个错误因为 id 不同被拆成很多条。"""
    return re.sub(r"\d+", "N", re.sub(r"[0-9a-f]{16,}", "H", msg.lower()))[:300]


@public.post("/client-errors")
def report(body: ErrorIn, request: Request, db: Session = Depends(get_db), me: User | None = Depends(current_user_optional)):
    ip = client_ip(request)
    q = _rate[ip]
    now = time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MIN:
        return {"ok": False, "throttled": True}
    q.append(now)
    client, version = client_of(request)
    version = body.version.strip() or version
    page = re.sub(r"[?#].*$", "", body.page.strip())[:300]
    fp = hashlib.sha256(f"{client}|{version}|{body.kind}|{page}|{_norm(body.message)}".encode()).hexdigest()
    row = db.scalar(select(ClientError).where(ClientError.fingerprint == fp))
    t = utcnow()
    if row is None:
        row = ClientError(fingerprint=fp, client=client or "", version=version, kind=body.kind, page=page, message=body.message[:500],
                          stack=body.stack[:8000], count=0, users=0, first_at=t, last_at=t, user_agent=request.headers.get("user-agent", "")[:300])
        db.add(row)
    row.count += 1
    row.last_at = t
    if me is not None and row.last_user_id != me.id:
        row.users += 1
        row.last_user_id = me.id
    db.commit()
    return {"ok": True}


# ================================================================ 接口健康
@router.get("/api-health")
def api_health(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    apistats.flush()
    since = (datetime.now(CN) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(select(ApiStat).where(ApiStat.hour >= since)).all()
    total_req = sum(r.requests for r in rows)
    total_5xx = sum(r.errors_5xx for r in rows)
    all_b: Counter = Counter()
    per: dict[tuple, dict] = {}
    series: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        all_b.update(r.buckets or {})
        k = (r.method, r.path)
        a = per.setdefault(k, {"count": 0, "e5": 0, "e4": 0, "max": 0, "b": Counter(), "last_err": None, "status": None})
        a["count"] += r.requests
        a["e5"] += r.errors_5xx
        a["e4"] += r.errors_4xx
        a["max"] = max(a["max"], r.max_ms or 0)
        a["b"].update(r.buckets or {})
        if r.last_error_at and (a["last_err"] is None or r.last_error_at > a["last_err"]):
            a["last_err"], a["status"] = r.last_error_at, r.last_status
        d = r.hour.astimezone(CN).strftime("%Y-%m-%d")
        series[d]["requests"] += r.requests
        series[d]["errors_5xx"] += r.errors_5xx
    slow = sorted(({"path": p, "method": m, "count": a["count"], "p50_ms": apistats.percentile(a["b"], 0.5),
                    "p95_ms": apistats.percentile(a["b"], 0.95), "max_ms": a["max"]} for (m, p), a in per.items() if a["count"] >= 5),
                  key=lambda x: -(x["p95_ms"] or 0))[:20]
    errors = sorted(({"path": p, "method": m, "status": a["status"], "count": a["e5"] + a["e4"], "errors_5xx": a["e5"], "errors_4xx": a["e4"],
                      "last_at": a["last_err"], "sample": None} for (m, p), a in per.items() if a["e5"]),
                    key=lambda x: -x["errors_5xx"])[:20]
    dates = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return {"days": days, "since": "v3.3.66 起统计",
            "totals": {"requests": total_req, "errors_5xx": total_5xx, "error_rate": round(total_5xx / total_req, 4) if total_req else None,
                       "p95_ms": apistats.percentile(all_b, 0.95)},
            "slow": slow, "errors": errors,
            "series": [{"date": d, "requests": series[d]["requests"], "errors_5xx": series[d]["errors_5xx"]} for d in dates]}


# ================================================================ 客户端报错
def _err_out(e: ClientError, who: dict) -> dict:
    u = who.get(e.last_user_id)
    return {"id": e.id, "client": e.client or "unknown", "client_label": CHANNELS.get(e.client or "", "未知"), "version": e.version or "未知",
            "page": e.page, "kind": e.kind, "kind_label": KINDS.get(e.kind, e.kind), "message": e.message, "stack": e.stack[:2000],
            "count": e.count, "users": e.users, "first_at": e.first_at, "last_at": e.last_at,
            "user": {"id": u.id, "label": users.label(u)} if u else None, "user_agent": e.user_agent}


@router.get("/client-errors")
def list_errors(client: str = "", version: str = "", kind: str = "", user_id: int | None = None, q: str = "", days: int = Query(30, ge=1, le=365),
                page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(ClientError).where(ClientError.last_at >= utcnow() - timedelta(days=days))
    if client:
        stmt = stmt.where(ClientError.client == ("" if client == "unknown" else client))
    if version:
        stmt = stmt.where(ClientError.version == ("" if version in ("unknown", "未知") else version))
    if kind:
        stmt = stmt.where(ClientError.kind == kind)
    if user_id:
        stmt = stmt.where(ClientError.last_user_id == user_id)
    if q.strip():
        stmt = stmt.where(or_(ClientError.message.ilike(f"%{q.strip()}%"), ClientError.page.ilike(f"%{q.strip()}%")))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ClientError.last_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.last_user_id for r in rows if r.last_user_id} or {-1})))}
    return {"total": total, "page": page, "page_size": page_size, "kinds": KINDS, "items": [_err_out(e, who) for e in rows]}


@router.get("/client-errors/summary")
def errors_summary(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    since = (datetime.now(CN) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.scalars(select(ClientError).where(ClientError.last_at >= since)).all()
    by_c, by_v, by_p, series = Counter(), Counter(), Counter(), Counter()
    for e in rows:
        by_c[e.client or ""] += e.count
        by_v[(e.client or "", e.version or "")] += e.count
        by_p[e.page or "（未知页面）"] += e.count
        series[e.last_at.astimezone(CN).strftime("%Y-%m-%d")] += e.count
    dates = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return {"days": days, "total": sum(by_c.values()), "distinct": len(rows),
            "by_client": [{"client": c or "unknown", "label": CHANNELS.get(c, "未知"), "count": n} for c, n in by_c.most_common()],
            "by_version": [{"client": c or "unknown", "version": v or "未知", "count": n} for (c, v), n in by_v.most_common(20)],
            "by_page": [{"page": p, "count": n} for p, n in by_p.most_common(20)],
            "series": [{"date": d, "count": series[d]} for d in dates], "note": "按每组报错的最近一次时间归到日期，趋势是近似值"}


def errors_for_user(db: Session, user_id: int, limit: int = 5) -> list[dict]:
    rows = db.scalars(select(ClientError).where(ClientError.last_user_id == user_id).order_by(ClientError.last_at.desc()).limit(limit)).all()
    return [{"id": e.id, "client_label": CHANNELS.get(e.client or "", "未知"), "version": e.version or "未知", "kind_label": KINDS.get(e.kind, e.kind),
             "message": e.message[:200], "page": e.page, "count": e.count, "last_at": e.last_at} for e in rows]


def errors_by_version(db: Session, since: datetime) -> dict[tuple[str, str], int]:
    out: Counter = Counter()
    for c, v, n in db.execute(select(ClientError.client, ClientError.version, func.sum(ClientError.count))
                              .where(ClientError.last_at >= since).group_by(ClientError.client, ClientError.version)).all():
        out[(c or "", v or "")] += int(n or 0)
    return dict(out)


# ================================================================ 版本与部署记录
@router.get("/releases")
def releases(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    rows = db.execute(select(ChangelogEntry.version, func.max(ChangelogEntry.released_at)).group_by(ChangelogEntry.version)
                      .order_by(func.max(ChangelogEntry.released_at).desc())).all()
    total = len(rows)
    rows = rows[(page - 1) * page_size: page * page_size]
    stats_start = db.scalar(select(func.min(ApiStat.hour)))
    out = []
    for ver, at in rows:
        entries = db.scalars(select(ChangelogEntry).where(ChangelogEntry.version == ver).order_by(ChangelogEntry.id)).all()

        def window(a, b):
            if stats_start is None or a < stats_start:
                return None, None
            r = db.execute(select(func.sum(ApiStat.requests), func.sum(ApiStat.errors_5xx)).where(ApiStat.hour >= a, ApiStat.hour < b)).one()
            req, e5 = int(r[0] or 0), int(r[1] or 0)
            return (round(e5 / req, 4) if req else None), e5

        rb, eb = window(at - timedelta(hours=24), at)
        ra, ea = window(at, at + timedelta(hours=24))
        ce = lambda a, b: db.scalar(select(func.coalesce(func.sum(ClientError.count), 0)).where(  # noqa: E731
            ClientError.first_at >= a, ClientError.first_at < b))
        out.append({"version": ver, "deployed_at": at, "title": entries[0].title if entries else "",
                    "changes": [{"category": e.category, "title": e.title} for e in entries],
                    "api_5xx_before": eb, "api_5xx_after": ea, "error_rate_before": rb, "error_rate_after": ra,
                    "client_errors_before": int(ce(at - timedelta(hours=24), at)), "client_errors_after": int(ce(at, at + timedelta(hours=24)))})
    return {"total": total, "page": page, "page_size": page_size, "window_hours": 24, "items": out,
            "note": "接口数据从 v3.3.66 起统计，之前的版本为 null；客户端报错按新出现的报错计"}
