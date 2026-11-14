from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db import get_db
from ..models import Favorite, Item, User
from ..schemas import LoginIn
from ..seed import KINDS
from ..services import mailer, wechat
from ..services.extract import model_label

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login")
def login(body: LoginIn, request: Request):
    """v1.x 的管理员密码登录，v2.0 起停用：管理员用 admin 账号登录。"""
    raise HTTPException(410, "管理员密码登录已停用，请用 admin 账号登录")


@router.get("/auth/check", dependencies=[Depends(auth.require_admin)])
def check():
    return {"ok": True}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True}


@router.get("/meta")
def meta(db: Session = Depends(get_db), me: User | None = Depends(auth.current_user_optional)):
    untranslated = db.scalar(select(func.count()).where(
        Item.repo_id.is_not(None), Item.status == "published", Item.ai_status.in_(("rule", "failed"))))
    # “今日”按服务器本地时区的 0 点计算
    today = datetime.combine(datetime.now().date(), time.min).astimezone(timezone.utc)
    today_new = db.scalar(select(func.count()).where(Item.status == "published", Item.collected_at >= today))
    return {
        "untranslated": untranslated,
        "today_new": today_new,
        # v3.2.1 首页第四个指标：今日下架（今天被检测为失效、已下线的条目）
        "today_offline": db.scalar(select(func.count()).select_from(Item).where(Item.status == "offline", Item.offline_at >= today)),
        # v3.1 首页「收录条目」统一用这个数（与列表总数同口径：已发布），不再用分类合计——停用分类里的条目会让两处差几条
        "published_total": db.scalar(select(func.count()).select_from(Item).where(Item.status == "published")),
        "favorites": db.scalar(select(func.count()).select_from(Favorite).join(Item, Item.id == Favorite.item_id)
                               .where(Favorite.owner_id == me.id, Item.status == "published")) if me else None,
        "email_login": mailer.email_login_ready(),
        "contact_email": settings.contact_email or None,
        "wx_qr": wechat.ready(),  # v3.3.9 网页微信扫码登录 / 绑定是否可用（服务器配了小程序 AppID / Secret）
        "ai_enabled": settings.ai_enabled,
        "ai_model": model_label() if settings.ai_enabled else None,
        "asr_model": settings.asr_model_label if settings.funasr_ws_url else None,
        "kinds": [{"key": k, "name": v[0], "icon": v[1], "desc": v[2]} for k, v in KINDS.items()],
        "asr_enabled": bool(settings.funasr_ws_url),
        "github_token": bool(settings.github_token),
        "admin_configured": bool(settings.admin_password_hash),
    }
