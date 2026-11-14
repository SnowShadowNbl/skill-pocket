"""存量条目重新分类：领域分类换版本后，由 AI 重新判定「领域分类 + 使用类型」。

不重新读文档、不重写介绍，只用已有的名称、简介、介绍和 topics 判断，每 12 个条目合并成一次 AI 调用。
人工锁定过的字段：分类仍可用就保留；所在分类已停用的照样重判。
"""

import threading

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Category, Item, Ranking
from ..seed import FALLBACK_CODE
from . import judge, tracking
from .ingest import category_choices
from .rankings import compute_rankings

BATCH = 12
LOW_CONFIDENCE = 0.5


def _brief(it: Item) -> dict:
    return {
        "id": it.id, "name": it.name,
        "repo": (it.repo.full_name + (f"/{it.sub_path}" if it.sub_path else "")) if it.repo else (it.homepage_url or ""),
        "type": "Agent Skill（SKILL.md）" if it.sub_path else "仓库 / 资源",
        "summary": it.summary[:200], "description": it.description[:500],
        "topics": (it.repo.topics or [])[:10] if it.repo else [],
    }


def start(only_missing: bool = False, retry: bool = True) -> int | None:
    """后台重新分类全部条目（only_missing：只处理还没有使用类型、或挂在停用分类上的）。"""
    with SessionLocal() as db:
        q = select(Item).where(Item.status.in_(("published", "hidden", "pending_review"))).order_by(Item.id)
        items = db.scalars(q).all()
        if only_missing:
            disabled = set(db.scalars(select(Category.id).where(Category.enabled.is_(False))).all())
            items = [i for i in items if not i.kind or i.category_id in disabled]
        rows = [(i.id, i.name) for i in items]
    if not rows:
        return None
    ids = [i for i, _ in rows]
    task_id = tracking.create_task("reclassify", f"AI 重新分类 · {len(rows)} 个条目", rows)
    verdicts: dict[int, dict | None] = {}

    def one(item_id: int, tid: int) -> tuple[bool, str]:
        if item_id not in verdicts:
            # 从当前条目起取一批，一次调用判定
            pos = ids.index(item_id)
            chunk = ids[pos:pos + BATCH]
            with SessionLocal() as db:
                briefs = [_brief(it) for it in db.scalars(select(Item).where(Item.id.in_(chunk)))]
                choices = category_choices(db)
            try:
                got = judge.classify_items(briefs, choices)
            except judge.JudgeUnavailable as e:
                got = {}
                for i in chunk:
                    verdicts[i] = None
                tracking.log(trigger="reclassify", stage="classify", level="error", message=f"AI 重新分类失败：{e}", task_id=tid)
            for i in chunk:
                verdicts.setdefault(i, got.get(i))
        return _apply(item_id, verdicts.get(item_id), tid)

    def run():
        tracking.run_task(task_id, ids, one, workers=1)
        # AI 偶尔漏判个别条目：对还没判定的再跑一轮（只重试一次），结束后重算榜单
        if not (retry and start(only_missing=True, retry=False)):
            recompute_latest_rankings()

    threading.Thread(target=run, daemon=True, name=f"reclassify-{task_id}").start()
    return task_id


def recompute_latest_rankings() -> None:
    """分类变了之后，最近一期日榜 / 周榜按新分类重算（更早的榜单保留当时的分类）。"""
    with SessionLocal() as db:
        for period in ("daily", "weekly"):
            day = db.scalar(select(Ranking.period_date).where(Ranking.period == period).order_by(Ranking.period_date.desc()).limit(1))
            if day is not None:
                compute_rankings(db, day, period)


def _apply(item_id: int, v: dict | None, task_id: int) -> tuple[bool, str]:
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None:
            return False, "条目不存在"
        if not v:
            return False, "AI 没有给出这个条目的分类"
        tr = tracking.ItemTracker(item, "reclassify", task_id)
        tr.stage("classify")
        locked = set(item.locked_fields or [])
        cur = db.get(Category, item.category_id)
        keep_cat = "category_id" in locked and cur is not None and cur.enabled and (cur.parent is None or cur.parent.enabled)
        cat = None
        if not keep_cat:
            code = v["category_code"] or FALLBACK_CODE
            cat = db.scalar(select(Category).where(Category.code == code))
            if cat is not None:
                item.category_id, item.ai_confidence = cat.id, v["confidence"]
        if "kind" not in locked and v["kind"]:
            item.kind, item.kind_confidence = v["kind"], v["kind_confidence"]
        db.commit()
        cat = cat or cur
        msg = f"分类：{cat.parent.name + ' › ' if cat and cat.parent else ''}{cat.name if cat else '-'} · 使用类型：{item.kind or '未判定'}"
        if min(v["confidence"], v["kind_confidence"]) < LOW_CONFIDENCE:
            tr.warn(f"AI 把握较低（分类 {v['confidence']:.0%} / 类型 {v['kind_confidence']:.0%}），建议人工核对", "classify")
        tr.success(msg)
        return True, msg
