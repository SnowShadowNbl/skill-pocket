from fastapi.testclient import TestClient

from conftest import login_client
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Category, Item
from app.seed import seed_categories


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        cat = s.scalar(select(Category).where(Category.code == "other-misc"))
        for n in ("a", "b", "c"):
            s.add(Item(name=n, category_id=cat.id, locked_fields=[], install_steps=[]))
        s.commit()


def test_favorite_toggle_filter_and_sort():
    assert TestClient(app).post('/api/items/1/favorite', json={'on': True}).status_code == 401  # 收藏需要登录
    c = login_client('fav@example.com')
    ids = [i["id"] for i in c.get("/api/items?sort=collected").json()["items"]]
    assert all(not i["favorited"] for i in c.get("/api/items").json()["items"])

    r = c.post(f"/api/items/{ids[2]}/favorite", json={"on": True}).json()
    assert r == {"favorited": True, "favorites": 1}
    c.post(f"/api/items/{ids[0]}/favorite", json={"on": True})
    c.post(f"/api/items/{ids[0]}/favorite", json={"on": True})  # 重复收藏不改时间、不重复计数

    fav = c.get("/api/items?fav=true&sort=favorited").json()
    assert fav["total"] == 2
    assert [i["id"] for i in fav["items"]] == [ids[0], ids[2]]  # 最近收藏的在前
    assert c.get("/api/meta").json()["favorites"] == 2
    assert c.get(f"/api/items/{ids[0]}").json()["favorited"] is True

    assert c.post(f"/api/items/{ids[0]}/favorite", json={"on": False}).json()["favorited"] is False
    assert c.get("/api/items?fav=true").json()["total"] == 1
    assert c.post("/api/items/999999/favorite", json={"on": True}).status_code == 404
    # 前端不筛选时会传空字符串 fav=，必须当作“不筛选”而不是报错
    assert c.get("/api/items?fav=&q=&category=").json()["total"] == 3
