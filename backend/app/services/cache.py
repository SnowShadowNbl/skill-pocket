"""数据库里的通用缓存（多进程 / 重启后仍有效）。"""

import hashlib
from datetime import timedelta

from sqlalchemy import delete

from ..db import SessionLocal, utcnow
from ..models import CacheEntry


def make_key(prefix: str, raw: str) -> str:
    return f"{prefix}:{hashlib.sha1(raw.strip().lower().encode()).hexdigest()}"


def get(key: str):
    with SessionLocal() as db:
        e = db.get(CacheEntry, key)
        if e is None or e.expires_at <= utcnow():
            return None
        return e.value.get("v")


def put(key: str, value, ttl: timedelta) -> None:
    try:
        with SessionLocal() as db:
            db.merge(CacheEntry(key=key, value={"v": value}, expires_at=utcnow() + ttl))
            db.commit()
    except Exception:  # 缓存写失败（如并发写同一键）不影响主流程
        pass


def purge_expired() -> None:
    with SessionLocal() as db:
        db.execute(delete(CacheEntry).where(CacheEntry.expires_at <= utcnow()))
        db.commit()
