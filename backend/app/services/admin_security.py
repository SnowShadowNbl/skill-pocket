"""v3.3.55 后台批次 4b：管理员账号安全——登录记录、新设备提醒、高危操作二次验证。

- 新设备：同一个管理员从没出现过的「设备（系统 · 浏览器）+ IP 网段（IPv4 前两段 / IPv6 前三组）」组合。
  登录时给本人发站内消息，并提醒其他超级管理员。
- 二次验证：给管理员的邮箱发 6 位验证码（沿用登录验证码的频率和错误次数限制），确认后签发 5 分钟有效的令牌；
  高危接口要求请求头 X-Verify-Token（或查询参数 verify_token），缺失 / 过期返回 403 verify_required。
"""

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuthSession, User

ACTIONS = {"export_email": "导出含完整邮箱的用户名单", "change_email": "修改用户邮箱", "delete_user": "删除用户",
           "staff_role": "任免管理员或修改管理员角色", "retention": "修改数据保留天数", "schedule": "暂停或恢复定时任务",
           "code_limit": "修改验证码频率阈值"}
VERIFY_TTL = 300
_ser = URLSafeTimedSerializer(settings.secret_key, salt="admin-verify")


def net(ip: str) -> str:
    ip = (ip or "").strip()
    if ":" in ip:
        return ":".join(ip.split(":")[:3])
    parts = ip.split(".")
    return ".".join(parts[:2]) if len(parts) == 4 else ip


def device_key(device: str, ip: str) -> str:
    return f"{device}|{net(ip)}"


def is_new_device(db: Session, user_id: int, device: str, ip: str, exclude_id: int | None = None) -> bool:
    key = device_key(device, ip)
    stmt = select(AuthSession.device, AuthSession.ip).where(AuthSession.user_id == user_id)
    if exclude_id:
        stmt = stmt.where(AuthSession.id != exclude_id)
    seen = {device_key(d, i) for d, i in db.execute(stmt).all()}
    return bool(seen) and key not in seen  # 第一次登录不算「新设备」


def on_login(db: Session, user: User, sess: AuthSession) -> bool:
    """管理员登录后调用（同一事务里，session 已 flush）。返回是否新设备。"""
    from . import notify, users
    from .geo import lookup

    if not is_new_device(db, user.id, sess.device, sess.ip, exclude_id=sess.id):
        return False
    where = lookup(sess.ip) or "未知地区"
    notify.push(db, user.id, "system", "你的管理员账号在新设备上登录", f"{sess.device} · {where} · {sess.ip}。如果不是你本人，请尽快联系超级管理员。")
    for su in db.scalars(select(User).where(User.role == "admin", User.id != user.id)):
        notify.push(db, su.id, "system", f"管理员「{users.label(user)}」在新设备上登录", f"{sess.device} · {where} · {sess.ip}")
    return True


def logins(db: Session, user_id: int, limit: int = 50) -> list[dict]:
    from .client import CHANNELS, METHODS
    from .geo import lookup

    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user_id).order_by(AuthSession.id.asc())).all()
    seen: set[str] = set()
    out = []
    for s in rows:
        key = device_key(s.device, s.ip)
        out.append({"id": s.id, "at": s.created_at, "last_seen_at": s.last_seen_at, "ip": s.ip, "geo": lookup(s.ip) or "",
                    "device": s.device, "client": s.client, "client_label": CHANNELS.get(s.client or "", "未知"),
                    "client_version": s.client_version, "method": s.method, "method_label": METHODS.get(s.method or "", "未知"),
                    "new_device": bool(seen) and key not in seen, "active": s.revoked_at is None})
        seen.add(key)
    return list(reversed(out))[:limit]


# ---------------------------------------------------------------- 二次验证
def issue(user_id: int, action: str) -> str:
    return _ser.dumps({"u": user_id, "a": action})


def check_token(user: User, action: str, token: str | None) -> None:
    if not settings.admin_verify_required:
        return
    if not token:
        raise HTTPException(403, {"code": "verify_required", "message": f"「{ACTIONS.get(action, action)}」需要先验证身份", "action": action})
    try:
        data = _ser.loads(token, max_age=VERIFY_TTL)
    except SignatureExpired:
        raise HTTPException(403, {"code": "verify_required", "message": "身份验证已过期，请重新验证", "action": action})
    except BadSignature:
        raise HTTPException(403, {"code": "verify_required", "message": "身份验证无效，请重新验证", "action": action})
    if data.get("u") != user.id or data.get("a") != action:
        raise HTTPException(403, {"code": "verify_required", "message": "身份验证和当前操作不匹配，请重新验证", "action": action})


def token_from(request: Request) -> str | None:
    return request.headers.get("x-verify-token") or request.query_params.get("verify_token")


def require(action: str):
    """FastAPI 依赖：高危接口加 Depends(admin_security.require("delete_user"))。"""
    from fastapi import Depends

    from ..auth import require_admin

    def dep(request: Request, me: User = Depends(require_admin)) -> User:
        check_token(me, action, token_from(request))
        return me

    return dep
