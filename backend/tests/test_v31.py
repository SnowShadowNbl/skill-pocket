"""v3.1：周榜改为每天更新的「近 7 天」并补算；首页收录数统一口径；图片集覆盖率。"""

from datetime import date, timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Category, Item, Ranking, Repo, StarSnapshot
from app.seed import seed_categories
from app.services import crawler
from app.services.rankings import backfill_weekly, compute_rankings
from conftest import login_client

D = date(2026, 11, 7)  # 周六：原来只有周一才出周榜


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def _item(db, gid, stars_by_day, status="published", images=None, cat_code="model-asr"):
    repo = Repo(github_id=gid, full_name=f"o/r{gid}", html_url=f"https://github.com/o/r{gid}")
    db.add(repo)
    db.flush()
    for d, s in stars_by_day.items():
        db.add(StarSnapshot(repo_id=repo.id, snap_date=d, stars=s))
    cid = db.scalar(select(Category.id).where(Category.code == cat_code))
    it = Item(repo_id=repo.id, name=f"r{gid}", category_id=cid, status=status, locked_fields=[], install_steps=[], images=images or [])
    db.add(it)
    db.commit()
    return it


def test_backfill_creates_weekly_for_every_daily_date():
    with SessionLocal() as db:
        days = [D - timedelta(days=k) for k in range(3, -1, -1)]  # 11-04 ~ 11-07
        _item(db, 1, {d: 100 + 50 * i for i, d in enumerate(days)})
        for d in days[1:]:
            compute_rankings(db, d, "daily")
        assert backfill_weekly(db) == 6  # 3 天 × 周榜 + 月榜（v3.3 起）
        weekly = set(db.scalars(select(Ranking.period_date).where(Ranking.period == "weekly")).all())
        assert weekly == set(days[1:])
        assert backfill_weekly(db) == 0  # 补过的跳过


def test_weekly_differs_from_daily_and_crawler_runs_it_every_day(monkeypatch):
    with SessionLocal() as db:
        days = [D - timedelta(days=k) for k in range(5, -1, -1)]
        _item(db, 1, {d: 100 + 10 * i for i, d in enumerate(days)})  # 每天 +10，6 天前 100
    monkeypatch.setattr(crawler, "local_today", lambda: D)
    with SessionLocal() as db:
        stats = {}
        crawler.rankings(db, stats)
        assert stats["daily_boards"] == 1 and stats["weekly_boards"] == 1
        from app.models import RankingEntry
        deltas = dict(db.execute(select(Ranking.period, RankingEntry.stars_delta).join(RankingEntry, RankingEntry.ranking_id == Ranking.id)).all())
        assert deltas == {"daily": 10, "weekly": 50, "monthly": 50}


def test_meta_published_total_matches_list_total():
    with SessionLocal() as db:
        _item(db, 1, {}, status="published")
        _item(db, 2, {}, status="published")
        _item(db, 3, {}, status="offline")
        # 停用分类里的已发布条目：分类合计不算它，但列表和首页数字都算
        cat = db.scalar(select(Category).where(Category.code == "model-tts"))
        cat.enabled = False
        db.commit()
        _item(db, 4, {}, status="published", cat_code="model-tts")
    c = login_client("meta31@example.com")
    meta = c.get("/api/meta").json()
    assert meta["published_total"] == 3
    assert c.get("/api/items?size=1").json()["total"] == 3


def test_images_coverage():
    with SessionLocal() as db:
        _item(db, 1, {}, images=["/media/a.png", "/media/b.png"])
        _item(db, 2, {}, images=["/media/c.png"])
        _item(db, 3, {}, status="offline", images=["/media/d.png", "/media/e.png"])
    admin = login_client("cov31@example.com", role="admin")
    r = admin.get("/api/admin/gallery-coverage").json()
    assert r == {"total": 2, "with_gallery": 1, "github_total": 2}
    assert login_client("cov31u@example.com").get("/api/admin/gallery-coverage").status_code in (401, 403)

