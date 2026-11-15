"""v3.1 小程序账号：微信登录、给当前账号绑定邮箱、账号合并、解绑微信。

一个人只对应一行 users：邮箱和微信是同一账号的两种登录方式。会话令牌与网页完全相同（auth.create_session）。
"""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db import get_db
from ..models import QuotaLedger, User
from ..services import activity, billing, merge, visits, wechat
from ..services.users import label as users_label
from .account import AVATARS, _consume_code, _norm_email, user_out

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["wechat"])

_ticket_serializer = URLSafeTimedSerializer(settings.secret_key, salt="skillpocket-merge")
TICKET_TTL = 600


# ---------------------------------------------------------------- 微信登录

class WxLoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)


@router.post("/auth/wx/login")
def wx_login(body: WxLoginIn, request: Request, db: Session = Depends(get_db)):
    """wx.login 的 code → openid：已绑定的账号直接登录；没有则新建一个只有微信的账号。"""
    try:
        info = wechat.code2session(body.code)
    except wechat.WechatError as e:
        raise HTTPException(503 if not wechat.ready() else 400, str(e))
    user = db.scalar(select(User).where(User.wx_openid == info["openid"]))
    is_new = user is None
    if is_new:
        user = User(wx_openid=info["openid"], wx_unionid=info.get("unionid"), signup_channel="miniprogram",
                    nickname=f"微信用户{secrets.randbelow(9000) + 1000}",
                    avatar=AVATARS[secrets.randbelow(len(AVATARS))], role="user", status="active")
        db.add(user)
        db.flush()
    elif user.status != "active":
        raise HTTPException(403, "这个账号已被停用，如有疑问请联系管理员")
    elif info.get("unionid") and not user.wx_unionid:
        user.wx_unionid = info["unionid"]
    if is_new:  # v3.3.91 微信注册当场发放免费额度（每个微信只发一次）
        billing.ensure(db, user)
    token = auth.create_session(db, user, request, "wechat")
    activity.record("register" if is_new else "login", f"{'微信注册' if is_new else '微信登录'}：{user.nickname}", user=user,
                    ip=auth.client_ip(request))
    visits.server_event(request, "register" if is_new else "login", user, {"method": "wechat"})
    return {"token": token, "user": user_out(user), "is_new": is_new}


# ---------------------------------------------------------------- 绑定邮箱（必要时合并）

class BindEmailIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)  # 邮箱；管理员填用户名 admin
    code: str = ""
    password: str = Field("", max_length=128)


def _preview(db: Session, primary: User, secondary: User) -> dict:
    return {
        "primary": {"id": primary.id, "nickname": primary.nickname, "email": primary.email,
                    "username": primary.username, **merge.counts(db, primary.id)},
        "secondary": {"id": secondary.id, "nickname": secondary.nickname, **merge.counts(db, secondary.id)},
    }


@router.post("/auth/me/email")
def bind_email(body: BindEmailIn, request: Request, me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """给当前（只有微信的）账号绑定邮箱。邮箱未注册：直接写入；已是网页账号：返回合并预览 + 合并凭证。"""
    me = db.get(User, me.id)
    if me.email or me.username:
        raise HTTPException(400, "这个账号已经绑定了邮箱")
    raw = body.email.strip().lower()
    if "@" in raw:
        account = _norm_email(raw)
        target = db.scalar(select(User).where(User.email == account))
    else:
        account = raw
        target = db.scalar(select(User).where(User.username == account))
        if target is None or not body.password:
            raise HTTPException(400, "邮箱格式不对")

    if body.code:
        if target is not None and not target.email:
            raise HTTPException(400, "这个账号请用密码验证")
        _consume_code(db, account, "login", body.code)
    elif body.password:
        key = f"pw:{account}"
        auth.check_lock(key)
        if target is None or not auth.verify_password(body.password, target.password_hash):
            left = auth.record_fail(key)
            raise HTTPException(400, f"账号或密码不对，还可以再试 {left} 次" if left > 0 else "错误次数过多，已暂时锁定")
        auth.clear_fails(key)
    else:
        raise HTTPException(400, "请输入验证码或密码")

    if target is None:
        me.email = account
        db.commit()
        activity.record("bind_email", f"绑定邮箱：{me.nickname}", user=me, ip=auth.client_ip(request))
        return {"status": "bound", "user": user_out(me)}
    if target.id == me.id:
        raise HTTPException(400, "这个账号已经绑定了邮箱")
    if target.status != "active":
        raise HTTPException(400, "这个邮箱对应的账号已停用，无法绑定")
    if target.wx_openid:
        raise _conflict(request, me, "email_has_wechat", "该邮箱已绑定其他微信，请先在网页解绑", target)
    ticket = _ticket_serializer.dumps({"p": target.id, "s": me.id, "n": secrets.token_hex(8)})
    return {"status": "merge", "ticket": ticket, "expires_in": TICKET_TTL, "preview": _preview(db, target, me)}


class MergeIn(BaseModel):
    ticket: str


_used_tickets: set[str] = set()


@router.post("/auth/me/merge")
def merge_account(body: MergeIn, request: Request, me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """确认合并：一个事务内把当前（微信）账号并入邮箱账号，返回主账号的新令牌。不可撤销。"""
    try:
        data = _ticket_serializer.loads(body.ticket, max_age=TICKET_TTL)
    except (BadSignature, SignatureExpired):
        raise HTTPException(400, "合并凭证已过期，请重新验证邮箱")
    if data["s"] != me.id:
        raise HTTPException(403, "合并凭证不属于当前账号")
    if data["n"] in _used_tickets:
        raise HTTPException(400, "合并凭证已使用过")
    secondary = db.get(User, me.id)
    primary = db.get(User, data["p"])
    if primary is None or primary.status != "active" or secondary.status != "active":
        raise HTTPException(400, "账号状态已变化，请重新验证邮箱")
    if primary.wx_openid or secondary.email or secondary.username:
        raise HTTPException(409, "账号绑定状态已变化，请重新验证邮箱")
    before = {"primary": merge.counts(db, primary.id), "secondary": merge.counts(db, secondary.id)}
    try:
        old_avatar = merge.merge_users(db, primary, secondary)
        billing.ensure(db, primary)  # v3.3.91 合并后邮箱账号带上了微信，按需发放免费额度
        token = auth.create_session(db, primary, request, "merge")  # 与合并同一次提交
    except Exception:
        db.rollback()
        log.exception("merge users %s -> %s failed", secondary.id, primary.id)
        raise HTTPException(500, "合并失败，数据没有任何改动，请稍后再试")
    _used_tickets.add(data["n"])
    merge.drop_file(old_avatar)
    activity.record("merge_account", f"合并账号：微信账号 #{secondary.id} 并入 {primary.nickname}（#{primary.id}）",
                    user=primary, target_type="user", target_id=secondary.id, detail=before, ip=auth.client_ip(request))
    return {"token": token, "user": user_out(primary)}


# ---------------------------------------------------------------- v3.3.92 小程序里给已登录的（邮箱）账号绑定当前微信

class BindWechatIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)  # wx.login 的 code（一次性，合并确认时要重新取）
    merge: bool = False


def _granted_since(db: Session, user_id: int, last_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(QuotaLedger.delta), 0)).where(
        QuotaLedger.user_id == user_id, QuotaLedger.kind == "grant", QuotaLedger.id > last_id)) or 0)


@router.post("/auth/me/wechat")
def bind_wechat_here(body: BindWechatIn, request: Request, me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """和网页扫码绑定同一套规则，只是微信身份来自 code2session。绑定后按需发放免费额度（每个微信一次），granted 是这次实际发放的数量。"""
    me = db.get(User, me.id)
    if me.wx_openid:
        raise HTTPException(400, "这个账号已经绑定了微信")
    try:
        info = wechat.code2session(body.code)
    except wechat.WechatError as e:
        raise HTTPException(503 if not wechat.ready() else 400, str(e))
    last = db.scalar(select(func.coalesce(func.max(QuotaLedger.id), 0))) or 0
    other = db.scalar(select(User).where(User.wx_openid == info["openid"]))
    if other is None:
        me.wx_openid, me.wx_unionid = info["openid"], info.get("unionid") or me.wx_unionid
        db.flush()
        billing.ensure(db, me)
        db.commit()
        activity.record("bind_wechat", f"小程序绑定微信：{me.nickname}", user=me, ip=auth.client_ip(request))
        return {"status": "bound", "user": user_out(me), "granted": _granted_since(db, me.id, last)}
    if other.id == me.id:
        return {"status": "bound", "user": user_out(me), "granted": 0}
    if other.status != "active":
        raise _conflict(request, me, "wechat_disabled", "这个微信对应的账号已被停用，如有疑问请联系管理员", other)
    if other.email or other.username:
        raise _conflict(request, me, "wechat_has_email", "这个微信已经绑定了另一个邮箱账号，请先在那个账号里解绑微信", other)
    c = merge.counts(db, other.id)
    has_data = any(c.values())
    if has_data and not body.merge:
        return {"status": "merge", "preview": _preview(db, me, other)}
    try:
        old_avatar = merge.merge_users(db, me, other)
        billing.ensure(db, me)
        tok = auth.create_session(db, me, request, "merge")
    except Exception:
        db.rollback()
        log.exception("mp bind merge %s -> %s failed", other.id, me.id)
        raise HTTPException(500, "绑定失败，数据没有任何改动，请稍后再试")
    merge.drop_file(old_avatar)
    activity.record("bind_wechat", f"小程序绑定微信：{me.nickname}{'（合并了微信账号的数据）' if has_data else ''}", user=me,
                    target_type="user", target_id=other.id, detail={"secondary": other.id, "counts": c}, ip=auth.client_ip(request))
    return {"status": "merged" if has_data else "bound", "token": tok, "user": user_out(me), "granted": _granted_since(db, me.id, last)}


# ---------------------------------------------------------------- 解绑微信

@router.post("/auth/me/wechat/unbind")
def unbind_wechat(request: Request, me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    me = db.get(User, me.id)
    if not me.wx_openid:
        raise HTTPException(400, "这个账号没有绑定微信")
    if not me.email and not (me.username and me.password_hash):
        raise HTTPException(400, "这个账号只能用微信登录，解绑后将无法登录。请先绑定邮箱")
    me.wx_openid = me.wx_unionid = None
    db.commit()
    activity.record("unbind_wechat", f"解绑微信：{me.nickname}", user=me, ip=auth.client_ip(request))
    return {"user": user_out(me)}


# ---------------------------------------------------------------- v3.3.9 网页微信扫码登录 / 绑定（小程序码）

from collections import deque
from datetime import timedelta

from ..db import utcnow
from ..models import WxQrLogin

QR_TTL = 600  # 10 分钟
_qr_hits: dict[str, deque] = {}


def _rate_limit(ip: str, limit: int = 20, window: int = 600) -> None:
    """同一个 IP 10 分钟内最多生成 20 个小程序码（每个都会调一次微信接口）。"""
    import time

    q = _qr_hits.setdefault(ip, deque())
    now = time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "操作太频繁，请稍后再试")
    q.append(now)


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}" if len(name) > 2 else f"{name[:1]}***@{domain}"


def _conflict(request: Request, me: User, code: str, message: str, other: User | None = None) -> HTTPException:
    """v3.3.40 绑定冲突留痕：失败的绑定也记进操作日志（result=failed），后台「账号关系」能统计和排查。返回异常由调用方 raise。"""
    activity.record("bind_conflict", f"绑定冲突：{message}", user=me, target_type="user" if other else "",
                    target_id=other.id if other else None, ip=auth.client_ip(request), result="failed",
                    message=message, detail={"code": code}, target_label=users_label(other) if other else "")
    return HTTPException(409, message)


def _qr(db: Session, token: str) -> WxQrLogin:
    q = db.get(WxQrLogin, token) if token and len(token) <= 32 else None
    if q is None:
        raise HTTPException(404, "二维码不存在")
    return q


def _status(q: WxQrLogin) -> str:
    if q.status in ("pending", "scanned") and q.expires_at <= utcnow():
        return "expired"
    return q.status


class QrIn(BaseModel):
    purpose: str = Field("login", pattern="^(login|bind)$")
    admin: bool = False  # v3.3.55 管理端扫码登录：只给管理员签发令牌


@router.post("/auth/wx/qr")
def create_qr(body: QrIn, request: Request, db: Session = Depends(get_db), me: User | None = Depends(auth.current_user_optional)):
    """网页生成小程序码：login 任何人可用；bind 需要网页已登录且还没绑微信。"""
    if body.purpose == "bind":
        if me is None:
            raise HTTPException(401, "请先登录", headers={"X-Login-Required": "1"})
        if me.wx_openid:
            raise HTTPException(400, "这个账号已经绑定了微信")
    _rate_limit(auth.client_ip(request))
    token = secrets.token_urlsafe(16)[:22]  # scene 最长 32 个字符
    try:
        image = wechat.qr_image(token)
    except wechat.WechatError as e:
        raise HTTPException(503, str(e))
    db.add(WxQrLogin(token=token, purpose=body.purpose, status="pending", web_user_id=me.id if body.purpose == "bind" else None,
                     result={"admin": True} if body.admin and body.purpose == "login" else {},
                     expires_at=utcnow() + timedelta(seconds=QR_TTL)))
    db.commit()
    return {"token": token, "image": image, "expires_in": QR_TTL}


@router.get("/auth/wx/qr/{token}")
def poll_qr(token: str, request: Request, db: Session = Depends(get_db), me: User | None = Depends(auth.current_user_optional)):
    """网页每 2 秒轮询。login 确认后这里签发网页令牌（只发一次，之后状态变成 done）；bind 返回绑定结果。"""
    q = _qr(db, token)
    if q.purpose == "bind" and (me is None or me.id != q.web_user_id):
        raise HTTPException(403, "无权查看")
    st = _status(q)
    out = {"status": st}
    if st == "scanned":
        wx_user = db.get(User, q.wx_user_id) if q.wx_user_id else None
        out["scanner"] = {"nickname": wx_user.nickname, "avatar": wx_user.avatar} if wx_user else None
    if st == "confirmed" and q.purpose == "login":
        user = db.get(User, q.wx_user_id)
        if user is None or user.status != "active":
            q.status = "canceled"
            db.commit()
            return {"status": "canceled"}
        if (q.result or {}).get("admin") and user.role not in auth.STAFF_ROLES:
            q.status = "canceled"
            db.commit()
            activity.record("login_fail", f"非管理员扫码登录管理端：{user.nickname}", user=user, ip=auth.client_ip(request),
                            result="failed", message="不是管理员")
            raise HTTPException(403, {"code": "not_staff", "message": "这个微信对应的账号不是管理员"})
        q.status = "done"
        tok = auth.create_session(db, user, request, "wx_qr")  # 与状态变更同一次提交
        activity.record("login", f"微信扫码登录网页：{user.nickname}", user=user, ip=auth.client_ip(request))
        visits.server_event(request, "login", user, {"method": "wechat_qr"})
        return {"status": "confirmed", "token": tok, "user": user_out(user)}
    if st in ("confirmed", "done") and q.purpose == "bind":
        out["status"] = "confirmed"
        out["result"] = q.result
        out["user"] = user_out(db.get(User, q.web_user_id))
    if st == "done" and q.purpose == "login":
        out["status"] = "expired"  # 令牌已经发过了
    return out


@router.get("/auth/wx/qr/{token}/info")
def qr_info(token: str, db: Session = Depends(get_db)):
    """小程序扫码确认页：读用途；bind 时显示网页账号的昵称和打码邮箱，让用户确认绑到哪个账号。"""
    q = _qr(db, token)
    # v3.3.17 加 expires_in（剩余秒数），客户端不用自己解析时间
    left = max(0, int((q.expires_at - utcnow()).total_seconds())) if q.expires_at else 0
    out = {"purpose": q.purpose, "status": _status(q), "expires_at": q.expires_at, "expires_in": left}
    if q.purpose == "bind":
        web = db.get(User, q.web_user_id)
        out["web_user"] = {"nickname": web.nickname, "email": _mask_email(web.email), "avatar": web.avatar} if web else None
    return out


def _open(db: Session, token: str, me: User) -> WxQrLogin:
    q = _qr(db, token)
    st = _status(q)
    if st == "expired":
        raise HTTPException(410, "二维码已过期，请在电脑上刷新后重新扫码")
    if st not in ("pending", "scanned"):
        raise HTTPException(409, "这个二维码已经处理过了")
    if q.wx_user_id and q.wx_user_id != me.id:
        raise HTTPException(409, "这个二维码已被其他微信扫过")
    if not db.get(User, me.id).wx_openid:
        raise HTTPException(400, "请在小程序里用微信登录后再扫码")
    return q


@router.post("/auth/wx/qr/{token}/scan")
def qr_scan(token: str, me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """小程序打开扫码页时调用：网页上显示「已扫码，请在手机上确认」。"""
    q = _open(db, token, me)
    q.status, q.wx_user_id = "scanned", me.id
    db.commit()
    return {"status": "scanned"}


class QrConfirmIn(BaseModel):
    merge: bool = False  # bind 时这个微信账号已有数据：第一次确认返回合并预览，用户同意后带 merge=true 再确认


@router.post("/auth/wx/qr/{token}/confirm")
def qr_confirm(token: str, request: Request, body: QrConfirmIn = QrConfirmIn(), me: User = Depends(auth.current_user),
               db: Session = Depends(get_db)):
    q = _open(db, token, me)
    wx_user = db.get(User, me.id)
    if q.purpose == "login":
        q.status, q.wx_user_id = "confirmed", wx_user.id
        db.commit()
        return {"status": "confirmed"}

    web = db.get(User, q.web_user_id)
    if web is None or web.status != "active":
        raise HTTPException(400, "网页上的账号状态已变化，请刷新后重试")
    if web.id == wx_user.id:
        q.status, q.result = "done", {"status": "bound"}
        db.commit()
        return {"status": "bound"}
    if web.wx_openid:
        raise _conflict(request, wx_user, "web_has_wechat", "网页账号已经绑定了别的微信", web)
    if wx_user.email or wx_user.username:
        raise _conflict(request, wx_user, "wechat_has_email", "这个微信已经绑定了另一个邮箱账号，请先在那个账号里解绑微信", web)
    c = merge.counts(db, wx_user.id)
    has_data = any(c.values())
    if has_data and not body.merge:
        return {"status": "merge", "preview": _preview(db, web, wx_user)}
    try:
        old_avatar = merge.merge_users(db, web, wx_user)
        billing.ensure(db, web)  # v3.3.91 邮箱账号绑定微信后发放免费额度（这个微信领过就不再发）
        q.status, q.wx_user_id = "done", web.id
        q.result = {"status": "merged" if has_data else "bound"}
        tok = auth.create_session(db, web, request, "merge")  # 小程序随即换成主账号的登录状态
    except Exception:
        db.rollback()
        log.exception("qr bind merge %s -> %s failed", wx_user.id, web.id)
        raise HTTPException(500, "绑定失败，数据没有任何改动，请稍后再试")
    merge.drop_file(old_avatar)
    activity.record("bind_wechat", f"扫码绑定微信：{web.nickname}{'（合并了微信账号的数据）' if has_data else ''}", user=web,
                    target_type="user", target_id=wx_user.id if has_data else web.id, detail={"secondary": wx_user.id, "counts": c}, ip=auth.client_ip(request))
    return {"status": q.result["status"], "token": tok, "user": user_out(web)}


@router.post("/auth/wx/qr/{token}/cancel")
def qr_cancel(token: str, me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = _open(db, token, me)
    q.status = "canceled"
    db.commit()
    return {"status": "canceled"}
