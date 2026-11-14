"""v3.3.48 后台批次 3b：推荐位排期列表、黑名单、下架申请（用户侧提交 + 后台处理）。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..auth import client_ip, current_user, require_admin
from ..db import get_db, utcnow
from ..models import BlockEntry, Item, Repo, TakedownRequest, User
from ..services import activity, blocklist, notify, pins, search, users
from .manage import ITEM_STATUS

router = APIRouter(prefix="/api", tags=["takedown"])
admin = APIRouter(prefix="/api/admin", tags=["admin-takedown"], dependencies=[Depends(require_admin)])

RELATIONS = {"author": "原作者", "maintainer": "维护者", "other": "其他"}
TD_STATUS = {"pending": "待处理", "approved": "已下架", "rejected": "已驳回"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _who(db: Session, uid: int | None):
    if not uid:
        return None
    u = db.get(User, uid)
    return {"id": uid, "label": users.label(u) if u else f"用户 #{uid}"}


# ================================================================ 用户侧：申请下架
class TakedownIn(BaseModel):
    relation: str = Field("author", pattern="^(author|maintainer|other)$")
    reason: str = Field(min_length=5, max_length=1000)
    contact: str = Field("", max_length=200)
    evidence_url: str = Field("", max_length=500)


def _mine_out(t: TakedownRequest | None) -> dict | None:
    if t is None:
        return None
    return {"id": t.id, "status": t.status, "status_label": TD_STATUS[t.status], "created_at": t.created_at,
            "handled_at": t.handled_at, "handle_reason": t.handle_reason if t.status == "rejected" else ""}


@router.get("/items/{item_id}/takedown")
def my_takedown(item_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """我对这个条目最近一次的下架申请（没有为 null）。"""
    t = db.scalar(select(TakedownRequest).where(TakedownRequest.item_id == item_id, TakedownRequest.user_id == me.id)
                  .order_by(TakedownRequest.id.desc()))
    return {"request": _mine_out(t)}


@router.post("/items/{item_id}/takedown")
def submit_takedown(item_id: int, body: TakedownIn, request: Request, db: Session = Depends(get_db), me: User = Depends(current_user)):
    it = db.scalar(select(Item).options(joinedload(Item.repo)).where(Item.id == item_id))
    if it is None or it.status not in ("published", "offline"):
        _err(404, "not_found", "条目不存在")
    if db.scalar(select(TakedownRequest.id).where(TakedownRequest.item_id == item_id, TakedownRequest.user_id == me.id,
                                                  TakedownRequest.status == "pending")):
        _err(409, "duplicate_pending", "你已经提交过申请，正在处理中")
    t = TakedownRequest(item_id=it.id, item_name=it.name, repo_full_name=it.repo.full_name if it.repo else "", user_id=me.id,
                        relation=body.relation, reason=body.reason.strip(), contact=body.contact.strip(),
                        evidence_url=body.evidence_url.strip())
    db.add(t)
    db.commit()
    activity.record("takedown_request", f"申请下架「{it.name}」（{RELATIONS[body.relation]}）", user=me, target_type="item",
                    target_id=it.id, ip=client_ip(request), reason=body.reason.strip()[:300], target_label=it.name)
    return {"request": _mine_out(t)}


# ================================================================ 后台：下架申请
def _td_out(db: Session, t: TakedownRequest, items: dict | None = None) -> dict:
    it = (items or {}).get(t.item_id) if items is not None else (db.get(Item, t.item_id) if t.item_id else None)
    return {"id": t.id, "item": {"id": t.item_id, "name": it.name if it else t.item_name, "status": it.status if it else "deleted",
                                 "status_label": ITEM_STATUS.get(it.status, it.status) if it else "已删除"},
            "repo": t.repo_full_name, "user": _who(db, t.user_id), "relation": t.relation, "relation_label": RELATIONS.get(t.relation, t.relation),
            "reason": t.reason, "contact": t.contact, "evidence_url": t.evidence_url, "status": t.status, "status_label": TD_STATUS[t.status],
            "created_at": t.created_at, "handled": {"by": _who(db, t.handled_by), "at": t.handled_at, "reason": t.handle_reason,
                                                     "action": t.handle_action, "blocked": t.blocked} if t.handled_at else None}


@admin.get("/takedowns")
def list_takedowns(status: str = Query("pending", pattern="^(pending|approved|rejected|all)$"), item_id: int | None = None,
                   id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(TakedownRequest)
    if id is not None:
        stmt = stmt.where(TakedownRequest.id == id)
    else:
        if status != "all":
            stmt = stmt.where(TakedownRequest.status == status)
        if item_id:
            stmt = stmt.where(TakedownRequest.item_id == item_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(TakedownRequest.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({r.item_id for r in rows if r.item_id} or {-1})))}
    # 同一条目的其他申请次数（多次申请合并显示）
    same = dict(db.execute(select(TakedownRequest.item_id, func.count()).where(TakedownRequest.item_id.in_(list(items) or [-1]))
                           .group_by(TakedownRequest.item_id)).all())
    counts = dict(db.execute(select(TakedownRequest.status, func.count()).group_by(TakedownRequest.status)).all())
    return {"total": total, "page": page, "page_size": page_size, "counts": {k: counts.get(k, 0) for k in TD_STATUS},
            "items": [{**_td_out(db, r, items), "requests_for_item": same.get(r.item_id, 1)} for r in rows]}


class TdActIn(BaseModel):
    reason: str = Field("", max_length=300)
    expected_status: str | None = None
    action: str = Field("hide", pattern="^(hide|delete)$")  # 同意时：隐藏条目（可恢复）/ 删除条目
    block: bool = False  # 同意时：同时把仓库加入黑名单


def _check(db: Session, t: TakedownRequest | None, body: TdActIn) -> TakedownRequest:
    if t is None:
        _err(404, "not_found", "申请不存在")
    if (body.expected_status and body.expected_status != t.status) or t.status != "pending":
        who = _who(db, t.handled_by)
        _err(409, "already_handled", f"已被{who['label'] if who else '其他人'}处理（当前：{TD_STATUS[t.status]}）",
             handled_by=who, handled_at=t.handled_at, status=t.status)
    reason = body.reason.strip()
    if len(reason) < 2:
        _err(400, "reason_required", "请填写原因")
    return t


def add_block(db: Session, kind: str, value: str, reason: str, me: User, source: str = "manual", takedown_id: int | None = None):
    value = blocklist.norm_repo(value) if kind == "repo" else value.strip().lower()
    e = db.scalar(select(BlockEntry).where(BlockEntry.kind == kind, BlockEntry.value == value))
    if e is None:
        e = BlockEntry(kind=kind, value=value, reason=reason, source=source, takedown_id=takedown_id, created_by=me.id)
        db.add(e)
        if kind == "repo":
            repo = db.scalar(select(Repo).where(func.lower(Repo.full_name) == value))
            if repo is not None:
                repo.repo_status = "rejected"
    return e


@admin.post("/takedowns/{td_id}/approve")
def approve_takedown(td_id: int, body: TdActIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = _check(db, db.get(TakedownRequest, td_id), body)
    reason = body.reason.strip()
    it = db.get(Item, t.item_id) if t.item_id else None
    if it is not None:
        if body.action == "delete":
            search.forget(it.id)
            db.delete(it)
        elif it.status in ("published", "offline"):
            it.status = "hidden"
    if body.block and t.repo_full_name:
        add_block(db, "repo", t.repo_full_name, f"下架申请 #{t.id}：{reason}", me, source="takedown", takedown_id=t.id)
    t.status, t.handled_by, t.handled_at, t.handle_reason, t.handle_action, t.blocked = (
        "approved", me.id, utcnow(), reason, body.action, bool(body.block and t.repo_full_name))
    # 同一条目其他待处理的申请一并结案
    for other in db.scalars(select(TakedownRequest).where(TakedownRequest.item_id == t.item_id, TakedownRequest.id != t.id,
                                                         TakedownRequest.status == "pending")):
        other.status, other.handled_by, other.handled_at, other.handle_reason, other.handle_action = (
            "approved", me.id, utcnow(), reason, body.action)
    if t.user_id:
        notify.push(db, t.user_id, "system", f"你申请下架的「{t.item_name}」已下架", reason)
    db.commit()
    activity.record("takedown_approve", f"同意下架「{t.item_name}」（{'删除' if body.action == 'delete' else '隐藏'}"
                    + ("，加入黑名单" if t.blocked else "") + "）", user=me, target_type="item", target_id=t.item_id,
                    ip=client_ip(request), reason=reason, before={"status": "published"},
                    after={"status": "deleted" if body.action == "delete" else "hidden"}, target_label=t.item_name)
    return _td_out(db, t)


@admin.post("/takedowns/{td_id}/reject")
def reject_takedown(td_id: int, body: TdActIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = _check(db, db.get(TakedownRequest, td_id), body)
    reason = body.reason.strip()
    t.status, t.handled_by, t.handled_at, t.handle_reason = "rejected", me.id, utcnow(), reason
    if t.user_id:
        notify.push(db, t.user_id, "system", f"你申请下架的「{t.item_name}」未通过", reason, f"/items/{t.item_id}" if t.item_id else "")
    db.commit()
    activity.record("takedown_reject", f"驳回下架申请「{t.item_name}」", user=me, target_type="item", target_id=t.item_id,
                    ip=client_ip(request), reason=reason, target_label=t.item_name)
    return _td_out(db, t)


# ================================================================ 后台：黑名单
def _block_out(db: Session, e: BlockEntry) -> dict:
    return {"id": e.id, "kind": e.kind, "kind_label": "仓库" if e.kind == "repo" else "GitHub 账号", "value": e.value,
            "reason": e.reason, "source": e.source, "takedown_id": e.takedown_id, "by": _who(db, e.created_by), "at": e.created_at}


@admin.get("/blocklist")
def list_blocks(kind: str = Query("", pattern="^(|repo|owner)$"), q: str = "", page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(BlockEntry)
    if kind:
        stmt = stmt.where(BlockEntry.kind == kind)
    if q.strip():
        stmt = stmt.where(BlockEntry.value.ilike(f"%{q.strip().lower()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(BlockEntry.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_block_out(db, e) for e in rows]}


class BlockIn(BaseModel):
    kind: str = Field(pattern="^(repo|owner)$")
    value: str = Field(min_length=1, max_length=200)
    reason: str = Field("", max_length=300)


@admin.post("/blocklist")
def create_block(body: BlockIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    v = body.value.strip().removeprefix("https://github.com/").strip("/")
    if body.kind == "repo" and v.count("/") != 1:
        _err(400, "bad_value", "仓库请填写 owner/name 或 GitHub 链接")
    if body.kind == "owner" and "/" in v:
        _err(400, "bad_value", "GitHub 账号只填 owner")
    if len(body.reason.strip()) < 2:
        _err(400, "reason_required", "请填写原因")
    key = blocklist.norm_repo(v) if body.kind == "repo" else v.lower()
    if db.scalar(select(BlockEntry.id).where(BlockEntry.kind == body.kind, BlockEntry.value == key)):
        _err(400, "duplicate", "已经在黑名单里")
    e = add_block(db, body.kind, v, body.reason.strip(), me)
    db.commit()
    # 已收录的条目不自动下线，返回数量供前端提示
    like = f"{key}/%" if body.kind == "owner" else key
    n = db.scalar(select(func.count()).select_from(Item).join(Repo, Repo.id == Item.repo_id)
                  .where(func.lower(Repo.full_name).like(like) if body.kind == "owner" else func.lower(Repo.full_name) == key,
                         Item.status == "published")) or 0
    activity.record("block_add", f"加入黑名单（{'仓库' if body.kind == 'repo' else 'GitHub 账号'}）：{key}", user=me,
                    target_type="block", target_id=e.id, ip=client_ip(request), reason=body.reason.strip())
    return {**_block_out(db, e), "published_items": n}


@admin.delete("/blocklist/{entry_id}")
def delete_block(entry_id: int, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    e = db.get(BlockEntry, entry_id)
    if e is None:
        _err(404, "not_found", "记录不存在")
    if e.kind == "repo":
        repo = db.scalar(select(Repo).where(func.lower(Repo.full_name) == e.value))
        if repo is not None and repo.repo_status == "rejected":
            repo.repo_status = "active"
    value = e.value
    db.delete(e)
    db.commit()
    activity.record("block_remove", f"移出黑名单：{value}", user=me, target_type="block", target_id=entry_id, ip=client_ip(request))
    return {"ok": True}


# ================================================================ 后台：推荐位
@admin.get("/pins")
def list_pins(state: str = Query("", pattern="^(|active|scheduled|expired)$"), db: Session = Depends(get_db)):
    """所有设置过置顶的条目，按状态（生效中 → 未开始 → 已结束）、权重排序。"""
    rows = db.scalars(select(Item).options(joinedload(Item.repo)).where(Item.pin_weight > 0)).unique().all()
    order = {"active": 0, "scheduled": 1, "expired": 2}
    out = []
    for it in rows:
        p = pins.out(it)
        if state and p["state"] != state:
            continue
        out.append({"id": it.id, "name": it.name, "status": it.status, "status_label": ITEM_STATUS.get(it.status, it.status),
                    "repo": it.repo.full_name if it.repo else "", "pin": p})
    out.sort(key=lambda x: (order[x["pin"]["state"]], -x["pin"]["weight"], x["id"]))
    counts = {k: sum(1 for x in out if x["pin"]["state"] == k) for k in order} if not state else None
    return {"items": out, "counts": counts}
