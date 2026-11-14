"""v3.3.40 后台「账号关系」：账号构成、渠道、趋势、扫码漏斗、单个用户的绑定关系、按登录方式 / 渠道筛选、绑定冲突留痕。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import ActivityLog, User, WxQrLogin
from app.seed import seed_categories
from app.services import activity, wechat
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        mail = User(email="m1@example.com", nickname="邮箱甲", role="user", status="active", signup_channel="web-pc")
        wx = User(nickname="微信乙", role="user", status="active", wx_openid="oid-acct-1", signup_channel="miniprogram")
        both = User(email="b1@example.com", nickname="双绑丙", role="user", status="active", wx_openid="oid-acct-2")
        s.add_all([mail, wx, both])
        s.flush()
        gone = User(nickname="并入丁", role="user", status="merged", wx_openid="oid-acct-3", merged_into=both.id)
        s.add(gone)
        now = utcnow()
        for st, exp in (("pending", now + timedelta(minutes=5)), ("pending", now - timedelta(minutes=1)), ("scanned", now - timedelta(minutes=1)),
                        ("done", now), ("canceled", now)):
            s.add(WxQrLogin(token=f"t{st}{exp.timestamp():.0f}"[:22], purpose="login", status=st, result={}, created_at=now, expires_at=exp))
        s.add(WxQrLogin(token="bindtok1", purpose="bind", status="done", web_user_id=both.id, wx_user_id=gone.id, result={}, created_at=now,
                        expires_at=now + timedelta(minutes=5)))
        s.commit()
        activity.record("merge_account", "合并测试", user=both, target_type="user", target_id=gone.id)
        activity.record("bind_wechat", "绑定测试", user=both)


def test_overview():
    admin = login_client("acctboss@example.com", role="admin")
    o = admin.get("/api/admin/accounts/overview?days=7").json()
    c = {k: v["count"] for k, v in o["composition"].items()}
    assert c["email_only"] >= 1 and c["wechat_only"] == 1 and c["both"] == 1 and c["merged"] == 1
    assert o["signup_channels"]["miniprogram"]["count"] == 1 and o["signup_channels"]["web-pc"]["count"] == 1
    f = o["qr_funnel"]["login"]
    assert (f["created"], f["scanned"], f["done"], f["scanned_not_confirmed"], f["expired_unscanned"], f["waiting"]) == (5, 3, 1, 1, 1, 1)
    assert o["qr_scanned_not_confirmed"] == 1 and o["qr_funnel"]["bind"]["done"] == 1
    assert o["totals"]["merge_account"]["count"] == 1 and len(o["trend"]) == 7 and o["trend"][-1]["bind_wechat"] == 1


def test_user_account_and_filters():
    admin = login_client("acctboss2@example.com", role="admin")
    with SessionLocal() as s:
        both = s.scalar(select(User).where(User.email == "b1@example.com"))
        gone = s.scalar(select(User).where(User.nickname == "并入丁"))
    a = admin.get(f"/api/admin/users/{both.id}/account").json()
    assert a["kind"] == "both" and a["identities"]["wechat"]["bound"] and a["identities"]["wechat"]["openid"].startswith("…")
    assert [m["id"] for m in a["merged_from"]] == [gone.id]
    assert {e["action"] for e in a["timeline"]} >= {"merge_account", "bind_wechat"}
    assert a["qr_logins"][0]["purpose_label"] == "扫码绑定" and a["qr_logins"][0]["role"] == "网页账号"
    g = admin.get(f"/api/admin/users/{gone.id}/account").json()
    assert g["merged_into"]["id"] == both.id and g["status"] == "merged"

    ids = lambda qs: {x["id"] for x in admin.get(f"/api/admin/users?{qs}").json()["items"]}  # noqa: E731
    assert both.id in ids("login=both") and both.id not in ids("login=email_only")
    assert all(x for x in ids("login=wechat_only")) and both.id not in ids("login=wechat_only")
    assert ids("channel=miniprogram") and both.id in ids("channel=unknown")


def test_bind_conflict_is_logged(monkeypatch):
    """绑定冲突（邮箱已绑定其他微信）记进日志 result=failed。"""
    monkeypatch.setattr(wechat, "ready", lambda: True)
    monkeypatch.setattr(wechat, "code2session", lambda code: {"openid": f"oid-c-{code}", "unionid": None})
    c = TestClient(app)
    tok = c.post("/api/auth/wx/login", json={"code": "z"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    from conftest import solve_pow  # noqa: F401  已登录不需要 PoW
    code = c.post("/api/auth/code", json={"email": "b1@example.com", "purpose": "login"}).json()["dev_code"]
    r = c.post("/api/auth/me/email", json={"email": "b1@example.com", "code": code})
    assert r.status_code == 409
    with SessionLocal() as s:
        log = s.scalar(select(ActivityLog).where(ActivityLog.action == "bind_conflict").order_by(ActivityLog.id.desc()))
        assert log is not None and log.result == "failed" and "已绑定其他微信" in log.message
