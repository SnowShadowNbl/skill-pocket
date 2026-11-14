"""v3.3.42 后台批次 1：用户内容与行为、保存的筛选视图、全局搜索。"""

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import (Category, CategorySubscription, Comment, CompareRun, FavDimension, Favorite, FavFolder,
                        FavoriteFolderLink, Feedback, Item, User)
from app.seed import seed_categories
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        u = User(email="content1@example.com", nickname="内容用户", remark="老客户甲", role="user", status="active")
        s.add(u)
        s.flush()
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        items = [Item(name=f"测试条目{i}", category_id=cat.id, status="published", created_by=u.id if i < 12 else None)
                 for i in range(14)]
        s.add_all(items)
        s.flush()
        s.add_all([Comment(item_id=items[0].id, user_id=u.id, content="好用" * 100, rating=4),
                   Comment(item_id=items[1].id, user_id=u.id, content="一般", rating=2, status="pending", review_reason="疑似广告"),
                   Comment(item_id=items[2].id, user_id=u.id, content="没打分")])
        dim = FavDimension(owner_id=u.id, name="我的分类")
        s.add(dim)
        s.flush()
        folder = FavFolder(dimension_id=dim.id, name="工作", share_token="tok-secret-123")
        s.add(folder)
        fav = Favorite(owner_id=u.id, item_id=items[0].id)
        s.add_all([fav, Favorite(owner_id=u.id, item_id=items[1].id)])
        s.flush()
        s.add(FavoriteFolderLink(favorite_id=fav.id, folder_id=folder.id))
        s.add(Feedback(user_id=u.id, category="bug", content="搜索框在手机上被挡住了"))
        s.add(CompareRun(key="k1", entries=[{"item_id": 1}, {"item_id": 2}], subjects=[{"name": "A"}, {"name": "B"}], status="done", user_id=u.id))
        s.add(CategorySubscription(user_id=u.id, category_id=cat.id))
        s.commit()
        S["uid"] = u.id
        S["item0"] = items[0].id


def test_user_content():
    admin = login_client("b1boss@example.com", role="admin")
    r = admin.get(f"/api/admin/users/{S['uid']}/content").json()
    assert r["submissions"]["total"] == 12 and len(r["submissions"]["items"]) == 10
    c = r["comments"]
    assert c["total"] == 3 and c["avg_rating"] == 3.0 and c["rated_count"] == 2
    assert any(x["review_reason"] == "疑似广告" for x in c["items"]) and all(len(x["content"]) <= 121 for x in c["items"])
    f = r["favorites"]
    assert f["total"] == 2 and f["folders"][0]["count"] == 1 and f["folders"][0]["shared"] is True
    assert "tok-secret" not in str(f)
    assert r["feedback"]["total"] == 1 and r["feedback"]["items"][0]["category_label"] == "Bug"
    assert r["compares"]["items"][0]["count"] == 2
    assert r["subscriptions"]["total"] == 1 and r["subscriptions"]["daily_push"] is True
    p = admin.get(f"/api/admin/users/{S['uid']}/content/submissions?page=2&page_size=10").json()
    assert p["total"] == 12 and len(p["items"]) == 2
    assert admin.get(f"/api/admin/users/{S['uid']}/content/nope").status_code == 404


def test_views():
    a = login_client("b1views@example.com", role="admin")
    b = login_client("b1views2@example.com", role="admin")
    v = a.post("/api/admin/views", json={"scope": "users", "name": "纯微信", "query": {"login": "wechat_only"}}).json()
    assert v["query"] == {"login": "wechat_only"}
    assert a.post("/api/admin/views", json={"scope": "users", "name": "纯微信", "query": {}}).json()["detail"]["code"] == "duplicate_name"
    assert b.get("/api/admin/views?scope=users").json()["items"] == []
    assert b.delete(f"/api/admin/views/{v['id']}").status_code == 404
    assert a.put(f"/api/admin/views/{v['id']}", json={"name": "微信用户", "position": 5}).json()["name"] == "微信用户"
    for i in range(19):
        assert a.post("/api/admin/views", json={"scope": "users", "name": f"v{i}", "query": {}}).status_code == 200
    r = a.post("/api/admin/views", json={"scope": "users", "name": "多一个", "query": {}})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "too_many"
    assert a.delete(f"/api/admin/views/{v['id']}").json()["ok"]
    assert len(a.get("/api/admin/views?scope=users").json()["items"]) == 19


def test_search():
    a = login_client("b1search@example.com", role="admin")
    assert a.get("/api/admin/search?q=x").json()["users"] == []
    r = a.get("/api/admin/search?q=老客户").json()
    assert r["users"][0]["id"] == S["uid"] and r["users"][0]["label"] == "老客户甲"
    r = a.get(f"/api/admin/search?q={S['item0']}").json()
    assert r["items"][0]["id"] == S["item0"]  # 纯数字优先按编号
    r = a.get("/api/admin/search?q=测试条目&limit=10").json()
    assert len(r["items"]) == 10
    assert a.get("/api/admin/search?q=手机上被挡").json()["feedback"][0]["status_label"] == "新提交"
    assert a.get("/api/admin/search?q=ab&limit=11").status_code == 422
