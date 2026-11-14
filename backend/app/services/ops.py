"""v3.3.64 后台批次 6a：告警同步、数据保留天数、备份状态。

告警：资源监控的提醒（DeepSeek 余额、向量额度、磁盘、内存）+ 磁盘超过 80% + 备份超过 36 小时没更新，统一进 alerts 表。
- sync() 把「当前成立的条件」写进表：已有未恢复的同 key 告警就合并计数，否则新建；不再成立的系统告警自动恢复。
- 新建和自动恢复时给有「运行监控」权限的管理员发站内消息（同一告警 1 小时内不重复发）。
"""

import gzip
import json
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import Alert, AppMeta, User

LEVEL = {"bad": "critical", "warn": "warn", "info": "info"}
AUTO_SOURCES = ("resource", "backup")
NOTIFY_GAP = timedelta(hours=1)
BACKUP_STALE_HOURS = 36
_last_sync = 0.0
_sync_lock = threading.Lock()

# ---------------------------------------------------------------- 数据保留天数
RETENTION_DEFAULT = {"activity_days": 180, "events_days": 180, "logs_days": 180, "visitors_days": 365}
RETENTION_RANGE = (7, 730)


def retention(db: Session | None = None) -> dict:
    def read(s: Session) -> dict:
        m = s.get(AppMeta, "retention")
        try:
            v = json.loads(m.value) if m and m.value else {}
        except ValueError:
            v = {}
        return {k: int(v.get(k, d)) for k, d in RETENTION_DEFAULT.items()}

    if db is not None:
        return read(db)
    with SessionLocal() as s:
        return read(s)


def set_retention(db: Session, values: dict) -> dict:
    cur = retention(db)
    cur.update({k: int(v) for k, v in values.items() if k in RETENTION_DEFAULT})
    db.merge(AppMeta(key="retention", value=json.dumps(cur)))
    db.commit()
    return cur


# ---------------------------------------------------------------- 备份状态
def backup_dir() -> Path:
    return Path(settings.backup_dir)


def backups() -> list[dict]:
    d = backup_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.sql.gz"), key=lambda x: x.stat().st_mtime, reverse=True)[:30]:
        st = p.stat()
        ok = st.st_size > 0
        if ok:
            try:
                with gzip.open(p, "rb") as f:
                    f.read(64)
            except OSError:
                ok = False
        out.append({"name": p.name, "at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc), "size_bytes": st.st_size, "ok": ok,
                    "note": "部署前备份" if p.name.startswith("pre-") else "每日备份"})
    return out


def backup_status() -> dict:
    hist = backups()
    if not backup_dir().is_dir():
        return {"last_at": None, "last_size_bytes": None, "last_ok": None, "history": [], "next_expected_at": None, "status": "unknown",
                "dir_visible": False}
    daily = [h for h in hist if h["note"] == "每日备份"]
    last = daily[0] if daily else (hist[0] if hist else None)
    status = "unknown" if last is None else ("warn" if not last["ok"] or utcnow() - last["at"] > timedelta(hours=BACKUP_STALE_HOURS) else "ok")
    return {"last_at": last["at"] if last else None, "last_size_bytes": last["size_bytes"] if last else None, "last_ok": last["ok"] if last else None,
            "history": hist[:14], "next_expected_at": (last["at"] + timedelta(days=1)) if daily else None, "status": status, "dir_visible": True}


# ---------------------------------------------------------------- 告警
def _conditions() -> list[dict]:
    from . import resources

    out = []
    for a in resources.alerts(fetch_remote=False):
        if a["key"] == "disk":
            continue  # 磁盘下面按 80% 单独判断
        out.append({"key": f"resource:{a['key']}", "source": "resource", "level": LEVEL.get(a["level"], "warn"),
                    "title": a["text"].split("，")[0][:200], "detail": a["text"]})
    try:
        du = shutil.disk_usage(settings.media_dir if settings.media_dir.exists() else "/")
        pct = du.used / du.total * 100
        if pct >= 80:
            out.append({"key": "resource:disk", "source": "resource", "level": "critical" if pct >= 90 else "warn",
                        "title": f"服务器磁盘已用 {pct:.0f}%", "detail": f"剩余 {du.free / 1024 ** 3:.1f} GB，请清理或扩容。"})
    except OSError:
        pass
    b = backup_status()
    if b["status"] == "warn":
        out.append({"key": "backup:stale", "source": "backup", "level": "critical",
                    "title": "数据库备份异常" if b["last_ok"] is False else f"超过 {BACKUP_STALE_HOURS} 小时没有新的数据库备份",
                    "detail": f"最近一次备份：{b['last_at'].astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M') if b['last_at'] else '无'}"})
    return out


def _recipients(db: Session) -> list[int]:
    from . import permissions

    roles = [r for r, m in permissions.MATRIX.items() if m.get("resources")]
    return list(db.scalars(select(User.id).where(User.role.in_(roles), User.status == "active")))


def _notify(db: Session, a: Alert, resolved: bool = False) -> None:
    from . import notify

    now = utcnow()
    if not resolved and a.notified_at and now - a.notified_at < NOTIFY_GAP:
        return
    title = f"{'已恢复' if resolved else '告警'}：{a.title}"[:200]
    for uid in _recipients(db):
        notify.push(db, uid, "system", title, a.detail[:500], "/admin/resources?tab=alerts")
    a.notified_at = now


def raise_alert(db: Session, key: str, source: str, level: str, title: str, detail: str = "") -> Alert:
    """记一条告警（同 key 未恢复则合并计数）。风控等模块也用这个。"""
    now = utcnow()
    a = db.scalar(select(Alert).where(Alert.key == key, Alert.status != "resolved").order_by(Alert.id.desc()))
    if a is None:
        a = Alert(key=key, source=source, level=level, title=title[:200], detail=detail, count=1, first_at=now, last_at=now, status="open")
        db.add(a)
        db.flush()
        _notify(db, a)
    else:
        a.count += 1
        a.last_at, a.level, a.title, a.detail = now, level, title[:200], detail
    return a


def sync(force: bool = False) -> None:
    """按当前条件更新告警表（最多每分钟一次，force 立即执行）。"""
    global _last_sync
    if not force and time.time() - _last_sync < 60:
        return
    with _sync_lock:
        _last_sync = time.time()
        with SessionLocal() as db:
            now = utcnow()
            current = {c["key"]: c for c in _conditions()}
            for c in current.values():
                a = db.scalar(select(Alert).where(Alert.key == c["key"], Alert.status != "resolved").order_by(Alert.id.desc()))
                if a is None:
                    raise_alert(db, c["key"], c["source"], c["level"], c["title"], c["detail"])
                else:  # 持续成立：只更新最后时间和内容，不累加次数（次数表示「出现过几次」）
                    a.last_at, a.level, a.title, a.detail = now, c["level"], c["title"][:200], c["detail"]
            for a in db.scalars(select(Alert).where(Alert.status != "resolved", Alert.source.in_(AUTO_SOURCES))):
                if a.key not in current:
                    a.status, a.resolved_at, a.resolved_auto = "resolved", now, True
                    _notify(db, a, resolved=True)
            db.commit()


# ---------------------------------------------------------------- v3.3.68 验证码频率阈值（后台可调，存 app_meta）
CODE_LIMIT_KEYS = {"resend_seconds": "同一邮箱重发间隔（秒）", "per_email_daily": "每个邮箱每天", "per_ip_daily": "每个 IP 每天",
                   "per_account_hour": "每个已登录账号每小时"}
CODE_LIMIT_RANGE = {"resend_seconds": (10, 600), "per_email_daily": (1, 100), "per_ip_daily": (1, 500), "per_account_hour": (1, 60)}


def code_limits(db: Session | None = None) -> dict:
    default = {"resend_seconds": settings.code_resend_seconds, "per_email_daily": settings.code_per_email_daily,
               "per_ip_daily": settings.code_per_ip_daily, "per_account_hour": 8}

    def read(s: Session) -> dict:
        m = s.get(AppMeta, "code_limits")
        try:
            v = json.loads(m.value) if m and m.value else {}
        except ValueError:
            v = {}
        return {k: int(v.get(k, d)) for k, d in default.items()}

    if db is not None:
        return read(db)
    with SessionLocal() as s:
        return read(s)


def set_code_limits(db: Session, values: dict) -> dict:
    cur = code_limits(db)
    cur.update({k: int(v) for k, v in values.items() if k in CODE_LIMIT_KEYS})
    db.merge(AppMeta(key="code_limits", value=json.dumps(cur)))
    db.commit()
    return cur
