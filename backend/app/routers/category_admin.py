"""v3.3.50 后台批次 3c：分类治理——健康度、合并、拆分、AI 抽检。

合并：条目迁到目标子分类（人工锁定的也迁，迁完保持锁定），被合并的分类停用，旧 code 的筛选重定向到目标分类。
拆分：把选中的条目迁到新建的同一大类下的子分类，并锁定 category_id。
抽检：随机抽已上线条目让 AI 判断分类（judge.classify_items），不同意当前分类的排前面，管理员逐条「保持 / 改到建议分类」。
"""

import random
import re
import secrets
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..db import SessionLocal, get_db, utcnow
from ..models import Category, CategoryAudit, Item, User
from ..services import activity, judge, tracking, users
from ..services.reclassify import _brief, recompute_latest_rankings

router = APIRouter(prefix="/api/admin", tags=["admin-categories"], dependencies=[Depends(require_admin)])

TOO_BIG = 200
REASON_MIN = 2


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < REASON_MIN:
        _err(400, "reason_required", "请填写原因")
    return r


def _sub(db: Session, cid: int | None, code: str = "bad_target", msg: str = "请选择一个子分类") -> Category:
    c = db.get(Category, cid) if cid else None
    if c is None or c.parent_id is None:
        _err(400, code, msg)
    return c


def _brief_cat(c: Category | None) -> dict | None:
    return {"id": c.id, "name": c.name, "code": c.code} if c else None


# ---------------------------------------------------------------- 健康度
@router.get("/categories/health")
def health(db: Session = Depends(get_db)):
    pub = case((Item.status == "published", 1), else_=0)
    counts = {cid: (p or 0, t or 0) for cid, p, t in db.execute(
        select(Item.category_id, func.sum(pub), func.count()).group_by(Item.category_id)).all()}
    subs = db.scalars(select(Category).where(Category.parent_id.is_not(None)).order_by(Category.parent_id, Category.sort)).all()
    items = []
    for c in subs:
        p, t = counts.get(c.id, (0, 0))
        st = "empty" if p == 0 else "too_big" if p > TOO_BIG else "ok"
        items.append({"id": c.id, "name": c.name, "code": c.code, "enabled": c.enabled, "parent": _brief_cat(c.parent),
                      "published_count": p, "total_count": t, "status": st,
                      "merged_into": _brief_cat(db.get(Category, c.merged_into_id)) if c.merged_into_id else None})
    return {"thresholds": {"empty": 0, "too_big": TOO_BIG}, "items": items}


# ---------------------------------------------------------------- 合并
class MergeIn(BaseModel):
    target_id: int
    reason: str = Field("", max_length=300)
    dry_run: bool = True


@router.post("/categories/{cid}/merge")
def merge(cid: int, body: MergeIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    src = _sub(db, cid, "not_found", "分类不存在或不是子分类")
    dst = _sub(db, body.target_id)
    if dst.id == src.id:
        _err(400, "bad_target", "不能合并到自己")
    rows = db.execute(select(Item.id, Item.name, Item.locked_fields).where(Item.category_id == src.id).order_by(Item.id)).all()
    conflicts = []
    if not dst.enabled or (dst.parent and not dst.parent.enabled):
        conflicts.append("目标分类已停用，合并后这些条目在前台的分类里看不到")
    if dst.merged_into_id:
        conflicts.append("目标分类本身已被合并到其他分类")
    preview = {"moved_count": len(rows), "sample": [n for _, n, _ in rows[:10]],
               "locked_count": sum(1 for _, _, lf in rows if "category_id" in (lf or [])), "conflicts": conflicts,
               "source": _brief_cat(src), "target": _brief_cat(dst)}
    if body.dry_run:
        return preview
    reason = _reason(body.reason)
    db.execute(update(Item).where(Item.category_id == src.id).values(category_id=dst.id))
    src.enabled, src.merged_into_id = False, dst.id
    # 之前合并到 src 的分类改指向 dst，避免两跳
    db.execute(update(Category).where(Category.merged_into_id == src.id).values(merged_into_id=dst.id))
    db.commit()
    activity.record("category_merge", f"合并分类「{src.name}」→「{dst.name}」：迁移 {len(rows)} 个条目", user=me, target_type="category",
                    target_id=src.id, ip=client_ip(request), reason=reason, before={"category": src.name, "enabled": True},
                    after={"category": dst.name, "enabled": False}, target_label=src.name, detail={"moved": len(rows), "target_id": dst.id})
    threading.Thread(target=recompute_latest_rankings, daemon=True).start()
    return {**preview, "task_id": None}


# ---------------------------------------------------------------- 拆分
class SplitPart(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    item_ids: list[int]


class SplitIn(BaseModel):
    reason: str = Field("", max_length=300)
    dry_run: bool = True
    parts: list[SplitPart] = Field(min_length=1, max_length=10)


def _new_code(db: Session, base: str) -> str:
    for _ in range(20):
        code = f"{base}-{secrets.token_hex(2)}"[:64]
        if not db.scalar(select(Category.id).where(Category.code == code)):
            return code
    return f"cat-{secrets.token_hex(6)}"


@router.post("/categories/{cid}/split")
def split(cid: int, body: SplitIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    src = _sub(db, cid, "not_found", "分类不存在或不是子分类")
    mine = set(db.scalars(select(Item.id).where(Item.category_id == src.id)))
    siblings = {c.name.strip().lower() for c in db.scalars(select(Category).where(Category.parent_id == src.parent_id))}
    seen_names, seen_ids, parts = set(), set(), []
    for p in body.parts:
        name = p.name.strip()
        key = name.lower()
        if not name:
            _err(400, "bad_name", "请填写新分类名称")
        if key in siblings or key in seen_names:
            _err(400, "duplicate_name", f"「{name}」和已有分类重名")
        bad = [i for i in p.item_ids if i not in mine]
        if bad or not p.item_ids:
            _err(400, "bad_items", "有条目不属于这个分类" if bad else f"「{name}」没有选条目", item_ids=bad)
        dup = seen_ids & set(p.item_ids)
        if dup:
            _err(400, "bad_items", "同一个条目不能拆到两个分类", item_ids=sorted(dup))
        seen_names.add(key)
        seen_ids |= set(p.item_ids)
        parts.append((name, list(dict.fromkeys(p.item_ids))))
    preview = {"source": _brief_cat(src), "parts": [{"name": n, "count": len(ids)} for n, ids in parts],
               "remaining_count": len(mine - seen_ids), "conflicts": []}
    if body.dry_run:
        return preview
    reason = _reason(body.reason)
    base = re.sub(r"[^a-z0-9-]", "", src.code.lower()) or "cat"
    top = db.scalar(select(func.max(Category.sort)).where(Category.parent_id == src.parent_id)) or 0
    created = []
    for i, (name, ids) in enumerate(parts, start=1):
        c = Category(parent_id=src.parent_id, code=_new_code(db, base), name=name, icon=src.icon, sort=top + i, enabled=True,
                     remark=f"由「{src.name}」拆分")
        db.add(c)
        db.flush()
        for it in db.scalars(select(Item).where(Item.id.in_(ids))):
            it.category_id = c.id
            it.locked_fields = sorted(set(it.locked_fields or []) | {"category_id"})
        created.append({"id": c.id, "name": c.name, "code": c.code, "count": len(ids)})
    db.commit()
    activity.record("category_split", f"拆分分类「{src.name}」→ " + "、".join(f"「{c['name']}」{c['count']} 个" for c in created), user=me,
                    target_type="category", target_id=src.id, ip=client_ip(request), reason=reason, target_label=src.name,
                    detail={"created": created})
    threading.Thread(target=recompute_latest_rankings, daemon=True).start()
    return {**preview, "created": created}


# ---------------------------------------------------------------- AI 抽检
class AuditRunIn(BaseModel):
    sample: int = Field(20, ge=1, le=100)
    category_id: int | None = None


def _run_audit(task_id: int, ids: list[int]) -> None:
    """后台：每 12 个一批调用 AI 分类，写抽检记录。"""
    from ..services.ingest import category_choices

    done: dict[int, dict | None] = {}

    def one(item_id: int, tid: int) -> tuple[bool, str]:
        if item_id not in done:
            pos = ids.index(item_id)
            chunk = ids[pos:pos + 12]
            with SessionLocal() as db:
                briefs = [_brief(it) for it in db.scalars(select(Item).where(Item.id.in_(chunk)))]
                choices = category_choices(db)
            try:
                got = judge.classify_items(briefs, choices)
            except judge.JudgeUnavailable as e:
                got = {}
                tracking.log(trigger="audit", stage="classify", level="error", message=f"AI 分类抽检失败：{e}", task_id=tid)
            for i in chunk:
                done.setdefault(i, got.get(i))
        v = done.get(item_id)
        if not v:
            return False, "AI 没有给出分类"
        with SessionLocal() as db:
            it = db.get(Item, item_id)
            if it is None:
                return False, "条目不存在"
            sug = db.scalar(select(Category).where(Category.code == v.get("category_code"))) if v.get("category_code") else None
            agree = sug is None or sug.id == it.category_id
            db.add(CategoryAudit(task_id=tid, item_id=it.id, current_id=it.category_id, suggested_id=sug.id if sug else it.category_id,
                                 confidence=v.get("confidence"), reason=(v.get("reason") or "")[:300], agree=agree,
                                 status="open"))
            db.commit()
            return True, "同意当前分类" if agree else f"建议改到「{sug.name}」"

    tracking.run_task(task_id, ids, one, workers=1)


@router.post("/category-audit/run")
def run_audit(body: AuditRunIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    from ..config import settings

    if not settings.ai_enabled:
        _err(400, "ai_disabled", "还没有配置 AI 接口")
    stmt = select(Item.id, Item.name).where(Item.status == "published")
    if body.category_id:
        stmt = stmt.where(Item.category_id == body.category_id)
    rows = db.execute(stmt).all()
    if not rows:
        _err(400, "empty_scope", "没有可以抽检的条目")
    pick = random.sample(rows, min(body.sample, len(rows)))
    task_id = tracking.create_task("audit", f"AI 分类抽检 · {len(pick)} 个条目", [(i, n) for i, n in pick])
    threading.Thread(target=_run_audit, args=(task_id, [i for i, _ in pick]), daemon=True, name=f"audit-{task_id}").start()
    activity.record("category_audit", f"发起 AI 分类抽检：{len(pick)} 个条目", user=me, ip=client_ip(request), detail={"task_id": task_id})
    return {"task_id": task_id, "sample": len(pick)}


AUDIT_STATUS = {"open": "待确认", "kept": "保持现分类", "moved": "已改分类"}


@router.get("/category-audit")
def list_audit(status: str = Query("open", pattern="^(open|decided|all)$"), task_id: int | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(CategoryAudit)
    if status == "open":
        stmt = stmt.where(CategoryAudit.status == "open")
    elif status == "decided":
        stmt = stmt.where(CategoryAudit.status != "open")
    if task_id:
        stmt = stmt.where(CategoryAudit.task_id == task_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(CategoryAudit.agree.asc(), CategoryAudit.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    cats = {c.id: c for c in db.scalars(select(Category))}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({r.item_id for r in rows if r.item_id} or {-1})))}
    n_open = db.scalar(select(func.count()).select_from(CategoryAudit).where(CategoryAudit.status == "open")) or 0
    n_all = db.scalar(select(func.count()).select_from(CategoryAudit)) or 0
    out = []
    for r in rows:
        it = items.get(r.item_id)
        who = db.get(User, r.decided_by) if r.decided_by else None
        out.append({"id": r.id, "item": {"id": it.id, "name": it.name, "summary": it.summary,
                                         "category": _brief_cat(cats.get(it.category_id))} if it else None,
                    "current": _brief_cat(cats.get(r.current_id)),
                    "suggested": {**(_brief_cat(cats.get(r.suggested_id)) or {}), "confidence": r.confidence, "reason": r.reason},
                    "agree": r.agree, "status": r.status, "status_label": AUDIT_STATUS[r.status],
                    "decided_by": {"id": who.id, "label": users.label(who)} if who else None, "decided_at": r.decided_at,
                    "decision_reason": r.decision_reason, "task_id": r.task_id, "created_at": r.created_at})
    return {"total": total, "counts": {"open": n_open, "decided": n_all - n_open}, "items": out}


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(keep|move)$")
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


@router.post("/category-audit/{audit_id}/decide")
def decide_audit(audit_id: int, body: DecideIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    a = db.get(CategoryAudit, audit_id)
    if a is None:
        _err(404, "not_found", "抽检记录不存在")
    if (body.expected_status and body.expected_status != a.status) or a.status != "open":
        who = db.get(User, a.decided_by) if a.decided_by else None
        _err(409, "already_handled", f"已被{users.label(who) if who else '其他人'}处理（当前：{AUDIT_STATUS[a.status]}）",
             handled_by={"id": who.id, "label": users.label(who)} if who else None, handled_at=a.decided_at, status=a.status)
    reason = (body.reason or "").strip()
    it = db.get(Item, a.item_id) if a.item_id else None
    if body.decision == "move":
        reason = _reason(reason)
        dst = db.get(Category, a.suggested_id)
        if it is None or dst is None:
            _err(400, "bad_target", "条目或建议分类不存在")
        before = db.get(Category, it.category_id)
        it.category_id = dst.id
        it.locked_fields = sorted(set(it.locked_fields or []) | {"category_id"})
        a.status = "moved"
    else:
        a.status = "kept"
    a.decided_by, a.decided_at, a.decision_reason = me.id, utcnow(), reason
    db.commit()
    if body.decision == "move":
        activity.record("item_edit", f"AI 抽检后改分类「{it.name}」", user=me, target_type="item", target_id=it.id, ip=client_ip(request),
                        reason=reason, before={"category": before.name if before else ""}, after={"category": dst.name},
                        target_label=it.name, detail={"audit_id": a.id})
    return {"id": a.id, "status": a.status, "status_label": AUDIT_STATUS[a.status]}
