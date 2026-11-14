from datetime import date

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..auth import current_user_optional, require_admin
from ..models import User
from ..config import settings
from ..db import get_db
from ..models import Category, Item, JobRun, Ranking, RankingEntry
from ..schemas import category_brief, item_card
from ..seed import KINDS
from ..services import blurbs, reclassify
from ..services.extract import model_label
from .favorites import fav_ids
from ..services import crawler, ingest, scheduler, tracking
from ..services.github import rate_state

router = APIRouter(prefix="/api", tags=["crawl"])


# ---- 榜单 ----

@router.get("/rankings")
def rankings(
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    day: date | None = Query(None, alias="date"),
    group: str = "",
    kind: str = "",
    db: Session = Depends(get_db),
    me: User | None = Depends(current_user_optional),
):
    dates = db.scalars(
        select(Ranking.period_date).where(Ranking.period == period).distinct().order_by(Ranking.period_date.desc()).limit(30)
    ).all()
    day = day or (dates[0] if dates else None)
    if day is None:
        return {"period": period, "date": None, "dates": [], "boards": []}

    rows = db.scalars(
        select(Ranking).options(joinedload(Ranking.category).joinedload(Category.parent))
        .where(Ranking.period == period, Ranking.period_date == day)
    ).unique().all()
    if group:
        rows = [r for r in rows if r.category.code == group or (r.category.parent and r.category.parent.code == group)]
    rows.sort(key=lambda r: ((r.category.parent or r.category).sort, r.category.sort))

    boards = []
    favs = fav_ids(db, me.id if me else None)
    for r in rows:
        entries = db.execute(
            select(RankingEntry, Item).join(Item, Item.id == RankingEntry.item_id)
            .options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
            .where(RankingEntry.ranking_id == r.id, Item.status == "published").order_by(RankingEntry.rank)
        ).unique().all()
        if kind:
            entries = [(e, it) for e, it in entries if it.kind == kind]
            if not entries:
                continue
        boards.append({
            "category": category_brief(r.category),
            "entries": [{"rank": e.rank, "stars_delta": e.stars_delta, "stars_end": e.stars_end,
                         "item": {**item_card(it, favs), "rank_blurb": it.rank_blurb,
                                  "rank_blurb_model": model_label(it.rank_blurb_model) if it.rank_blurb_model else None}}
                        for e, it in entries],
        })
    return {"period": period, "date": day, "dates": dates, "boards": boards}


@router.get("/rankings/trends")
def ranking_trends(db: Session = Depends(get_db)):
    """v3.3 分类热度趋势（大类近 7 天星标增量与再前 7 天对比），缓存 10 分钟。"""
    import time

    from ..services.rankings import group_trends

    global _trend_cache
    if time.time() - _trend_cache[0] > 600:
        _trend_cache = (time.time(), group_trends(db))
    return _trend_cache[1]


_trend_cache: tuple[float, list] = (0.0, [])


# ---- 待确认队列 ----

@router.get("/review", dependencies=[Depends(require_admin)])
def review_queue(db: Session = Depends(get_db)):
    items = db.scalars(
        select(Item).options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
        .where(Item.status == "pending_review").order_by(Item.collected_at.desc())
    ).unique().all()
    return [{
        **item_card(it),
        "review_note": it.review_note,
        "github_url": it.repo.html_url if it.repo else None,
        "topics": it.repo.topics if it.repo else [],
        "language": it.repo.language if it.repo else "",
    } for it in items]


@router.post("/review/{item_id}/approve", dependencies=[Depends(require_admin)])
def approve(item_id: int, tasks: BackgroundTasks, category_id: int | None = Body(None, embed=True),
            db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None or item.status != "pending_review":
        raise HTTPException(404, "待确认条目不存在")
    if category_id is not None:
        cat = db.get(Category, category_id)
        if cat is None or cat.parent_id is None:
            raise HTTPException(400, "请选择一个子分类")
        item.category_id = category_id
        item.locked_fields = ["category_id"]
    item.status, item.ai_status = "published", "pending"
    db.commit()
    task_id = ingest.start_process_task("review", f"确认收录 · {item.name}", [item_id])
    return {"ok": True, "task_id": task_id}


@router.post("/review/{item_id}/reject", dependencies=[Depends(require_admin)])
def reject(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None or item.status != "pending_review":
        raise HTTPException(404, "待确认条目不存在")
    if item.repo:
        item.repo.repo_status = "ignored"  # 以后采集不再判定这个仓库
    tracking.log(trigger="review", stage="discover", level="info", message="人工确认为不相关，已忽略",
                 item_name=item.name, repo=item.repo.full_name if item.repo else "")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ---- 采集任务 ----

@router.get("/jobs", dependencies=[Depends(require_admin)])
def jobs(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    runs = db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)).all()
    nxt = scheduler.next_run_time()
    return {
        "running": crawler.is_running(),
        "enabled": settings.crawl_enabled,
        "window": {"start": settings.crawl_start, "end": settings.crawl_end, "tz": settings.crawl_tz},
        "next_run": nxt.isoformat() if nxt else None,
        "github_token": bool(settings.github_token),
        "rate": rate_state,
        **crawler.pending_counts(db),
        "runs": [{"id": r.id, "job_name": r.job_name, "status": r.status, "started_at": r.started_at,
                  "finished_at": r.finished_at, "stats": r.stats, "error": r.error} for r in runs],
    }


@router.post("/jobs/crawl", dependencies=[Depends(require_admin)])
def trigger_crawl():
    if not crawler.start_in_background("manual"):
        raise HTTPException(409, "已有采集任务在运行")
    return {"ok": True}


# ---- v1.3：重新分类、榜单详解 ----

@router.post("/reclassify", dependencies=[Depends(require_admin)])
def start_reclassify(only_missing: bool = Body(False, embed=True)):
    """AI 重新判定领域分类和使用类型（不重写介绍）。"""
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口")
    task_id = reclassify.start(only_missing=only_missing)
    return {"task_id": task_id, "queued": task_id is not None}


@router.post("/rankings/blurbs", dependencies=[Depends(require_admin)])
def refresh_blurbs(force: bool = Body(False, embed=True)):
    """给当前在榜条目补齐中文详解（force 时全部重新生成）。"""
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口")
    task_id = blurbs.start_refresh_all(force=force)
    return {"task_id": task_id, "queued": task_id is not None}


@router.post("/items/{item_id}/blurb", dependencies=[Depends(require_admin)])
def regenerate_blurb(item_id: int):
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口")
    from ..services.github import GitHub
    with GitHub() as gh:
        ok, msg = blurbs.generate(item_id, gh, force=True)
    if not ok:
        raise HTTPException(502, msg)
    return {"ok": True, "message": msg}
