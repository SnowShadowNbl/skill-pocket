"""账号：邮箱验证码登录注册一体、密码登录、找回 / 修改密码、资料、登录设备、注销，以及「我的」数据。"""

import hashlib
import re
import secrets
import threading
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from .. import auth
from ..config import settings
from ..db import get_db, utcnow
from ..models import AuthSession, Category, Comment, ItemReview, EmailCode, EmailLog, FavDimension, Favorite, Item, User
from ..schemas import item_card, public_user  # noqa: F401
from ..services import activity, geo, judge, mailer, users, visits
from ..services.client import client_of

router = APIRouter(prefix="/api", tags=["account"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PURPOSES = ("login", "reset", "change", "delete")
AVATARS = ("indigo", "pink", "teal", "amber", "violet", "sky", "rose", "lime")
MAX_CODE_ATTEMPTS = 5


def user_out(u: User) -> dict:
    out = {"id": u.id, "email": u.email, "username": u.username, "nickname": u.nickname, "avatar": u.avatar,
           "role": u.role, "has_password": bool(u.password_hash), "created_at": u.created_at,
           "needs_setup": auth.admin_needs_setup(u),
           "wechat_bound": bool(u.wx_openid), "has_email": bool(u.email), "prefs": u.prefs or {}}
    if u.role in auth.STAFF_ROLES:  # v3.3.55 管理员：角色、各后台模块的读写权限、能力
        from ..services import permissions

        out.update(role_label=permissions.ROLE_LABELS.get(u.role, u.role), permissions=permissions.permissions(u.role),
                   capabilities=permissions.capabilities(u.role))
    return out


def _norm_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "邮箱格式不对")
    return email


def _code_hash(email: str, purpose: str, code: str) -> str:
    return hashlib.sha256(f"{settings.secret_key}:{email}:{purpose}:{code}".encode()).hexdigest()


def _check_password_strength(pw: str) -> None:
    if len(pw) < 8 or len(pw) > 64:
        raise HTTPException(400, "密码长度需要 8~64 位")
    if pw.isdigit() or pw.isalpha():
        raise HTTPException(400, "密码需要同时包含字母和数字（或符号）")


def _check_nickname(name: str) -> str:
    name = name.strip()
    if not 2 <= len(name) <= 20:
        raise HTTPException(400, "昵称需要 2~20 个字")
    try:
        ok, reason = judge.check_nickname(name)
    except judge.JudgeUnavailable:
        ok, reason = True, ""
    if not ok:
        raise HTTPException(400, f"这个昵称不太合适：{reason}" if reason else "这个昵称不太合适，换一个吧")
    return name


# ---------------------------------------------------------------- 验证码

class CodeIn(BaseModel):
    email: str = ""
    purpose: str = Field("login", pattern="^(login|reset|change|delete)$")
    # v3.3.11 已登录用户可以不带（小程序真机算人机校验太慢）；未登录时仍然必填
    pow_token: str = ""
    pow_nonce: str = ""


# 已登录用户免人机校验，改按用户限频：每小时最多 8 次
USER_CODE_PER_HOUR = 8
_user_code_hits: dict[int, list[float]] = {}
_user_code_lock = threading.Lock()


def _limited(kind: str, key: str, ip: str = "") -> None:
    """v3.3.68 记一次「验证码请求被限频」：后台验证码风控统计用（同一 key 一分钟内只记一次）。"""
    k = f"{kind}:{key}"
    now = time.time()
    if now - _limited_seen.get(k, 0) < 60:
        return
    _limited_seen[k] = now
    activity.record("code_limited", f"验证码请求被限制（{kind}）", actor="guest", ip=ip, target_type="code_limit", target_label=k[:200],
                    result="failed")


_limited_seen: dict[str, float] = {}


def _user_code_limit(uid: int) -> None:
    from ..services.ops import code_limits

    per_hour = code_limits()["per_account_hour"]
    now = time.time()
    with _user_code_lock:
        hits = [t for t in _user_code_hits.get(uid, []) if now - t < 3600]
        if len(hits) >= per_hour:
            _limited("account", str(uid))
            raise HTTPException(429, "获取验证码太频繁了，请稍后再试")
        hits.append(now)
        _user_code_hits[uid] = hits


@router.get("/auth/challenge")
def challenge():
    """发验证码前的人机校验题目（浏览器算出 nonce 后随验证码请求一起提交）。"""
    return auth.issue_challenge()


@router.post("/auth/code")
def send_code(body: CodeIn, request: Request, db: Session = Depends(get_db),
              me: User | None = Depends(auth.current_user_optional)):
    if me is None:
        if not body.pow_token or not body.pow_nonce:
            raise HTTPException(400, "缺少安全校验，请刷新后重试")
        auth.verify_pow(body.pow_token, body.pow_nonce)
    else:
        _user_code_limit(me.id)
    if not mailer.email_login_ready():
        raise HTTPException(503, "邮件验证码服务正在开通中，暂时请使用密码登录")
    if body.purpose in ("change", "delete"):
        if me is None:
            raise HTTPException(401, "请先登录", headers={"X-Login-Required": "1"})
        if not me.email:
            raise HTTPException(400, "这个账号没有绑定邮箱")
        email = me.email
    else:
        email = _norm_email(body.email)
    if body.purpose == "reset":
        u = db.scalar(select(User).where(User.email == email, User.status != "deleted"))
        if u is None:
            raise HTTPException(400, "这个邮箱还没有注册，直接用验证码登录即可")

    from ..services.ops import code_limits

    lim = code_limits(db)  # v3.3.68 阈值可在后台调整
    now = utcnow()
    ip = auth.client_ip(request)
    last = db.scalar(select(EmailCode.created_at).where(EmailCode.email == email, EmailCode.purpose == body.purpose)
                     .order_by(EmailCode.created_at.desc()).limit(1))
    if last and (now - last).total_seconds() < lim["resend_seconds"]:
        wait = lim["resend_seconds"] - int((now - last).total_seconds())
        raise HTTPException(429, f"发送太频繁，请 {wait} 秒后再试")
    day = now - timedelta(days=1)
    if db.scalar(select(func.count()).select_from(EmailCode).where(EmailCode.email == email, EmailCode.created_at >= day)) >= lim["per_email_daily"]:
        _limited("email", email, ip)
        raise HTTPException(429, "这个邮箱今天收到的验证码太多了，明天再试")
    if db.scalar(select(func.count()).select_from(EmailCode).where(EmailCode.ip == ip, EmailCode.created_at >= day)) >= lim["per_ip_daily"]:
        _limited("ip", ip, ip)
        raise HTTPException(429, "当前网络今天发送的验证码太多了，明天再试")
    if db.scalar(select(func.count()).select_from(EmailLog).where(EmailLog.created_at >= day, EmailLog.ok.is_(True))) >= settings.email_daily_limit:
        raise HTTPException(503, "今天的邮件发送量已达上限，请明天再试或使用密码登录")

    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(EmailCode(email=email, purpose=body.purpose, code_hash=_code_hash(email, body.purpose, code), ip=ip,
                     created_at=now, expires_at=now + timedelta(minutes=settings.code_ttl_minutes)))
    db.commit()
    try:
        mailer.send_code(email, code, body.purpose)
    except mailer.MailError:
        raise HTTPException(502, "验证码邮件发送失败，请稍后再试")
    out = {"ok": True, "cooldown": lim["resend_seconds"], "ttl_minutes": settings.code_ttl_minutes}
    if settings.auth_dev_codes:
        out["dev_code"] = code
    return out


def _consume_code(db: Session, email: str, purpose: str, code: str) -> None:
    rec = db.scalar(select(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.used_at.is_(None))
                    .order_by(EmailCode.created_at.desc()).limit(1))
    if rec is None or rec.expires_at <= utcnow():
        raise HTTPException(400, "验证码已过期，请重新获取")
    if rec.attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(400, "错误次数过多，这个验证码已失效，请重新获取")
    if not secrets.compare_digest(rec.code_hash, _code_hash(email, purpose, code.strip())):
        rec.attempts += 1
        db.commit()
        left = MAX_CODE_ATTEMPTS - rec.attempts
        raise HTTPException(400, f"验证码不对，还可以再试 {left} 次" if left else "错误次数过多，这个验证码已失效，请重新获取")
    rec.used_at = utcnow()
    db.commit()


# ---------------------------------------------------------------- 登录 / 注册

class CodeLoginIn(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


@router.post("/auth/login/code")
def login_by_code(body: CodeLoginIn, request: Request, db: Session = Depends(get_db)):
    """邮箱 + 验证码：已注册直接登录，未注册自动注册。"""
    email = _norm_email(body.email)
    _consume_code(db, email, "login", body.code)
    user = db.scalar(select(User).where(User.email == email))
    is_new = user is None
    if is_new:
        prefix = email.split("@")[0][:16]
        user = User(email=email, signup_channel=client_of(request)[0], nickname=prefix if len(prefix) >= 2 else f"用户{secrets.randbelow(9000) + 1000}",
                    avatar=AVATARS[secrets.randbelow(len(AVATARS))], role="user", status="active")
        db.add(user)
        db.flush()
    elif user.status != "active":
        raise HTTPException(403, "这个账号已被停用，如有疑问请联系管理员")
    token = auth.create_session(db, user, request, "email_code")
    activity.record("register" if is_new else "login", f"{'注册' if is_new else '验证码登录'}：{user.nickname}", user=user,
                    ip=auth.client_ip(request))
    visits.server_event(request, "register" if is_new else "login", user, {"method": "code"})
    return {"token": token, "user": user_out(user), "is_new": is_new}


class PasswordLoginIn(BaseModel):
    account: str = Field(min_length=1, max_length=254)  # 邮箱，或管理员用户名 admin
    password: str = Field(min_length=1, max_length=128)


@router.post("/auth/login/password")
def login_by_password(body: PasswordLoginIn, request: Request, db: Session = Depends(get_db)):
    account = body.account.strip().lower()
    key = f"pw:{account}"
    auth.check_lock(key)
    auth.check_lock(f"pw-ip:{auth.client_ip(request)}")
    user = db.scalar(select(User).where((User.email == account) | (User.username == account)))
    if user is None or not auth.verify_password(body.password, user.password_hash):
        left = auth.record_fail(key)
        auth.record_fail(f"pw-ip:{auth.client_ip(request)}")
        activity.record("login_fail", f"密码登录失败：{account}", user=user, actor="guest" if user is None else None,
                        ip=auth.client_ip(request))
        raise HTTPException(401, f"账号或密码不对，还可以再试 {left} 次" if left > 0 else "错误次数过多，已暂时锁定")
    if user.status != "active":
        raise HTTPException(403, "这个账号已被停用，如有疑问请联系管理员")
    auth.clear_fails(key)
    activity.record("login", f"密码登录：{user.nickname}", user=user, ip=auth.client_ip(request))
    token = auth.create_session(db, user, request, "password")
    visits.server_event(request, "login", user, {"method": "password"})
    return {"token": token, "user": user_out(user), "is_new": False}


@router.post("/auth/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    s = auth.session_for(db, request.headers.get("authorization"))
    if s is not None:
        s.revoked_at = utcnow()
        db.commit()
    return {"ok": True}


@router.get("/auth/me")
def me(user: User | None = Depends(auth.current_user_optional)):
    return {"user": user_out(user) if user else None}


# ---------------------------------------------------------------- 资料与密码

class ProfileIn(BaseModel):
    nickname: str | None = None
    avatar: str | None = None


@router.patch("/auth/me")
def update_profile(body: ProfileIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if body.nickname is not None and body.nickname.strip() != user.nickname:
        user.nickname = _check_nickname(body.nickname)
    if body.avatar is not None and body.avatar != user.avatar:
        if body.avatar not in AVATARS:
            raise HTTPException(400, "头像不存在")
        _drop_avatar_file(user.avatar)
        user.avatar = body.avatar
    db.commit()
    return {"user": user_out(user)}


# ---------------------------------------------------------------- 偏好（v3.3.85）

HOME_MODES = ("classic", "simple")
HISTORY_MAX, HISTORY_LEN = 10, 200


class PrefsIn(BaseModel):
    home_mode: str | None = None
    search_history: list[str] | None = None


def _clean_history(items: list[str]) -> list[str]:
    out, seen = [], set()
    for s in items:
        s = (s or "").strip()[:HISTORY_LEN]
        if len(s) < 2 or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
        if len(out) >= HISTORY_MAX:
            break
    return out


@router.get("/me/prefs")
def get_prefs(user: User = Depends(auth.current_user)):
    return user.prefs or {}


@router.patch("/me/prefs")
def update_prefs(body: PrefsIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    prefs = dict(user.prefs or {})
    if body.home_mode is not None:
        if body.home_mode not in HOME_MODES:
            raise HTTPException(400, "首页模式不存在")
        prefs["home_mode"] = body.home_mode
    if body.search_history is not None:
        prefs["search_history"] = _clean_history(body.search_history)
    user.prefs = prefs  # 整个换掉，JSON 列才会被识别为已修改
    db.commit()
    return prefs


# ---------------------------------------------------------------- 上传头像

AVATAR_SIZE = 256  # 正方形边长；页面上最大显示 64px，2x 屏也足够清晰
MAX_AVATAR_UPLOAD = 10 * 1024 * 1024


def _drop_avatar_file(avatar: str) -> None:
    if avatar and avatar.startswith("avatars/"):
        (settings.media_dir / avatar).unlink(missing_ok=True)


def compress_avatar(content: bytes) -> bytes:
    """居中裁成正方形 → 缩到 256×256 → WebP（质量 82）。几 MB 的照片压到 10~20KB，肉眼看不出差别。"""
    from io import BytesIO

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(BytesIO(content))
        img.seek(0)  # 动图只取第一帧
        img = ImageOps.exif_transpose(img)  # 手机照片按拍摄方向摆正
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise HTTPException(400, "无法识别这张图片，请换一张 PNG / JPG / WebP") from e
    if img.width < 32 or img.height < 32:
        raise HTTPException(400, "图片太小了，至少 32×32 像素")
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    out = BytesIO()
    img.save(out, "WEBP", quality=82, method=6)
    return out.getvalue()


@router.post("/auth/me/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    content = await file.read(MAX_AVATAR_UPLOAD + 1)
    if len(content) > MAX_AVATAR_UPLOAD:
        raise HTTPException(400, "图片不能超过 10MB")
    data = compress_avatar(content)
    folder = settings.media_dir / "avatars"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"avatars/{user.id}-{hashlib.sha1(data).hexdigest()[:10]}.webp"
    (settings.media_dir / name).write_bytes(data)
    user = db.get(User, user.id)
    if user.avatar != name:
        _drop_avatar_file(user.avatar)
    user.avatar = name
    db.commit()
    return {"user": user_out(user), "bytes": len(data), "original_bytes": len(content)}


class PasswordIn(BaseModel):
    new_password: str
    old_password: str = ""
    code: str = ""


@router.post("/auth/password")
def set_password(body: PasswordIn, request: Request, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """首次设置密码直接设；修改密码要旧密码或邮箱验证码。改完后其他设备全部退出。"""
    user = db.get(User, user.id)
    if user.password_hash:
        if body.old_password:
            if not auth.verify_password(body.old_password, user.password_hash):
                raise HTTPException(400, "旧密码不对")
        elif body.code and user.email:
            _consume_code(db, user.email, "change", body.code)
        else:
            raise HTTPException(400, "请输入旧密码，或用邮箱验证码验证")
    _check_password_strength(body.new_password)
    user.password_hash = auth.hash_password(body.new_password)
    current = auth.session_for(db, request.headers.get("authorization"))
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        if current is None or s.id != current.id:
            s.revoked_at = utcnow()
    db.commit()
    return {"ok": True}


class ResetIn(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)
    new_password: str


@router.post("/auth/password/reset")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    email = _norm_email(body.email)
    _consume_code(db, email, "reset", body.code)
    user = db.scalar(select(User).where(User.email == email, User.status == "active"))
    if user is None:
        raise HTTPException(400, "账号不存在或已停用")
    _check_password_strength(body.new_password)
    user.password_hash = auth.hash_password(body.new_password)
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        s.revoked_at = utcnow()
    db.commit()
    auth.clear_fails(f"pw:{email}")
    return {"token": auth.create_session(db, user, request, "email_code"), "user": user_out(user)}


# ---------------------------------------------------------------- 登录设备

@router.get("/auth/sessions")
def sessions(request: Request, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    current = auth.session_for(db, request.headers.get("authorization"))
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
                                                AuthSession.expires_at > utcnow()).order_by(AuthSession.last_seen_at.desc()))
    return [{"id": s.id, "device": s.device, "ip": s.ip, "geo": geo.lookup(s.ip), "created_at": s.created_at, "last_seen_at": s.last_seen_at,
             "current": current is not None and s.id == current.id} for s in rows]


@router.delete("/auth/sessions/{session_id}")
def revoke_session(session_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    s = db.get(AuthSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "设备不存在")
    s.revoked_at = utcnow()
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 注销账号

class DeleteIn(BaseModel):
    # v3.3.17 有邮箱：邮箱验证码确认；只有微信的账号：输入「注销」两个字确认
    code: str = Field("", max_length=6)
    confirm: str = ""


@router.post("/auth/delete")
def delete_account(body: DeleteIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """收藏与收藏分类删除；评论和提交的条目保留，显示为「已注销用户」；邮箱释放，可重新注册。"""
    if user.role in auth.STAFF_ROLES:
        raise HTTPException(400, "管理员账号不能注销，请先让超级管理员取消你的管理员身份")
    user = db.get(User, user.id)
    if user.email:
        if len(body.code) != 6:
            raise HTTPException(400, "请输入邮箱收到的 6 位验证码")
        _consume_code(db, user.email, "delete", body.code)
    elif body.confirm.strip() != "注销":
        raise HTTPException(400, "请输入「注销」确认")
    nickname = user.nickname
    users.anonymize(db, user)
    db.commit()
    # 日志用独立会话写，必须在本事务提交之后（SQLite 下否则会互相等锁）
    activity.record("delete_account", f"注销账号：{nickname}", user=user)
    return {"ok": True}


# ---------------------------------------------------------------- 「我的」数据

@router.get("/auth/me/quota")
def my_quota(db: Session = Depends(get_db), me: User = Depends(auth.current_user)):
    """我的 AI 额度：余额、今天和近 30 天的用量、充值与调整记录。"""
    from ..services import billing

    return billing.user_summary(db, me)


@router.get("/me/comments")
def my_comments(page: int = Query(1, ge=1), user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    base = select(Comment).where(Comment.user_id == user.id, Comment.status.in_(("visible", "pending")))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.options(joinedload(Comment.item)).order_by(Comment.created_at.desc()).offset((page - 1) * 20).limit(20)).all()
    return {"total": total, "items": [{"id": c.id, "item_id": c.item_id, "item_name": c.item.name, "content": c.content,
                                       "input_type": c.input_type, "created_at": c.created_at, "status": c.status or "visible"} for c in rows]}


@router.get("/me/submissions")
def my_submissions(page: int = Query(1, ge=1), user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """我提交的条目：含审核状态、处理进度和最近一次审核结论（谁、何时、理由）。"""
    base = select(Item).where(Item.created_by == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
                      .order_by(Item.collected_at.desc()).offset((page - 1) * 24).limit(24)).unique().all()
    last = {}
    for r in db.scalars(select(ItemReview).where(ItemReview.item_id.in_([i.id for i in rows])).order_by(ItemReview.id)):
        last[r.item_id] = r
    return {"total": total, "items": [{
        **item_card(i), "status": i.status, "updated_at": i.updated_at, "ai_error": i.ai_error, "review_note": i.review_note,
        "last_review": {"reviewer": r.reviewer, "decision": r.decision, "reason": r.reason, "at": r.created_at} if (r := last.get(i.id)) else None,
    } for i in rows]}


@router.get("/me/stats")
def my_stats(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return {
        "favorites": db.scalar(select(func.count()).select_from(Favorite).where(Favorite.owner_id == user.id)),
        "comments": db.scalar(select(func.count()).select_from(Comment).where(Comment.user_id == user.id, Comment.status.in_(("visible", "pending")))),
        "submissions": db.scalar(select(func.count()).select_from(Item).where(Item.created_by == user.id)),
    }

