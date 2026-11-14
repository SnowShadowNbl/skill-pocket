"""v3.3.61 后台批次 5b：维护工具、数据一致性检查与修复。"""

from datetime import timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import AuthSession, BlockEntry, Category, Comment, FavDimension, Favorite, FavFolder, FavoriteFolderLink, Item, Repo, User
from app.seed import seed_categories
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        subs = s.scalars(select(Category).where(Category.parent_id.is_not(None)).order_by(Category.id)).all()
        good, old = subs[0], subs[1]
        old.enabled, old.merged_into_id = False, good.id
        a = User(email="m1@example.com", nickname="甲", role="user", status="active")
        b = User(email="m2@example.com", nickname="乙", role="user", status="disabled")
        s.add_all([a, b])
        s.flush()
        r = Repo(github_id=9, full_name="bad/repo", html_url="https://github.com/bad/repo")
        s.add(r)
        s.flush()
        it1 = Item(name="评分不对", category_id=good.id, status="published", rating_avg=1.0, rating_count=5)
        it2 = Item(name="挂在旧分类", category_id=old.id, status="published")
        it3 = Item(name="黑名单仓库", category_id=good.id, status="published", repo_id=r.id)
        s.add_all([it1, it2, it3])
        s.flush()
        s.add(Comment(item_id=it1.id, user_id=a.id, content="好", rating=4))
        s.add(BlockEntry(kind="owner", value="bad", reason="测试"))
        da, db_ = FavDimension(owner_id=a.id, name="甲的"), FavDimension(owner_id=b.id, name="乙的")
        s.add_all([da, db_])
        s.flush()
        fb = FavFolder(dimension_id=db_.id, name="乙的收藏夹")
        s.add(fb)
        fav = Favorite(owner_id=a.id, item_id=it1.id)
        s.add(fav)
        s.flush()
        s.add(FavoriteFolderLink(favorite_id=fav.id, folder_id=fb.id))
        now = utcnow()
        s.add(AuthSession(user_id=b.id, token_hash="h" * 64, created_at=now, last_seen_at=now, expires_at=now + timedelta(days=3)))
        s.commit()
        S.update(it1=it1.id, it2=it2.id, it3=it3.id, good=good.id, b=b.id)


def test_tools():
    m = login_client("mboss@example.com", role="admin")
    tools = {t["key"]: t for t in m.get("/api/admin/maintenance").json()["tools"]}
    assert set(tools) >= {"recalc_ratings", "recalc_rankings", "embed_backfill", "media_backfill", "clear_cache"} and tools["clear_cache"]["last_run"] is None
    pv = m.post("/api/admin/maintenance/recalc_ratings/run", json={"dry_run": True}).json()
    assert pv["dry_run"] and "1 个条目" in pv["summary"] or "个条目" in pv["summary"]
    assert m.post("/api/admin/maintenance/recalc_ratings/run", json={}).json()["detail"]["code"] == "reason_required"
    r = m.post("/api/admin/maintenance/recalc_ratings/run", json={"reason": "数据核对"}).json()
    assert r["ok"] and "重算" in r["summary"]
    with SessionLocal() as s:
        it = s.get(Item, S["it1"])
        assert it.rating_count == 1 and it.rating_avg == 4.0
    assert m.post("/api/admin/maintenance/clear_cache/run", json={"reason": "清一下"}).json()["ok"]
    last = {t["key"]: t for t in m.get("/api/admin/maintenance").json()["tools"]}["clear_cache"]["last_run"]
    assert last["ok"] and last["by"]["label"] and last["reason"] == "清一下"
    assert m.get("/api/admin/activity?target_type=maintenance").json()["total"] >= 2
    assert m.post("/api/admin/maintenance/nope/run", json={"reason": "xx"}).status_code == 404
    mod = login_client("mmod@example.com", role="moderator")
    assert mod.get("/api/admin/maintenance").status_code == 403
    view = login_client("mview@example.com", role="viewer")
    assert view.get("/api/admin/maintenance").status_code == 200
    assert view.post("/api/admin/maintenance/clear_cache/run", json={"reason": "xx"}).status_code == 403


def test_consistency():
    m = login_client("mboss@example.com", role="admin")
    with SessionLocal() as s:
        it = s.get(Item, S["it1"])
        it.rating_avg, it.rating_count = 2.0, 9  # 再弄乱一次
        s.commit()
    lst = {c["key"]: c for c in m.get("/api/admin/consistency").json()["checks"]}
    assert lst["item_ratings"]["status"] == "unknown"
    for k in lst:
        m.post(f"/api/admin/consistency/{k}/scan")
    lst = {c["key"]: c for c in m.get("/api/admin/consistency").json()["checks"]}
    assert {k: c["mismatches"] for k, c in lst.items()} == {"item_ratings": 1, "item_category": 1, "fav_folder_owner": 1,
                                                           "published_blocked": 1, "inactive_sessions": 1}
    d = m.get("/api/admin/consistency/item_ratings").json()
    assert d["items"][0]["stored"]["count"] == 9 and d["items"][0]["actual"] == {"avg": 4.0, "count": 1}
    assert m.post("/api/admin/consistency/item_ratings/fix", json={"all": True, "dry_run": True}).json()["count"] == 1
    for k in ("item_ratings", "item_category", "fav_folder_owner", "published_blocked", "inactive_sessions"):
        r = m.post(f"/api/admin/consistency/{k}/fix", json={"all": True, "reason": "修复测试"}).json()
        assert r["ok_count"] == 1, (k, r)
    lst = {c["key"]: c for c in m.get("/api/admin/consistency").json()["checks"]}
    assert all(c["status"] == "ok" for c in lst.values())
    with SessionLocal() as s:
        assert s.get(Item, S["it2"]).category_id == S["good"] and s.get(Item, S["it3"]).status == "hidden"
        assert s.scalar(select(AuthSession).where(AuthSession.user_id == S["b"])).revoked_at is not None
    r = m.post("/api/admin/consistency/item_ratings/fix", json={"ids": [S["it1"]], "reason": "再修一次"}).json()
    assert r["results"][0]["code"] == "noop"
