"""v3.3.65 后台批次 6b：邮件发送记录、站内消息发送记录、每日推送执行记录。

邮件：只有验证码邮件（登录 / 找回密码 / 修改 / 注销 / 后台二次验证），记录在 email_logs；退信和单封耗时没有记录，给 null。
站内消息：notifications 表本身就是发送记录（只保留 60 天）。
每日推送：从 v3.3.64 起每次执行记一条（app_meta push_runs，保留最近 60 次）。
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import AppMeta, EmailLog, Notification, User
from ..services import users
from ..services.mailer import PURPOSE_LABEL
from .user_care import KIND_LABELS

router = APIRouter(prefix="/api/admin", tags=["admin-comms"], dependencies=[Depends(require_admin)])
CN = ZoneInfo("Asia/Shanghai")
MAIL_PURPOSES = {**PURPOSE_LABEL, "change": "修改邮箱 / 后台身份验证"}


def _mask(email: str) -> str:
    name, _, domain = (email or "").partition("@")
    return f"{name[:2]}***@{domain}" if domain else "***"


def _day_range(created_from: str, created_to: str):
    from .admin import _parse_day

    a, b = _parse_day(created_from), _parse_day(created_to)
    return a, (b + timedelta(days=1)) if b else None


@router.get("/emails")
def list_emails(purpose: str = "", status: str = Query("", pattern="^(|sent|failed)$"), q: str = "", created_from: str = "",
                created_to: str = "", page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(EmailLog)
    if purpose:
        stmt = stmt.where(EmailLog.purpose == purpose)
    if status:
        stmt = stmt.where(EmailLog.ok.is_(status == "sent"))
    if q.strip():
        stmt = stmt.where(or_(EmailLog.email.ilike(f"%{q.strip()}%"), EmailLog.error.ilike(f"%{q.strip()}%")))
    a, b = _day_range(created_from, created_to)
    if a:
        stmt = stmt.where(EmailLog.created_at >= a)
    if b:
        stmt = stmt.where(EmailLog.created_at < b)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sent = db.scalar(select(func.count()).select_from(stmt.where(EmailLog.ok.is_(True)).subquery())) or 0
    rows = db.scalars(stmt.order_by(EmailLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    who = {u.email.lower(): u for u in db.scalars(select(User).where(func.lower(User.email).in_({r.email.lower() for r in rows} or {""})))}
    return {"total": total, "page": page, "page_size": page_size, "purposes": MAIL_PURPOSES,
            "counts": {"sent": sent, "failed": total - sent, "bounced": None},
            "items": [{"id": r.id, "at": r.created_at, "purpose": r.purpose, "purpose_label": MAIL_PURPOSES.get(r.purpose, r.purpose),
                       "email": _mask(r.email), "user": {"id": u.id, "label": users.label(u)} if (u := who.get(r.email.lower())) else None,
                       "status": "sent" if r.ok else "failed", "error": r.error or "", "channel": r.provider, "duration_ms": None} for r in rows]}


@router.get("/emails/stats")
def email_stats(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    since = (datetime.now(CN) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(select(EmailLog.purpose, EmailLog.ok, EmailLog.created_at).where(EmailLog.created_at >= since)).all()
    sent = sum(1 for _, ok, _ in rows if ok)
    failed = len(rows) - sent
    by = defaultdict(lambda: Counter())
    series = defaultdict(Counter)
    for p, ok, at in rows:
        by[p]["sent" if ok else "failed"] += 1
        series[at.astimezone(CN).strftime("%Y-%m-%d")]["sent" if ok else "failed"] += 1
    dates = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return {"days": days, "sent": sent, "failed": failed, "bounced": None, "fail_rate": round(failed / len(rows), 3) if rows else None,
            "by_purpose": [{"purpose": p, "label": MAIL_PURPOSES.get(p, p), "sent": c["sent"], "failed": c["failed"]} for p, c in by.items()],
            "series": [{"date": d, "sent": series[d]["sent"], "failed": series[d]["failed"]} for d in dates]}


@router.get("/notifications")
def list_notifications(kind: str = "", user_id: int | None = None, created_from: str = "", created_to: str = "",
                       page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    conds = []
    if kind:
        conds.append(Notification.kind == kind)
    if user_id:
        conds.append(Notification.user_id == user_id)
    a, b = _day_range(created_from, created_to)
    if a:
        conds.append(Notification.created_at >= a)
    if b:
        conds.append(Notification.created_at < b)
    stmt = select(Notification).where(*conds)
    total = db.scalar(select(func.count()).select_from(Notification).where(*conds)) or 0
    agg = db.execute(select(Notification.kind, func.count(), func.count(Notification.read_at)).where(*conds).group_by(Notification.kind)).all()
    rows = db.scalars(stmt.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    ids = {x for r in rows for x in (r.user_id, r.sender_id) if x}
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids or {-1})))}
    lab = lambda uid: {"id": uid, "label": users.label(who[uid])} if uid in who else None  # noqa: E731
    return {"total": total, "page": page, "page_size": page_size, "kinds": KIND_LABELS, "retention_days": 60,
            "by_kind": [{"kind": k, "label": KIND_LABELS.get(k, k), "sent": n, "read": r, "read_rate": round(r / n, 3) if n else None}
                        for k, n, r in agg],
            "items": [{"id": n.id, "user": lab(n.user_id), "kind": n.kind, "kind_label": KIND_LABELS.get(n.kind, n.kind), "title": n.title,
                       "at": n.created_at, "read_at": n.read_at, "source": lab(n.sender_id) or "系统"} for n in rows]}


@router.get("/push-runs")
def push_runs(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=60), db: Session = Depends(get_db)):
    m = db.get(AppMeta, "push_runs")
    try:
        runs = json.loads(m.value) if m and m.value else []
    except ValueError:
        runs = []
    runs = list(reversed(runs))
    start = (page - 1) * page_size
    return {"total": len(runs), "page": page, "page_size": page_size, "since": "v3.3.64 起记录",
            "items": [{"id": i + start + 1, "kind": "daily", "kind_label": "每日上新与版本提醒", "started_at": r.get("started_at"),
                       "finished_at": r.get("at"), "ok": r.get("ok"), "users_targeted": None,
                       "sent": (r.get("digests") or 0) + (r.get("releases") or 0) if r.get("ok") else None,
                       "digests": r.get("digests"), "releases": r.get("releases"), "failed": None, "error": r.get("error", "")}
                      for i, r in enumerate(runs[start:start + page_size])]}
