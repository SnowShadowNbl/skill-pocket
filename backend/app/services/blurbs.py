"""榜单中文详解：只给上榜条目生成，结果存在条目上反复使用。

- 每晚算完榜单后，给「今天在榜、还没有详解」的条目生成
- 已有详解的条目每 7 天抽查一次文档：和生成时的依据相比变化超过 30%（README 大改）才重新生成
- 人工编辑过的详解（locked_fields 含 rank_blurb）不再自动覆盖
"""

import difflib
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import Item, Ranking, RankingEntry
from . import judge, tracking
from .github import BudgetExhausted, GitHub, GitHubError
from .ingest import fetch_doc

BASIS_CHARS = 6000
RECHECK_DAYS = 7
# 文档相似度低于这个值视为「大改」
MAJOR_CHANGE_RATIO = 0.7


def doc_basis(text: str) -> str:
    """归一化文档开头：去掉徽章、图片、链接地址和多余空白，只比较实质内容。"""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", text)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.I)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()[:BASIS_CHARS]


def changed_a_lot(old: str, new: str) -> bool:
    if not old:
        return True
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    # quick_ratio 是上界：上界都超过阈值时再算精确值
    return sm.quick_ratio() < MAJOR_CHANGE_RATIO or sm.ratio() < MAJOR_CHANGE_RATIO


def board_item_ids(db: Session) -> list[int]:
    """最近一期日榜和周榜上的全部条目。"""
    ids: list[int] = []
    for period in ("daily", "weekly"):
        day = db.scalar(select(Ranking.period_date).where(Ranking.period == period).order_by(Ranking.period_date.desc()).limit(1))
        if day is None:
            continue
        ids += db.scalars(select(RankingEntry.item_id).join(Ranking, Ranking.id == RankingEntry.ranking_id)
                          .where(Ranking.period == period, Ranking.period_date == day)).all()
    return list(dict.fromkeys(ids))


def generate(item_id: int, gh: GitHub, force: bool = False, task_id: int | None = None) -> tuple[bool, str]:
    """给一个条目生成 / 检查详解。返回 (是否成功, 结果说明)。"""
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None or item.repo is None:
            return False, "条目不存在或没有关联仓库"
        if "rank_blurb" in (item.locked_fields or []) and item.rank_blurb and not force:
            return True, "人工编辑过，跳过"
        now = utcnow()
        if item.rank_blurb and not force and item.rank_blurb_checked_at and now - item.rank_blurb_checked_at < timedelta(days=RECHECK_DAYS):
            return True, "近期已检查，跳过"

        tr = tracking.ItemTracker(item, "blurb", task_id)
        tr.stage("doc")
        try:
            _, _, text, _, _ = fetch_doc(gh, item.repo, item.sub_path)
        except BudgetExhausted:
            raise
        except GitHubError as e:
            tr.error(f"读取文档失败：{e}", "doc")
            return False, f"读取文档失败：{e}"
        basis = doc_basis(text)
        item.rank_blurb_checked_at = now
        if item.rank_blurb and not force and not changed_a_lot(item.rank_blurb_basis, basis):
            db.commit()
            return True, "文档没有大改，沿用原详解"

        tr.stage("blurb")
        try:
            blurb = judge.write_blurb(item.name, item.repo.full_name, item.summary, item.description, basis)
        except judge.JudgeUnavailable as e:
            db.commit()
            tr.error(f"生成详解失败：{e}", "blurb")
            return False, f"生成详解失败：{e}"
        reason = "首次生成" if not item.rank_blurb else ("手动重新生成" if force else "README 大改，重新生成")
        item.rank_blurb, item.rank_blurb_basis, item.rank_blurb_at = blurb, basis, now
        item.rank_blurb_model = settings.ai_text_model
        if force:
            item.locked_fields = [f for f in item.locked_fields or [] if f != "rank_blurb"]
        db.commit()
        tr.success(f"榜单详解：{reason}")
        return True, reason


def refresh(db: Session, gh: GitHub, stats: dict) -> None:
    """采集流水线里的一个阶段：处理当前在榜的条目。"""
    if not settings.ai_enabled:
        return
    ids = board_item_ids(db)
    now = utcnow()
    rows = db.execute(select(Item.id, Item.name, Item.rank_blurb, Item.rank_blurb_checked_at).where(Item.id.in_(ids))).all() if ids else []
    todo = [(i, n) for i, n, b, chk in rows if not b or chk is None or now - chk >= timedelta(days=RECHECK_DAYS)]
    stats["blurb_total"] = len(todo)
    if not todo:
        return
    task_id = tracking.create_task("blurb", f"榜单中文详解 · {len(todo)} 个条目", todo)
    tracking.run_task(task_id, [i for i, _ in todo], lambda i, t: generate(i, gh, task_id=t), workers=1,
                      stop_on=(BudgetExhausted,))


def start_refresh_all(force: bool = False) -> int | None:
    """管理员手动触发：给当前在榜条目补齐详解（后台任务）。"""
    with SessionLocal() as db:
        ids = board_item_ids(db)
        q = select(Item.id, Item.name).where(Item.id.in_(ids)) if ids else None
        rows = db.execute(q).all() if q is not None else []
        if not force:
            rows = [(i, n) for i, n in rows if not db.get(Item, i).rank_blurb]
    if not rows:
        return None
    task_id = tracking.create_task("blurb", f"榜单中文详解 · {len(rows)} 个条目", [(i, n) for i, n in rows])

    def one(item_id: int, tid: int):
        with GitHub() as gh:
            return generate(item_id, gh, force=force, task_id=tid)

    tracking.start_task(task_id, [i for i, _ in rows], one, workers=3)
    return task_id
