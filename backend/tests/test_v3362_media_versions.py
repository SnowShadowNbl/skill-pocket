"""v3.3.62 后台批次 5c：封面缩略图 / 动图队列、客户端版本统计与按版本筛用户。"""

import os
import time
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import AuthSession, Category, Item, User
from app.seed import seed_categories
from app.services import anim
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        s.add_all([Item(name="有缩略图", category_id=cat.id, status="published", cover_path="covers/a.svg"),
                   Item(name="缺缩略图", category_id=cat.id, status="published", cover_path="covers/b.svg"),
                   Item(name="位图封面", category_id=cat.id, status="published", cover_path="covers/c.png")])
        u1 = User(email="v1@example.com", nickname="新版", role="user", status="active", last_client="miniprogram", last_client_version="1.2.0")
        u2 = User(email="v2@example.com", nickname="旧版", role="user", status="active", last_client="miniprogram", last_client_version="1.1.0")
        s.add_all([u1, u2])
        s.flush()
        now = utcnow()
        for n, (uid, v) in enumerate(((u1.id, "1.2.0"), (u1.id, "1.2.0"), (u2.id, "1.1.0"))):
            s.add(AuthSession(user_id=uid, token_hash=f"tok-{n}-{uid}", client="miniprogram", client_version=v,
                              created_at=now, last_seen_at=now, expires_at=now + timedelta(days=1)))
        s.add(AuthSession(user_id=u1.id, token_hash=f"web{time.time_ns()}", client="web-pc", client_version="3.3.62", created_at=now,
                          last_seen_at=now, expires_at=now + timedelta(days=1)))
        s.commit()
        S.update(u1=u1.id, u2=u2.id)


def _media(tmp_path):
    for name in ("a.svg", "b.svg", "c.png"):
        p = tmp_path / "covers" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<svg/>")
        os.utime(p, (time.time() - 100, time.time() - 100))
    t = tmp_path / "thumb" / "covers" / "a.svg.jpg"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_bytes(b"x" * 10)
    a = tmp_path / "anim" / "covers" / "a.svg.webp.none"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"")


def test_cover_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_dir", tmp_path)
    monkeypatch.setattr(anim, "enqueue", lambda p, front=False: anim._queued.add(p))
    from app.services import thumbs

    # 插入条目时封面监听已把封面排进真实的后台队列：让后台线程不真正渲染，并清空队列，避免和断言赛跑
    monkeypatch.setattr(thumbs, "ensure", lambda rel: None)
    monkeypatch.setattr(anim, "ensure", lambda rel: None)
    with anim._cv:
        anim._queue.clear()
        anim._queued.clear()
    _media(tmp_path)
    m = login_client("mediaboss@example.com", role="admin")
    o = m.get("/api/admin/cover-queue").json()
    assert o["thumb"] == {"done": 1, "queued": 0, "missing": 2} and o["anim"] == {"done": 0, "queued": 0, "missing": 1, "no_anim": 1}
    assert o["storage"]["thumb_bytes"] == 10 and o["covers"] == 3
    items = m.get("/api/admin/cover-queue/items?kind=thumb&status=missing").json()
    assert {x["item"]["name"] for x in items["items"]} == {"缺缩略图", "位图封面"}
    assert m.get("/api/admin/cover-queue/items?kind=anim&status=no_anim").json()["items"][0]["item"]["name"] == "有缩略图"
    r = m.post("/api/admin/cover-queue/retry-failed", json={"kind": "all", "reason": "补一下"}).json()
    assert r["queued"] == 2
    o = m.get("/api/admin/cover-queue").json()
    assert o["thumb"]["queued"] == 2
    with SessionLocal() as s:
        iid = s.scalar(select(Item.id).where(Item.name == "有缩略图"))
        bmp = s.scalar(select(Item.id).where(Item.name == "位图封面"))
    assert m.post(f"/api/admin/items/{bmp}/regenerate-cover", json={"kind": "anim", "reason": "重做"}).json()["detail"]["code"] == "no_anim"
    assert m.post(f"/api/admin/items/{iid}/regenerate-cover", json={"kind": "all", "reason": "重做"}).json()["queued"]
    assert not (tmp_path / "thumb" / "covers" / "a.svg.jpg").exists() and not (tmp_path / "anim" / "covers" / "a.svg.webp.none").exists()
    anim._queued.clear()


def test_client_versions_and_filter():
    m = login_client("mediaboss@example.com", role="admin")
    r = m.get("/api/admin/client-versions").json()
    mp = next(x for x in r["by_client"] if x["client"] == "miniprogram")
    assert [(v["version"], v["users"], v["sessions"]) for v in mp["versions"]] == [("1.1.0", 1, 1), ("1.2.0", 1, 2)]
    assert mp["versions"][1]["current_users"] == 1 and mp["versions"][0]["errors"] == 0
    ids = {x["id"] for x in m.get("/api/admin/users?client=miniprogram&client_version=1.1.0").json()["items"]}
    assert ids == {S["u2"]}
    r = m.post("/api/admin/users/bulk", json={"action": "disable", "reason": "测试筛选", "filter": {"client_version": "1.2.0"}, "total": 1})
    assert r.status_code == 200 and r.json()["results"][0]["id"] == S["u1"]
