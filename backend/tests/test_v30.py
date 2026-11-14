"""v3.0：首页「今日」排序、动效封面的安全清洗、封面主题切换只重画一次、搜索被 AI 判为多个项目时转去逐个识别。"""

from datetime import date, datetime, timedelta
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import AppMeta, Category, FinderJob, Item, Repo, StarSnapshot
from app.seed import seed_categories
from app.services import finder, ingest
from app.services.cover import COVER_THEME, sanitize_svg
from conftest import login_client


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def _item(db, gid, name, stars=None, collected=None, cover_source="readme"):
    cat = db.scalar(select(Category).where(Category.parent_id.is_not(None)))
    repo = Repo(github_id=gid, full_name=f"o/{name}", html_url=f"https://github.com/o/{name}", stars=stars)
    db.add(repo)
    db.flush()
    for d, n in (stars or {}).items() if isinstance(stars, dict) else []:
        db.add(StarSnapshot(repo_id=repo.id, snap_date=d, stars=n))
    it = Item(repo_id=repo.id, name=name, category_id=cat.id, status="published", locked_fields=[], install_steps=[],
              cover_source=cover_source, collected_at=collected or datetime(2026, 1, 1))
    db.add(it)
    db.commit()
    return it.id


def test_today_sort_puts_new_first_then_star_gainers_then_daily_shuffle():
    y, t = date.today() - timedelta(days=1), date.today()
    with SessionLocal() as db:
        cat = db.scalar(select(Category).where(Category.parent_id.is_not(None)))
        made = {}
        for gid, (name, snaps) in enumerate([("big", {y: 100, t: 400}), ("small", {y: 100, t: 120}), ("flat", {y: 50, t: 50})], 1):
            repo = Repo(github_id=gid, full_name=f"o/{name}", html_url="https://github.com/x", stars=list(snaps.values())[-1])
            db.add(repo)
            db.flush()
            for d, n in snaps.items():
                db.add(StarSnapshot(repo_id=repo.id, snap_date=d, stars=n))
            it = Item(repo_id=repo.id, name=name, category_id=cat.id, status="published", locked_fields=[], install_steps=[],
                      collected_at=datetime(2026, 1, 1))
            db.add(it)
            db.flush()
            made[name] = it.id
        fresh = Item(name="fresh", category_id=cat.id, status="published", locked_fields=[], install_steps=[], collected_at=datetime.now())
        db.add(fresh)
        for k in range(6):
            db.add(Item(name=f"old{k}", category_id=cat.id, status="published", locked_fields=[], install_steps=[], collected_at=datetime(2026, 1, 1)))
        db.commit()
    c = TestClient(app)
    names = [x["name"] for x in c.get("/api/items?sort=today&size=50").json()["items"]]
    assert names[:3] == ["fresh", "big", "small"]  # v3.3.10：今天新收录的排在涨星前面
    assert len(names) == 10
    # 同一天内顺序固定，翻页不乱
    assert names == [x["name"] for x in c.get("/api/items?sort=today&size=50").json()["items"]]
    page2 = [x["name"] for x in c.get("/api/items?sort=today&size=5&page=2").json()["items"]]
    assert page2 == names[5:10]


def test_today_sort_without_snapshots_still_works():
    with SessionLocal() as db:
        cat = db.scalar(select(Category).where(Category.parent_id.is_not(None)))
        db.add(Item(name="a", category_id=cat.id, status="published", locked_fields=[], install_steps=[]))
        db.commit()
    r = TestClient(app).get("/api/items?sort=today")
    assert r.status_code == 200 and r.json()["total"] == 1


def test_sanitize_keeps_safe_animation_and_drops_unsafe():
    raw = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360">
      <rect width="640" height="360" fill="#EAF1FE"/>
      <circle cx="300" cy="180" r="20" fill="#1E56D6">
        <animate attributeName="r" values="20;24;20" dur="4s" repeatCount="indefinite"/>
        <animate attributeName="href" values="javascript:alert(1)" dur="1s"/>
        <animate attributeName="fill" values="url(http://evil.example/a)" dur="1s"/>
      </circle>
      <g><animateTransform attributeName="transform" type="translate" values="0 0;0 -6;0 0" dur="6s" repeatCount="indefinite"/></g>
      <set attributeName="opacity" to="0"/>
    </svg>'''
    out = sanitize_svg(raw)
    assert 'attributeName="r"' in out and 'repeatCount="indefinite"' in out
    assert 'type="translate"' in out and "animateTransform" in out
    for bad in ("href", "javascript", "evil.example", "<set"):
        assert bad not in out, bad
    # 只有动画、没有图形的 SVG 不算封面
    assert sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="opacity" dur="1s"/></svg>') is None


def test_cover_redraw_resumes_only_stale_covers():
    from app.config import settings
    covers = settings.media_dir / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    (covers / "t-old.svg").write_text('<svg><rect/></svg>', encoding="utf-8")
    (covers / "t-new.svg").write_text('<svg><rect><animate attributeName="opacity"/></rect></svg>', encoding="utf-8")
    with SessionLocal() as db:
        _item(db, 1, "ai1", cover_source="ai")
        _item(db, 2, "shot", cover_source="readme")
        _item(db, 3, "ai-done", cover_source="ai")
        db.execute(Item.__table__.update().where(Item.name == "ai1").values(cover_path="covers/t-old.svg"))
        db.execute(Item.__table__.update().where(Item.name == "ai-done").values(cover_path="covers/t-new.svg"))
        db.commit()
    started = []
    with mock.patch.object(ingest, "start_task", lambda tid, ids, fn, w: started.append(ids)):
        ingest.redraw_covers_if_theme_changed()   # 主题变了：只画旧的
        ingest.redraw_covers_if_theme_changed()   # 重启后：旧的还没画完就接着画
    assert len(started) == 2 and all(len(x) == 1 for x in started)
    (covers / "t-old.svg").write_text('<svg><rect><animate attributeName="r"/></rect></svg>', encoding="utf-8")
    with mock.patch.object(ingest, "start_task", lambda tid, ids, fn, w: started.append(ids)):
        assert ingest.redraw_covers_if_theme_changed() is None  # 都是新主题了，不再起任务
    with SessionLocal() as db:
        assert db.get(AppMeta, "cover_theme").value == COVER_THEME
        ai_id = db.scalar(select(Item.id).where(Item.name == "ai1"))
        shot_id = db.scalar(select(Item.id).where(Item.name == "shot"))
    assert started[0] == [ai_id]
    # 画失败保留旧图；不是 AI 封面的跳过
    with mock.patch.object(ingest, "ai_cover", lambda db, it: False):
        assert ingest.redraw_cover_for(ai_id)[0] is False
    assert ingest.redraw_cover_for(shot_id) == (True, "封面不是 AI 画的，跳过")


def test_search_rerouted_to_text_when_ai_sees_a_list():
    login_client("finder30@example.com")
    job_id = finder.create_job("search", "browser-use、mem0、crawl4ai 这几个怎么样")
    plan = {"intent": "list", "kind": "", "understanding": "三个项目", "queries": ["x"], "skill_queries": []}
    with mock.patch.object(finder, "_plan", lambda q, avoid: plan), \
         mock.patch.object(finder, "_run_text", lambda jid: finder._update(jid, status="done", stage="done", candidates=[])) as rt:
        finder._run_search(job_id, False)
    with SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        assert job.kind == "text" and job.result["rerouted"] == "text"


def test_today_sort_boosts_only_one_item_per_monorepo():
    y, t = date.today() - timedelta(days=1), date.today()
    with SessionLocal() as db:
        cat = db.scalar(select(Category).where(Category.parent_id.is_not(None)))
        mono = Repo(github_id=1, full_name="o/mono", html_url="https://github.com/x", stars=900)
        solo = Repo(github_id=2, full_name="o/solo", html_url="https://github.com/y", stars=150)
        db.add_all([mono, solo])
        db.flush()
        db.add_all([StarSnapshot(repo_id=mono.id, snap_date=y, stars=100), StarSnapshot(repo_id=mono.id, snap_date=t, stars=900),
                    StarSnapshot(repo_id=solo.id, snap_date=y, stars=100), StarSnapshot(repo_id=solo.id, snap_date=t, stars=150)])
        for k in range(5):
            db.add(Item(repo_id=mono.id, sub_path=f"skills/s{k}", name=f"mono{k}", category_id=cat.id, status="published",
                        locked_fields=[], install_steps=[], collected_at=datetime(2026, 1, 1)))
        db.add(Item(repo_id=solo.id, name="solo", category_id=cat.id, status="published", locked_fields=[], install_steps=[],
                    collected_at=datetime(2026, 1, 1)))
        db.commit()
    names = [x["name"] for x in TestClient(app).get("/api/items?sort=today&size=50").json()["items"]]
    assert names[0].startswith("mono") and names[1] == "solo"
    assert len(names) == 6
