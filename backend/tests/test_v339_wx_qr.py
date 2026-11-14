"""v3.3.9 网页微信扫码：小程序码登录 / 绑定（含合并）。微信接口全部 mock。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import Category, Favorite, Item, User, WxQrLogin
from app.routers import wechat as wx_router
from app.seed import seed_categories
from app.services import wechat
from conftest import login_client

ITEM: list[int] = []


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        cat = s.scalar(select(Category).where(Category.parent_id.is_not(None)))
        it = Item(name="x", category_id=cat.id, status="published", locked_fields=[], install_steps=[])
        s.add(it)
        s.commit()
        ITEM.append(it.id)


@pytest.fixture(autouse=True)
def fake_wx(monkeypatch):
    monkeypatch.setattr(wechat, "ready", lambda: True)
    monkeypatch.setattr(wechat, "code2session", lambda code: {"openid": f"oid-{code}", "unionid": None})
    monkeypatch.setattr(wechat, "qr_image", lambda scene, page="pages/scan/index": f"data:image/png;base64,{scene}")
    wx_router._qr_hits.clear()


def wx(code: str) -> tuple[TestClient, dict]:
    c = TestClient(app)
    r = c.post("/api/auth/wx/login", json={"code": code}).json()
    c.headers["Authorization"] = f"Bearer {r['token']}"
    return c, r["user"]


def test_qr_login_flow():
    web = TestClient(app)
    q = web.post("/api/auth/wx/qr", json={"purpose": "login"}).json()
    assert q["expires_in"] == 600 and q["image"].endswith(q["token"]) and len(q["token"]) <= 32
    tok = q["token"]
    assert web.get(f"/api/auth/wx/qr/{tok}").json()["status"] == "pending"
    mp, wxu = wx("alice")
    assert mp.get(f"/api/auth/wx/qr/{tok}/info").json()["purpose"] == "login"
    assert mp.post(f"/api/auth/wx/qr/{tok}/scan").json()["status"] == "scanned"
    p = web.get(f"/api/auth/wx/qr/{tok}").json()
    assert p["status"] == "scanned" and p["scanner"]["nickname"] == wxu["nickname"]
    other, _ = wx("bob")
    assert other.post(f"/api/auth/wx/qr/{tok}/confirm").status_code == 409  # 别人扫过的码不能抢
    assert mp.post(f"/api/auth/wx/qr/{tok}/confirm").json()["status"] == "confirmed"
    r = web.get(f"/api/auth/wx/qr/{tok}").json()
    assert r["status"] == "confirmed" and r["user"]["id"] == wxu["id"] and r["user"]["wechat_bound"] is True
    web.headers["Authorization"] = f"Bearer {r['token']}"
    assert web.get("/api/auth/me").json()["user"]["id"] == wxu["id"]
    assert TestClient(app).get(f"/api/auth/wx/qr/{tok}").json()["status"] == "expired"  # 令牌只发一次
    assert mp.post(f"/api/auth/wx/qr/{tok}/confirm").status_code == 409


def test_qr_expired_and_cancel():
    web = TestClient(app)
    tok = web.post("/api/auth/wx/qr", json={"purpose": "login"}).json()["token"]
    mp, _ = wx("carol")
    assert mp.post(f"/api/auth/wx/qr/{tok}/cancel").json()["status"] == "canceled"
    assert web.get(f"/api/auth/wx/qr/{tok}").json()["status"] == "canceled"
    tok2 = web.post("/api/auth/wx/qr", json={"purpose": "login"}).json()["token"]
    with SessionLocal() as s:
        s.get(WxQrLogin, tok2).expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert web.get(f"/api/auth/wx/qr/{tok2}").json()["status"] == "expired"
    assert mp.post(f"/api/auth/wx/qr/{tok2}/scan").status_code == 410
    assert web.get("/api/auth/wx/qr/nope").status_code == 404
    # 邮箱账号不能扫码确认（必须是小程序微信登录）
    em = login_client("noqr@example.com")
    tok3 = web.post("/api/auth/wx/qr", json={"purpose": "login"}).json()["token"]
    assert em.post(f"/api/auth/wx/qr/{tok3}/scan").status_code == 400


def test_qr_bind_without_data():
    assert TestClient(app).post("/api/auth/wx/qr", json={"purpose": "bind"}).status_code == 401
    web = login_client("bind1@example.com")
    tok = web.post("/api/auth/wx/qr", json={"purpose": "bind"}).json()["token"]
    assert TestClient(app).get(f"/api/auth/wx/qr/{tok}").status_code == 403  # 只有发起绑定的人能轮询
    mp, wxu = wx("dave")
    info = mp.get(f"/api/auth/wx/qr/{tok}/info").json()
    assert info["purpose"] == "bind" and info["web_user"]["email"] == "bi***@example.com"
    r = mp.post(f"/api/auth/wx/qr/{tok}/confirm").json()
    assert r["status"] == "bound" and r["user"]["email"] == "bind1@example.com" and r["user"]["wechat_bound"]
    assert web.get(f"/api/auth/wx/qr/{tok}").json()["result"] == {"status": "bound"}
    assert mp.get("/api/auth/me").json().get("user") is None  # 小程序原来的微信小账号已并入，令牌作废
    mp.headers["Authorization"] = f"Bearer {r['token']}"
    assert mp.get("/api/auth/me").json()["user"]["email"] == "bind1@example.com"
    # 以后小程序用同一个微信登录，进的是邮箱账号
    _, again = wx("dave")
    assert again["email"] == "bind1@example.com"
    assert web.post("/api/auth/wx/qr", json={"purpose": "bind"}).status_code == 400  # 已绑定


def test_qr_bind_with_data_needs_merge_confirm():
    web = login_client("bind2@example.com")
    tok = web.post("/api/auth/wx/qr", json={"purpose": "bind"}).json()["token"]
    mp, wxu = wx("erin")
    with SessionLocal() as s:
        s.add(Favorite(owner_id=wxu["id"], item_id=ITEM[0]))
        s.commit()
    r = mp.post(f"/api/auth/wx/qr/{tok}/confirm").json()
    assert r["status"] == "merge" and r["preview"]["secondary"]["favorites"] == 1
    with SessionLocal() as s:
        assert s.get(User, wxu["id"]).status == "active"  # 预览阶段没有任何改动
    r = mp.post(f"/api/auth/wx/qr/{tok}/confirm", json={"merge": True}).json()
    assert r["status"] == "merged" and r["user"]["email"] == "bind2@example.com"
    with SessionLocal() as s:
        primary = s.scalar(select(User).where(User.email == "bind2@example.com"))
        assert s.scalar(select(Favorite).where(Favorite.owner_id == primary.id)) is not None
        assert s.get(User, wxu["id"]).status == "merged"


def test_qr_bind_rejects_wechat_with_other_email():
    a = login_client("bind3@example.com")
    tok = a.post("/api/auth/wx/qr", json={"purpose": "bind"}).json()["token"]
    mp, _ = wx("frank")
    b = login_client("bind4@example.com")
    tok_b = b.post("/api/auth/wx/qr", json={"purpose": "bind"}).json()["token"]
    mp.post(f"/api/auth/wx/qr/{tok_b}/confirm")  # frank 绑到 bind4
    mp2, _ = wx("frank")  # 重新登录拿到 bind4 的令牌
    assert mp2.post(f"/api/auth/wx/qr/{tok}/confirm").status_code == 409


def test_qr_rate_limit():
    c = TestClient(app)
    for _ in range(20):
        assert c.post("/api/auth/wx/qr", json={"purpose": "login"}).status_code == 200
    assert c.post("/api/auth/wx/qr", json={"purpose": "login"}).status_code == 429


def test_info_has_expires_in():
    """v3.3.17 info 带剩余秒数，客户端不用解析时间。"""
    web = TestClient(app)
    tok = web.post("/api/auth/wx/qr", json={"purpose": "login"}).json()["token"]
    mp, _ = wx("exp-in")
    info = mp.get(f"/api/auth/wx/qr/{tok}/info").json()
    assert 590 <= info["expires_in"] <= 600
