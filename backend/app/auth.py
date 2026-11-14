"""登录与权限。

- 用户：邮箱验证码 / 密码登录，会话令牌放在 Authorization: Bearer 里，库里只存令牌哈希
- 管理员：admin 账号登录后就是管理员会话；v1.x 的「管理员密码 → X-Admin-Token」仍然可用
- 人机校验：发验证码前做一次工作量证明（浏览器算几十万次哈希，脚本批量刷就很贵）
"""

import hashlib
import secrets
import threading
import time
from collections import defaultdict
from datetime import timedelta

import bcrypt
from fastapi import Depends, Header, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, utcnow
from .models import AuthSession, User

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="skillhub-admin")
_pow_serializer = URLSafeTimedSerializer(settings.secret_key, salt="skillpocket-pow")
_fails: dict[str, list[float]] = defaultdict(list)
_fails_lock = threading.Lock()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    # 前面只有我们自己的 nginx 一层代理，它把真实来源地址追加在最后；最前面的值可由客户端伪造，不能用
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "unknown")


_client_ip = client_ip


# ---------------------------------------------------------------- 失败次数锁定（密码登录、管理员密码）

def check_lock(key: str) -> None:
    window = settings.login_lock_minutes * 60
    now = time.time()
    with _fails_lock:
        _fails[key] = [t for t in _fails[key] if now - t < window]
        if len(_fails[key]) >= settings.login_max_fails:
            wait = int(window - (now - _fails[key][0])) // 60 + 1
            raise HTTPException(429, f"错误次数过多，请 {wait} 分钟后再试")


def record_fail(key: str) -> int:
    with _fails_lock:
        _fails[key].append(time.time())
        return settings.login_max_fails - len(_fails[key])


def clear_fails(key: str) -> None:
    with _fails_lock:
        _fails.pop(key, None)


# ---------------------------------------------------------------- v1.x 管理员密码（保留）

def login(request: Request, password: str) -> str:
    if not settings.admin_password_hash:
        raise HTTPException(500, "服务端未配置管理员密码（ADMIN_PASSWORD_HASH）")
    key = f"admin-pw:{client_ip(request)}"
    check_lock(key)
    if not verify_password(password, settings.admin_password_hash):
        left = record_fail(key)
        raise HTTPException(401, f"密码错误，还可尝试 {left} 次" if left > 0 else "密码错误，已锁定")
    clear_fails(key)
    return _serializer.dumps({"role": "admin"})


# ---------------------------------------------------------------- 用户会话

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _device(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    os_ = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                                ("Mac OS", "macOS"), ("Linux", "Linux")) if k in ua), "未知系统")
    br = next((n for k, n in (("MicroMessenger", "微信"), ("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                               ("Safari/", "Safari")) if k in ua), "浏览器")
    return f"{os_} · {br}"


def create_session(db: Session, user: User, request: Request, method: str = "") -> str:
    """签发登录令牌。v3.3.37 同时记下这次登录的端、版本和方式（后台用户详情「账号与设备」）。"""
    from .services.client import client_of

    token = secrets.token_urlsafe(32)
    now = utcnow()
    client, version = client_of(request)
    db.add(AuthSession(user_id=user.id, token_hash=_token_hash(token), device=_device(request), ip=client_ip(request),
                       created_at=now, last_seen_at=now, expires_at=now + timedelta(days=settings.session_days),
                       client=client, client_version=version, method=method[:16]))
    if user.role in STAFF_ROLES:  # v3.3.55 管理员新设备登录提醒
        db.flush()
        from .services import admin_security

        sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        try:
            admin_security.on_login(db, user, sess)
        except Exception:  # noqa: BLE001  提醒失败不影响登录
            pass
    user.last_login_at = now
    if client:
        user.last_client, user.last_client_version = client, version
    db.commit()
    return token


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def session_for(db: Session, authorization: str | None) -> AuthSession | None:
    token = _bearer(authorization)
    if not token:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    now = utcnow()
    if s is None or s.revoked_at is not None or s.expires_at <= now:
        return None
    if now - s.last_seen_at > timedelta(minutes=10):
        # 滑动续期：活跃用户不会被强制登出
        s.last_seen_at, s.expires_at = now, now + timedelta(days=settings.session_days)
        db.commit()
    return s


def current_user_optional(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User | None:
    s = session_for(db, authorization)
    if s is None:
        return None
    user = db.get(User, s.user_id)
    return user if user is not None and user.status == "active" else None


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(401, "请先登录", headers={"X-Login-Required": "1"})
    return user


# v3.3.55 管理员角色：超级管理员 admin（唯一）/ 管理员 subadmin（老角色）/ 内容审核 moderator / 客服 support / 只读 viewer。
# 各角色能访问哪些后台模块见 services/permissions.py
STAFF_ROLES = ("admin", "subadmin", "moderator", "support", "viewer")


def is_admin(user: User | None) -> bool:
    """超级管理员或子管理员。"""
    return user is not None and user.role in STAFF_ROLES


def is_super(user: User | None) -> bool:
    return user is not None and user.role == "admin"


def admin_needs_setup(user: User) -> bool:
    """超级管理员用「首次登录」进来、还没设置自己的密码。"""
    from .services import admin_setup

    return is_super(user) and admin_setup.pending()


def can(user: User | None, module: str, level: str = "w") -> bool:
    """v3.3.55 这个管理员对某个后台模块有没有读（r）/ 写（w）权限。"""
    from .services import permissions

    if user is None or not is_admin(user):
        return False
    have = permissions.MATRIX.get(user.role, {}).get(module)
    return have == "w" or (level == "r" and have == "r")


def require_admin(request: Request, user: User | None = Depends(current_user_optional)) -> User:
    """管理功能：所有管理员角色都能进入；v3.3.55 起再按「请求路径 → 后台模块」检查读写权限。"""
    from .services import permissions

    if user is None:
        raise HTTPException(401, "请先用管理员账号登录", headers={"X-Login-Required": "1"})
    if not is_admin(user):
        raise HTTPException(403, "需要管理员权限")
    if admin_needs_setup(user):
        raise HTTPException(403, "请先设置 Admin 的登录密码", headers={"X-Setup-Required": "1"})
    ok, module, need = permissions.check(user.role, request.url.path, request.method)
    if not ok:
        role = permissions.ROLE_LABELS.get(user.role, user.role)
        what = permissions.MODULE_LABELS.get(module, "这个功能")
        raise HTTPException(403, {"code": "no_permission",
                                  "message": f"当前角色（{role}）没有「{what}」的{'修改' if need == 'w' else '查看'}权限"})
    return user


def require_super(user: User = Depends(require_admin)) -> User:
    """任免管理员：只有超级管理员。"""
    if not is_super(user):
        raise HTTPException(403, "只有超级管理员可以操作")
    return user


# ---------------------------------------------------------------- 人机校验（工作量证明）

_used_pow: dict[str, float] = {}
_pow_lock = threading.Lock()
POW_TTL = 300


def issue_challenge() -> dict:
    salt = secrets.token_hex(12)
    return {"token": _pow_serializer.dumps({"s": salt, "b": settings.pow_bits}), "salt": salt, "bits": settings.pow_bits}


def _leading_zero_bits(digest: bytes) -> int:
    n = 0
    for byte in digest:
        if byte == 0:
            n += 8
            continue
        return n + 8 - byte.bit_length()
    return n


def verify_pow(token: str, nonce: str) -> None:
    try:
        data = _pow_serializer.loads(token, max_age=POW_TTL)
    except (BadSignature, SignatureExpired):
        raise HTTPException(400, "安全校验已过期，请重试")
    digest = hashlib.sha256(f"{data['s']}:{nonce}".encode()).digest()
    if _leading_zero_bits(digest) < data["b"]:
        raise HTTPException(400, "安全校验未通过，请重试")
    now = time.time()
    with _pow_lock:
        for k in [k for k, t in _used_pow.items() if now - t > POW_TTL]:
            _used_pow.pop(k, None)
        if data["s"] in _used_pow:
            raise HTTPException(400, "安全校验已使用过，请重试")
        _used_pow[data["s"]] = now
