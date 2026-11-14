"""v3.3.57 后台批次 4c：单发站内消息、以用户视角只读查看、站内消息已读率。"""

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import ActivityLog, Category, Favorite, Item, User
from app.routers import user_care
from app.seed import seed_categories
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        u = User(email="care@example.com", nickname="小乙", role="user", status="active")
        s.add(u)
        s.flush()
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        it = Item(name="收藏的条目", category_id=cat.id, status="published")
        s.add(it)
        s.flush()
        s.add(Favorite(owner_id=u.id, item_id=it.id))
        s.commit()
        S.update(u=u.id)


def test_send_and_list_messages(monkeypatch):
    sup = login_client("care-support@example.com", role="support")
    mod = login_client("care-mod@example.com", role="moderator")
    r = mod.post(f"/api/admin/users/{S['u']}/messages", json={"title": "你好", "text": "测试", "reason": "回访用户"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_permission"
    assert sup.post(f"/api/admin/users/{S['u']}/messages", json={"title": "你好", "text": "x"}).json()["detail"]["code"] == "reason_required"
    assert sup.post(f"/api/admin/users/{S['u']}/messages", json={"title": "x", "text": "x", "reason": "回访", "link": "https://evil"}).json()["detail"]["code"] == "bad_link"
    m = sup.post(f"/api/admin/users/{S['u']}/messages", json={"title": "{nickname}你好", "text": "你的问题已处理", "reason": "回访用户",
                                                              "link": "/me?tab=feedback"}).json()
    assert m["title"] == "小乙你好" and m["by"]["label"] and m["read_at"] is None
    user = login_client("care@example.com")
    notes = user.get("/api/notifications").json()["items"]
    assert notes[0]["kind"] == "admin_message" and notes[0]["title"] == "小乙你好"
    user.post(f"/api/notifications/{notes[0]['id']}/read")
    lst = sup.get(f"/api/admin/users/{S['u']}/messages").json()
    assert lst["total"] == 1 and lst["items"][0]["read_at"] is not None
    st = sup.get("/api/admin/messages/stats").json()
    row = next(x for x in st["by_type"] if x["type"] == "admin_message")
    assert row["sent"] == 1 and row["read_rate"] == 1.0
    monkeypatch.setattr(user_care, "DAILY_LIMIT", 1)
    r = sup.post(f"/api/admin/users/{S['u']}/messages", json={"title": "再发", "text": "x", "reason": "回访用户"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"


def test_view_as_user(monkeypatch):
    sup = login_client("care-support@example.com", role="support")
    view = login_client("care-viewer@example.com", role="viewer")
    assert view.post(f"/api/admin/users/{S['u']}/view-sessions", json={"reason": "排查问题"}).status_code == 403
    assert sup.post(f"/api/admin/users/{S['u']}/view-sessions", json={"reason": "查"}).json()["detail"]["code"] == "reason_required"
    sid = sup.post(f"/api/admin/users/{S['u']}/view-sessions", json={"reason": "排查收藏问题"}).json()["session_id"]
    p = sup.get(f"/api/admin/users/{S['u']}/view/pocket", params={"session_id": sid}).json()
    assert p["total"] == 1 and p["items"][0]["item"]["name"] == "收藏的条目" and "email" not in str(p["user"])
    assert sup.get(f"/api/admin/users/{S['u']}/view/notifications", params={"session_id": sid}).json()["total"] >= 1
    assert sup.get(f"/api/admin/users/{S['u']}/view/nope", params={"session_id": sid}).status_code == 404
    # 别的管理员拿这个会话不行；看别的用户也不行
    boss = login_client("care-boss@example.com", role="admin")
    assert boss.get(f"/api/admin/users/{S['u']}/view/pocket", params={"session_id": sid}).json()["detail"]["code"] == "view_expired"
    assert sup.get(f"/api/admin/users/1/view/pocket", params={"session_id": sid}).json()["detail"]["code"] == "view_expired"
    monkeypatch.setattr(user_care, "VIEW_TTL", -1)
    assert sup.get(f"/api/admin/users/{S['u']}/view/pocket", params={"session_id": sid}).json()["detail"]["code"] == "view_expired"
    with SessionLocal() as s:
        n = s.scalar(select(ActivityLog).where(ActivityLog.action == "view_as_user", ActivityLog.reason == "排查收藏问题"))
        assert n is not None
