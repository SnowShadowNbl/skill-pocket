"""v3.3.55 后台批次 4b：角色权限、管理员任免、登录记录与新设备提醒、高危操作二次验证、管理端扫码登录。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import Notification, User, WxQrLogin
from app.seed import seed_categories
from app.services import permissions
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        u = User(email="plain@example.com", nickname="普通人", role="user", status="active")
        wx = User(nickname="纯微信", role="user", status="active", wx_openid="oid-role-1")
        s.add_all([u, wx])
        s.commit()
        S.update(plain=u.id, wx=wx.id)


def _uid(email):
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.email == email))


def test_matrix_and_me():
    for role in ("moderator", "support", "viewer"):
        c = login_client(f"{role}@example.com", role=role)
        me = c.get("/api/auth/me").json()
        me = me.get("user", me)
        assert me["role"] == role and me["permissions"] == permissions.permissions(role) and "role_label" in me
    sup = login_client("support@example.com", role="support")
    view = login_client("viewer@example.com", role="viewer")
    mod = login_client("moderator@example.com", role="moderator")
    # 客服：能看反馈和用户，不能看内容审核以外的模块、不能停用用户、不能导出
    assert sup.get("/api/admin/feedback").status_code == 200
    r = sup.get("/api/admin/takedowns")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_permission" and "客服" in r.json()["detail"]["message"]
    assert sup.get("/api/admin/users").status_code == 200
    assert sup.post(f"/api/admin/users/{S['plain']}/status", json={"status": "disabled", "reason": "测试测试"}).status_code == 403
    assert sup.get("/api/admin/users/export").status_code == 403
    # 只读：能看不能改
    assert view.get("/api/admin/comments").status_code == 200
    assert view.post("/api/admin/blocklist", json={"kind": "owner", "value": "x", "reason": "测试"}).status_code == 403
    assert view.get("/api/admin/staff").status_code == 403
    # 内容审核：能改黑名单，反馈只读，前台不能删别人的评论以外的事不受影响
    assert mod.post("/api/admin/blocklist", json={"kind": "owner", "value": "spam-owner", "reason": "测试"}).status_code == 200
    assert mod.patch("/api/admin/feedback/1", json={"priority": "P1"}).status_code == 403
    # 所有角色都能用的：概览角标、全局搜索
    for c in (sup, view, mod):
        assert c.get("/api/admin/summary").status_code == 200 and c.get("/api/admin/search?q=ab").status_code == 200
    # 反馈可指派的人：有反馈修改权限的角色
    roles = {x["role"] for x in sup.get("/api/admin/feedback/assignees").json()["items"]}
    assert "support" in roles and "moderator" not in roles and "viewer" not in roles


def test_staff_and_verify(monkeypatch):
    boss = login_client("boss@example.com", role="admin")
    # 纯微信账号也能当候选人
    cands = {x["id"] for x in boss.get("/api/admin/staff/candidates?q=纯微信").json()["items"]}
    assert S["wx"] in cands
    monkeypatch.setattr(settings, "admin_verify_required", True)
    r = boss.post("/api/admin/staff", json={"user_id": S["wx"], "role": "support", "reason": "客服人手"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "verify_required"
    code = boss.post("/api/admin/verify/request", json={"action": "staff_role"}).json()["dev_code"]
    bad = boss.post("/api/admin/verify/confirm", json={"action": "staff_role", "code": "000000" if code != "000000" else "111111"})
    assert bad.json()["detail"]["code"] == "bad_code"
    # 换一个超管账号，避开验证码重发冷却
    boss2 = login_client("boss2@example.com", role="admin")
    c2 = boss2.post("/api/admin/verify/request", json={"action": "staff_role"}).json()["dev_code"]
    tok = boss2.post("/api/admin/verify/confirm", json={"action": "staff_role", "code": c2}).json()["token"]
    h = {"X-Verify-Token": tok}
    out = boss2.post("/api/admin/staff", json={"user_id": S["wx"], "role": "support", "reason": "客服人手"}, headers=h).json()
    assert out["role"] == "support" and out["role_label"] == "客服"
    # 令牌和动作绑定：拿去删用户不行
    assert boss2.delete(f"/api/admin/users/{S['plain']}", headers=h).json()["detail"]["code"] == "verify_required"
    assert boss2.put(f"/api/admin/staff/{S['wx']}/role", json={"role": "viewer", "reason": "调岗"}, headers=h).json()["role"] == "viewer"
    assert boss2.put(f"/api/admin/staff/{S['wx']}/role", json={"role": "admin", "reason": "升级"}, headers=h).json()["detail"]["code"] == "bad_role"
    me_id = _uid("boss2@example.com")
    assert boss2.put(f"/api/admin/staff/{me_id}/role", json={"role": "viewer", "reason": "降级"}, headers=h).json()["detail"]["code"] == "cannot_change_super"
    assert boss2.request("DELETE", f"/api/admin/staff/{S['wx']}", json={"reason": "不需要了"}, headers=h).json()["ok"]
    # 没有邮箱的管理员不能发验证码
    with SessionLocal() as s:
        s.get(User, S["wx"]).role = "subadmin"
        s.commit()
    from app.auth import create_session
    from starlette.requests import Request

    with SessionLocal() as s:
        t = create_session(s, s.get(User, S["wx"]), Request({"type": "http", "headers": [], "client": ("1.2.3.4", 0)}))
    wxc = TestClient(app)
    wxc.headers["Authorization"] = f"Bearer {t}"
    assert wxc.post("/api/admin/verify/request", json={"action": "delete_user"}).json()["detail"]["code"] == "no_email"
    roles = boss2.get("/api/admin/staff-roles").json()
    assert set(roles["roles"]) == {"subadmin", "moderator", "support", "viewer"} and roles["matrix"]["viewer"]["content"] == "r"
    assert isinstance(boss2.get("/api/admin/staff").json(), list)


def test_logins_new_device():
    from app.auth import create_session
    from starlette.requests import Request

    uid = _uid("boss@example.com")

    def req(ua, ip):
        return Request({"type": "http", "headers": [(b"user-agent", ua.encode())], "client": (ip, 0)})

    with SessionLocal() as s:
        u = s.get(User, uid)
        create_session(s, u, req("Mozilla/5.0 (Windows) Chrome/120", "10.1.2.3"))
        create_session(s, u, req("Mozilla/5.0 (Windows) Chrome/120", "10.1.9.9"))  # 同网段：不算新设备
        create_session(s, u, req("Mozilla/5.0 (iPhone) MicroMessenger", "8.8.8.8"))  # 新设备
    boss = login_client("boss@example.com", role="admin")
    items = boss.get(f"/api/admin/staff/{uid}/logins").json()["items"]
    by_ip = {x["ip"]: x for x in items}
    assert by_ip["8.8.8.8"]["new_device"] and by_ip["8.8.8.8"]["device"].startswith("iPhone")
    assert not by_ip["10.1.9.9"]["new_device"]  # 同一设备、同一网段
    assert boss.get("/api/admin/me/logins").json()["items"]
    with SessionLocal() as s:
        assert s.scalar(select(Notification).where(Notification.user_id == uid, Notification.title.like("%新设备%"))) is not None
    sup = login_client("support@example.com", role="support")
    assert sup.get(f"/api/admin/staff/{uid}/logins").status_code == 403
    assert sup.get("/api/admin/me/logins").status_code == 200


def test_admin_qr_only_staff(monkeypatch):
    from app.services import wechat as wx

    monkeypatch.setattr(wx, "qr_image", lambda token: "data:image/png;base64,xx")
    c = TestClient(app)
    tok = c.post("/api/auth/wx/qr", json={"purpose": "login", "admin": True}).json()["token"]
    with SessionLocal() as s:
        q = s.scalar(select(WxQrLogin).where(WxQrLogin.token == tok))
        q.status, q.wx_user_id = "confirmed", S["plain"]
        s.commit()
    r = c.get(f"/api/auth/wx/qr/{tok}")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_staff"
    tok2 = c.post("/api/auth/wx/qr", json={"purpose": "login", "admin": True}).json()["token"]
    with SessionLocal() as s:
        q = s.scalar(select(WxQrLogin).where(WxQrLogin.token == tok2))
        q.status, q.wx_user_id = "confirmed", S["wx"]  # 现在是 subadmin
        s.commit()
    r = c.get(f"/api/auth/wx/qr/{tok2}").json()
    assert r["status"] == "confirmed" and r["token"] and r["user"]["permissions"]["users"] == "w"
