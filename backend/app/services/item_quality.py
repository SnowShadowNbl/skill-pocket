"""v3.3.46 后台批次 3a：条目质量问题的口径（筛选条件 + 单条标记）与「疑似刷星」检测。

口径：
- no_cover 无封面：cover_path 为空（占位图）
- no_summary 无简介：summary 为空
- no_install 无安装说明：install_steps 为空
- source_broken 来源失效：status=offline（失效巡检判定原地址不可访问）
- zero_fav 零收藏：没有任何人收藏
- low_star 低星：GitHub 星标少于阈值（默认 10；非 GitHub 条目不算）
- star_spike 疑似刷星：近 7 天星标增长 ≥ 200 且 ≥ 7 天前星标的 60%
- rank_excluded 已排除出榜单
"""

import time
from datetime import timedelta

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..models import Favorite, Item, Repo, StarSnapshot

QUALITY = {
    "no_cover": "无封面", "no_summary": "无简介", "no_install": "无安装说明", "source_broken": "来源失效",
    "zero_fav": "零收藏", "low_star": "低星", "star_spike": "疑似刷星", "rank_excluded": "已排除出榜单",
}
LOW_STAR = 10
SPIKE_MIN = 200
SPIKE_RATIO = 0.6
_spike_cache: tuple[float, set[int]] = (0.0, set())


def spike_repo_ids(db: Session) -> set[int]:
    """近 7 天星标暴涨的仓库（缓存 10 分钟）。"""
    global _spike_cache
    if time.time() - _spike_cache[0] < 600:
        return _spike_cache[1]
    last = db.scalar(select(func.max(StarSnapshot.snap_date)))
    out: set[int] = set()
    if last is not None:
        now = dict(db.execute(select(StarSnapshot.repo_id, StarSnapshot.stars).where(StarSnapshot.snap_date == last)).all())
        then_day = db.scalar(select(func.max(StarSnapshot.snap_date)).where(StarSnapshot.snap_date <= last - timedelta(days=7)))
        if then_day is not None:
            then = dict(db.execute(select(StarSnapshot.repo_id, StarSnapshot.stars).where(StarSnapshot.snap_date == then_day)).all())
            for rid, s in now.items():
                b = then.get(rid)
                if b is not None and s - b >= SPIKE_MIN and s - b >= SPIKE_RATIO * max(b, 1):
                    out.add(rid)
    _spike_cache = (time.time(), out)
    return out


def _empty_json(col):
    return or_(col.is_(None), cast(col, String).in_(("", "[]", "null")))


def conds(db: Session, keys: list[str], low_star: int = LOW_STAR) -> list:
    """多个质量问题取「同时满足」。调用方的查询需要 outerjoin Repo。"""
    out = []
    for k in keys:
        if k == "no_cover":
            out.append(or_(Item.cover_path.is_(None), Item.cover_path == ""))
        elif k == "no_summary":
            out.append(or_(Item.summary.is_(None), func.trim(Item.summary) == ""))
        elif k == "no_install":
            out.append(_empty_json(Item.install_steps))
        elif k == "source_broken":
            out.append(Item.status == "offline")
        elif k == "zero_fav":
            out.append(~Item.id.in_(select(Favorite.item_id)))
        elif k == "low_star":
            out.append((Item.repo_id.is_not(None)) & (Repo.stars < low_star))
        elif k == "star_spike":
            out.append(Item.repo_id.in_(list(spike_repo_ids(db)) or [-1]))
        elif k == "rank_excluded":
            out.append(Item.rank_excluded.is_(True))
    return out


def flags(db: Session, items: list[Item], low_star: int = LOW_STAR) -> dict[int, list[str]]:
    """一页条目各自命中的质量问题。"""
    ids = [i.id for i in items]
    faved = set(db.scalars(select(Favorite.item_id).where(Favorite.item_id.in_(ids or [-1])).distinct()))
    spike = spike_repo_ids(db)
    out = {}
    for it in items:
        f = []
        if not it.cover_path:
            f.append("no_cover")
        if not (it.summary or "").strip():
            f.append("no_summary")
        if not it.install_steps:
            f.append("no_install")
        if it.status == "offline":
            f.append("source_broken")
        if it.id not in faved:
            f.append("zero_fav")
        if it.repo is not None and (it.repo.stars or 0) < low_star:
            f.append("low_star")
        if it.repo_id in spike:
            f.append("star_spike")
        if it.rank_excluded:
            f.append("rank_excluded")
        out[it.id] = f
    return out
