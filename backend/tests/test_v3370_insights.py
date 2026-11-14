"""v3.3.70 后台批次 7a：增长与活跃、内容表现、搜索质量、AI 功能效果。"""

from datetime import timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import AiCall, Category, CompareRun, Event, Favorite, Item, SearchTerm, User
from app.seed import seed_categories
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        now = utcnow()
        old = User(email="old@example.com", nickname="老用户", role="user", status="active", signup_channel="web-pc", created_at=now - timedelta(days=20))
        new = User(email="new@example.com", nickname="新用户", role="user", status="active", signup_channel="miniprogram", created_at=now - timedelta(days=3))
        s.add_all([old, new])
        s.flush()
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        a = Item(name="热门条目", category_id=cat.id, status="published")
        b = Item(name="冷门条目", category_id=cat.id, status="published")
        s.add_all([a, b])
        s.flush()
        ev = lambda **k: Event(**{"category": "view", "page": "", "client": "web-pc", **k})  # noqa: E731
        t0 = now - timedelta(days=1)
        s.add_all([
            ev(vid="v1", user_id=old.id, name="search", props={"q": "PDF"}, created_at=t0),
            ev(vid="v1", user_id=old.id, name="item_view", props={"item_id": a.id}, created_at=t0 + timedelta(minutes=1)),
            ev(vid="v1", user_id=old.id, name="favorite", props={"item_id": a.id}, created_at=t0 + timedelta(minutes=2)),
            ev(vid="v2", name="search", props={"q": "pdf"}, created_at=t0),
            ev(vid="v2", name="item_view", props={"item_id": a.id}, created_at=t0 + timedelta(minutes=30)),  # 超过 10 分钟，不算点击
            ev(vid="v3", name="copy_prompt", props={"label": "安装"}, page=f"/items/{a.id}", created_at=t0),
            Event(vid="v4", user_id=new.id, name="page_view", category="view", page="/", client="miniprogram", props={}, created_at=now - timedelta(days=2)),
        ])
        s.add(Favorite(owner_id=old.id, item_id=a.id))
        s.add(CompareRun(key="k", entries=[{"item_id": a.id}, {"item_id": b.id}], subjects=[], status="done", user_id=old.id,
                         created_at=now - timedelta(hours=3), finished_at=now - timedelta(hours=3) + timedelta(seconds=20)))
        s.add(SearchTerm(term="没有的东西", shown="没有的东西", searches=3, empty_count=3, last_results=0, last_at=now))
        s.add_all([AiCall(purpose="AI-17", model="m", tokens_in=10, tokens_out=5, latency_ms=100, ok=True, user_id=old.id, created_at=now),
                   AiCall(purpose="AI-17", model="m", tokens_in=1, tokens_out=0, latency_ms=50, ok=False, user_id=new.id, created_at=now)])
        s.commit()
        S.update(a=a.id, b=b.id, old=old.id, new=new.id)


def test_growth():
    m = login_client("insboss@example.com", role="admin")
    g = m.get("/api/admin/insights/growth?days=7").json()
    assert g["totals"]["new_users"] >= 1 and g["totals"]["active_users"] == 2 and g["totals"]["active_devices"] == 4
    assert g["totals"]["retention_d7"] is None and g["totals"]["retention_d7_pending"]  # 新用户注册才 3 天
    assert len(g["series"]) == 7 and {c["channel"] for c in g["by_channel"]} == {"web-pc", "web-mobile", "miniprogram"}
    mp = m.get("/api/admin/insights/growth?days=7&channel=miniprogram").json()
    assert mp["totals"]["active_users"] == 1 and mp["totals"]["active_devices"] == 1 and mp["by_channel"] == []


def test_content_and_export():
    m = login_client("insboss@example.com", role="admin")
    c = m.get("/api/admin/insights/content?days=7").json()
    top = c["items"][0]
    assert top["item"]["id"] == S["a"] and top["views"] == 2 and top["viewers"] == 2 and top["favorites"] == 1 and top["copies"] == 1
    assert top["compares"] == 1 and top["favorite_rate"] == 0.5 and top["drill"] == {"module": "content", "query": {"id": S["a"]}}
    assert c["totals"]["never_viewed_items"] == 1 and c["totals"]["new_favorites"] == 1
    assert m.get("/api/admin/insights/content?days=7&sort=compares").json()["items"][0]["compares"] == 1
    r = m.get("/api/admin/insights/content?days=7&format=csv")
    assert r.status_code == 200 and "热门条目" in r.text and r.headers["x-export-count"] == "2"


def test_search_and_ai():
    m = login_client("insboss@example.com", role="admin")
    s = m.get("/api/admin/insights/search?days=7").json()
    pdf = next(t for t in s["terms"] if t["term"].lower() == "pdf")
    assert pdf["searches"] == 2 and pdf["click_rate"] == 0.5 and pdf["action_rate"] == 0.5
    assert s["empty"][0]["term"] == "没有的东西" and s["totals"]["empty_terms"] == 1
    a = m.get("/api/admin/insights/ai?days=7").json()
    f = next(x for x in a["features"] if x["purpose"] == "AI-17")
    assert f["calls"] == 2 and f["users"] == 2 and f["success_rate"] == 0.5
    assert a["tasks"]["compare"]["completion_rate"] == 1.0 and a["tasks"]["compare"]["avg_duration_s"] == 20
    assert a["tasks"]["finder"]["completion_rate"] is None
    sup = login_client("inssup@example.com", role="support")
    assert sup.get("/api/admin/insights/growth").status_code == 403
