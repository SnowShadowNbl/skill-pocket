"""v3.3.71 后台批次 7b：用户标签、小范围公告、首页运营位、分类订阅人数。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import Category, CategorySubscription, Notification, User
from app.seed import seed_categories
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        a = User(email="t1@example.com", nickname="内测甲", role="user", status="active", signup_channel="miniprogram")
        b = User(email="t2@example.com", nickname="内测乙", role="user", status="active", signup_channel="web-pc")
        c = User(email="t3@example.com", nickname="停用丙", role="user", status="disabled", signup_channel="miniprogram")
        s.add_all([a, b, c])
        s.flush()
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        s.add_all([CategorySubscription(user_id=a.id, category_id=cat.id), CategorySubscription(user_id=b.id, category_id=cat.id)])
        s.commit()
        S.update(a=a.id, b=b.id, c=c.id, cat=cat.id)


def test_tags():
    m = login_client("opboss@example.com", role="admin")
    t = m.post("/api/admin/tags", json={"name": "内测用户", "color": "green"}).json()
    assert m.post("/api/admin/tags", json={"name": "内测用户"}).json()["detail"]["code"] == "duplicate"
    S["tag"] = t["id"]
    r = m.put(f"/api/admin/users/{S['a']}/tags", json={"tag_ids": [t["id"]]}).json()
    assert r["tags"][0]["name"] == "内测用户"
    b = m.post("/api/admin/users/bulk", json={"action": "add_tag", "tag_id": t["id"], "reason": "批量加内测标签", "ids": [S["a"], S["b"], S["c"]]}).json()
    assert {x["id"]: x["code"] for x in b["results"]} == {S["a"]: "noop", S["b"]: "ok", S["c"]: "ok"}
    lst = m.get(f"/api/admin/users?tag={t['id']}").json()
    assert {x["id"] for x in lst["items"]} == {S["a"], S["b"], S["c"]} and lst["items"][0]["tags"][0]["id"] == t["id"]
    assert m.get("/api/admin/tags").json()["items"][0]["users"] == 3
    m.post("/api/admin/users/bulk", json={"action": "remove_tag", "tag_id": t["id"], "reason": "去掉内测标签", "ids": [S["c"]]})
    assert S["c"] not in {x["id"] for x in m.get(f"/api/admin/users?tag={t['id']}").json()["items"]}
    assert S["c"] in {x["id"] for x in m.get("/api/admin/users?tag=none").json()["items"]}


def test_announcements():
    m = login_client("opboss@example.com", role="admin")
    a = m.post("/api/admin/announcements", json={"title": "内测邀请", "text": "欢迎参加新功能内测", "link": "/me",
                                                 "audience": {"tag_ids": [S["tag"]], "channels": ["miniprogram"]}}).json()
    assert a["status"] == "draft" and "内测用户" in a["audience_label"]
    pv = m.post(f"/api/admin/announcements/{a['id']}/preview").json()
    assert pv["count"] == 1 and pv["sample"][0]["id"] == S["a"]  # 标签与渠道取交集，停用的不发
    assert m.post(f"/api/admin/announcements/{a['id']}/send", json={"reason": "发送", "expected_count": 5}).json()["detail"]["code"] == "count_changed"
    out = m.post(f"/api/admin/announcements/{a['id']}/send", json={"reason": "内测开始", "expected_count": 1}).json()
    assert out["status"] == "sent" and out["recipients"] == 1 and out["read"] == 0 and out["read_rate"] == 0.0
    assert m.post(f"/api/admin/announcements/{a['id']}/send", json={"reason": "再发"}).status_code == 409
    with SessionLocal() as s:
        n = s.scalar(select(Notification).where(Notification.announcement_id == a["id"]))
        n.read_at = utcnow()
        s.commit()
    assert m.get("/api/admin/announcements").json()["items"][0]["read_rate"] == 1.0
    assert m.post("/api/admin/announcements", json={"title": "x", "text": "y", "link": "https://evil"}).json()["detail"]["code"] == "bad_link"
    empty = m.post("/api/admin/announcements", json={"title": "空", "text": "没人", "audience": {}}).json()
    assert m.post(f"/api/admin/announcements/{empty['id']}/send", json={"reason": "试试"}).json()["detail"]["code"] == "empty_audience"
    assert m.delete(f"/api/admin/announcements/{empty['id']}").json()["ok"]


def test_home_config_and_subscriptions():
    m = login_client("opboss@example.com", role="admin")
    pub = TestClient(app)
    assert pub.get("/api/home-config").json() == {"banner": None, "search_placeholders": [], "onboarding_enabled": True}
    assert m.put("/api/admin/home-config", json={"onboarding_enabled": False}).json()["detail"]["code"] == "reason_required"
    later = (utcnow() + timedelta(days=1)).isoformat()
    r = m.put("/api/admin/home-config", json={"banner": {"enabled": True, "text": "明天上新功能", "link": "/rankings", "starts_at": later},
                                               "search_placeholders": ["会议纪要", " ", "PPT 生成"], "onboarding_enabled": False,
                                               "reason": "运营活动"}).json()
    assert r["search_placeholders"] == ["会议纪要", "PPT 生成"] and r["banner_live"] is False  # 还没到开始时间
    p = pub.get("/api/home-config").json()
    assert p["banner"] is None and p["onboarding_enabled"] is False and p["search_placeholders"] == ["会议纪要", "PPT 生成"]
    r = m.put("/api/admin/home-config", json={"banner": {"enabled": True, "text": "今天上新功能", "link": "/rankings"}, "reason": "提前"}).json()
    assert r["banner_live"] and pub.get("/api/home-config").json()["banner"]["text"] == "今天上新功能"
    assert m.put("/api/admin/home-config", json={"banner": {"enabled": True, "text": ""}, "reason": "空的"}).json()["detail"]["code"] == "empty_banner"
    st = m.get("/api/admin/subscriptions/stats").json()
    assert st["subscribers"] == 2 and st["items"][0]["subscribers"] == 2
    sup = login_client("opsup@example.com", role="support")
    assert sup.get("/api/admin/announcements").status_code == 403


def test_banner_times_without_timezone():
    """v3.3.72 修复：前端传不带时区的北京时间，存进去后首页接口不能 500。"""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    m = login_client("opboss@example.com", role="admin")
    pub = TestClient(app)
    cn = ZoneInfo("Asia/Shanghai")
    past = (datetime.now(cn) - timedelta(hours=1)).replace(tzinfo=None).isoformat(timespec="minutes")
    future = (datetime.now(cn) + timedelta(hours=2)).replace(tzinfo=None).isoformat(timespec="minutes")
    r = m.put("/api/admin/home-config", json={"banner": {"enabled": True, "text": "限时横幅", "starts_at": past, "ends_at": future},
                                               "reason": "定时横幅"})
    assert r.status_code == 200 and r.json()["banner_live"]
    stored = datetime.fromisoformat(r.json()["banner"]["starts_at"])
    assert stored.tzinfo is not None and stored.utcoffset() == timedelta(0)
    assert m.get("/api/admin/home-config").status_code == 200
    assert pub.get("/api/home-config").json()["banner"]["text"] == "限时横幅"
    # 坏数据也不能让首页报错
    import json

    from app.models import AppMeta

    with SessionLocal() as s:
        s.merge(AppMeta(key="home_config", value=json.dumps({"banner": {"enabled": True, "text": "坏", "starts_at": "2026-11-14T01:00"}})))
        s.commit()
    assert pub.get("/api/home-config").status_code == 200
    assert m.get("/api/admin/home-config").status_code == 200
    with SessionLocal() as s:
        s.merge(AppMeta(key="home_config", value=json.dumps({"banner": {"enabled": True, "text": "坏", "starts_at": "不是时间"}})))
        s.commit()
    assert pub.get("/api/home-config").json()["banner"] is None


def test_user_detail_has_tags():
    m = login_client("opboss@example.com", role="admin")
    d = m.get(f"/api/admin/users/{S['a']}").json()
    assert [t["id"] for t in d["tags"]] == [S["tag"]]
