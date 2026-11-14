"""普通用户的每日额度：截图识别、长文识别、搜索添加都会消耗 AI，按账号限次；管理员不限。"""

from datetime import datetime, time, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CompareRun, FinderJob, Item, Upload, User

DAILY_NEW_ITEMS = 50  # 每人每天最多新增的条目数（每个条目都要 AI 提炼）


def _today_start() -> datetime:
    return datetime.combine(datetime.now().date(), time.min).astimezone(timezone.utc)


def ai_used_today(db: Session, user: User) -> int:
    since = _today_start()
    jobs = db.scalar(select(func.count()).select_from(FinderJob).where(FinderJob.user_id == user.id, FinderJob.created_at >= since))
    ups = db.scalar(select(func.count()).select_from(Upload).where(Upload.user_id == user.id, Upload.created_at >= since))
    cmp = db.scalar(select(func.count()).select_from(CompareRun).where(CompareRun.user_id == user.id, CompareRun.created_at >= since))
    return jobs + ups + cmp


def check_ai(db: Session, user: User) -> None:
    """v2.6 起按 AI 额度（token）判断，余额用完要充值；管理员不限。"""
    from . import billing

    billing.check(db, user)


def check_new_items(db: Session, user: User, n: int) -> None:
    if user.role in ("admin", "subadmin", "moderator", "support", "viewer"):
        return
    used = db.scalar(select(func.count()).select_from(Item).where(Item.created_by == user.id, Item.collected_at >= _today_start()))
    if used + n > DAILY_NEW_ITEMS:
        raise HTTPException(429, f"每天最多新增 {DAILY_NEW_ITEMS} 个条目，今天还可以加 {max(0, DAILY_NEW_ITEMS - used)} 个")
