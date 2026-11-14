"""按子类生成日榜 / 周榜 / 月榜（周榜 = 近 7 天、月榜 = 近 30 天，都每天更新）：用自建的每日星标快照算增量，不依赖 GitHub Trending。"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Item, Ranking, RankingEntry, StarSnapshot


WINDOW = {"daily": 1, "weekly": 7, "monthly": 30}


def _snapshots(db: Session, day: date) -> dict[int, int]:
    return dict(db.execute(select(StarSnapshot.repo_id, StarSnapshot.stars).where(StarSnapshot.snap_date == day)).all())


def _baseline(db: Session, day: date, period: str) -> dict[int, int]:
    """日榜对比前一天；周榜 / 月榜对比 7 / 30 天前，不足时用窗口内最早的一次快照。"""
    if period == "daily":
        return _snapshots(db, day - timedelta(days=1))
    span = WINDOW[period]
    rows = db.execute(
        select(StarSnapshot.repo_id, StarSnapshot.snap_date, StarSnapshot.stars)
        .where(StarSnapshot.snap_date >= day - timedelta(days=span), StarSnapshot.snap_date < day)
        .order_by(StarSnapshot.snap_date)
    ).all()
    base: dict[int, int] = {}
    for repo_id, _, stars in rows:
        base.setdefault(repo_id, stars)
    return base


def compute_rankings(db: Session, day: date, period: str) -> int:
    """生成（或重算）某天的榜单，返回有上榜条目的子类数量。"""
    today = _snapshots(db, day)
    base = _baseline(db, day, period)
    if not today or not base:
        return 0

    items = db.scalars(
        select(Item).where(Item.status == "published", Item.repo_id.is_not(None), Item.rank_excluded.is_not(True)).order_by(Item.id)
    ).all()

    boards: dict[int, list[tuple[int, int, int]]] = defaultdict(list)  # category_id → [(delta, stars, item_id)]
    seen: set[tuple[int, int]] = set()
    for it in items:
        if it.repo_id not in today or it.repo_id not in base:
            continue
        # 同一仓库（monorepo）的多个 Skill 在同一子类里只占一个名额，取最早收录的那个
        if (it.category_id, it.repo_id) in seen:
            continue
        seen.add((it.category_id, it.repo_id))
        delta = today[it.repo_id] - base[it.repo_id]
        if delta > 0:
            boards[it.category_id].append((delta, today[it.repo_id], it.id))

    # 重算时先清掉当天旧榜单
    old_ids = db.scalars(select(Ranking.id).where(Ranking.period == period, Ranking.period_date == day)).all()
    if old_ids:
        db.execute(delete(RankingEntry).where(RankingEntry.ranking_id.in_(old_ids)))
        db.execute(delete(Ranking).where(Ranking.id.in_(old_ids)))

    for category_id, rows in boards.items():
        rows.sort(key=lambda r: (-r[0], -r[1]))
        ranking = Ranking(period=period, period_date=day, category_id=category_id)
        db.add(ranking)
        db.flush()
        for rank, (delta, stars, item_id) in enumerate(rows[: settings.rank_top_n], start=1):
            db.add(RankingEntry(ranking_id=ranking.id, item_id=item_id, rank=rank, stars_delta=delta, stars_end=stars))
    db.commit()
    return len(boards)


def backfill_weekly(db: Session) -> int:
    """给有日榜、但还没有周榜 / 月榜的日期补算（v3.1 周榜改为每天更新，v3.3 新增月榜）。返回补算的榜单天数。"""
    daily = set(db.scalars(select(Ranking.period_date).where(Ranking.period == "daily").distinct()).all())
    done = 0
    for period in ("weekly", "monthly"):
        have = set(db.scalars(select(Ranking.period_date).where(Ranking.period == period).distinct()).all())
        for day in sorted(daily - have):
            if compute_rankings(db, day, period):
                done += 1
    return done


def group_trends(db: Session) -> list[dict]:
    """v3.3 分类热度趋势：每个大类近 7 天的星标增量，与再往前 7 天对比（数据不满 14 天时 prev 为 None）。"""
    from ..models import Category

    d1 = db.scalar(select(StarSnapshot.snap_date).order_by(StarSnapshot.snap_date.desc()).limit(1))
    if d1 is None:
        return []
    first = db.scalar(select(StarSnapshot.snap_date).order_by(StarSnapshot.snap_date).limit(1))

    def at(d: date) -> dict[int, int]:
        # 当天没有快照就往后找最近的一天（开站不满 14 天时用最早的一天）
        snap = db.scalar(select(StarSnapshot.snap_date).where(StarSnapshot.snap_date >= d).order_by(StarSnapshot.snap_date).limit(1))
        return _snapshots(db, snap) if snap else {}

    now, w1 = _snapshots(db, d1), at(d1 - timedelta(days=7))
    w2 = at(d1 - timedelta(days=14)) if first and first <= d1 - timedelta(days=14) else None
    cats = {c.id: c for c in db.scalars(select(Category))}
    seen: set[int] = set()
    acc: dict[int, list] = {}
    for it in db.scalars(select(Item).where(Item.status == "published", Item.repo_id.is_not(None))):
        if it.repo_id in seen or it.category_id not in cats:
            continue
        seen.add(it.repo_id)
        g = cats[it.category_id].parent_id or it.category_id
        a = acc.setdefault(g, [0, 0 if w2 is not None else None])
        if it.repo_id in now and it.repo_id in w1:
            a[0] += max(0, now[it.repo_id] - w1[it.repo_id])
        if w2 is not None and it.repo_id in w1 and it.repo_id in w2:
            a[1] += max(0, w1[it.repo_id] - w2[it.repo_id])
    out = []
    for gid, (cur, prev) in acc.items():
        g = cats[gid]
        change = round((cur - prev) / prev * 100) if prev else None
        out.append({"code": g.code, "name": g.name, "stars": cur, "prev": prev, "change": change})
    return sorted(out, key=lambda x: -x["stars"])
