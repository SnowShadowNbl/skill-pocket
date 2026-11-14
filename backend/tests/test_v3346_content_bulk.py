"""v3.3.46 后台批次 3a：质量筛选、条目批量、修改记录、排除出榜单。"""

from datetime import date, timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import Category, Favorite, Item, Ranking, RankingEntry, Repo, StarSnapshot
from app.seed import seed_categories
from app.services import ingest, item_quality, rankings, tracking
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    item_quality._spike_cache = (0.0, set())
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        subs = s.scalars(select(Category).where(Category.parent_id.is_not(None))).all()
        cat, cat2 = subs[0], subs[1]
        r1 = Repo(github_id=1, full_name="a/good", html_url="https://github.com/a/good", stars=500)
        r2 = Repo(github_id=2, full_name="a/spike", html_url="https://github.com/a/spike", stars=900)
        r3 = Repo(github_id=3, full_name="a/tiny", html_url="https://github.com/a/tiny", stars=3)
        s.add_all([r1, r2, r3])
        s.flush()
        good = Item(name="好条目", repo_id=r1.id, category_id=cat.id, status="published", summary="有简介", cover_path="c.svg",
                    install_steps=[{"title": "装", "command": "pip install x"}])
        spike = Item(name="刷星条目", repo_id=r2.id, category_id=cat.id, status="published", summary="s", cover_path="d.svg",
                     install_steps=[{"title": "装"}])
        tiny = Item(name="小条目", repo_id=r3.id, category_id=cat.id, status="published", summary="", cover_path="",
                    install_steps=[], locked_fields=["cover_path"])
        gone = Item(name="已下线", category_id=cat.id, status="offline", summary="x", cover_path="", install_steps=[])
        hidden = Item(name="隐藏的", category_id=cat.id, status="hidden", summary="x", cover_path="e.svg", install_steps=[])
        s.add_all([good, spike, tiny, gone, hidden])
        s.flush()
        s.add(Favorite(owner_id=1, item_id=good.id))
        today = date.today()
        for d, a, b, c in ((today - timedelta(days=7), 400, 100, 3), (today - timedelta(days=1), 450, 850, 3), (today, 500, 900, 3)):
            s.add_all([StarSnapshot(repo_id=r1.id, snap_date=d, stars=a), StarSnapshot(repo_id=r2.id, snap_date=d, stars=b),
                       StarSnapshot(repo_id=r3.id, snap_date=d, stars=c)])
        s.commit()
        rankings.compute_rankings(s, today, "daily")
        S.update(good=good.id, spike=spike.id, tiny=tiny.id, gone=gone.id, hidden=hidden.id, cat=cat.id, cat2=cat2.id, cat2_name=cat2.name)


def _ids(c, qs):
    return {x["id"] for x in c.get(f"/api/admin/items?{qs}").json()["items"]}


def test_quality_filters():
    m = login_client("cboss@example.com", role="admin")
    assert _ids(m, "quality=no_cover") == {S["tiny"], S["gone"]}
    assert _ids(m, "quality=no_summary") == {S["tiny"]}
    assert _ids(m, "quality=no_install") == {S["tiny"], S["gone"], S["hidden"]}
    assert _ids(m, "quality=source_broken") == {S["gone"]}
    assert S["good"] not in _ids(m, "quality=zero_fav") and S["spike"] in _ids(m, "quality=zero_fav")
    assert _ids(m, "quality=low_star") == {S["tiny"]} and _ids(m, "quality=low_star&low_star=600") == {S["good"], S["tiny"]}
    assert _ids(m, "quality=star_spike") == {S["spike"]}
    assert _ids(m, "quality=no_cover,no_summary") == {S["tiny"]}
    row = next(x for x in m.get("/api/admin/items?quality=no_cover").json()["items"] if x["id"] == S["tiny"])
    assert set(row["quality"]) >= {"no_cover", "no_summary", "no_install", "zero_fav", "low_star"} and row["locked_fields"] == ["cover_path"]
    st = m.get("/api/admin/items/quality-stats").json()["items"]
    assert st["star_spike"]["count"] == 1 and st["no_cover"]["count"] == 2  # 隐藏的不统计


def test_bulk_status_category_and_changes():
    m = login_client("cboss@example.com", role="admin")
    r = m.post("/api/admin/items/bulk", json={"action": "hide", "ids": [S["good"], S["hidden"], S["gone"], 99999]})
    assert r.json()["detail"]["code"] == "reason_required"
    r = m.post("/api/admin/items/bulk", json={"action": "hide", "reason": "质量差", "ids": [S["good"], S["hidden"], S["gone"], 99999]}).json()
    codes = {x["id"]: x["code"] for x in r["results"]}
    assert codes == {S["good"]: "ok", S["hidden"]: "noop", S["gone"]: "bad_state", 99999: "not_found"}
    assert r["ok_count"] == 2 and r["fail_count"] == 2
    m.post("/api/admin/items/bulk", json={"action": "show", "reason": "恢复", "ids": [S["good"]]})
    # 按筛选 + total 校验
    r = m.post("/api/admin/items/bulk", json={"action": "set_category", "params": {"category_id": S["cat2"]},
                                               "filter": {"quality": "no_summary"}, "total": 5})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "count_changed"
    r = m.post("/api/admin/items/bulk", json={"action": "set_category", "params": {"category_id": S["cat2"]},
                                               "filter": {"quality": "no_summary"}, "total": 1}).json()
    assert r["results"][0]["code"] == "ok"
    with SessionLocal() as s:
        it = s.get(Item, S["tiny"])
        assert it.category_id == S["cat2"] and "category_id" in it.locked_fields
    ch = m.get(f"/api/admin/items/{S['tiny']}/changes").json()["items"][0]
    assert ch["changes"][0]["field"] == "category" and ch["changes"][0]["after"] == S["cat2_name"]
    # 编辑接口也记修改前后
    m.put(f"/api/items/{S['good']}", json={"summary": "新的简介", "name": "好条目"})
    ch = m.get(f"/api/admin/items/{S['good']}/changes").json()["items"]
    assert ch[0]["changes"] == [{"field": "summary", "label": "简介", "before": "有简介", "after": "新的简介"}]
    assert any(c["action"] == "item_bulk" for c in ch)
    logs = m.get(f"/api/admin/activity?target_type=item&target_id={S['good']}").json()
    assert logs["total"] == len(ch)


def test_bulk_ai_actions(monkeypatch):
    m = login_client("cboss@example.com", role="admin")
    started = {}
    monkeypatch.setattr(ingest, "start_process_task", lambda kind, title, ids, **kw: started.setdefault("re", ids) and 77)
    r = m.post("/api/admin/items/bulk", json={"action": "reextract", "ids": [S["good"], S["gone"]]}).json()
    codes = {x["id"]: (x["code"], x.get("task_id")) for x in r["results"]}
    assert codes[S["good"]] == ("queued", 77) and codes[S["gone"]][0] == "no_repo" and started["re"] == [S["good"]]
    monkeypatch.setattr(ingest.settings, "ai_base_url", "http://x", raising=False)
    monkeypatch.setattr(type(ingest.settings), "ai_enabled", property(lambda self: True))
    monkeypatch.setattr(tracking, "create_task", lambda *a, **k: 88)
    monkeypatch.setattr(tracking, "start_task", lambda *a, **k: started.setdefault("cover", a[1]))
    r = m.post("/api/admin/items/bulk", json={"action": "cover", "ids": [S["tiny"], S["gone"], S["spike"]]}).json()
    codes = {x["id"]: x["code"] for x in r["results"]}
    assert codes == {S["tiny"]: "locked_skipped", S["gone"]: "queued", S["spike"]: "has_cover"} and started["cover"] == [S["gone"]]


def test_rank_exclude():
    m = login_client("cboss@example.com", role="admin")
    with SessionLocal() as s:
        assert S["spike"] in set(s.scalars(select(RankingEntry.item_id)))
    r = m.post("/api/admin/items/bulk", json={"action": "rank_exclude", "reason": "疑似刷星", "ids": [S["spike"]]}).json()
    assert r["results"][0]["code"] == "ok"
    with SessionLocal() as s:
        assert S["spike"] not in set(s.scalars(select(RankingEntry.item_id))) and s.scalar(select(Ranking.id)) is not None
        assert s.get(Item, S["spike"]).status == "published"
    assert _ids(m, "quality=rank_excluded") == {S["spike"]}
    row = next(x for x in m.get("/api/admin/items?quality=rank_excluded").json()["items"])
    assert row["rank_excluded"]["reason"] == "疑似刷星"
    m.post("/api/admin/items/bulk", json={"action": "rank_include", "reason": "误判", "ids": [S["spike"]]})
    with SessionLocal() as s:
        assert S["spike"] in set(s.scalars(select(RankingEntry.item_id)))
