"""v3.3.40 后台「账号关系」：微信账号与邮箱账号的绑定、合并、扫码登录的展示与统计。

- /api/admin/accounts/overview：账号构成、注册渠道、按天趋势（注册 / 绑定 / 解绑 / 合并 / 绑定冲突）、扫码漏斗、小程序版本分布
- /api/admin/users/{id}/account：单个用户的身份、合并关系、绑定时间线、扫码记录、登录端
口径：只统计普通用户（不含管理员）；已合并 / 已注销的账号单列，不计入有效用户；历史数据缺失时显示「未知」，不倒推。
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import STAFF_ROLES, require_admin
from ..db import get_db, utcnow
from ..models import ActivityLog, AuthSession, User, WxQrLogin
from ..services import users
from ..services.client import CHANNELS, METHODS

router = APIRouter(prefix="/api/admin", tags=["admin-accounts"], dependencies=[Depends(require_admin)])
CN = ZoneInfo("Asia/Shanghai")

ACCOUNT_ACTIONS = ("register", "bind_wechat", "unbind_wechat", "bind_email", "merge_account", "bind_conflict", "delete_account")
ACTION_LABELS = {"register": "注册", "bind_wechat": "绑定微信", "unbind_wechat": "解绑微信", "bind_email": "绑定邮箱",
                 "merge_account": "账号合并", "bind_conflict": "绑定冲突", "delete_account": "注销账号",
                 "user_status": "停用 / 启用", "login": "登录"}
QR_STATUS = {"pending": "未扫码", "scanned": "已扫码未确认", "confirmed": "已确认", "done": "已完成", "expired": "已过期",
             "canceled": "已取消"}


def _kind(u: User) -> str:
    """账号形态：email_only / wechat_only / both / password_only（只有用户名密码，如老管理员）/ none。"""
    has_mail = bool(u.email)
    has_wx = bool(u.wx_openid)
    if has_mail and has_wx:
        return "both"
    if has_mail:
        return "email_only"
    if has_wx:
        return "wechat_only"
    return "password_only" if u.username else "none"


KIND_LABELS = {"email_only": "纯邮箱", "wechat_only": "纯微信", "both": "邮箱 + 微信", "password_only": "仅用户名密码", "none": "无登录方式"}


@router.get("/accounts/overview")
def accounts_overview(days: int = Query(30, ge=7, le=180), db: Session = Depends(get_db)):
    people = db.execute(select(User.id, User.email, User.wx_openid, User.username, User.status, User.signup_channel)
                        .where(User.role.not_in(STAFF_ROLES))).all()
    comp = Counter()
    channels = Counter()
    for _id, email, wx, uname, status, ch in people:
        if status == "merged":
            comp["merged"] += 1
            continue
        if status == "deleted":
            comp["deleted"] += 1
            continue
        comp[_kind(User(email=email, wx_openid=wx, username=uname))] += 1
        channels[ch or ""] += 1
    effective = sum(v for k, v in comp.items() if k not in ("merged", "deleted"))

    # 按天趋势（北京时间）
    since = (datetime.now(CN) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(select(ActivityLog.action, ActivityLog.created_at, ActivityLog.result)
                      .where(ActivityLog.action.in_(ACCOUNT_ACTIONS), ActivityLog.created_at >= since)).all()
    trend = defaultdict(Counter)
    totals = Counter()
    for action, at, _res in rows:
        day = at.astimezone(CN).strftime("%Y-%m-%d")
        trend[day][action] += 1
        totals[action] += 1
    dates = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    # 扫码漏斗：按用途统计各状态；过期的待扫码 / 已扫码按「过期」计
    now = utcnow()
    # 漏斗按原始状态算：生成 → 扫了（含扫后确认 / 取消 / 过期）→ 完成；「扫了没确认」和「没扫就过期」单列，方便排查
    funnel = {}
    stuck = 0
    for purpose in ("login", "bind"):
        f = Counter()
        for status, exp in db.execute(select(WxQrLogin.status, WxQrLogin.expires_at)
                                      .where(WxQrLogin.purpose == purpose, WxQrLogin.created_at >= since)).all():
            f["created"] += 1
            if status in ("scanned", "confirmed", "done", "canceled"):
                f["scanned"] += 1
            if status in ("confirmed", "done"):
                f["done"] += 1
            if status == "scanned":
                f["scanned_not_confirmed"] += 1
            if status == "canceled":
                f["canceled"] += 1
            if status == "pending":
                f["expired_unscanned" if exp <= now else "waiting"] += 1
        stuck += f["scanned_not_confirmed"]
        funnel[purpose] = {
            "label": "扫码登录" if purpose == "login" else "扫码绑定",
            **{k: f.get(k, 0) for k in ("created", "scanned", "done", "scanned_not_confirmed", "canceled", "expired_unscanned", "waiting")},
            "scan_rate": round(f["scanned"] / f["created"], 3) if f["created"] else None,
            "done_rate": round(f["done"] / f["created"], 3) if f["created"] else None,
        }

    # 小程序版本分布（最近 N 天的登录会话）
    ver = Counter(v or "未知" for (v,) in db.execute(select(AuthSession.client_version)
                                                    .where(AuthSession.client == "miniprogram", AuthSession.created_at >= since)).all())
    login_by_client = Counter(c or "" for (c,) in db.execute(select(AuthSession.client).where(AuthSession.created_at >= since)).all())

    return {
        "days": days,
        "composition": {k: {"label": KIND_LABELS.get(k, {"merged": "已合并", "deleted": "已注销"}.get(k, k)), "count": comp.get(k, 0)}
                        for k in ("email_only", "wechat_only", "both", "password_only", "merged", "deleted")},
        "effective_users": effective,
        "signup_channels": {k: {"label": CHANNELS.get(k, "未知"), "count": channels.get(k, 0)} for k in ("web-pc", "web-mobile", "miniprogram", "")},
        "totals": {a: {"label": ACTION_LABELS[a], "count": totals.get(a, 0)} for a in ACCOUNT_ACTIONS},
        "trend": [{"date": d, **{a: trend[d].get(a, 0) for a in ACCOUNT_ACTIONS}} for d in dates],
        "qr_funnel": funnel,
        "qr_scanned_not_confirmed": stuck,
        "miniprogram_versions": [{"version": k, "count": v} for k, v in ver.most_common(20)],
        "logins_by_client": {k: {"label": CHANNELS.get(k, "未知"), "count": login_by_client.get(k, 0)} for k in ("web-pc", "web-mobile", "miniprogram", "")},
    }


def _mask_openid(o: str | None) -> str:
    return f"…{o[-6:]}" if o else ""


@router.get("/users/{user_id}/account")
def user_account(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "用户不存在")
    into = db.get(User, u.merged_into) if u.merged_into else None
    merged_from = db.scalars(select(User).where(User.merged_into == u.id).order_by(User.id)).all()
    ids = [u.id] + [m.id for m in merged_from]
    events = db.scalars(select(ActivityLog).where(
        ActivityLog.action.in_(ACCOUNT_ACTIONS + ("user_status",)),
        or_(ActivityLog.user_id.in_(ids), (ActivityLog.target_type == "user") & ActivityLog.target_id.in_(ids)),
    ).order_by(ActivityLog.id.desc()).limit(50)).all()
    qrs = db.scalars(select(WxQrLogin).where(or_(WxQrLogin.web_user_id == u.id, WxQrLogin.wx_user_id == u.id))
                     .order_by(WxQrLogin.created_at.desc()).limit(20)).all()
    now = utcnow()
    clients = Counter((s.client or "") for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id)))
    return {
        "id": u.id, "nickname": u.nickname, "account_label": users.account_id(u), "status": u.status,
        "kind": _kind(u), "kind_label": KIND_LABELS.get(_kind(u)),
        "identities": {
            "email": u.email or "", "username": u.username or "", "has_password": bool(u.password_hash),
            "wechat": {"bound": bool(u.wx_openid), "openid": _mask_openid(u.wx_openid), "unionid": bool(u.wx_unionid)},
        },
        "signup_channel": u.signup_channel or "", "signup_channel_label": CHANNELS.get(u.signup_channel or "", "未知"),
        "merged_into": {"id": into.id, "label": users.label(into)} if into else None,
        "merged_from": [{"id": m.id, "label": users.label(m), "kind_label": KIND_LABELS.get(_kind(m))} for m in merged_from],
        "timeline": [{"id": e.id, "action": e.action, "action_label": ACTION_LABELS.get(e.action, e.action), "summary": e.summary,
                      "result": e.result or "ok", "message": e.message or "", "reason": e.reason or "",
                      "created_at": e.created_at} for e in events],
        "qr_logins": [{"purpose": q.purpose, "purpose_label": "扫码登录" if q.purpose == "login" else "扫码绑定",
                       "status": "expired" if q.status in ("pending", "scanned") and q.expires_at <= now else q.status,
                       "status_label": QR_STATUS.get("expired" if q.status in ("pending", "scanned") and q.expires_at <= now else q.status),
                       "role": "网页账号" if q.web_user_id == u.id else "扫码的微信", "created_at": q.created_at} for q in qrs],
        "logins_by_client": {CHANNELS.get(k, "未知"): v for k, v in clients.items()},
        "login_method_labels": METHODS,
    }
