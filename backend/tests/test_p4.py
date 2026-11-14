"""P4：超级管理员 Admin 首次登录（有时限的窗口）+ 强制设置密码；子管理员任免与权限。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import AppMeta, User
from app.seed import seed_categories
from app.services import admin_setup
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def first_login(c: TestClient):
    return c.post("/api/auth/admin/first-login", json={"account": "admin"})


def test_first_login_closed_by_default():
    c = TestClient(app)
    assert first_login(c).status_code == 401
    assert c.post("/api/auth/admin/first-login", json={"account": "someone"}).status_code == 400


def test_first_login_window_and_forced_setup():
    admin_setup.open_window(1)
    c = TestClient(app)
    r = first_login(c)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["needs_setup"] is True
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    # 设置密码前不能用管理功能
    blocked = c.get("/api/admin/summary")
    assert blocked.status_code == 403 and blocked.headers.get("x-setup-required") == "1"
    assert c.post("/api/admin-setup/password", json={"password": "short"}).status_code == 400
    ok = c.post("/api/admin-setup/password", json={"password": "Admin2026pw"})
    assert ok.status_code == 200 and ok.json()["user"]["needs_setup"] is False
    assert c.get("/api/admin/summary").status_code == 200
    # 设置后首次登录永久关闭，只能用密码
    assert first_login(TestClient(app)).status_code == 401
    assert TestClient(app).post("/api/auth/login/password", json={"account": "admin", "password": "Admin2026pw"}).status_code == 200
    assert c.post("/api/admin-setup/password", json={"password": "Another2026"}).status_code == 400


def test_expired_window():
    with SessionLocal() as s:
        s.merge(AppMeta(key=admin_setup.DONE, value="0"))
        s.merge(AppMeta(key=admin_setup.UNTIL, value=(utcnow() - timedelta(minutes=1)).isoformat()))
        s.commit()
    assert first_login(TestClient(app)).status_code == 401
    admin_setup.complete()


def admin_client():
    from starlette.requests import Request

    from app import auth
    c = TestClient(app)
    with SessionLocal() as s:
        admin = s.scalar(select(User).where(User.username == "admin"))
        token = auth.create_session(s, admin, Request({"type": "http", "headers": [], "client": ("127.0.0.1", 0)}))
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_staff_management():
    sub = login_client("future.sub@example.com")
    assert sub.get("/api/admin/summary").status_code == 403
    a = admin_client()
    cands = a.get("/api/admin/staff/candidates", params={"q": "future"}).json()["items"]
    uid = next(u["id"] for u in cands if u["email"] == "future.sub@example.com")
    assert a.post("/api/admin/staff", json={"user_id": uid}).status_code == 400  # v3.3.55 必填原因
    assert a.post("/api/admin/staff", json={"user_id": uid, "reason": "补充人手"}).status_code == 200
    assert a.post("/api/admin/staff", json={"user_id": uid, "reason": "补充人手"}).status_code == 400

    # 子管理员：管理功能可用，但不能任免管理员
    assert sub.get("/api/admin/summary").status_code == 200
    assert sub.get("/api/admin/analytics/overview").status_code == 200
    assert sub.get("/api/admin/staff").status_code == 200
    assert sub.get("/api/admin/staff/candidates", params={"q": "future"}).status_code == 403
    other = login_client("other.user@example.com")
    with SessionLocal() as s:
        other_id = s.scalar(select(User.id).where(User.email == "other.user@example.com"))
    assert sub.post("/api/admin/staff", json={"user_id": other_id, "reason": "补充人手"}).status_code == 403
    assert other.get("/api/admin/summary").status_code == 403

    staff = a.get("/api/admin/staff").json()
    assert {u["role"] for u in staff} == {"admin", "subadmin"}
    # 超级管理员不能被取消；子管理员可以
    admin_id = next(u["id"] for u in staff if u["role"] == "admin")
    assert a.request("DELETE", f"/api/admin/staff/{admin_id}", json={"reason": "测试"}).status_code == 400
    assert a.request("DELETE", f"/api/admin/staff/{uid}", json={"reason": "测试"}).status_code == 200
    assert sub.get("/api/admin/summary").status_code == 403
    feed = a.get("/api/admin/activity", params={"action": "staff"}).json()
    assert feed["total"] == 2
