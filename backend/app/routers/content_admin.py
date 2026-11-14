"""v3.3.46 后台批次 3a：内容管理的质量统计、批量操作、关键字段修改记录。

- GET  /api/admin/items/quality-stats：各质量问题的条目数（只统计已上线 + 原文已下线）
- POST /api/admin/items/bulk：set_category / hide / show / reextract / cover / rank_exclude / rank_include
- GET  /api/admin/items/{id}/changes：这个条目的修改记录（操作日志里 target=item 的，带修改前后）
"""

from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..auth import client_ip, require_admin
from ..config import settings
from ..db import get_db, utcnow
from ..models import ActivityLog, Category, Item, Ranking, User
from ..services import activity, ingest, item_quality, rankings, tracking, users
from .manage import ITEM_STATUS, ItemFilter, items_stmt

router = APIRouter(prefix="/api/admin", tags=["admin-content"], dependencies=[Depends(require_admin)])

BULK_MAX = 1000
AI_BULK_MAX = 200  # 重新提炼 / 补封面会调用 AI，一次最多 200 个
ACTIONS = {"set_category": "改分类", "hide": "隐藏（下线）", "show": "重新上线", "reextract": "重新提炼", "cover": "补封面",
           "rank_exclude": "排除出榜单", "rank_include": "恢复进榜单"}
NEED_REASON = {"hide", "show", "rank_exclude", "rank_include"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


@router.get("/items/quality-stats")
def quality_stats(low_star: int = Query(item_quality.LOW_STAR, ge=1, le=100000), db: Session = Depends(get_db)):
    from ..models import Repo

    base = select(Item.id).outerjoin(Repo, Repo.id == Item.repo_id).where(Item.status.in_(("published", "offline")))
    out = {}
    for k, label in item_quality.QUALITY.items():
        n = db.scalar(select(func.count()).select_from(base.where(*item_quality.conds(db, [k], low_star)).subquery()))
        out[k] = {"label": label, "count": n}
    return {"low_star": low_star, "spike": {"min": item_quality.SPIKE_MIN, "ratio": item_quality.SPIKE_RATIO}, "items": out}


class BulkParams(BaseModel):
    category_id: int | None = None


class ItemBulkIn(BaseModel):
    action: str = Field(pattern="^(set_category|hide|show|reextract|cover|rank_exclude|rank_include)$")
    reason: str = Field("", max_length=300)
    params: BulkParams = BulkParams()
    ids: list[int] | None = None
    filter: ItemFilter | None = None
    exclude: list[int] = []
    total: int | None = None


def _latest_rank_days(db: Session) -> list[tuple[Date, str]]:
    out = []
    for period in ("daily", "weekly"):
        d = db.scalar(select(func.max(Ranking.period_date)).where(Ranking.period == period))
        if d is not None:
            out.append((d, period))
    return out


@router.post("/items/bulk")
def bulk_items(body: ItemBulkIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """逐项返回 {id, label, ok, code, message}。code：ok / noop（已经是目标状态）/ queued（已排进后台任务，带 task_id）
    / not_found / bad_state / no_repo / locked_skipped / has_cover。按 filter 选择时后端重新统计，与 total 不一致返回 409 count_changed。"""
    reason = body.reason.strip()
    if body.action in NEED_REASON and len(reason) < 2:
        _err(400, "reason_required", "请填写原因")
    if body.ids is not None:
        ids = list(dict.fromkeys(body.ids))
    elif body.filter is not None:
        all_ids = list(db.scalars(items_stmt(db, body.filter).with_only_columns(Item.id).order_by(Item.id.desc())))
        if body.total is not None and len(all_ids) != body.total:
            _err(409, "count_changed", f"符合条件的条目数量已变化（现在 {len(all_ids)} 个，选择时 {body.total} 个），请重新确认")
        skip = set(body.exclude)
        ids = [i for i in all_ids if i not in skip]
    else:
        ids = []
    if not ids:
        _err(400, "empty_scope", "请先选择条目")
    limit = AI_BULK_MAX if body.action in ("reextract", "cover") else BULK_MAX
    if len(ids) > limit:
        _err(400, "too_many", f"一次最多操作 {limit} 个条目，请缩小范围")
    if body.action == "cover" and not settings.ai_enabled:
        _err(400, "ai_disabled", "还没有配置 AI 接口")
    cat = None
    if body.action == "set_category":
        cat = db.get(Category, body.params.category_id) if body.params.category_id else None
        if cat is None or cat.parent_id is None:
            _err(400, "bad_category", "请选择一个子分类")

    rows = {i.id: i for i in db.scalars(select(Item).options(joinedload(Item.repo), joinedload(Item.category))
                                        .where(Item.id.in_(ids))).unique()}
    results, changed, queue = [], [], []
    for iid in ids:
        it = rows.get(iid)
        if it is None:
            results.append({"id": iid, "label": f"条目 #{iid}", "ok": False, "code": "not_found", "message": "条目不存在"})
            continue
        r = {"id": iid, "label": it.name}
        a = body.action
        if a == "set_category":
            if it.category_id == cat.id:
                r.update(ok=True, code="noop", message=f"本来就在「{cat.name}」")
            else:
                before = {"category": it.category.name if it.category else ""}
                it.category_id = cat.id
                it.locked_fields = sorted(set(it.locked_fields or []) | {"category_id"})
                changed.append((it, before, {"category": cat.name}))
                r.update(ok=True, code="ok", message="")
        elif a in ("hide", "show"):
            src, dst = ("published", "hidden") if a == "hide" else ("hidden", "published")
            if it.status == dst:
                r.update(ok=True, code="noop", message=f"本来就是{ITEM_STATUS[dst]}")
            elif it.status != src:
                r.update(ok=False, code="bad_state", message=f"当前是「{ITEM_STATUS.get(it.status, it.status)}」，不能{ACTIONS[a]}")
            else:
                it.status = dst
                changed.append((it, {"status": src}, {"status": dst}))
                r.update(ok=True, code="ok", message="")
        elif a in ("rank_exclude", "rank_include"):
            want = a == "rank_exclude"
            if bool(it.rank_excluded) == want:
                r.update(ok=True, code="noop", message="本来就不在榜单里" if want else "本来就在参与排名")
            else:
                it.rank_excluded = want
                it.rank_exclude_reason, it.rank_excluded_at, it.rank_excluded_by = (reason, utcnow(), me.id) if want else ("", None, None)
                changed.append((it, {"rank_excluded": not want}, {"rank_excluded": want}))
                r.update(ok=True, code="ok", message="")
        elif a == "reextract":
            if it.repo is None:
                r.update(ok=False, code="no_repo", message="不是 GitHub 条目，无法重新提炼")
            else:
                it.ai_status = "pending"
                locked = [f for f in (it.locked_fields or []) if f in ingest.EDITABLE_FIELDS]
                queue.append(it.id)
                r.update(ok=True, code="queued", message=("人工修改过的字段会保留：" + "、".join(locked)) if locked else "",
                         locked_fields=locked)
        elif a == "cover":
            if "cover_path" in (it.locked_fields or []):
                r.update(ok=True, code="locked_skipped", message="封面是人工设置的，已跳过")
            elif it.cover_path:
                r.update(ok=True, code="has_cover", message="已有封面，跳过")
            else:
                queue.append(it.id)
                r.update(ok=True, code="queued", message="")
        results.append(r)
    db.commit()

    task_id = None
    if queue and body.action == "reextract":
        task_id = ingest.start_process_task("reextract", f"批量重新提炼 · {len(queue)} 个条目", queue, workers=2, force=True)
    elif queue and body.action == "cover":
        names = {i: rows[i].name for i in queue}
        task_id = tracking.create_task("cover", f"批量补封面 · {len(queue)} 个条目", [(i, names[i]) for i in queue])
        tracking.start_task(task_id, queue, lambda i, t: ingest.cover_for(i, t), workers=2)
    if task_id:
        for r in results:
            if r.get("code") == "queued":
                r["task_id"] = task_id
    if body.action in ("rank_exclude", "rank_include") and changed:
        for d, period in _latest_rank_days(db):
            rankings.compute_rankings(db, d, period)  # 当前榜单立即重算

    ip = client_ip(request)
    for it, before, after in changed:
        activity.record("item_bulk", f"批量{ACTIONS[body.action]}：{it.name}", user=me, target_type="item", target_id=it.id, ip=ip,
                        reason=reason, before=before, after=after, target_label=it.name, detail={"bulk": True, "action": body.action})
    if queue:
        activity.record("item_bulk", f"批量{ACTIONS[body.action]}：{len(queue)} 个条目", user=me, ip=ip, reason=reason,
                        detail={"bulk": True, "action": body.action, "ids": queue[:200], "task_id": task_id})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok, "task_id": task_id}


CHANGE_ACTIONS = ("item_edit", "item_bulk", "item_pin", "item_delete", "review", "item_submit")


@router.get("/items/{item_id}/changes")
def item_changes(item_id: int, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    stmt = select(ActivityLog).where(ActivityLog.target_type == "item", ActivityLog.target_id == item_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(ActivityLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id} or {-1})))}
    out = []
    for r in rows:
        keys = list(dict.fromkeys(list((r.before or {}).keys()) + list((r.after or {}).keys())))
        out.append({"id": r.id, "action": r.action, "action_label": activity.ACTIONS.get(r.action, r.action), "summary": r.summary,
                    "by": {"id": r.user_id, "label": users.label(who[r.user_id])} if r.user_id in who else None,
                    "actor": r.actor, "at": r.created_at, "reason": r.reason or "",
                    "changes": [{"field": k, "label": activity.FIELD_LABELS.get(k, k), "before": (r.before or {}).get(k),
                                 "after": (r.after or {}).get(k)} for k in keys]})
    return {"total": total, "page": page, "page_size": page_size, "items": out}
