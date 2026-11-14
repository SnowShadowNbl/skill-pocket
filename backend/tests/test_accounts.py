"""v2.0-α 用户体系：验证码登录注册一体、限流、人机校验、密码、找回、设备、注销、权限与数据隔离。"""

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import Category, EmailCode, Item, User
from app.seed import seed_categories
from conftest import login_client, solve_pow


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        cat = s.scalar(select(Category).where(Category.code == "other-misc"))
        s.add(Item(name="x", category_id=cat.id, locked_fields=[], install_steps=[]))
        s.commit()


def pow_args(c: TestClient) -> dict:
    ch = c.get("/api/auth/challenge").json()
    return {"pow_token": ch["token"], "pow_nonce": solve_pow(ch)}


def get_code(c: TestClient, email: str, purpose: str = "login") -> str:
    r = c.post("/api/auth/code", json={"email": email, "purpose": purpose, **pow_args(c)})
    assert r.status_code == 200, r.text
    return r.json()["dev_code"]


def allow_resend(email: str):
    """跳过 60 秒重发间隔（把上一条验证码的时间往前挪）。"""
    from datetime import timedelta
    with SessionLocal() as s:
        for rec in s.scalars(select(EmailCode).where(EmailCode.email == email)):
            rec.created_at = rec.created_at - timedelta(minutes=5)
        s.commit()


def test_code_login_registers_then_logs_in():
    c = TestClient(app)
    code = get_code(c, "New.User@Example.com")
    r = c.post("/api/auth/login/code", json={"email": "new.user@example.com", "code": code})
    assert r.status_code == 200 and r.json()["is_new"] is True
    assert r.json()["user"]["nickname"] == "new.user" and r.json()["user"]["has_password"] is False
    token = r.json()["token"]
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"]["email"] == "new.user@example.com"
    # 验证码一次性
    assert c.post("/api/auth/login/code", json={"email": "new.user@example.com", "code": code}).status_code == 400
    allow_resend("new.user@example.com")
    code2 = get_code(c, "new.user@example.com")
    assert c.post("/api/auth/login/code", json={"email": "new.user@example.com", "code": code2}).json()["is_new"] is False


def test_code_rules():
    c = TestClient(app)
    # 人机校验必须通过、不能复用
    bad = c.post("/api/auth/code", json={"email": "a@b.cn", "pow_token": "x", "pow_nonce": "1"})
    assert bad.status_code == 400
    args = pow_args(c)
    assert c.post("/api/auth/code", json={"email": "rules@example.com", **args}).status_code == 200
    assert c.post("/api/auth/code", json={"email": "rules2@example.com", **args}).status_code == 400
    # 60 秒内不能重发
    r = c.post("/api/auth/code", json={"email": "rules@example.com", **pow_args(c)})
    assert r.status_code == 429 and "秒后" in r.json()["detail"]
    # 输错 5 次作废
    for _ in range(5):
        assert c.post("/api/auth/login/code", json={"email": "rules@example.com", "code": "000000"}).status_code == 400
    with SessionLocal() as s:
        real = s.scalar(select(EmailCode).where(EmailCode.email == "rules@example.com"))
        assert real.attempts == 5
    assert c.post("/api/auth/code", json={"email": "bad-email", **pow_args(c)}).status_code == 400
    # 没注册的邮箱不能找回密码
    assert c.post("/api/auth/code", json={"email": "nobody@example.com", "purpose": "reset", **pow_args(c)}).status_code == 400


def test_password_set_change_reset_and_sessions():
    c = login_client("pw@example.com")
    assert c.post("/api/auth/password", json={"new_password": "12345678"}).status_code == 400  # 太简单
    assert c.post("/api/auth/password", json={"new_password": "pocket2026"}).status_code == 200
    # 第二个设备登录
    other = TestClient(app)
    r = other.post("/api/auth/login/password", json={"account": "PW@example.com", "password": "pocket2026"})
    assert r.status_code == 200
    other.headers["Authorization"] = f"Bearer {r.json()['token']}"
    devices = c.get("/api/auth/sessions").json()
    assert len(devices) == 2 and sum(d["current"] for d in devices) == 1
    # 改密码要旧密码；改完其他设备退出
    assert c.post("/api/auth/password", json={"new_password": "pocket2027"}).status_code == 400
    assert c.post("/api/auth/password", json={"new_password": "pocket2027", "old_password": "wrong"}).status_code == 400
    assert c.post("/api/auth/password", json={"new_password": "pocket2027", "old_password": "pocket2026"}).status_code == 200
    assert other.get("/api/auth/me").json()["user"] is None
    assert c.get("/api/auth/me").json()["user"] is not None
    # 找回密码
    anon = TestClient(app)
    code = get_code(anon, "pw@example.com", "reset")
    r = anon.post("/api/auth/password/reset", json={"email": "pw@example.com", "code": code, "new_password": "reset2028"})
    assert r.status_code == 200 and r.json()["token"]
    assert c.get("/api/auth/me").json()["user"] is None  # 找回后所有旧会话失效
    assert anon.post("/api/auth/login/password", json={"account": "pw@example.com", "password": "reset2028"}).status_code == 200


def test_admin_password_login_and_admin_rights():
    from app import auth
    with SessionLocal() as s:
        s.execute(update(User).where(User.username == "admin").values(password_hash=auth.hash_password("admin-pass-1")))
        s.commit()
    c = TestClient(app)
    r = c.post("/api/auth/login/password", json={"account": "admin", "password": "admin-pass-1"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    item_id = TestClient(app).get("/api/items").json()["items"][0]["id"]
    # admin 会话可以直接做管理操作（不再需要单独输管理员密码）
    assert c.put(f"/api/items/{item_id}", json={"summary": "admin edit"}).status_code == 200
    assert login_client("plain@example.com").put(f"/api/items/{item_id}", json={"summary": "x"}).status_code == 403


def test_comments_permissions_and_display():
    item_id = TestClient(app).get("/api/items").json()["items"][0]["id"]
    assert TestClient(app).post(f"/api/items/{item_id}/comments", json={"content": "hi"}).status_code == 401
    alice, bob = login_client("alice@example.com"), login_client("bob@example.com")
    cid = alice.post(f"/api/items/{item_id}/comments", json={"content": "好用"}).json()["id"]
    lst = bob.get(f"/api/items/{item_id}/comments").json()
    mine = next(x for x in lst if x["id"] == cid)
    assert mine["author"]["nickname"] == "alice" and "email" not in mine["author"] and mine["can_delete"] is False
    assert bob.delete(f"/api/comments/{cid}").status_code == 403
    assert alice.delete(f"/api/comments/{cid}").status_code == 200


def test_favorites_are_per_user_and_guests_cannot():
    item_id = TestClient(app).get("/api/items").json()["items"][0]["id"]
    a, b = login_client("fa@example.com"), login_client("fb@example.com")
    a.post(f"/api/items/{item_id}/favorite", json={"on": True})
    assert a.get("/api/items?fav=1").json()["total"] == 1
    assert b.get("/api/items?fav=1").json()["total"] == 0
    assert b.get(f"/api/items/{item_id}").json()["favorited"] is False
    assert TestClient(app).get("/api/items?fav=1").status_code == 401
    assert TestClient(app).get("/api/favorites/structure").status_code == 401


def test_logs_and_tasks_are_scoped():
    from app.services import tracking
    a, b = login_client("la@example.com"), login_client("lb@example.com")
    with SessionLocal() as s:
        ua = s.scalar(select(User).where(User.email == "la@example.com"))
    tracking.log(trigger="github", stage="repo", level="error", message="a 的日志", user_id=ua.id)
    tracking.create_task("github", "a 的任务", [], user_id=ua.id)
    # v3.2：入库日志只对管理员开放
    assert a.get("/api/logs").status_code == 403 and b.get("/api/logs").status_code == 403
    adm = login_client("ladm@example.com", role="admin")
    assert any(x["message"] == "a 的日志" for x in adm.get("/api/logs").json()["items"])
    assert TestClient(app).get("/api/logs").status_code == 401
    assert all(t["title"] != "a 的任务" for t in b.get("/api/tasks").json()["items"])
    assert TestClient(app).get("/api/tasks/active").json() == []


def test_delete_account_keeps_comments_anonymous():
    c = login_client("bye@example.com")
    item_id = c.get("/api/items").json()["items"][0]["id"]
    cid = c.post(f"/api/items/{item_id}/comments", json={"content": "再见"}).json()["id"]
    c.post(f"/api/items/{item_id}/favorite", json={"on": True})
    code = get_code(c, "", "delete")
    assert c.post("/api/auth/delete", json={"code": code}).status_code == 200
    assert c.get("/api/auth/me").json()["user"] is None
    lst = TestClient(app).get(f"/api/items/{item_id}/comments").json()
    assert next(x for x in lst if x["id"] == cid)["author"]["nickname"] == "已注销用户"
    # 邮箱释放，可以重新注册
    anon = TestClient(app)
    code = get_code(anon, "bye@example.com")
    assert anon.post("/api/auth/login/code", json={"email": "bye@example.com", "code": code}).json()["is_new"] is True
