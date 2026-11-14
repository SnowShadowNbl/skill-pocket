"""管理端：用户管理（详情、停用、删除）、IP 封禁、内容管理（条目列表、全部字段、图片集）。

超级管理员和子管理员都可以用；管理员账号不能在这里停用或删除（先取消管理员身份）。
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..auth import STAFF_ROLES, client_ip, require_admin
from ..config import settings
from ..db import get_db, utcnow
from ..models import (UserTag, ActivityLog, AuthSession, Category, Comment, CompareRun, Favorite, Feedback, IpBan, Item, Repo,
                      User, Visitor)
from ..schemas import github_url, image_urls, kind_brief
from ..services.thumbs import thumb_url
from ..seed import KINDS
from ..services import activity, admin_security, geo, ingest, ipban, item_quality, permissions, pins, users
from ..services.client import CHANNELS, METHODS
from ..services.github import GitHub, GitHubError, NotFound, find_images

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

STATUS_LABEL = {"active": "正常", "disabled": "已停用", "deleted": "已删除", "merged": "已合并"}
ITEM_STATUS = {"published": "已上线", "hidden": "已隐藏", "offline": "原文已下线", "awaiting": "审核中", "declined": "未通过",
               "pending_review": "采集待确认", "candidate": "候选", "rejected": "已忽略"}
MAX_UPLOAD = 8 * 1024 * 1024


# ---------------------------------------------------------------- 用户管理

def _last_seen(db: Session, uid: int) -> AuthSession | None:
    return db.scalar(select(AuthSession).where(AuthSession.user_id == uid).order_by(AuthSession.last_seen_at.desc()).limit(1))


def _login_methods(u: User) -> list[str]:
    out = []
    if u.email:
        out.append("email")
    if u.wx_openid:
        out.append("wechat")
    if u.password_hash:
        out.append("password")
    return out


def _user_row(db: Session, u: User) -> dict:
    s = _last_seen(db, u.id)
    merged = db.get(User, u.merged_into) if u.merged_into else None
    return {"id": u.id, "email": u.email, "username": u.username, "nickname": u.nickname, "avatar": u.avatar, "role": u.role,
            "role_label": permissions.ROLE_LABELS.get(u.role, "普通用户"),
            "status": u.status, "status_label": STATUS_LABEL.get(u.status, u.status), "created_at": u.created_at,
            # v3.3.37 后台批次 0：统一称呼（没有邮箱显示「微信用户 #id」）、登录方式、合并去向、注册渠道和最近登录的端
            "account_label": users.account_id(u), "display_label": users.label(u), "login_methods": _login_methods(u),
            "merged_into": {"id": merged.id, "label": users.label(merged)} if merged else None,
            "signup_channel": u.signup_channel or "", "signup_channel_label": CHANNELS.get(u.signup_channel or "", "未知"),
            "last_client": u.last_client or "", "last_client_label": CHANNELS.get(u.last_client or "", "未知"),
            "last_client_version": u.last_client_version or "",
            "last_login_at": u.last_login_at, "last_seen_at": s.last_seen_at if s else None,
            "ip": s.ip if s else "", "geo": geo.lookup(s.ip) if s else "", "device": s.device if s else "",
            "remark": u.remark or "", "quota_balance": u.quota_balance}


def _user_conds(q: str = "", status: str = "", role: str = "", login: str = "", channel: str = "", client: str = "",
                client_version: str = "", tag: str = "") -> list:
    """用户列表 / 批量操作 / 导出共用的筛选条件（v3.3.39 抽出来，保证「全选筛选结果」和列表口径一致）。"""
    conds = [User.status != "deleted"] if status != "deleted" else [User.status == "deleted"]
    if status in ("active", "disabled", "merged"):
        conds.append(User.status == status)
    if role == "staff":
        conds.append(User.role.in_(STAFF_ROLES))
    elif role == "user":
        conds.append(User.role == "user")
    for w in (q or "").split():
        like = f"%{w}%"
        conds.append(or_(User.email.ilike(like), User.nickname.ilike(like), User.username.ilike(like), User.remark.ilike(like)))
    # v3.3.40 账号关系：按登录方式、注册渠道筛选（unknown = 历史账号没记录渠道）
    if login == "email_only":
        conds += [User.email.is_not(None), User.wx_openid.is_(None)]
    elif login == "wechat_only":
        conds += [User.email.is_(None), User.wx_openid.is_not(None)]
    elif login == "both":
        conds += [User.email.is_not(None), User.wx_openid.is_not(None)]
    if channel in ("web-pc", "web-mobile", "miniprogram"):
        conds.append(User.signup_channel == channel)
    elif channel == "unknown":
        conds.append(or_(User.signup_channel == "", User.signup_channel.is_(None)))
    # v3.3.62 按最近一次登录的端和版本筛选（P36 客户端版本）
    if client:
        conds.append(User.last_client == ("" if client == "unknown" else client))
    if client_version:
        conds.append(User.last_client_version == ("" if client_version == "unknown" else client_version))
    # v3.3.71 按标签筛选（none = 没有任何标签）
    if tag == "none":
        conds.append(~User.id.in_(select(UserTag.user_id)))
    elif tag.isdigit():
        conds.append(User.id.in_(select(UserTag.user_id).where(UserTag.tag_id == int(tag))))
    return conds


@router.get("/users")
def list_users(q: str = "", status: str = "", role: str = "", login: str = "", channel: str = "", client: str = "",
               client_version: str = "", tag: str = "", page: int = Query(1, ge=1), size: int = Query(30, le=100), db: Session = Depends(get_db)):
    base = select(User).where(*_user_conds(q, status, role, login, channel, client, client_version, tag))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(User.id.desc()).offset((page - 1) * size).limit(size)).all()
    counts = {
        "users": db.scalar(select(func.count()).select_from(User).where(User.status != "deleted", User.role == "user")),
        "staff": db.scalar(select(func.count()).select_from(User).where(User.role.in_(STAFF_ROLES))),
        "disabled": db.scalar(select(func.count()).select_from(User).where(User.status == "disabled")),
        "guests": db.scalar(select(func.count()).select_from(Visitor).where(Visitor.user_id.is_(None))),
    }
    from .operations import user_tags

    tags = user_tags(db, [u.id for u in rows])  # v3.3.71 用户标签
    return {"total": total, "counts": counts, "items": [{**_user_row(db, u), "tags": tags.get(u.id, [])} for u in rows]}


# v3.3.39 导出必须定义在 /users/{user_id} 之前，否则 export 会被当成用户编号（422）
EXPORT_MAX = 5000


def _mask_email(e: str | None) -> str:
    if not e or "@" not in e:
        return e or ""
    name, domain = e.split("@", 1)
    return f"{name[:2]}***@{domain}" if len(name) > 2 else f"{name[:1]}***@{domain}"


@router.get("/users/export")
def export_users(request: Request, q: str = "", status: str = "", role: str = "", login: str = "", channel: str = "",
                 client: str = "", client_version: str = "", tag: str = "", with_email: int = 0,
                 db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """按当前筛选导出 CSV（UTF-8 带 BOM，Excel 直接打开不乱码）。完整邮箱只有超级管理员能导出；每次导出都记日志。"""
    import csv
    import io
    from urllib.parse import quote

    from fastapi.responses import Response

    if with_email:
        admin_security.check_token(me, "export_email", admin_security.token_from(request))
    if with_email and me.role != "admin":
        raise HTTPException(403, {"code": "forbidden", "message": "只有超级管理员可以导出完整邮箱"})
    base = select(User).where(*_user_conds(q, status, role, login, channel, client, client_version, tag))
    n = db.scalar(select(func.count()).select_from(base.subquery()))
    if n > EXPORT_MAX:
        raise HTTPException(400, {"code": "too_many", "message": f"一次最多导出 {EXPORT_MAX} 个账号（当前 {n} 个），请缩小筛选范围"})
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(["ID", "昵称", "账号", "登录方式", "身份", "状态", "注册渠道", "最近登录端", "注册时间", "最近登录", "AI 额度", "备注"])
    way = {"email": "邮箱", "wechat": "微信", "password": "密码"}
    fmt = lambda t: t.astimezone(CN).strftime("%Y-%m-%d %H:%M") if t else ""  # noqa: E731
    for u in db.scalars(base.order_by(User.id.desc())):
        acct = _mask_email(u.email) if (u.email and not with_email) else users.account_id(u)
        w.writerow([u.id, u.nickname or "", acct, "、".join(way[m] for m in _login_methods(u)) or "—",
                    permissions.ROLE_LABELS.get(u.role, "普通用户"), STATUS_LABEL.get(u.status, u.status),
                    CHANNELS.get(u.signup_channel or "", "未知"), CHANNELS.get(u.last_client or "", "未知"),
                    fmt(u.created_at), fmt(u.last_login_at),
                    u.quota_balance if u.quota_balance is not None else "", u.remark or ""])
    activity.record("user_export", f"导出用户 {n} 个" + ("（含完整邮箱）" if with_email else ""), user=me, target_type="user",
                    ip=client_ip(request), detail={"q": q, "status": status, "role": role, "with_email": bool(with_email), "count": n})
    fname = f"用户导出-{datetime.now(CN).strftime('%Y%m%d-%H%M')}.csv"
    return Response(buf.getvalue().encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}", "X-Export-Count": str(n)})


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "用户不存在")
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == u.id).order_by(AuthSession.last_seen_at.desc()).limit(20)).all()
    visitors = db.scalars(select(Visitor).where(Visitor.user_id == u.id).order_by(Visitor.last_seen.desc()).limit(10)).all()
    recent = db.scalars(select(ActivityLog).where(ActivityLog.user_id == u.id).order_by(ActivityLog.id.desc()).limit(20)).all()
    subs = db.scalars(select(Item).where(Item.created_by == u.id).order_by(Item.collected_at.desc()).limit(20)).all()
    count = lambda m, col: db.scalar(select(func.count()).select_from(m).where(col == u.id))  # noqa: E731
    from .operations import user_tags

    return {
        **_user_row(db, u),
        "tags": user_tags(db, [u.id]).get(u.id, []),  # v3.3.73 详情也返回标签
        "stats": {"submissions": count(Item, Item.created_by), "comments": count(Comment, Comment.user_id),
                  "favorites": count(Favorite, Favorite.owner_id), "feedback": count(Feedback, Feedback.user_id),
                  "compares": count(CompareRun, CompareRun.user_id)},
        "sessions": [{"id": s.id, "device": s.device, "ip": s.ip, "geo": geo.lookup(s.ip), "created_at": s.created_at,
                      "client": s.client or "", "client_label": CHANNELS.get(s.client or "", "未知"), "client_version": s.client_version or "",
                      "method": s.method or "", "method_label": METHODS.get(s.method or "", "未知"),
                      "last_seen_at": s.last_seen_at, "active": s.revoked_at is None and s.expires_at > utcnow()} for s in sessions],
        "visitors": [{"vid": v.id, "device": v.device, "ip": v.last_ip, "geo": geo.lookup(v.last_ip) or v.last_geo,
                      "first_seen": v.first_seen, "last_seen": v.last_seen, "visits": v.visits, "converted_at": v.converted_at} for v in visitors],
        "activity": [{"id": r.id, "action": activity.ACTIONS.get(r.action, r.action), "summary": r.summary, "ip": r.ip,
                      "geo": geo.lookup(r.ip), "created_at": r.created_at} for r in recent],
        "submissions": [{"id": i.id, "name": i.name, "status": i.status, "status_label": ITEM_STATUS.get(i.status, i.status),
                         "collected_at": i.collected_at} for i in subs],
    }


def _target_user(db: Session, user_id: int, me: User, allow_subadmin_for_super: bool = False) -> User:
    u = db.get(User, user_id)
    if u is None or u.status == "deleted":
        raise HTTPException(404, "用户不存在或已删除")
    if u.id == me.id:
        raise HTTPException(400, "不能对自己操作")
    if u.role in STAFF_ROLES and not (allow_subadmin_for_super and me.role == "admin" and u.role != "admin"):
        raise HTTPException(400, "管理员账号不能停用或删除，请先在「管理员」里取消其管理员身份")
    return u


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")
    reason: str = Field("", max_length=200)


REASON_MIN = 4  # v3.3.37 管理操作原因最少字数（前后端都校验）


def _need_reason(reason: str) -> str:
    r = (reason or "").strip()
    if len(r) < REASON_MIN:
        raise HTTPException(400, {"code": "reason_required", "message": f"请填写原因（至少 {REASON_MIN} 个字）"})
    return r


@router.post("/users/{user_id}/status")
def set_user_status(user_id: int, body: StatusIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """停用：立即退出所有设备，不能再登录；已有的内容保留。启用：恢复正常。v3.3.37 必须填原因（≥4 字），留修改前后。"""
    reason = _need_reason(body.reason)
    raw = db.get(User, user_id)
    if raw is not None and raw.status == "merged":
        raise HTTPException(409, {"code": "merged_account", "message": "这个账号已合并到其他账号，不能启用或停用"})
    if raw is not None and raw.status == "deleted":
        raise HTTPException(409, {"code": "deleted_account", "message": "这个账号已注销"})
    u = _target_user(db, user_id, me)
    old = u.status
    u.status = body.status
    if body.status == "disabled":
        users.revoke_sessions(db, u.id)
    db.commit()
    word = "停用" if body.status == "disabled" else "启用"
    activity.record("user_status", f"{word}用户：{users.label(u)}", user=me, target_type="user",
                    target_id=u.id, ip=client_ip(request), reason=reason, before={"status": old}, after={"status": u.status},
                    target_label=users.label(u), result="ok" if old != u.status else "ok",
                    message="" if old != u.status else "状态未变化")
    return _user_row(db, u)


# ---------------------------------------------------------------- v3.3.39 批量停用 / 启用、导出

BULK_MAX = 2000  # 批量上限：状态切换是纯数据库操作，2000 个以内同步完成（不转后台任务）


class BulkFilter(BaseModel):
    q: str = ""
    status: str = ""
    role: str = ""
    login: str = ""
    channel: str = ""
    client: str = ""
    client_version: str = ""
    tag: str = ""


class BulkIn(BaseModel):
    action: str = Field(pattern="^(disable|enable|add_tag|remove_tag)$")
    tag_id: int | None = None  # v3.3.71 add_tag / remove_tag 用
    reason: str = Field("", max_length=300)
    ids: list[int] | None = None
    filter: BulkFilter | None = None
    exclude: list[int] = []
    total: int | None = None


@router.post("/users/bulk")
def bulk_users(body: BulkIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """批量停用 / 启用。按 ids，或按筛选条件（filter + exclude，后端重新统计，和 total 不一致返回 409 count_changed）。
    逐项返回结果：已合并 / 已注销 / 管理员 / 自己 → ok:false 带 code；已经是目标状态 → ok:true, code:noop（重试幂等）。"""
    reason = _need_reason(body.reason)
    if body.ids is not None:
        ids = list(dict.fromkeys(body.ids))
    elif body.filter is not None:
        conds = _user_conds(body.filter.q, body.filter.status, body.filter.role, body.filter.login, body.filter.channel,
                            body.filter.client, body.filter.client_version, body.filter.tag)
        all_ids = list(db.scalars(select(User.id).where(*conds).order_by(User.id.desc())))
        if body.total is not None and len(all_ids) != body.total:
            raise HTTPException(409, {"code": "count_changed",
                                      "message": f"符合条件的账号数量已变化（现在 {len(all_ids)} 个，选择时 {body.total} 个），请重新确认"})
        skip = set(body.exclude)
        ids = [i for i in all_ids if i not in skip]
    else:
        raise HTTPException(400, {"code": "empty_scope", "message": "请先选择账号"})
    if not ids:
        raise HTTPException(400, {"code": "empty_scope", "message": "请先选择账号"})
    if len(ids) > BULK_MAX:
        raise HTTPException(400, {"code": "too_many", "message": f"一次最多操作 {BULK_MAX} 个账号，请缩小范围"})

    if body.action in ("add_tag", "remove_tag"):
        return _bulk_tags(db, body, ids, me, request)
    target = "disabled" if body.action == "disable" else "active"
    word = "停用" if body.action == "disable" else "启用"
    rows = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}
    results, changed = [], []
    for uid in ids:
        u = rows.get(uid)
        if u is None:
            results.append({"id": uid, "label": f"用户 #{uid}", "ok": False, "code": "not_found", "message": "用户不存在"})
            continue
        label = users.label(u)
        fail = None
        if u.status == "merged":
            fail = ("merged_account", "已合并到其他账号")
        elif u.status == "deleted":
            fail = ("deleted_account", "账号已注销")
        elif u.id == me.id:
            fail = ("self", "不能对自己操作")
        elif u.role in STAFF_ROLES:
            fail = ("staff_account", "管理员账号不能停用或启用，请先取消其管理员身份")
        if fail:
            results.append({"id": uid, "label": label, "ok": False, "code": fail[0], "message": fail[1]})
            continue
        if u.status == target:
            results.append({"id": uid, "label": label, "ok": True, "code": "noop", "message": f"本来就是{STATUS_LABEL[target]}"})
            continue
        old = u.status
        u.status = target
        if target == "disabled":
            users.revoke_sessions(db, u.id)
        changed.append((u, old, label))
        results.append({"id": uid, "label": label, "ok": True})
    db.commit()
    ip = client_ip(request)
    for u, old, label in changed:
        activity.record("user_status", f"批量{word}用户：{label}", user=me, target_type="user", target_id=u.id,
                        ip=ip, reason=reason, before={"status": old}, after={"status": u.status}, target_label=label,
                        detail={"bulk": True})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok}


def _bulk_tags(db: Session, body: "BulkIn", ids: list[int], me: User, request: Request) -> dict:
    """v3.3.71 批量加 / 去用户标签。已经有（或已经没有）的返回 noop。"""
    from ..models import Tag

    tag = db.get(Tag, body.tag_id) if body.tag_id else None
    if tag is None:
        raise HTTPException(400, {"code": "bad_tag", "message": "请选择标签"})
    have = set(db.scalars(select(UserTag.user_id).where(UserTag.tag_id == tag.id, UserTag.user_id.in_(ids))))
    rows = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}
    results, changed = [], []
    for uid in ids:
        u = rows.get(uid)
        if u is None:
            results.append({"id": uid, "label": f"用户 #{uid}", "ok": False, "code": "not_found", "message": "用户不存在"})
            continue
        label = users.label(u)
        add = body.action == "add_tag"
        if (uid in have) == add:
            results.append({"id": uid, "label": label, "ok": True, "code": "noop", "message": "本来就有这个标签" if add else "本来就没有这个标签"})
            continue
        if add:
            db.add(UserTag(user_id=uid, tag_id=tag.id, created_by=me.id))
        else:
            db.query(UserTag).filter(UserTag.user_id == uid, UserTag.tag_id == tag.id).delete()
        changed.append((uid, label))
        results.append({"id": uid, "label": label, "ok": True, "code": "ok", "message": ""})
    db.commit()
    word = "加上" if body.action == "add_tag" else "去掉"
    for uid, label in changed:
        activity.record("user_tags", f"批量{word}标签「{tag.name}」：{label}", user=me, target_type="user", target_id=uid, ip=client_ip(request),
                        reason=body.reason.strip(), target_label=label, detail={"bulk": True, "tag_id": tag.id})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    admin_security.check_token(me, "delete_user", admin_security.token_from(request))
    """删除账号：和用户自己注销一样——收藏删除，评论和提交的条目保留并显示为「已注销用户」，邮箱可以重新注册。"""
    u = _target_user(db, user_id, me)
    label = users.label(u)
    users.anonymize(db, u)
    db.commit()
    activity.record("user_delete", f"删除用户：{label}", user=me, target_type="user", target_id=u.id, ip=client_ip(request))
    return {"ok": True}


class EmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.put("/users/{user_id}/email")
def change_email(user_id: int, body: EmailIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    admin_security.check_token(me, "change_email", admin_security.token_from(request))
    """管理员修改用户的登录邮箱（例如用户换邮箱、填错邮箱）。改后用新邮箱登录，原有登录设备保持登录。"""
    from .account import _norm_email

    u = _target_user(db, user_id, me, allow_subadmin_for_super=True)  # 超级管理员也能改子管理员的邮箱
    email = _norm_email(body.email)
    if email == u.email:
        return _user_row(db, u)
    if db.scalar(select(User).where(User.email == email, User.id != u.id)):
        raise HTTPException(400, "这个邮箱已经被其他账号使用")
    old = u.email
    u.email = email
    db.commit()
    activity.record("user_email", f"修改用户邮箱：{u.nickname}，{old} → {email}", user=me, target_type="user", target_id=u.id,
                    ip=client_ip(request))
    return _user_row(db, u)


class RemarkIn(BaseModel):
    remark: str = Field("", max_length=60)


@router.put("/users/{user_id}/remark")
def set_remark(user_id: int, body: RemarkIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """管理员给账号起备注名（只在管理端显示，用户自己看不到）。管理员账号也可以备注。"""
    u = db.get(User, user_id)
    if u is None or u.status == "deleted":
        raise HTTPException(404, "用户不存在或已删除")
    old, u.remark = u.remark, body.remark.strip()
    db.commit()
    activity.record("user_remark", f"备注用户：{u.nickname}，{old or '（无）'} → {u.remark or '（无）'}", user=me, target_type="user",
                    target_id=u.id, ip=client_ip(request))
    return _user_row(db, u)


# ---------------------------------------------------------------- AI 额度

class QuotaSettingsIn(BaseModel):
    default_free: int = Field(ge=0, le=10_000_000_000)


@router.get("/quota/settings")
def quota_settings(db: Session = Depends(get_db)):
    from ..services import billing

    return {"default_free": billing.default_free(db), "standard_free": billing.STANDARD_FREE, "rate": billing.RATE,
            "explain": billing.standard_free_explain(), "not_billed": sorted(billing.NOT_BILLED)}


@router.put("/quota/settings")
def save_quota_settings(body: QuotaSettingsIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """免费额度的默认值：只影响之后第一次用到 AI 的账号；已有账号要改用「重置」。"""
    from ..services import billing

    old = billing.default_free(db)
    billing.set_default_free(db, body.default_free)
    db.commit()
    activity.record("quota_settings", f"免费额度默认值：{old:,} → {body.default_free:,}", user=me, ip=client_ip(request))
    return quota_settings(db)


@router.get("/quota/board")
def quota_board(days: int = Query(14, ge=1, le=90), db: Session = Depends(get_db)):
    from ..services import billing

    return billing.usage_board(db, days)


@router.get("/quota/records")
def quota_records(db: Session = Depends(get_db)):
    from ..services import billing

    return billing.recharges(db)


@router.get("/users/{user_id}/quota")
def user_quota(user_id: int, days: int = Query(60, ge=7, le=365), db: Session = Depends(get_db)):
    from ..services import billing

    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "用户不存在")
    return billing.admin_detail(db, u, days)


class QuotaChangeIn(BaseModel):
    action: str = Field(pattern="^(recharge|adjust|set|reset)$")
    amount: int = Field(0, ge=-10_000_000_000, le=10_000_000_000)  # 额度（用户侧，真实 token 的 2 倍）
    yuan: float | None = Field(None, ge=0, le=1_000_000)
    note: str = Field("", max_length=200)


@router.post("/users/{user_id}/quota")
def change_quota(user_id: int, body: QuotaChangeIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """充值（加额度并记下收款）、调整（加减）、设为指定值、重置为默认免费额度。"""
    from ..services import billing

    u = db.get(User, user_id)
    if u is None or u.status == "deleted":
        raise HTTPException(404, "用户不存在或已删除")
    if body.action == "recharge":
        if body.amount <= 0:
            raise HTTPException(400, "充值的额度要大于 0")
        row = billing.change(db, u, "recharge", delta=body.amount, amount_yuan=body.yuan, note=body.note, operator=me)
    elif body.action == "adjust":
        if body.amount == 0:
            raise HTTPException(400, "调整的额度不能为 0")
        row = billing.change(db, u, "adjust", delta=body.amount, note=body.note, operator=me)
    elif body.action == "set":
        if body.amount < 0:
            raise HTTPException(400, "余额不能设为负数")
        row = billing.change(db, u, "adjust", set_to=body.amount, note=body.note or "设为指定额度", operator=me)
    else:
        row = billing.change(db, u, "reset", set_to=billing.default_free(db), note=body.note or "重置为默认免费额度", operator=me)
    db.commit()
    label = billing.KIND_LABEL.get(row.kind, row.kind)
    activity.record("quota_change", f"{label}：{u.nickname}，{row.delta:+,} → 余额 {row.balance_after:,}"
                    + (f"（收款 ¥{body.yuan:g}）" if body.yuan else ""), user=me, target_type="user", target_id=u.id, ip=client_ip(request))
    return billing.admin_detail(db, u)


# ---------------------------------------------------------------- IP 封禁

def _ban_out(b: IpBan, names: dict) -> dict:
    ip = b.cidr.split("/")[0]
    return {"id": b.id, "cidr": b.cidr, "single": b.cidr.endswith(("/32", "/128")), "geo": geo.lookup(ip), "reason": b.reason,
            "created_by": names.get(b.created_by), "created_at": b.created_at, "expires_at": b.expires_at,
            "expired": b.expires_at is not None and b.expires_at <= utcnow()}


@router.get("/ip-bans")
def list_bans(db: Session = Depends(get_db)):
    rows = db.scalars(select(IpBan).order_by(IpBan.id.desc())).all()
    uids = {b.created_by for b in rows if b.created_by}
    names = {u.id: u.nickname for u in db.scalars(select(User).where(User.id.in_(uids)))} if uids else {}
    return [_ban_out(b, names) for b in rows]


class BanIn(BaseModel):
    ip: str = Field(min_length=2, max_length=64)
    reason: str = Field("", max_length=200)
    days: int | None = Field(None, ge=1, le=3650)  # 空表示永久


@router.post("/ip-bans")
def add_ban(body: BanIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    try:
        cidr = ipban.parse(body.ip)
    except ValueError as e:
        raise HTTPException(400, str(e) if str(e).startswith("网段") else "IP 格式不对，例如 1.2.3.4 或 1.2.3.0/24") from e
    if ipban.covers(cidr, client_ip(request)):
        raise HTTPException(400, "这会封掉你自己当前的 IP，已取消")
    if db.scalar(select(IpBan).where(IpBan.cidr == cidr)):
        raise HTTPException(400, "这个 IP 已经在封禁列表里")
    b = IpBan(cidr=cidr, reason=body.reason.strip(), created_by=me.id,
              expires_at=utcnow() + timedelta(days=body.days) if body.days else None)
    db.add(b)
    db.commit()
    ipban.refresh()
    activity.record("ip_ban", f"封禁 IP：{cidr}（{geo.lookup(cidr.split('/')[0]) or '未知地区'}）" + (f"，原因：{b.reason}" if b.reason else ""),
                    user=me, target_type="ip_ban", target_id=b.id, ip=client_ip(request))
    return _ban_out(b, {me.id: me.nickname})


@router.delete("/ip-bans/{ban_id}")
def remove_ban(ban_id: int, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    b = db.get(IpBan, ban_id)
    if b is None:
        raise HTTPException(404, "记录不存在")
    cidr = b.cidr
    db.delete(b)
    db.commit()
    ipban.refresh()
    activity.record("ip_ban", f"解除 IP 封禁：{cidr}", user=me, target_type="ip_ban", target_id=ban_id, ip=client_ip(request))
    return {"ok": True}


# ---------------------------------------------------------------- 内容管理

def _item_row(it: Item) -> dict:
    r = it.repo
    return {"id": it.id, "name": it.name, "summary": it.summary, "status": it.status, "status_label": ITEM_STATUS.get(it.status, it.status),
            "source": it.source, "kind": kind_brief(it.kind), "category": it.category.name if it.category else "",
            "repo": r.full_name if r else "", "sub_path": it.sub_path, "stars": r.stars if r else None,
            "cover_url": f"/media/{it.cover_path}" if it.cover_path else None, "cover_thumb_url": thumb_url(it.cover_path), "image_count": len(it.images or ([it.cover_path] if it.cover_path else [])),
            "ai_status": it.ai_status, "uploader": it.creator.nickname if it.creator else None,
            "collected_at": it.collected_at, "updated_at": it.updated_at, "pin_weight": it.pin_weight or 0,
            "locked_fields": it.locked_fields or [], "pin": pins.out(it),
            "rank_excluded": {"reason": it.rank_exclude_reason, "at": it.rank_excluded_at, "by": it.rank_excluded_by} if it.rank_excluded else None}


CN = ZoneInfo("Asia/Shanghai")


def _day_start(d: date):
    """北京时间某天 0 点（数据库里存的是 UTC）"""
    return datetime.combine(d, time.min, tzinfo=CN)


@router.get("/items/days")
def item_days(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), field: str = Query("collected", pattern="^(collected|updated)$"),
              db: Session = Depends(get_db)):
    """日历上每天的条目数（北京时间），用来在日期选择器里标出哪天有内容。"""
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    col = Item.collected_at if field == "collected" else Item.updated_at
    out: dict[str, int] = {}
    for (ts,) in db.execute(select(col).where(col >= _day_start(first), col < _day_start(nxt))):
        k = ts.astimezone(CN).date().isoformat()
        out[k] = out.get(k, 0) + 1
    return out


class ItemFilter(BaseModel):
    """内容管理的筛选条件（列表、批量共用）。quality 为逗号分隔的质量问题，同时满足。"""
    q: str = ""
    status: str = ""
    kind: str = ""
    category: str = ""
    source: str = ""
    date_from: date | None = None
    date_to: date | None = None
    date_field: str = "collected"
    pinned: str = ""
    quality: str = ""
    low_star: int = item_quality.LOW_STAR


def items_stmt(db: Session, f: ItemFilter):
    stmt = select(Item).outerjoin(Repo, Repo.id == Item.repo_id).outerjoin(User, User.id == Item.created_by)
    # 按收录 / 修改日期筛（北京时间，含首尾两天）
    col = Item.collected_at if f.date_field == "collected" else Item.updated_at
    if f.date_from:
        stmt = stmt.where(col >= _day_start(f.date_from))
    if f.date_to:
        stmt = stmt.where(col < _day_start(f.date_to + timedelta(days=1)))
    if f.pinned in ("1", "true"):
        stmt = stmt.where(Item.pin_weight > 0)
    elif f.pinned == "active":
        stmt = stmt.where(pins.effective_weight() > 0)
    if f.status:
        stmt = stmt.where(Item.status == f.status)
    if f.kind:
        stmt = stmt.where(Item.kind == ("" if f.kind == "none" else f.kind))
    if f.source:
        stmt = stmt.where(Item.source == f.source)
    if f.category:
        cat = db.scalar(select(Category).where(Category.code == f.category))
        if cat is not None and cat.merged_into_id:  # v3.3.50 被合并的分类：旧链接改看合并到的分类
            cat = db.get(Category, cat.merged_into_id) or cat
        if cat is not None:
            stmt = stmt.where(Item.category_id.in_([cat.id] + [c.id for c in cat.children]))
    for w in f.q.split():
        like = f"%{w}%"
        stmt = stmt.where(or_(Item.name.ilike(like), Item.summary.ilike(like), Repo.full_name.ilike(like),
                              User.nickname.ilike(like), User.email.ilike(like)))
    keys = [k for k in f.quality.split(",") if k in item_quality.QUALITY]
    if keys:
        stmt = stmt.where(*item_quality.conds(db, keys, f.low_star))
    return stmt


@router.get("/items")
def list_items(q: str = "", status: str = "", kind: str = "", category: str = "", source: str = "",
               sort: str = Query("collected", pattern="^(collected|updated|stars|name|pinned)$"),
               date_from: date | None = None, date_to: date | None = None,
               date_field: str = Query("collected", pattern="^(collected|updated)$"), pinned: str = "",
               quality: str = "", low_star: int = Query(item_quality.LOW_STAR, ge=1, le=100000),
               page: int = Query(1, ge=1), size: int = Query(30, le=100), db: Session = Depends(get_db)):
    f = ItemFilter(q=q, status=status, kind=kind, category=category, source=source, date_from=date_from, date_to=date_to,
                   date_field=date_field, pinned=pinned, quality=quality, low_star=low_star)
    stmt = items_stmt(db, f)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {"collected": Item.collected_at.desc(), "updated": Item.updated_at.desc(), "stars": Repo.stars.desc().nulls_last(),
             "name": Item.name.asc(), "pinned": Item.pin_weight.desc()}[sort]
    rows = db.scalars(stmt.options(joinedload(Item.repo), joinedload(Item.category), joinedload(Item.creator))
                      .order_by(order, Item.id.desc()).offset((page - 1) * size).limit(size)).unique().all()
    by_status = dict(db.execute(select(Item.status, func.count()).group_by(Item.status)).all())
    pinned_count = db.scalar(select(func.count()).select_from(Item).where(Item.pin_weight > 0))
    fl = item_quality.flags(db, rows, low_star)
    return {"total": total, "statuses": ITEM_STATUS, "counts": by_status, "kinds": {k: v[0] for k, v in KINDS.items()},
            "pinned_count": pinned_count, "qualities": item_quality.QUALITY,
            "items": [{**_item_row(i), "quality": fl[i.id]} for i in rows]}


class PinIn(BaseModel):
    weight: int = Field(ge=0, le=100)
    # v3.3.48 推荐位排期：不传表示不限；传 null 清除
    starts_at: datetime | None = None
    ends_at: datetime | None = None


@router.put("/items/{item_id}/pin")
def pin_item(item_id: int, body: PinIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """首页置顶：权重 1~100，越大越靠前；0 取消置顶。"""
    it = _item(db, item_id)
    starts, ends = (body.starts_at, body.ends_at) if body.weight else (None, None)
    if starts and starts.tzinfo is None:
        starts = starts.replace(tzinfo=CN)
    if ends and ends.tzinfo is None:
        ends = ends.replace(tzinfo=CN)
    if starts and ends and ends <= starts:
        raise HTTPException(400, {"code": "bad_range", "message": "结束时间要晚于开始时间"})
    before = {"pin_weight": it.pin_weight or 0, "pin_starts_at": it.pin_starts_at, "pin_ends_at": it.pin_ends_at}
    it.pin_weight, it.pin_starts_at, it.pin_ends_at = body.weight, starts, ends
    db.commit()
    db.refresh(it)
    after = {"pin_weight": it.pin_weight, "pin_starts_at": it.pin_starts_at, "pin_ends_at": it.pin_ends_at}
    if before != after:
        from fastapi.encoders import jsonable_encoder

        diff = [k for k in after if before[k] != after[k]]
        activity.record("item_pin", f"{'取消置顶' if not body.weight else f'首页置顶（权重 {body.weight}）'}：{it.name}", user=me,
                        target_type="item", target_id=it.id, ip=client_ip(request),
                        before=jsonable_encoder({k: before[k] for k in diff}), after=jsonable_encoder({k: after[k] for k in diff}),
                        target_label=it.name)
    return _item_row(it)


def _item(db: Session, item_id: int) -> Item:
    it = db.scalar(select(Item).options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent),
                                        joinedload(Item.creator)).where(Item.id == item_id))
    if it is None:
        raise HTTPException(404, "条目不存在")
    return it


def _item_full(it: Item) -> dict:
    r = it.repo
    return {
        **_item_row(it),
        "category_id": it.category_id, "category_group": it.category.parent.name if it.category and it.category.parent else "",
        "kind_key": it.kind, "description": it.description, "install_steps": it.install_steps or [], "homepage_url": it.homepage_url,
        "github_url": github_url(it), "images": [{"path": p, "url": f"/media/{p}"} for p in (it.images or ([it.cover_path] if it.cover_path else []))],
        "cover_source": it.cover_source, "ai_error": it.ai_error, "ai_model": it.ai_model, "ai_confidence": it.ai_confidence,
        "kind_confidence": it.kind_confidence, "review_note": it.review_note, "review_state": it.review_state,
        "locked_fields": it.locked_fields or [], "search_tags": it.search_tags or [], "rank_blurb": it.rank_blurb,
        "offline_reason": it.offline_reason, "offline_at": it.offline_at, "checked_at": it.checked_at,
        "stars_at_collect": it.stars_at_collect,
        "repo_info": {"full_name": r.full_name, "html_url": r.html_url, "language": r.language, "license": r.license,
                      "stars": r.stars, "forks": r.forks, "topics": r.topics or [], "pushed_at": r.pushed_at,
                      "archived": r.archived, "default_branch": r.default_branch} if r else None,
    }


@router.get("/items/{item_id}")
def item_full(item_id: int, db: Session = Depends(get_db)):
    return _item_full(_item(db, item_id))


def _set_images(it: Item, paths: list[str]) -> None:
    """更新图片集：第一张做封面；人工改过后锁定，重新提炼时不再覆盖。"""
    it.images = paths
    it.cover_path = paths[0] if paths else ""
    if not paths:
        it.cover_source = "placeholder"
    elif it.cover_source == "placeholder":
        it.cover_source = "upload"
    it.locked_fields = sorted(set(it.locked_fields or []) | {"cover_path"})


def _remove_files(db: Session, paths: list[str]) -> None:
    """删掉不再被任何条目引用的图片文件。"""
    for p in paths:
        if not p.startswith("covers/"):
            continue
        still = db.scalar(select(func.count()).select_from(Item).where(Item.cover_path == p))
        if not still:
            (settings.media_dir / p).unlink(missing_ok=True)


class ImagesIn(BaseModel):
    paths: list[str] = Field(max_length=30)


@router.put("/items/{item_id}/images")
def reorder_images(item_id: int, body: ImagesIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """调整顺序、设为封面、删除图片：传入新的完整列表（只能是原有图片的子集）。"""
    it = _item(db, item_id)
    old = list(it.images or ([it.cover_path] if it.cover_path else []))
    if any(p not in old for p in body.paths):
        raise HTTPException(400, "图片列表有误，请刷新后重试")
    removed = [p for p in old if p not in body.paths]
    _set_images(it, list(dict.fromkeys(body.paths)))
    db.commit()
    _remove_files(db, removed)
    activity.record("item_edit", f"调整「{it.name}」的图片（共 {len(it.images)} 张" + (f"，删除 {len(removed)} 张" if removed else "") + "）",
                    user=me, target_type="item", target_id=it.id)
    return _item_full(it)


_CTYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@router.post("/items/{item_id}/images")
async def upload_image(item_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), me: User = Depends(require_admin)):
    it = _item(db, item_id)
    if file.content_type not in _CTYPES:
        raise HTTPException(400, "只支持 PNG、JPG、GIF、WebP 图片")
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(400, "图片不能超过 8MB")
    path = ingest.save_image(it.id, content, file.content_type)
    images = list(it.images or ([it.cover_path] if it.cover_path else []))
    if path not in images:
        images.append(path)
    _set_images(it, images)
    if len(images) == 1:
        it.cover_source = "upload"
    db.commit()
    activity.record("item_edit", f"给「{it.name}」上传图片", user=me, target_type="item", target_id=it.id)
    return _item_full(it)


@router.post("/items/{item_id}/images/refetch")
def refetch_images(item_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """重新从 GitHub 文档里抓图片，补进图片集（已有的保留）。"""
    it = _item(db, item_id)
    if it.repo is None:
        raise HTTPException(400, "不是 GitHub 条目，没有文档可以抓图")
    try:
        with GitHub() as gh:
            _, _, _, raw, doc_path = ingest.fetch_doc(gh, it.repo, it.sub_path or "")  # Skill 读 SKILL.md，仓库读 README
            urls = find_images(raw, it.repo.full_name, it.repo.default_branch, doc_path)
            got, tried = ingest.save_gallery(gh, it.id, urls)
    except NotFound as e:
        raise HTTPException(502, f"读取 GitHub 文档失败：{e}" + ingest.gone_check(it.id, "refetch")) from e
    except GitHubError as e:
        raise HTTPException(502, f"读取 GitHub 文档失败：{e}") from e
    images = list(it.images or ([it.cover_path] if it.cover_path else []))
    added = [p for p in got if p not in images]
    if it.cover_source in ("ai", "placeholder") and added:
        images = added + images  # 有真实截图时放在 AI 示意图前面
    else:
        images += added
    _set_images(it, images)
    if added and it.cover_source in ("ai", "placeholder"):
        it.cover_source = "readme"
    db.commit()
    activity.record("item_edit", f"给「{it.name}」从文档抓取图片：新增 {len(added)} 张", user=me, target_type="item", target_id=it.id)
    return {**_item_full(it), "added": len(added), "tried": tried}


@router.get("/gallery-coverage")
def images_coverage(db: Session = Depends(get_db)):
    """v3.1 图片集覆盖率：已发布条目里有 2 张及以上图片的数量（后台「批量补图片集」按钮旁显示）。"""
    rows = db.execute(select(Item.images, Item.repo_id).where(Item.status == "published")).all()
    return {
        "total": len(rows),
        "with_gallery": sum(1 for imgs, _ in rows if len(imgs or []) > 1),
        "github_total": sum(1 for _, repo in rows if repo is not None),
    }


@router.post("/items/images-backfill")
def images_backfill(request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """批量补图片集：给所有 GitHub 条目从文档里抓截图（已有多张图、或人工改过图片的跳过）。在右下角任务进度里看进度。"""
    from ..services import tracking

    rows = db.execute(select(Item.id, Item.name, Item.images, Item.cover_path, Item.locked_fields)
                      .where(Item.repo_id.is_not(None), Item.status.in_(("published", "offline", "hidden")))
                      .order_by(Item.id)).all()
    todo = [(i, n) for i, n, imgs, cover, locked in rows
            if "cover_path" not in (locked or []) and len(imgs or ([cover] if cover else [])) <= 1]
    if not todo:
        return {"queued": 0, "task_id": None}
    task_id = tracking.create_task("gallery", f"批量补图片集 · {len(todo)} 个条目", todo, source="manual", user_id=me.id)
    tracking.start_task(task_id, [i for i, _ in todo], lambda i, t: ingest.gallery_for(i, t), workers=3)
    activity.record("crawl", f"开始批量补图片集：{len(todo)} 个条目", user=me, ip=client_ip(request))
    return {"queued": len(todo), "task_id": task_id}


# ---------------------------------------------------------------- 资源监控

@router.get("/resources")
def resources_overview(refresh: bool = False):
    """DeepSeek 用量与余额、腾讯云邮件发送量、百炼向量用量估算、服务器内存 / 磁盘 / 图片增长。"""
    from ..services import resources

    if refresh:
        resources.deepseek_balance(force=True)
    return resources.overview()
