"""管理员接口：实时动态、操作日志、用户提交审核（待审核 / 上线日志 / 审核设置）、用户反馈、失效巡检、语义搜索补齐。

P4 管理端上线后这些接口原样复用。
"""

import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..auth import current_user, require_admin
from ..db import get_db, utcnow
from ..models import ActivityLog, AppMeta, Category, Comment, Feedback, Item, ItemReview, LivenessRun, TakedownRequest, User
from ..schemas import item_card
from ..services import activity, geo, liveness, resources, review, search
from ..services.users import label as user_label
from .feedback import CATEGORIES, MAX_IMAGES, STATUSES, feedback_out, save_images

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

USER_SIDE = ("user", "guest", "system")


def _users(db: Session, ids) -> dict[int, User]:
    ids = {i for i in ids if i}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _parse_day(v: str) -> datetime | None:
    """'2026-11-12'（北京时间的这一天 0 点）→ 带时区的时间；格式不对返回 None。"""
    try:
        return datetime.combine(date.fromisoformat((v or "").strip()), datetime.min.time(), tzinfo=ZoneInfo("Asia/Shanghai"))
    except ValueError:
        return None


def _log_out(r: ActivityLog, users: dict, targets: dict | None = None) -> dict:
    u = users.get(r.user_id)
    t = (targets or {}).get(r.target_id) if r.target_type == "user" else None
    keys = set((r.before or {}).keys()) | set((r.after or {}).keys())
    return {"id": r.id, "actor": r.actor, "action": r.action, "action_label": activity.ACTIONS.get(r.action, r.action),
            "target_type": r.target_type, "target_id": r.target_id, "summary": r.summary, "detail": r.detail or {},
            "ip": r.ip, "geo": geo.lookup(r.ip), "created_at": r.created_at,
            # v3.3.37 管理操作留痕：老日志没有这些字段，为空 / null
            # 老日志没存对象称呼：按对象用户补上
            "target_label": r.target_label or (user_label(t) if t else ""),
            "reason": r.reason or "", "before": r.before, "after": r.after,
            "fields": {k: activity.FIELD_LABELS.get(k, k) for k in keys}, "result": r.result or "ok", "message": r.message or "",
            "user": {"id": u.id, "nickname": u.nickname, "email": u.email or u.username, "avatar": u.avatar,
                     "label": user_label(u)} if u else None}


# ---------------------------------------------------------------- 实时动态

def _seen_id(db: Session) -> int:
    m = db.get(AppMeta, "admin_feed_seen")
    return int(m.value) if m and m.value.isdigit() else 0


@router.get("/feed")
def feed(after: int = 0, limit: int = Query(40, le=100), db: Session = Depends(get_db)):
    """用户侧动态（用户 / 访客操作 + 系统审核结果），按时间倒序；after 只取更新的。"""
    q = select(ActivityLog).where(ActivityLog.actor.in_(USER_SIDE))
    if after:
        q = q.where(ActivityLog.id > after)
    rows = db.scalars(q.order_by(ActivityLog.id.desc()).limit(limit)).all()
    users = _users(db, [r.user_id for r in rows])
    seen = _seen_id(db)
    return {"items": [{**_log_out(r, users), "unseen": r.id > seen} for r in rows], "seen_id": seen}


def _open_alerts(db) -> dict:
    from ..models import Alert
    from ..services import ops

    try:
        ops.sync()
        from .risk_admin import scan

        scan()  # v3.3.68 风控告警（最多 10 分钟扫一次）
    except Exception:  # noqa: BLE001  同步失败不影响角标
        pass
    return {"open": db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open")) or 0,
            "critical": db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open", Alert.level == "critical")) or 0}


def _ingest_counts(db) -> dict:
    from .ingest_monitor import summary_counts

    try:
        return summary_counts(db)
    except Exception:  # noqa: BLE001  概览角标不能因为统计出错而整体失败
        return {"ingest_stuck": None, "ingest_failed": None}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """导航红点与各标签角标。"""
    seen = _seen_id(db)
    return {
        "feed_unseen": db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.actor.in_(USER_SIDE), ActivityLog.id > seen)),
        "pending_reviews": db.scalar(select(func.count()).select_from(Item).where(Item.status == "awaiting", Item.review_state == "admin")),
        "reviewing": db.scalar(select(func.count()).select_from(Item).where(Item.status == "awaiting")),
        "feedback_new": db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == "new")),
        "feedback_urgent": db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status.in_(("new", "processing")),
                                                                                      Feedback.priority.in_(("P0", "P1")))),
        "pending_crawl": db.scalar(select(func.count()).select_from(Item).where(Item.status == "pending_review")),
        "pending_comments": db.scalar(select(func.count()).select_from(Comment).where(Comment.status == "pending")),
        # v3.3.44 统一待处理：还没有的类型给 null（前端显示「—」）
        "pending": {
            "items": db.scalar(select(func.count()).select_from(Item).where(Item.status == "awaiting", Item.review_state == "admin")),
            "comments": db.scalar(select(func.count()).select_from(Comment).where(Comment.status == "pending")),
            "feedback": db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == "new")),
            "crawl": db.scalar(select(func.count()).select_from(Item).where(Item.status == "pending_review")),
            "takedowns": db.scalar(select(func.count()).select_from(TakedownRequest).where(TakedownRequest.status == "pending")),
            **_ingest_counts(db),
            "alerts": _open_alerts(db),
            "reports": None,
            "shares_reported": None,
        },
        # 资源提醒（余额不足、磁盘 / 内存快满）：只用缓存的余额，不在这里发外部请求
        # v3.3.64 资源提醒并入告警表：角标 = 未处理告警数
        "resource_alerts": _open_alerts(db)["open"],
    }


@router.post("/feed/seen")
def feed_seen(last_id: int = Body(..., embed=True), db: Session = Depends(get_db)):
    if last_id > _seen_id(db):
        db.merge(AppMeta(key="admin_feed_seen", value=str(last_id)))
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 操作日志

@router.get("/activity")
def activity_logs(
    actor: str = "", action: str = "", user_id: int | None = None, q: str = "",
    result: str = "", target_user_id: int | None = None, created_from: str = "", created_to: str = "",
    target_type: str = "", target_id: int | None = None,
    page: int = Query(1, ge=1), size: int = Query(40, le=100), page_size: int | None = Query(None, le=100),
    db: Session = Depends(get_db),
):
    size = page_size or size
    conds = []
    if result in ("ok", "failed"):
        conds.append(ActivityLog.result == result)
    if target_user_id:
        conds += [ActivityLog.target_type == "user", ActivityLog.target_id == target_user_id]
    if target_type:
        conds.append(ActivityLog.target_type == target_type)
    if target_id is not None:
        conds.append(ActivityLog.target_id == target_id)
    for val, op in ((created_from, ">="), (created_to, "<")):
        d = _parse_day(val)
        if d is not None:
            conds.append(ActivityLog.created_at >= d if op == ">=" else ActivityLog.created_at < d + timedelta(days=1))
    if actor:
        conds.append(ActivityLog.actor == actor)
    if action:
        conds.append(ActivityLog.action == action)
    if user_id:
        conds.append(ActivityLog.user_id == user_id)
    for w in q.split():
        conds.append(ActivityLog.summary.ilike(f"%{w}%"))
    base = select(ActivityLog).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(ActivityLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    users = _users(db, [r.user_id for r in rows])
    targets = _users(db, [r.target_id for r in rows if r.target_type == "user" and not r.target_label and r.target_id])
    return {"total": total, "actions": activity.ACTIONS, "items": [_log_out(r, users, targets) for r in rows]}


# ---------------------------------------------------------------- 审核

@router.get("/reviews/pending")
def pending_reviews(db: Session = Depends(get_db)):
    """审核中的用户提交：review_state=admin 的待管理员审核，ai 的正在由系统处理。"""
    items = db.scalars(select(Item).options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent),
                                            joinedload(Item.creator))
                       .where(Item.status == "awaiting").order_by(Item.collected_at.desc())).unique().all()
    last = {}
    for r in db.scalars(select(ItemReview).where(ItemReview.item_id.in_([i.id for i in items])).order_by(ItemReview.id)):
        last[r.item_id] = r
    out = []
    for it in items:
        r = last.get(it.id)
        out.append({**item_card(it), "review_state": it.review_state, "ai_status": it.ai_status,
                    "submitter": {"id": it.creator.id, "nickname": it.creator.nickname, "email": it.creator.email} if it.creator else None,
                    "github_url": it.repo.html_url if it.repo else it.homepage_url,
                    "ai_opinion": {"decision": r.decision, "confidence": r.confidence, "reason": r.reason} if r else None})
    return out


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|revoke|restore)$")
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


@router.post("/items/{item_id}/review")
def decide(item_id: int, body: DecisionIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "条目不存在")
    allowed = {"approve": ("awaiting", "declined"), "reject": ("awaiting",), "revoke": ("published",),
               "restore": ("offline", "declined", "hidden")}[body.decision]
    if (body.expected_status and body.expected_status != item.status) or item.status not in allowed:
        # v3.3.44 并发保护：别人已经处理过（或状态已变）
        last = db.scalar(select(ItemReview).where(ItemReview.item_id == item.id).order_by(ItemReview.id.desc()))
        who = None
        if last is not None and last.reviewer_id:
            u = db.get(User, last.reviewer_id)
            who = {"id": last.reviewer_id, "label": user_label(u) if u else f"用户 #{last.reviewer_id}"}
        raise HTTPException(409, jsonable_encoder({"code": "already_handled", "message": f"已被{who['label'] if who else '其他人'}处理（当前：{item.status}）",
                                  "handled_by": who, "handled_at": last.created_at if last else None, "status": item.status}))
    if body.decision in ("reject", "revoke") and not body.reason.strip():
        raise HTTPException(400, "请填写理由，会展示给提交者")
    review.admin_decide(db, item, me, body.decision, body.reason.strip())
    if body.decision in ("approve", "restore"):
        threading.Thread(target=search.embed_items, args=([item.id],), daemon=True).start()
    return {"ok": True, "status": item.status}


@router.get("/reviews/log")
def review_log(reviewer: str = "", decision: str = "", page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    """上线日志。"""
    conds = []
    if reviewer:
        conds.append(ItemReview.reviewer == reviewer)
    if decision:
        conds.append(ItemReview.decision == decision)
    base = select(ItemReview).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(ItemReview.id.desc()).offset((page - 1) * 40).limit(40)).all()
    users = _users(db, [r.submitter_id for r in rows] + [r.reviewer_id for r in rows])
    status = dict(db.execute(select(Item.id, Item.status).where(Item.id.in_([r.item_id for r in rows if r.item_id]))).all())
    return {"total": total, "items": [{
        "id": r.id, "item_id": r.item_id, "item_name": r.item_name, "item_status": status.get(r.item_id),
        "reviewer": r.reviewer, "decision": r.decision, "confidence": r.confidence, "reason": r.reason, "mode": r.mode,
        "created_at": r.created_at,
        "submitter": (lambda u: {"nickname": u.nickname, "email": u.email} if u else None)(users.get(r.submitter_id)),
        "admin": (lambda u: u.nickname if u else None)(users.get(r.reviewer_id)),
    } for r in rows]}


@router.get("/reviews/settings")
def get_review_settings(db: Session = Depends(get_db)):
    return {**review.get_settings(db), "modes": review.MODES}


class ReviewSettingsIn(BaseModel):
    mode: str = Field(pattern="^(max|medium|off)$")
    threshold: float = Field(0.8, ge=0.5, le=0.99)


@router.put("/reviews/settings")
def put_review_settings(body: ReviewSettingsIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    out = review.set_settings(db, body.mode, body.threshold)
    activity.record("review_settings", f"AI 审核权限改为「{out['mode_label']}」，把握阈值 {out['threshold']:.0%}", user=me)
    return out


# ---------------------------------------------------------------- 用户反馈

# v3.3.52 反馈工单接口移到 routers/feedback_admin.py（负责人、备注、流转、统计、批量、模板）


# ---------------------------------------------------------------- 失效巡检 / 语义搜索

@router.get("/liveness")
def liveness_runs(db: Session = Depends(get_db)):
    runs = db.scalars(select(LivenessRun).order_by(LivenessRun.id.desc()).limit(20)).all()
    offline = db.scalars(select(Item).options(joinedload(Item.repo)).where(Item.status == "offline")
                         .order_by(Item.offline_at.desc()).limit(100)).unique().all()
    return {
        "runs": [{"id": r.id, "started_at": r.started_at, "finished_at": r.finished_at, "status": r.status, "checked": r.checked,
                  "went_offline": r.went_offline, "restored": r.restored, "errors": r.errors,
                  "changes": (r.detail or {}).get("changes", [])[:50]} for r in runs],
        "offline": [{"id": i.id, "name": i.name, "repo": i.repo.full_name if i.repo else "", "offline_at": i.offline_at,
                     "offline_reason": i.offline_reason} for i in offline],
    }


@router.post("/liveness/run")
def run_liveness(me: User = Depends(current_user)):
    threading.Thread(target=liveness.run, args=("manual",), daemon=True, name="liveness").start()
    activity.record("liveness", "手动触发失效巡检", user=me)
    return {"ok": True}


@router.post("/search/backfill")
def search_backfill():
    if not search.enabled():
        raise HTTPException(400, "还没有配置 Embedding 接口（EMBEDDING_API_KEY）")
    return {"task_id": search.start_backfill()}


# ---------------------------------------------------------------- v3.3 评论审核

# v3.3.44 评论审核接口移到 routers/moderation.py（增加驳回 / 删除 / 恢复、处置历史、并发保护）
