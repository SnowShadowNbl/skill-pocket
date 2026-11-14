"""批次任务进度与入库日志查询。"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..auth import current_user, current_user_optional
from ..db import get_db, utcnow
from ..models import IngestLog, Task, TaskItem, User
from ..services.tracking import STAGES, TRIGGERS

router = APIRouter(prefix="/api", tags=["tasks"])


def _task_out(t: Task, items: list[TaskItem] | None = None) -> dict:
    out = {
        "id": t.id, "kind": t.kind, "kind_label": TRIGGERS.get(t.kind, t.kind), "title": t.title, "source": t.source,
        "total": t.total, "done": t.done, "failed": t.failed, "status": t.status,
        "created_at": t.created_at, "finished_at": t.finished_at,
    }
    if items is not None:
        out["items"] = [{
            "seq": i.seq, "item_id": i.item_id, "name": i.name, "status": i.status, "stage": i.stage,
            "stage_label": STAGES.get(i.stage, i.stage), "message": i.message,
            "started_at": i.started_at, "finished_at": i.finished_at,
        } for i in items]
    return out


def _items(db: Session, task_id: int) -> list[TaskItem]:
    return db.scalars(select(TaskItem).where(TaskItem.task_id == task_id).order_by(TaskItem.seq)).all()


@router.get("/tasks/active")
def active_tasks(db: Session = Depends(get_db), me: User | None = Depends(current_user_optional)):
    """进度浮窗用：运行中的任务 + 2 分钟内刚结束的任务（让用户看到结果）。用户只看自己的，管理员看全部。"""
    if me is None:
        return []
    since = utcnow() - timedelta(minutes=2)
    stmt = select(Task).where(or_(Task.status == "running", Task.finished_at >= since))
    if not auth.is_admin(me):
        stmt = stmt.where(Task.user_id == me.id)
    tasks = db.scalars(stmt.order_by(Task.created_at.desc()).limit(6)).all()
    return [_task_out(t, _window(_items(db, t.id))) for t in tasks]


def _window(items: list[TaskItem], size: int = 12) -> list[TaskItem]:
    """大批量任务（几百个条目）只返回正在处理的附近一段 + 失败的，浮窗每 2 秒刷新也不卡。"""
    if len(items) <= size:
        return items
    cur = next((k for k, i in enumerate(items) if i.status in ("running", "pending")), len(items) - 1)
    start = max(0, min(cur - 4, len(items) - size))
    near = items[start:start + size]
    failed = [i for i in items if i.status == "failed" and i not in near][-5:]
    return sorted(near + failed, key=lambda i: i.seq)


@router.get("/tasks")
def list_tasks(page: int = Query(1, ge=1), size: int = Query(20, le=100), source: str = "", db: Session = Depends(get_db),
               me: User = Depends(current_user)):
    stmt = select(Task) if auth.is_admin(me) else select(Task).where(Task.user_id == me.id)
    if source in ("auto", "manual"):
        stmt = stmt.where(Task.source == source)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Task.created_at.desc()).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": [_task_out(t) for t in rows]}


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    t = db.get(Task, task_id)
    if t is None or (not auth.is_admin(me) and t.user_id != me.id):
        raise HTTPException(404, "任务不存在")
    return _task_out(t, _items(db, t.id))


@router.get("/logs")
def list_logs(
    source: str = Query("", pattern="^(|auto|manual)$"),
    level: str = Query("", pattern="^(|info|success|warn|error|problem)$"),
    stage: str = "",
    trigger: str = "",
    task_id: int | None = None,
    item_id: int | None = None,
    q: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(30, le=100),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """入库日志：v3.2 起只对管理员开放（普通用户在网页和小程序里都不显示这个入口）。"""
    if not auth.is_admin(me):
        raise HTTPException(403, "入库日志只有管理员可以查看")
    conds = []
    if source:
        conds.append(IngestLog.source == source)
    if level == "problem":  # 警告 + 失败
        conds.append(IngestLog.level.in_(("warn", "error")))
    elif level:
        conds.append(IngestLog.level == level)
    if stage:
        conds.append(IngestLog.stage == stage)
    if trigger:
        conds.append(IngestLog.trigger == trigger)
    if task_id:
        conds.append(IngestLog.task_id == task_id)
    if item_id:
        conds.append(IngestLog.item_id == item_id)
    for word in q.split():
        like = f"%{word}%"
        conds.append(or_(IngestLog.item_name.ilike(like), IngestLog.repo.ilike(like), IngestLog.message.ilike(like)))

    base = select(IngestLog).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(IngestLog.created_at.desc(), IngestLog.id.desc()).offset((page - 1) * size).limit(size)).all()

    # 近 7 天各级别数量（不受级别筛选影响，用于顶部统计）
    since = utcnow() - timedelta(days=7)
    stat_conds = conds if not level else ([] if auth.is_admin(me) else [IngestLog.user_id == me.id])
    counts = dict(db.execute(
        select(IngestLog.level, func.count()).where(IngestLog.created_at >= since, *stat_conds).group_by(IngestLog.level)
    ).all())

    return {
        "total": total,
        "counts_7d": {k: counts.get(k, 0) for k in ("success", "warn", "error", "info")},
        "stages": STAGES,
        "triggers": TRIGGERS,
        "items": [{
            "id": r.id, "task_id": r.task_id, "item_id": r.item_id, "item_name": r.item_name, "repo": r.repo,
            "source": r.source, "trigger": r.trigger, "trigger_label": TRIGGERS.get(r.trigger, r.trigger),
            "stage": r.stage, "stage_label": STAGES.get(r.stage, r.stage), "level": r.level,
            "message": r.message, "duration_ms": r.duration_ms, "created_at": r.created_at,
        } for r in rows],
    }
