"""v2.1（P3）：游客编号、行为上报、登录关联与转化、管理员访客分析、IP 中文归属地。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import Category, Event, EventDaily, Item, User, Visitor
from app.seed import seed_categories
from app.services import geo, visits
from conftest import login_client

VID = "v_test_visitor_0001"


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def fake_geo(monkeypatch):
    table = {"203.0.113.9": "中国 广东省 深圳市 电信", "198.51.100.7": "美国 加利福尼亚州 谷歌"}
    monkeypatch.setattr(geo, "lookup", lambda ip: table.get(ip, ""))


def admin_client():
    c = login_client("admin-p3@example.com")
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == "admin-p3@example.com"))
        u.role = "admin"
        s.commit()
    return c


def test_geo_pretty_and_private():
    assert geo._pretty("中国|0|广东省|深圳市|电信") == "中国 广东省 深圳市 电信"
    assert geo._pretty("中国|广东省|广州市|腾讯|CN") == "中国 广东省 广州市 腾讯"
    assert geo._pretty("中国|北京市|北京市|联通|CN") == "中国 北京市 联通"
    assert geo.lookup("127.0.0.1") == "本机"
    assert geo.lookup("192.168.3.4") == "局域网"
    assert geo.lookup("not-an-ip") == ""


def test_guest_events_recorded_with_ip_and_geo(monkeypatch):
    fake_geo(monkeypatch)
    c = TestClient(app)
    with SessionLocal() as s:
        cat = s.scalar(select(Category).where(Category.code == "coding-gen"))
        it = Item(name="探真条目", category_id=cat.id, status="published", summary="x", locked_fields=[], install_steps=[], source="manual")
        s.add(it)
        s.commit()
        item_id = it.id
    r = c.post("/api/t", headers={"X-Visitor-Id": VID, "X-Forwarded-For": "203.0.113.9", "User-Agent": "Mozilla/5.0 (iPhone) MicroMessenger"},
               json={"referrer": "https://example.com/", "landing": "/", "events": [
                   {"name": "page_view", "page": "/", "props": {"path": "/"}},
                   {"name": "search", "page": "/", "props": {"q": "H5 设计"}},
                   {"name": "item_view", "page": f"/items/{item_id}", "props": {"item_id": item_id}},
                   {"name": "register", "props": {}},  # 只能由服务端写，前端上报会被丢弃
                   {"name": "hack", "props": {}},
               ]})
    assert r.status_code == 204
    with SessionLocal() as s:
        v = s.get(Visitor, VID)
        assert v.last_ip == "203.0.113.9" and v.last_geo == "中国 广东省 深圳市 电信"
        assert v.device == "iPhone · 微信" and v.events == 3 and v.user_id is None
        names = sorted(e.name for e in s.scalars(select(Event).where(Event.vid == VID)))
        assert names == ["item_view", "page_view", "search"]


def test_invalid_vid_ignored():
    c = TestClient(app)
    r = c.post("/api/t", headers={"X-Visitor-Id": "bad id!"}, json={"events": [{"name": "page_view"}]})
    assert r.status_code == 204
    r = c.post("/api/t", content=b"not json")
    assert r.status_code == 204
    with SessionLocal() as s:
        assert s.get(Visitor, "bad id!") is None


def test_register_links_visitor_and_counts_conversion(monkeypatch):
    fake_geo(monkeypatch)
    with SessionLocal() as s:
        s.get(Visitor, VID).first_seen = utcnow() - timedelta(hours=1)
        s.commit()
    c = TestClient(app)
    h = {"X-Visitor-Id": VID, "X-Forwarded-For": "198.51.100.7"}
    from conftest import solve_pow

    ch = c.get("/api/auth/challenge").json()
    code = c.post("/api/auth/code", headers=h, json={"email": "newbie@example.com", "purpose": "login",
                                                     "pow_token": ch["token"], "pow_nonce": solve_pow(ch)})
    assert code.status_code == 200, code.text
    r = c.post("/api/auth/login/code", headers=h, json={"email": "newbie@example.com", "code": code.json()["dev_code"]})
    assert r.status_code == 200, r.text
    assert r.json()["is_new"] is True
    with SessionLocal() as s:
        v = s.get(Visitor, VID)
        u = s.scalar(select(User).where(User.email == "newbie@example.com"))
        assert v.user_id == u.id and v.converted_at is not None
        assert v.last_geo == "美国 加利福尼亚州 谷歌"
        assert s.scalar(select(Event).where(Event.vid == VID, Event.name == "register")).user_id == u.id


def test_admin_analytics(monkeypatch):
    fake_geo(monkeypatch)
    assert TestClient(app).get("/api/admin/analytics/overview").status_code == 401
    assert login_client("plain-p3@example.com").get("/api/admin/analytics/visitors").status_code == 403
    a = admin_client()
    ov = a.get("/api/admin/analytics/overview", params={"days": 7}).json()
    assert ov["today"]["uv"] >= 1 and ov["range"]["conversions"] == 1
    assert ov["top_searches"][0]["q"] == "H5 设计"
    assert ov["top_items"][0]["name"] == "探真条目"
    assert {"name": "美国", "count": 1} in ov["regions"]
    assert len(ov["series"]) == 7

    lst = a.get("/api/admin/analytics/visitors", params={"kind": "converted"}).json()
    assert lst["total"] == 1 and lst["items"][0]["user"]["email"] == "newbie@example.com"
    assert lst["items"][0]["first_geo"] == "中国 广东省 深圳市 电信" and lst["items"][0]["geo"] == "美国 加利福尼亚州 谷歌"
    assert a.get("/api/admin/analytics/visitors", params={"q": "newbie"}).json()["total"] == 1
    assert a.get("/api/admin/analytics/visitors", params={"q": "203.0.113"}).json()["total"] == 1

    d = a.get(f"/api/admin/analytics/visitors/{VID}").json()
    assert d["total"] == 4 and {x["ip"] for x in d["ips"]} == {"203.0.113.9", "198.51.100.7"}
    view = next(e for e in d["events"] if e["name"] == "item_view")
    assert view["item"]["name"] == "探真条目" and view["label"] == "查看详情" and view["geo"] == "中国 广东省 深圳市 电信"

    ev = a.get("/api/admin/analytics/events", params={"name": "search"}).json()
    assert ev["total"] == 1 and ev["items"][0]["props"]["q"] == "H5 设计"

    # 操作日志里的 IP 也带中文归属地
    feed = a.get("/api/admin/feed").json()["items"]
    reg = next(x for x in feed if x["action"] == "register")
    assert reg["ip"] == "198.51.100.7" and reg["geo"] == "美国 加利福尼亚州 谷歌"


def test_rollup_and_purge():
    with SessionLocal() as s:
        old = utcnow() - timedelta(days=1, hours=1)
        s.add(Event(vid=VID, name="page_view", category="view", props={}, page="/", ip="", geo="", created_at=old))
        s.add(Event(vid="v_other_visitor_01", name="page_view", category="view", props={}, page="/", ip="", geo="",
                    created_at=utcnow() - timedelta(days=200)))
        s.commit()
    visits.rollup(days=3)
    visits.rollup(days=3)  # 可重复执行，不会翻倍
    with SessionLocal() as s:
        rows = s.scalars(select(EventDaily).where(EventDaily.name == "page_view")).all()
        assert sum(r.count for r in rows) >= 1 and all(r.count < 10 for r in rows)
    assert visits.purge_old() == 1


def test_spoofed_forwarded_for_ignored():
    c = TestClient(app)
    c.post("/api/t", headers={"X-Visitor-Id": "v_spoof_check_01", "X-Forwarded-For": "1.2.3.4, 203.0.113.9"},
           json={"events": [{"name": "page_view"}]})
    with SessionLocal() as s:
        assert s.get(Visitor, "v_spoof_check_01").last_ip == "203.0.113.9"
