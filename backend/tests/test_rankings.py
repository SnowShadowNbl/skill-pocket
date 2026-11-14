from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Category, Item, Ranking, RankingEntry, Repo, StarSnapshot
from app.seed import seed_categories
from app.services.rankings import compute_rankings

D = date(2026, 11, 2)  # 周一


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        yield s


def cat(db, code):
    return db.scalar(select(Category).where(Category.code == code)).id


def add_repo(db, gid, stars_by_day, category, subs=("",), status="published"):
    repo = Repo(github_id=gid, full_name=f"o/r{gid}", html_url=f"https://github.com/o/r{gid}")
    db.add(repo)
    db.flush()
    for d, s in stars_by_day.items():
        db.add(StarSnapshot(repo_id=repo.id, snap_date=d, stars=s))
    items = []
    for sub in subs:
        it = Item(repo_id=repo.id, sub_path=sub, name=f"r{gid}{sub}", category_id=cat(db, category), status=status,
                  locked_fields=[], install_steps=[])
        db.add(it)
        items.append(it)
    db.commit()
    return items


def board(db, period, code):
    r = db.scalar(select(Ranking).where(Ranking.period == period, Ranking.period_date == D, Ranking.category_id == cat(db, code)))
    if r is None:
        return []
    rows = db.execute(select(RankingEntry).where(RankingEntry.ranking_id == r.id).order_by(RankingEntry.rank)).scalars().all()
    return [(e.item_id, e.stars_delta) for e in rows]


def test_daily_delta_sorted_and_capped(db):
    y = D - timedelta(days=1)
    a = add_repo(db, 1, {y: 100, D: 150}, "model-asr")[0]  # +50
    b = add_repo(db, 2, {y: 100, D: 400}, "model-asr")[0]  # +300
    c = add_repo(db, 3, {y: 100, D: 120}, "model-asr")[0]  # +20
    d = add_repo(db, 4, {y: 100, D: 110}, "model-asr")[0]  # +10 → 第 4 名，超出 top 3
    add_repo(db, 5, {y: 100, D: 100}, "model-asr")          # 0 不上榜
    add_repo(db, 6, {D: 999}, "model-asr")                   # 没有昨天快照不上榜
    assert compute_rankings(db, D, "daily") == 1
    assert board(db, "daily", "model-asr") == [(b.id, 300), (a.id, 50), (c.id, 20)]


def test_boards_split_by_subcategory(db):
    y = D - timedelta(days=1)
    add_repo(db, 1, {y: 10, D: 20}, "model-asr")
    add_repo(db, 2, {y: 10, D: 90}, "model-tts")
    assert compute_rankings(db, D, "daily") == 2
    assert board(db, "daily", "model-asr")[0][1] == 10
    assert board(db, "daily", "model-tts")[0][1] == 80


def test_monorepo_counts_once_per_board(db):
    y = D - timedelta(days=1)
    items = add_repo(db, 1, {y: 1000, D: 1500}, "office-docs", subs=("skills/pdf", "skills/docx", "skills/xlsx"))
    compute_rankings(db, D, "daily")
    assert board(db, "daily", "office-docs") == [(items[0].id, 500)]


def test_weekly_uses_earliest_snapshot_in_window(db):
    a = add_repo(db, 1, {D - timedelta(days=9): 0, D - timedelta(days=5): 100, D - timedelta(days=2): 150, D: 300}, "dev-inference")[0]
    compute_rankings(db, D, "weekly")
    assert board(db, "weekly", "dev-inference") == [(a.id, 200)]  # 300 - 100（9 天前的不在 7 天窗口内）


def test_recompute_replaces_old_boards_and_skips_unpublished(db):
    y = D - timedelta(days=1)
    add_repo(db, 1, {y: 10, D: 20}, "model-asr")
    add_repo(db, 2, {y: 10, D: 500}, "model-asr", status="pending_review")
    compute_rankings(db, D, "daily")
    compute_rankings(db, D, "daily")
    assert len(db.scalars(select(Ranking).where(Ranking.period_date == D)).all()) == 1
    assert [d for _, d in board(db, "daily", "model-asr")] == [10]
