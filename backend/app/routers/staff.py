"""管理员任免与超级管理员 Admin 的首次登录。

- 超级管理员 admin：唯一，可以把已注册用户设为子管理员、取消子管理员。
- 子管理员 subadmin：除任免管理员外，其他管理功能与超级管理员相同。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db, utcnow
from ..models import AuthSession, User
from ..services import activity, admin_setup, users, visits
from .account import _check_password_strength, user_out

router = APIRouter(tags=["staff"])


def _staff_out(u: User) -> dict:
    # v3.3.39 带上备注名和账号标识：设置管理员时能认出是谁（和用户管理页一致：有备注名先显示备注名）
    return {"id": u.id, "email": u.email, "username": u.username, "nickname": u.nickname, "avatar": u.avatar,
            "remark": u.remark or "", "account_label": users.account_id(u),
            "role": u.role, "status": u.status, "created_at": u.created_at, "last_login_at": u.last_login_at}


# ---------------------------------------------------------------- Admin 首次登录

class FirstLoginIn(BaseModel):
    account: str = Field(max_length=40)


@router.post("/api/auth/admin/first-login")
def admin_first_login(body: FirstLoginIn, request: Request, db: Session = Depends(get_db)):
    if body.account.strip().lower() != "admin":
        raise HTTPException(400, "请输入密码")
    auth.check_lock(f"pw-ip:{auth.client_ip(request)}")
    if not admin_setup.is_open():
        auth.record_fail(f"pw-ip:{auth.client_ip(request)}")
        raise HTTPException(401, "请输入 Admin 的密码")
    admin = db.scalar(select(User).where(User.username == "admin"))
    if admin is None or admin.status != "active":
        raise HTTPException(400, "超级管理员账号不存在")
    token = auth.create_session(db, admin, request, "password")
    activity.record("login", "超级管理员 Admin 首次登录（免密码）", user=admin, ip=auth.client_ip(request))
    visits.server_event(request, "login", admin, {"method": "first"})
    return {"token": token, "user": user_out(admin), "is_new": False}


class SetupPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.post("/api/admin-setup/password")
def admin_setup_password(body: SetupPasswordIn, request: Request, me: User = Depends(auth.current_user),
                         db: Session = Depends(get_db)):
    """首次登录后设置 Admin 的密码；设置后首次登录入口永久关闭，其他设备上的 Admin 会话全部退出。"""
    if not auth.is_super(me) or not admin_setup.pending():
        raise HTTPException(400, "不需要设置")
    _check_password_strength(body.password)
    admin = db.get(User, me.id)
    admin.password_hash = auth.hash_password(body.password)
    current = auth.session_for(db, request.headers.get("authorization"))
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == admin.id, AuthSession.revoked_at.is_(None))):
        if current is None or s.id != current.id:
            s.revoked_at = utcnow()
    db.commit()
    admin_setup.complete()
    activity.record("password", "超级管理员 Admin 设置了登录密码", user=admin, ip=auth.client_ip(request))
    return {"user": user_out(admin)}


# ---------------------------------------------------------------- 管理员任免（仅超级管理员）
# v3.3.55 角色：subadmin 管理员 / moderator 内容审核 / support 客服 / viewer 只读；超级管理员 admin 只有一个，不能任命或修改。
# 任命、改角色、取消都要填原因，并经过二次验证（action=staff_role）。

def _staff_full(db: Session, u: User) -> dict:
    from ..services import permissions

    return {**_staff_out(u), "role_label": permissions.ROLE_LABELS.get(u.role, u.role), "permissions": permissions.permissions(u.role),
            "capabilities": permissions.capabilities(u.role)}


@router.get("/api/admin/staff", dependencies=[Depends(auth.require_admin)])
def list_staff(db: Session = Depends(get_db)):
    from ..services import permissions

    rows = db.scalars(select(User).where(User.role.in_(auth.STAFF_ROLES))).all()
    order = {r: i for i, r in enumerate(("admin", "subadmin", "moderator", "support", "viewer"))}
    rows = sorted(rows, key=lambda u: (order.get(u.role, 9), u.id))
    return [_staff_full(db, u) for u in rows]  # 保持数组（老页面兼容）；角色和权限表见 /api/admin/staff-roles


@router.get("/api/admin/staff-roles", dependencies=[Depends(auth.require_admin)])
def staff_roles():
    from ..services import permissions

    return {"roles": {r: permissions.ROLE_LABELS[r] for r in permissions.ASSIGNABLE}, "labels": permissions.ROLE_LABELS,
            "matrix": {r: permissions.permissions(r) for r in permissions.ROLE_LABELS},
            "capabilities": {r: permissions.capabilities(r) for r in permissions.ROLE_LABELS}, "modules": permissions.MODULE_LABELS}


@router.get("/api/admin/staff/candidates", dependencies=[Depends(auth.require_super)])
def staff_candidates(q: str = Query("", max_length=100), page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    """可以设为管理员的已注册用户（v3.3.55 起纯微信账号也可以）：不搜索时按注册时间倒序，搜索时按邮箱、昵称、备注名过滤。"""
    conds = [User.role == "user", User.status == "active"]
    for w in q.split():
        like = f"%{w}%"
        conds.append(or_(User.email.ilike(like), User.nickname.ilike(like), User.remark.ilike(like), User.username.ilike(like)))
    base = select(User).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(User.id.desc()).offset((page - 1) * 20).limit(20))
    return {"total": total, "items": [_staff_out(u) for u in rows]}


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < 2:
        raise HTTPException(400, {"code": "reason_required", "message": "请填写原因"})
    return r


def _role(role: str) -> str:
    from ..services import permissions

    if role not in permissions.ASSIGNABLE:
        raise HTTPException(400, {"code": "bad_role", "message": "请选择角色"})
    return role


class StaffIn(BaseModel):
    user_id: int
    role: str = "subadmin"
    reason: str = Field("", max_length=300)


class RoleIn(BaseModel):
    role: str
    reason: str = Field("", max_length=300)


class ReasonIn(BaseModel):
    reason: str = Field("", max_length=300)


def _verify(request: Request, me: User) -> None:
    from ..services import admin_security

    admin_security.check_token(me, "staff_role", admin_security.token_from(request))


def _role_log(request: Request, me: User, u: User, old: str, new: str, reason: str, summary: str) -> None:
    from ..services import permissions

    activity.record("staff", summary, user=me, target_type="user", target_id=u.id, ip=auth.client_ip(request), reason=reason,
                    before={"role": permissions.ROLE_LABELS.get(old, "普通用户")}, after={"role": permissions.ROLE_LABELS.get(new, "普通用户")},
                    target_label=users.label(u))


@router.post("/api/admin/staff")
def add_staff(body: StaffIn, request: Request, me: User = Depends(auth.require_super), db: Session = Depends(get_db)):
    from ..services import permissions

    role, reason = _role(body.role), _reason(body.reason)
    _verify(request, me)
    u = db.get(User, body.user_id)
    if u is None or u.status != "active":
        raise HTTPException(404, {"code": "not_found", "message": "用户不存在或已停用"})
    if u.role in auth.STAFF_ROLES:
        raise HTTPException(400, {"code": "already_staff", "message": "已经是管理员"})
    u.role = role
    db.commit()
    _role_log(request, me, u, "user", role, reason, f"设为{permissions.ROLE_LABELS[role]}：{users.label(u)}")
    return _staff_full(db, u)


@router.put("/api/admin/staff/{user_id}/role")
def change_role(user_id: int, body: RoleIn, request: Request, me: User = Depends(auth.require_super), db: Session = Depends(get_db)):
    from ..services import permissions

    role, reason = _role(body.role), _reason(body.reason)
    _verify(request, me)
    u = db.get(User, user_id)
    if u is None or u.role not in auth.STAFF_ROLES:
        raise HTTPException(404, {"code": "not_found", "message": "这个用户不是管理员"})
    if u.role == "admin" or u.id == me.id:
        raise HTTPException(400, {"code": "cannot_change_super", "message": "不能修改超级管理员的角色"})
    if u.role == role:
        return _staff_full(db, u)
    old = u.role
    u.role = role
    db.commit()
    _role_log(request, me, u, old, role, reason, f"修改管理员角色：{users.label(u)}，{permissions.ROLE_LABELS[old]} → {permissions.ROLE_LABELS[role]}")
    return _staff_full(db, u)


@router.delete("/api/admin/staff/{user_id}")
def remove_staff(user_id: int, request: Request, body: ReasonIn | None = None, me: User = Depends(auth.require_super),
                 db: Session = Depends(get_db)):
    from ..services import permissions

    reason = _reason((body or ReasonIn()).reason)
    _verify(request, me)
    u = db.get(User, user_id)
    if u is None or u.role not in auth.STAFF_ROLES:
        raise HTTPException(400, {"code": "not_staff", "message": "这个用户不是管理员"})
    if u.role == "admin" or u.id == me.id:
        raise HTTPException(400, {"code": "cannot_change_super", "message": "不能取消超级管理员"})
    old = u.role
    u.role = "user"
    db.commit()
    _role_log(request, me, u, old, "user", reason, f"取消{permissions.ROLE_LABELS.get(old, '管理员')}：{users.label(u)}")
    return {"ok": True}


@router.get("/api/admin/staff/{user_id}/logins", dependencies=[Depends(auth.require_super)])
def staff_logins(user_id: int, db: Session = Depends(get_db)):
    from ..services import admin_security

    u = db.get(User, user_id)
    if u is None or u.role not in auth.STAFF_ROLES:
        raise HTTPException(404, {"code": "not_found", "message": "这个用户不是管理员"})
    return {"items": admin_security.logins(db, u.id)}


@router.get("/api/admin/me/logins")
def my_logins(me: User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    from ..services import admin_security

    return {"items": admin_security.logins(db, me.id)}


# ---------------------------------------------------------------- 高危操作二次验证

class VerifyReq(BaseModel):
    action: str


class VerifyConfirm(BaseModel):
    action: str
    code: str = Field(min_length=6, max_length=6)


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


@router.post("/api/admin/verify/request")
def verify_request(body: VerifyReq, request: Request, me: User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    """给当前管理员的邮箱发验证码（频率限制与登录验证码相同）。没有邮箱的账号返回 no_email。"""
    from ..services import admin_security
    from .account import CodeIn, send_code

    if body.action not in admin_security.ACTIONS:
        raise HTTPException(400, {"code": "bad_action", "message": "未知操作"})
    if not me.email:
        raise HTTPException(400, {"code": "no_email", "message": "这个账号没有绑定邮箱，暂时不能做这个操作"})
    out = send_code(CodeIn(email=me.email, purpose="change"), request, db, me)
    return {**out, "email": _mask(me.email), "action_label": admin_security.ACTIONS[body.action]}


@router.post("/api/admin/verify/confirm")
def verify_confirm(body: VerifyConfirm, request: Request, me: User = Depends(auth.require_admin), db: Session = Depends(get_db)):
    from ..services import admin_security
    from .account import _consume_code

    if body.action not in admin_security.ACTIONS:
        raise HTTPException(400, {"code": "bad_action", "message": "未知操作"})
    if not me.email:
        raise HTTPException(400, {"code": "no_email", "message": "这个账号没有绑定邮箱，暂时不能做这个操作"})
    try:
        _consume_code(db, me.email, "change", body.code)
    except HTTPException as e:
        raise HTTPException(400, {"code": "bad_code", "message": e.detail if isinstance(e.detail, str) else "验证码不对"})
    activity.record("admin_verify", f"高危操作身份验证：{admin_security.ACTIONS[body.action]}", user=me, ip=auth.client_ip(request))
    return {"token": admin_security.issue(me.id, body.action), "expires_in": admin_security.VERIFY_TTL}
