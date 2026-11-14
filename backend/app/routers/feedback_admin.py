"""v3.3.52 后台批次 4a：反馈工单。

状态：new 待处理 → processing 处理中 → resolved 已解决 → closed 已关闭；wontfix 不处理。
已解决 / 已关闭 / 不处理可以「重新打开」到处理中（必填原因）。不允许的流转返回 400 bad_transition。
回复、改为已解决 / 已关闭 / 不处理时给提交人发站内消息（kind=feedback_reply）。
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..auth import client_ip, is_super, require_admin, require_super, STAFF_ROLES
from ..db import get_db, utcnow
from ..models import Feedback, FeedbackNote, Item, ReplyTemplate, Task, User
from ..services import activity, notify, users
from ..services.client import CHANNELS
from .feedback import CATEGORIES, MAX_IMAGES, STATUSES, feedback_out, save_images

router = APIRouter(prefix="/api/admin", tags=["admin-feedback"], dependencies=[Depends(require_admin)])

OPEN = ("new", "processing")
DONE = ("resolved", "closed", "wontfix")
# 允许的流转（不含重新打开：DONE → processing 单独处理，必填原因）
FLOW = {"new": {"processing", "resolved", "wontfix", "closed"}, "processing": {"resolved", "wontfix", "closed", "new"},
        "resolved": {"closed"}, "wontfix": {"closed"}, "closed": set()}
SLA = {"P0": 4 * 3600, "P1": 24 * 3600}  # 首次响应时限
NOTIFY_STATUS = {"resolved": "已解决", "closed": "已关闭", "wontfix": "暂不处理"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _secs(a, b) -> int | None:
    return int((b - a).total_seconds()) if a and b else None


def _overdue(f: Feedback, now) -> bool:
    lim = SLA.get(f.priority or "")
    return bool(lim and f.status in OPEN and not f.first_response_at and (now - f.created_at).total_seconds() > lim)


def _label(db: Session, uid: int | None, cache: dict | None = None):
    if not uid:
        return None
    u = (cache or {}).get(uid) or db.get(User, uid)
    return {"id": uid, "label": users.label(u) if u else f"用户 #{uid}"}


def _row(db: Session, f: Feedback, ucache: dict) -> dict:
    now = utcnow()
    out = feedback_out(f, admin=True, users=ucache)
    u = ucache.get(f.user_id)
    if out.get("user") is not None and u is not None:
        out["user"]["label"] = users.label(u)
    out.update(assignee=_label(db, f.assignee_id, ucache), assigned_at=f.assigned_at, first_response_at=f.first_response_at,
               resolved_at=f.resolved_at, closed_at=f.closed_at, age_s=_secs(f.created_at, now),
               first_response_s=_secs(f.created_at, f.first_response_at), resolve_s=_secs(f.created_at, f.resolved_at),
               overdue=_overdue(f, now))
    return out


def _users_of(db: Session, rows) -> dict:
    ids = {x for f in rows for x in (f.user_id, f.assignee_id) if x}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids or {-1})))}


def _get(db: Session, fb_id: int) -> Feedback:
    f = db.get(Feedback, fb_id)
    if f is None:
        _err(404, "not_found", "反馈不存在")
    return f


# ---------------------------------------------------------------- 列表
class FbFilter(BaseModel):
    q: str = ""
    status: str = ""  # 逗号分隔多选
    priority: str = ""
    category: str = ""
    assignee: str = ""  # me / none / <id>
    user_id: int | None = None
    created_from: str = ""
    created_to: str = ""
    overdue: str = ""


def _conds(db: Session, f: FbFilter, me: User) -> list:
    from .admin import _parse_day

    c = []
    sts = [s for s in f.status.split(",") if s in STATUSES]
    if sts:
        c.append(Feedback.status.in_(sts))
    if f.priority:
        c.append(Feedback.priority == ("" if f.priority == "none" else f.priority))
    if f.category:
        c.append(Feedback.category == f.category)
    if f.assignee == "me":
        c.append(Feedback.assignee_id == me.id)
    elif f.assignee == "none":
        c.append(Feedback.assignee_id.is_(None))
    elif f.assignee.isdigit():
        c.append(Feedback.assignee_id == int(f.assignee))
    if f.user_id:
        c.append(Feedback.user_id == f.user_id)
    d = _parse_day(f.created_from)
    if d is not None:
        c.append(Feedback.created_at >= d)
    d = _parse_day(f.created_to)
    if d is not None:
        c.append(Feedback.created_at < d + timedelta(days=1))
    for w in f.q.split():
        like = f"%{w}%"
        uids = select(User.id).where(or_(User.email.ilike(like), User.nickname.ilike(like), User.remark.ilike(like)))
        c.append(or_(Feedback.content.ilike(like), Feedback.contact_email.ilike(like), Feedback.user_id.in_(uids),
                     Feedback.id == (int(w.lstrip("#")) if w.lstrip("#").isdigit() else -1)))
    if f.overdue in ("1", "true"):
        now = utcnow()
        c.append(Feedback.status.in_(OPEN) & Feedback.first_response_at.is_(None) & or_(
            (Feedback.priority == "P0") & (Feedback.created_at < now - timedelta(seconds=SLA["P0"])),
            (Feedback.priority == "P1") & (Feedback.created_at < now - timedelta(seconds=SLA["P1"]))))
    return c


@router.get("/feedback")
def list_feedback(q: str = "", status: str = "", priority: str = "", category: str = "", assignee: str = "",
                  user_id: int | None = None, created_from: str = "", created_to: str = "", overdue: str = "",
                  sort: str = Query("urgent", pattern="^(urgent|newest|oldest|updated)$"), page: int = Query(1, ge=1),
                  page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = FbFilter(q=q, status=status, priority=priority, category=category, assignee=assignee, user_id=user_id,
                 created_from=created_from, created_to=created_to, overdue=overdue)
    base = select(Feedback).where(*_conds(db, f, me))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    urgent = Feedback.priority.in_(("P0", "P1")) & Feedback.status.in_(OPEN)
    order = {"urgent": (case((urgent, 0), else_=1), Feedback.id.desc()), "newest": (Feedback.id.desc(),),
             "oldest": (Feedback.id.asc(),), "updated": (Feedback.updated_at.desc(), Feedback.id.desc())}[sort]
    rows = db.scalars(base.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    uc = _users_of(db, rows)
    by_status = dict(db.execute(select(Feedback.status, func.count()).group_by(Feedback.status)).all())
    open_q = select(func.count()).select_from(Feedback).where(Feedback.status.in_(OPEN))
    counts = {**{k: by_status.get(k, 0) for k in STATUSES},
              "mine": db.scalar(open_q.where(Feedback.assignee_id == me.id)),
              "unassigned": db.scalar(open_q.where(Feedback.assignee_id.is_(None))),
              "overdue": db.scalar(select(func.count()).select_from(Feedback).where(*_conds(db, FbFilter(overdue="1"), me)))}
    return {"total": total, "page": page, "page_size": page_size, "categories": CATEGORIES, "statuses": STATUSES,
            "sla": SLA, "counts": counts, "items": [_row(db, x, uc) for x in rows]}


# ---------------------------------------------------------------- 统计（放在 /feedback/{id} 之前）
@router.get("/feedback/stats")
def stats(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(select(Feedback).where(Feedback.created_at >= since)).all()
    fr = [_secs(f.created_at, f.first_response_at) for f in rows if f.first_response_at]
    rs = [_secs(f.created_at, f.resolved_at) for f in rows if f.resolved_at]
    now = utcnow()
    by_cat: dict[str, int] = {}
    by_as: dict[int, dict] = {}
    for f in rows:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
        if f.assignee_id:
            a = by_as.setdefault(f.assignee_id, {"open": 0, "resolved": 0})
            a["open" if f.status in OPEN else "resolved"] += 1
    uc = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(by_as) or [-1])))}
    return {"days": days, "total": len(rows), "by_status": {k: sum(1 for f in rows if f.status == k) for k in STATUSES},
            "avg_first_response_s": int(sum(fr) / len(fr)) if fr else None, "avg_resolve_s": int(sum(rs) / len(rs)) if rs else None,
            "overdue_count": sum(1 for f in rows if _overdue(f, now)),
            "by_category": [{"key": k, "label": CATEGORIES.get(k, k), "count": v} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
            "by_assignee": [{"user": _label(db, k, uc), **v} for k, v in by_as.items()]}


@router.get("/feedback/assignees")
def assignees(db: Session = Depends(get_db)):
    """可以指派的管理员（有「用户反馈」修改权限的角色）。"""
    from ..services import permissions

    roles = [r for r, m in permissions.MATRIX.items() if m.get("feedback") == "w"]
    rows = db.scalars(select(User).where(User.role.in_(roles), User.status == "active").order_by(User.id)).all()
    return {"items": [{"id": u.id, "label": users.label(u), "role": u.role, "role_label": permissions.ROLE_LABELS.get(u.role, u.role)}
                      for u in rows]}


# ---------------------------------------------------------------- 详情、关联
def _notes(db: Session, f: Feedback, me: User) -> list[dict]:
    rows = db.scalars(select(FeedbackNote).where(FeedbackNote.feedback_id == f.id).order_by(FeedbackNote.id)).all()
    return [{"id": n.id, "text": n.text, "by": _label(db, n.user_id), "at": n.created_at,
             "can_delete": n.user_id == me.id or is_super(me)} for n in rows]


@router.get("/feedback/{fb_id}")
def detail(fb_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = _get(db, fb_id)
    return {**_row(db, f, _users_of(db, [f])), "notes": _notes(db, f, me)}


def _client_errors(db: Session, uid: int) -> list[dict]:
    from .observability import errors_for_user

    return errors_for_user(db, uid)


@router.get("/feedback/{fb_id}/related")
def related(fb_id: int, db: Session = Depends(get_db)):
    from .ingest_monitor import _collect

    f = _get(db, fb_id)
    u = db.get(User, f.user_id) if f.user_id else None
    it = db.get(Item, f.item_id) if f.item_id else None
    from .manage import ITEM_STATUS

    same = db.scalars(select(Feedback).where(Feedback.user_id == f.user_id, Feedback.id != f.id).order_by(Feedback.id.desc()).limit(5)).all() if u else []
    sim_ids = [int(x) for x in ((f.ai_analysis or {}).get("similar_ids") or []) if str(x).isdigit()][:10]
    sims = db.scalars(select(Feedback).where(Feedback.id.in_(sim_ids or [-1]))).all()
    tasks = _collect(db, "", u.id, "", None, None)[:5] if u else []
    brief = lambda x: {"id": x.id, "summary": x.content[:60], "status": x.status, "status_label": STATUSES.get(x.status, x.status),  # noqa: E731
                       "created_at": x.created_at}
    return {"user": {"id": u.id, "label": users.label(u), "signup_channel_label": CHANNELS.get(u.signup_channel or "", "未知"),
                     "last_client_label": CHANNELS.get(u.last_client or "", "未知"), "last_client_version": u.last_client_version,
                     "status": u.status} if u else None,
            "item": {"id": it.id, "name": it.name, "status_label": ITEM_STATUS.get(it.status, it.status)} if it else None,
            "page_url": f.page_url, "diagnostics": f.diagnostics or {},
            "user_feedbacks": [brief(x) for x in same], "user_tasks": [{"id": t["id"], "title": t["title"], "status": t["status"],
                                                                        "status_label": t["status_label"]} for t in tasks],
            "similar": [brief(x) for x in sims], "client_errors": _client_errors(db, u.id) if u else None}


# ---------------------------------------------------------------- 状态 / 优先级 / 类别 / 回复
def _check_expected(f: Feedback, expected: str | None, db: Session):
    if expected and expected != f.status:
        _err(409, "already_handled", f"这条反馈已被处理（当前：{STATUSES.get(f.status, f.status)}）",
             handled_by=_label(db, f.assignee_id), handled_at=f.updated_at, status=f.status)


def _apply_status(f: Feedback, new: str, reason: str) -> str | None:
    """返回 None 表示没变化。"""
    if new == f.status:
        return None
    reopen = f.status in DONE and new == "processing"
    if reopen:
        if len(reason.strip()) < 2:
            _err(400, "reason_required", "重新打开需要填写原因")
        f.resolved_at = f.closed_at = None
    elif new not in FLOW.get(f.status, set()):
        _err(400, "bad_transition", f"不能从「{STATUSES[f.status]}」改为「{STATUSES.get(new, new)}」")
    old = f.status
    f.status = new
    now = utcnow()
    if new == "resolved":
        f.resolved_at = now
    if new == "closed":
        f.closed_at = now
        f.resolved_at = f.resolved_at or (now if old == "resolved" else f.resolved_at)
    return old


def _fill(text: str, f: Feedback, db: Session) -> str:
    u = db.get(User, f.user_id) if f.user_id else None
    return text.replace("{nickname}", (u.nickname if u else "") or "你").replace("{id}", str(f.id))


def _notify(db: Session, f: Feedback, reply: str = "", status_changed: bool = False) -> bool:
    if not f.user_id:
        return False
    if reply:
        title, body = f"你的反馈 #{f.id} 有了回复", reply[:200]
    elif status_changed and f.status in NOTIFY_STATUS:
        title, body = f"你的反馈 #{f.id} {NOTIFY_STATUS[f.status]}", f.content[:80]
    else:
        return False
    notify.push(db, f.user_id, "feedback_reply", title, body, "/me?tab=feedback")
    return True


class FeedbackPatch(BaseModel):
    status: str | None = Field(None, pattern="^(new|processing|resolved|closed|wontfix)$")
    priority: str | None = Field(None, pattern="^(|P0|P1|P2|P3|P4)$")
    category: str | None = Field(None, pattern="^(bug|feature|ux|content|account|other)$")
    reply: str | None = Field(None, max_length=2000)
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


@router.patch("/feedback/{fb_id}")
def patch(fb_id: int, body: FeedbackPatch, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = _get(db, fb_id)
    _check_expected(f, body.expected_status, db)
    before, after = {}, {}
    if body.status is not None:
        old = _apply_status(f, body.status, body.reason)
        if old is not None:
            before["status"], after["status"] = old, f.status
    for k in ("priority", "category"):
        v = getattr(body, k)
        if v is not None and v != getattr(f, k):
            before[k], after[k] = getattr(f, k), v
            setattr(f, k, v)
    reply = ""
    if body.reply is not None and body.reply.strip() and body.reply.strip() != f.admin_reply:
        reply = _fill(body.reply.strip(), f, db)
        now = utcnow()
        f.replies = [*(f.replies or []), {"text": reply, "images": [], "at": now.isoformat(), "by": me.nickname}]
        f.admin_reply, f.replied_at = reply, now
        f.first_response_at = f.first_response_at or now
        after["reply"] = reply[:200]
    notified = False
    if after:
        if f.user_id and ("status" in after or reply):
            f.user_unread = True
        notified = _notify(db, f, reply, "status" in after)
    db.commit()
    if after:
        activity.record("feedback_update", f"处理反馈 #{f.id}：" + "、".join(activity.FIELD_LABELS.get(k, k) for k in after),
                        user=me, target_type="feedback", target_id=f.id, ip=client_ip(request), reason=body.reason.strip(),
                        before=before or None, after=after, target_label=f"反馈 #{f.id}")
    return {**_row(db, f, _users_of(db, [f])), "notified": notified}


@router.post("/feedback/{fb_id}/replies")
async def reply(fb_id: int, request: Request, text: str = Form("", max_length=2000), status: str = Form(""),
                expected_status: str = Form(""), reason: str = Form(""), images: list[UploadFile] = File(default=[]),
                db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """回复（文字 + 最多 3 张图），可同时改状态。"""
    f = _get(db, fb_id)
    _check_expected(f, expected_status or None, db)
    if status and status not in STATUSES:
        _err(400, "bad_status", "未知状态")
    if not text.strip() and not images and not status:
        _err(400, "empty", "写点回复内容，或选一个处理状态")
    if len(images) > MAX_IMAGES:
        _err(400, "too_many_images", f"最多附 {MAX_IMAGES} 张图片")
    before, after = {}, {}
    body = ""
    if text.strip() or images:
        paths = await save_images(images, "feedback")
        now = utcnow()
        body = _fill(text.strip(), f, db)
        f.replies = [*(f.replies or []), {"text": body, "images": paths, "at": now.isoformat(), "by": me.nickname}]
        if body:
            f.admin_reply = body
        f.replied_at = now
        f.first_response_at = f.first_response_at or now
        after["reply"] = body[:200] or "（图片）"
    if status:
        old = _apply_status(f, status, reason)
        if old is not None:
            before["status"], after["status"] = old, f.status
    if f.user_id and after:
        f.user_unread = True
    notified = _notify(db, f, body or ("（回复了图片）" if images else ""), "status" in after)
    db.commit()
    activity.record("feedback_update", f"处理反馈 #{f.id}：" + "、".join(activity.FIELD_LABELS.get(k, k) for k in after),
                    user=me, target_type="feedback", target_id=f.id, ip=client_ip(request), reason=reason.strip(),
                    before=before or None, after=after, target_label=f"反馈 #{f.id}")
    return {**_row(db, f, _users_of(db, [f])), "notified": notified}


# ---------------------------------------------------------------- 负责人
class AssignIn(BaseModel):
    assignee_id: int | None = None
    expected_status: str | None = None


def _assign(db: Session, f: Feedback, assignee_id: int | None) -> tuple[int | None, int | None] | None:
    if assignee_id is not None:
        u = db.get(User, assignee_id)
        if u is None or u.role not in STAFF_ROLES:
            _err(400, "bad_assignee", "只能指派给管理员")
    if f.assignee_id == assignee_id:
        return None
    old = f.assignee_id
    f.assignee_id, f.assigned_at = assignee_id, utcnow() if assignee_id else None
    if assignee_id and f.status == "new":
        f.status = "processing"
    return old, assignee_id


@router.post("/feedback/{fb_id}/assign")
def assign(fb_id: int, body: AssignIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = _get(db, fb_id)
    _check_expected(f, body.expected_status, db)
    ch = _assign(db, f, body.assignee_id)
    db.commit()
    if ch:
        activity.record("feedback_assign", f"反馈 #{f.id} 负责人：{(_label(db, ch[0]) or {}).get('label', '无')} → "
                        f"{(_label(db, ch[1]) or {}).get('label', '无')}", user=me, target_type="feedback", target_id=f.id,
                        ip=client_ip(request), before={"assignee": (_label(db, ch[0]) or {}).get("label")},
                        after={"assignee": (_label(db, ch[1]) or {}).get("label")}, target_label=f"反馈 #{f.id}")
    return _row(db, f, _users_of(db, [f]))


# ---------------------------------------------------------------- 内部备注
class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/feedback/{fb_id}/notes")
def add_note(fb_id: int, body: NoteIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = _get(db, fb_id)
    db.add(FeedbackNote(feedback_id=f.id, user_id=me.id, text=body.text.strip()))
    db.commit()
    activity.record("feedback_note", f"反馈 #{f.id} 添加内部备注", user=me, target_type="feedback", target_id=f.id, ip=client_ip(request),
                    after={"note": body.text.strip()[:200]}, target_label=f"反馈 #{f.id}")
    return {"notes": _notes(db, f, me)}


@router.delete("/feedback/{fb_id}/notes/{note_id}")
def delete_note(fb_id: int, note_id: int, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    n = db.get(FeedbackNote, note_id)
    if n is None or n.feedback_id != fb_id:
        _err(404, "not_found", "备注不存在")
    if n.user_id != me.id and not is_super(me):
        _err(403, "forbidden", "只能删除自己的备注")
    text = n.text
    db.delete(n)
    db.commit()
    activity.record("feedback_note", f"反馈 #{fb_id} 删除内部备注", user=me, target_type="feedback", target_id=fb_id, ip=client_ip(request),
                    before={"note": text[:200]}, target_label=f"反馈 #{fb_id}")
    return {"notes": _notes(db, _get(db, fb_id), me)}


# ---------------------------------------------------------------- 批量
class BulkParams(BaseModel):
    assignee_id: int | None = None
    status: str | None = None
    priority: str | None = None


class BulkIn(BaseModel):
    action: str = Field(pattern="^(assign|status|priority|close)$")
    params: BulkParams = BulkParams()
    reason: str = Field("", max_length=300)
    ids: list[int] | None = None
    filter: FbFilter | None = None
    exclude: list[int] = []
    total: int | None = None


@router.post("/feedback/bulk")
def bulk(body: BulkIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    if body.ids is not None:
        ids = list(dict.fromkeys(body.ids))
    elif body.filter is not None:
        all_ids = list(db.scalars(select(Feedback.id).where(*_conds(db, body.filter, me)).order_by(Feedback.id.desc())))
        if body.total is not None and len(all_ids) != body.total:
            _err(409, "count_changed", f"符合条件的反馈数量已变化（现在 {len(all_ids)} 条，选择时 {body.total} 条），请重新确认")
        ids = [i for i in all_ids if i not in set(body.exclude)]
    else:
        ids = []
    if not ids:
        _err(400, "empty_scope", "请先选择反馈")
    if len(ids) > 500:
        _err(400, "too_many", "一次最多操作 500 条")
    if body.action == "status" and body.params.status not in STATUSES:
        _err(400, "bad_status", "请选择状态")
    if body.action == "priority" and body.params.priority not in ("", "P0", "P1", "P2", "P3", "P4"):
        _err(400, "bad_priority", "请选择优先级")
    rows = {f.id: f for f in db.scalars(select(Feedback).where(Feedback.id.in_(ids)))}
    results, logs = [], []
    for i in ids:
        f = rows.get(i)
        if f is None:
            results.append({"id": i, "label": f"反馈 #{i}", "ok": False, "code": "not_found", "message": "反馈不存在"})
            continue
        r = {"id": i, "label": f"#{i} {f.content[:30]}"}
        try:
            if body.action == "assign":
                ch = _assign(db, f, body.params.assignee_id)
                if ch is None:
                    r.update(ok=True, code="noop", message="负责人没有变化")
                else:
                    logs.append((f, {"assignee": (_label(db, ch[0]) or {}).get("label")}, {"assignee": (_label(db, ch[1]) or {}).get("label")}))
                    r.update(ok=True, code="ok", message="")
            elif body.action == "priority":
                if f.priority == body.params.priority:
                    r.update(ok=True, code="noop", message="优先级没有变化")
                else:
                    logs.append((f, {"priority": f.priority}, {"priority": body.params.priority}))
                    f.priority = body.params.priority
                    r.update(ok=True, code="ok", message="")
            else:
                target = "closed" if body.action == "close" else body.params.status
                old = _apply_status(f, target, body.reason)
                if old is None:
                    r.update(ok=True, code="noop", message=f"本来就是{STATUSES[target]}")
                else:
                    if f.user_id:
                        f.user_unread = True
                    _notify(db, f, "", True)
                    logs.append((f, {"status": old}, {"status": f.status}))
                    r.update(ok=True, code="ok", message="")
        except HTTPException as e:
            d = e.detail if isinstance(e.detail, dict) else {"code": "error", "message": str(e.detail)}
            r.update(ok=False, code=d.get("code"), message=d.get("message", ""))
        results.append(r)
    db.commit()
    ip = client_ip(request)
    for f, b, a in logs:
        activity.record("feedback_update", f"批量处理反馈 #{f.id}：" + "、".join(activity.FIELD_LABELS.get(k, k) for k in a), user=me,
                        target_type="feedback", target_id=f.id, ip=ip, reason=body.reason.strip(), before=b, after=a,
                        target_label=f"反馈 #{f.id}", detail={"bulk": True})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok}


# ---------------------------------------------------------------- 回复模板
TPL_SCOPES = {"feedback_reply": "反馈回复", "user_message": "站内消息"}
TPL_MAX = 30
DEFAULT_TPL = [
    ("feedback_reply", "已修复", "{nickname}你好，你反馈的问题（#{id}）已经修复，刷新页面后就能看到。感谢反馈！"),
    ("feedback_reply", "需要更多信息", "{nickname}你好，为了定位问题，能否补充一下出现问题的页面和操作步骤？有截图更好。"),
    ("feedback_reply", "已记录需求", "{nickname}你好，你的建议（#{id}）我们已经记录，会在后续版本中考虑。"),
]


def _tpl_out(t: ReplyTemplate) -> dict:
    return {"id": t.id, "scope": t.scope, "scope_label": TPL_SCOPES.get(t.scope, t.scope), "title": t.title, "text": t.text, "position": t.position}


@router.get("/reply-templates")
def list_tpl(scope: str = "", db: Session = Depends(get_db)):
    from ..models import AppMeta

    if not db.get(AppMeta, "reply_templates_seeded"):
        db.add_all([ReplyTemplate(scope=s, title=t, text=x, position=i) for i, (s, t, x) in enumerate(DEFAULT_TPL)])
        db.add(AppMeta(key="reply_templates_seeded", value="1"))
        db.commit()
    stmt = select(ReplyTemplate).order_by(ReplyTemplate.scope, ReplyTemplate.position, ReplyTemplate.id)
    if scope:
        stmt = stmt.where(ReplyTemplate.scope == scope)
    return {"scopes": TPL_SCOPES, "max": TPL_MAX, "variables": {"{nickname}": "用户昵称", "{id}": "反馈编号"},
            "items": [_tpl_out(t) for t in db.scalars(stmt)]}


class TplIn(BaseModel):
    scope: str
    title: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=500)


class TplPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=40)
    text: str | None = Field(None, min_length=1, max_length=500)
    position: int | None = None


@router.post("/reply-templates")
def create_tpl(body: TplIn, db: Session = Depends(get_db), me: User = Depends(require_super)):
    if body.scope not in TPL_SCOPES:
        _err(400, "bad_scope", "不支持的模板类型")
    n = db.scalar(select(func.count()).select_from(ReplyTemplate).where(ReplyTemplate.scope == body.scope)) or 0
    if n >= TPL_MAX:
        _err(400, "too_many", f"每类最多 {TPL_MAX} 条模板")
    top = db.scalar(select(func.max(ReplyTemplate.position)).where(ReplyTemplate.scope == body.scope))
    t = ReplyTemplate(scope=body.scope, title=body.title.strip(), text=body.text.strip(), position=(top or 0) + 1, created_by=me.id)
    db.add(t)
    db.commit()
    return _tpl_out(t)


@router.put("/reply-templates/{tpl_id}")
def update_tpl(tpl_id: int, body: TplPatch, db: Session = Depends(get_db), me: User = Depends(require_super)):
    t = db.get(ReplyTemplate, tpl_id)
    if t is None:
        _err(404, "not_found", "模板不存在")
    for k in ("title", "text", "position"):
        v = getattr(body, k)
        if v is not None:
            setattr(t, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return _tpl_out(t)


@router.delete("/reply-templates/{tpl_id}")
def delete_tpl(tpl_id: int, db: Session = Depends(get_db), me: User = Depends(require_super)):
    t = db.get(ReplyTemplate, tpl_id)
    if t is None:
        _err(404, "not_found", "模板不存在")
    db.delete(t)
    db.commit()
    return {"ok": True}
