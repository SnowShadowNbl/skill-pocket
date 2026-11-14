"""v3.3.52 后台批次 4a：反馈工单。"""

from datetime import timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import Feedback, Notification, User
from app.seed import seed_categories
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        u = User(email="fbuser@example.com", nickname="小甲", role="user", status="active")
        s.add(u)
        s.flush()
        now = utcnow()
        a = Feedback(user_id=u.id, category="bug", content="首页搜索框被挡住了", priority="P0", created_at=now - timedelta(hours=5))
        b = Feedback(user_id=u.id, category="feature", content="希望支持导出", priority="P2")
        c = Feedback(category="other", content="匿名反馈", contact_email="x@y.com")
        s.add_all([a, b, c])
        s.commit()
        a.ai_analysis = {"similar_ids": [b.id]}
        s.commit()
        S.update(u=u.id, a=a.id, b=b.id, c=c.id)


def test_list_overdue_and_flow():
    m = login_client("fbboss@example.com", role="admin")
    sub = login_client("fbsub@example.com", role="subadmin")
    with SessionLocal() as s:
        S["sub"] = s.scalar(select(User.id).where(User.email == "fbsub@example.com"))
    r = m.get("/api/admin/feedback").json()
    assert r["items"][0]["id"] == S["a"] and r["items"][0]["overdue"] and r["counts"]["overdue"] == 1 and r["counts"]["unassigned"] == 3
    assert m.get("/api/admin/feedback?overdue=1").json()["total"] == 1
    assert {x["id"] for x in m.get("/api/admin/feedback?status=new,processing&q=导出").json()["items"]} == {S["b"]}
    # 指派给子管理员 → 自动变为处理中
    x = m.post(f"/api/admin/feedback/{S['a']}/assign", json={"assignee_id": S["sub"], "expected_status": "new"}).json()
    assert x["assignee"]["id"] == S["sub"] and x["status"] == "processing"
    assert sub.get("/api/admin/feedback?assignee=me").json()["total"] == 1
    assert m.post(f"/api/admin/feedback/{S['a']}/assign", json={"assignee_id": S["u"]}).json()["detail"]["code"] == "bad_assignee"
    # 回复（模板变量）→ 首次响应、通知
    rr = sub.patch(f"/api/admin/feedback/{S['a']}", json={"reply": "{nickname}你好，#{id} 已修复", "status": "resolved"}).json()
    assert rr["notified"] and rr["first_response_at"] and rr["resolve_s"] and rr["admin_reply"] == f"小甲你好，#{S['a']} 已修复"
    # 并发：按旧状态再处理
    c = m.patch(f"/api/admin/feedback/{S['a']}", json={"status": "wontfix", "expected_status": "processing"})
    assert c.status_code == 409 and c.json()["detail"]["code"] == "already_handled"
    # 不允许的流转、重新打开需要原因
    assert m.patch(f"/api/admin/feedback/{S['a']}", json={"status": "new"}).json()["detail"]["code"] == "bad_transition"
    assert m.patch(f"/api/admin/feedback/{S['a']}", json={"status": "processing"}).json()["detail"]["code"] == "reason_required"
    ro = m.patch(f"/api/admin/feedback/{S['a']}", json={"status": "processing", "reason": "用户说还有问题"}).json()
    assert ro["status"] == "processing" and ro["resolved_at"] is None
    with SessionLocal() as s:
        assert s.scalar(select(Notification).where(Notification.kind == "feedback_reply")).link == "/me?tab=feedback"
    logs = m.get(f"/api/admin/activity?target_type=feedback&target_id={S['a']}").json()
    assert logs["total"] >= 3


def test_reply_multipart_and_notes_related():
    m = login_client("fbboss@example.com", role="admin")
    sub = login_client("fbsub@example.com", role="subadmin")
    r = m.post(f"/api/admin/feedback/{S['b']}/replies", data={"text": "收到", "status": "processing"}).json()
    assert r["status"] == "processing" and r["notified"]
    anon = m.post(f"/api/admin/feedback/{S['c']}/replies", data={"text": "收到", "status": "resolved"}).json()
    assert anon["notified"] is False
    n = sub.post(f"/api/admin/feedback/{S['b']}/notes", json={"text": "先排查一下导出接口"}).json()["notes"]
    assert n[0]["by"]["id"] == S["sub"]
    m2 = login_client("fbsub2@example.com", role="subadmin")
    assert m2.delete(f"/api/admin/feedback/{S['b']}/notes/{n[0]['id']}").json()["detail"]["code"] == "forbidden"
    assert m.delete(f"/api/admin/feedback/{S['b']}/notes/{n[0]['id']}").json()["notes"] == []  # 超管可删
    d = m.get(f"/api/admin/feedback/{S['b']}").json()
    assert d["notes"] == [] and d["assignee"] is None
    rel = m.get(f"/api/admin/feedback/{S['a']}/related").json()
    assert rel["user"]["id"] == S["u"] and [x["id"] for x in rel["user_feedbacks"]] == [S["b"]]
    assert [x["id"] for x in rel["similar"]] == [S["b"]] and rel["client_errors"] == []


def test_bulk_stats_templates():
    m = login_client("fbboss@example.com", role="admin")
    sub = login_client("fbsub@example.com", role="subadmin")
    r = m.post("/api/admin/feedback/bulk", json={"action": "close", "ids": [S["c"], S["b"], 9999]}).json()
    codes = {x["id"]: x["code"] for x in r["results"]}
    assert codes[S["c"]] == "ok" and codes[S["b"]] == "ok" and codes[9999] == "not_found"
    r = m.post("/api/admin/feedback/bulk", json={"action": "close", "ids": [S["c"]]}).json()
    assert r["results"][0]["code"] == "noop"
    r = m.post("/api/admin/feedback/bulk", json={"action": "priority", "params": {"priority": "P1"}, "filter": {"status": "processing"}, "total": 9})
    assert r.status_code == 409
    st = m.get("/api/admin/feedback/stats").json()
    assert st["total"] == 3 and st["by_status"]["closed"] == 2 and st["avg_first_response_s"] is not None
    assert any(x["user"]["id"] == S["sub"] for x in st["by_assignee"])
    t = sub.get("/api/admin/reply-templates?scope=feedback_reply").json()
    assert len(t["items"]) == 3 and t["max"] == 30
    assert sub.post("/api/admin/reply-templates", json={"scope": "feedback_reply", "title": "x", "text": "y"}).status_code == 403
    nt = m.post("/api/admin/reply-templates", json={"scope": "user_message", "title": "欢迎", "text": "{nickname}欢迎"}).json()
    assert m.put(f"/api/admin/reply-templates/{nt['id']}", json={"title": "欢迎回来"}).json()["title"] == "欢迎回来"
    assert m.delete(f"/api/admin/reply-templates/{nt['id']}").json()["ok"]
    # 用户侧能看到「已关闭」
    u = login_client("fbuser@example.com")
    mine = u.get("/api/me/feedback").json()
    items = mine["items"] if isinstance(mine, dict) else mine
    assert any(x["status_label"] == "已关闭" for x in items)
