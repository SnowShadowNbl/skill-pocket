"""超级管理员 Admin 的「首次登录」：不输密码直接进入，进去后必须先设置密码。

这个入口默认关闭，只能在服务器上用 `python -m app.cli open-admin-setup [小时]` 打开一个有时限的窗口；
Admin 设置好密码后永久关闭（之后只能用密码登录）。窗口打开期间，Admin 在设置密码前不能使用其他管理功能。
"""

from datetime import datetime, timedelta

from ..db import SessionLocal, utcnow
from ..models import AppMeta

UNTIL = "admin_setup_until"
DONE = "admin_password_set"


def _get(db, key: str) -> str:
    m = db.get(AppMeta, key)
    return m.value if m else ""


def is_open() -> bool:
    """现在能否用「首次登录」进入。"""
    with SessionLocal() as db:
        if _get(db, DONE) == "1":
            return False
        until = _get(db, UNTIL)
    try:
        return bool(until) and datetime.fromisoformat(until) > utcnow()
    except ValueError:
        return False


def pending() -> bool:
    """打开过首次登录窗口、Admin 还没设置自己的密码。"""
    with SessionLocal() as db:
        return bool(_get(db, UNTIL)) and _get(db, DONE) != "1"


def open_window(hours: float = 24) -> datetime:
    until = utcnow() + timedelta(hours=hours)
    with SessionLocal() as db:
        db.merge(AppMeta(key=UNTIL, value=until.isoformat()))
        done = db.get(AppMeta, DONE)
        if done:
            db.delete(done)
        db.commit()
    return until


def complete() -> None:
    with SessionLocal() as db:
        db.merge(AppMeta(key=DONE, value="1"))
        m = db.get(AppMeta, UNTIL)
        if m:
            db.delete(m)
        db.commit()
