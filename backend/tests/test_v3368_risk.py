"""v3.3.68 后台批次 6d：风控概览与告警、验证码阈值、定时任务控制。"""

from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import ActivityLog, Alert, User
from app.routers import risk_admin
from app.seed import seed_categories
from app.services import ops, scheduler
from conftest import login_client, solve_pow

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        ids = []
        for i in range(6):
            u = User(email=f"bot{i}@example.com", nickname=f"机器人{i}", role="user", status="active")
            s.add(u)
            s.flush()
            ids.append(u.id)
            s.add(ActivityLog(action="register", summary="注册", user_id=u.id, ip=f"10.9.8.{i + 1}", created_at=utcnow() - timedelta(hours=2)))
        s.commit()
        S["bots"] = ids


def test_risk_overview_and_alerts():
    m = login_client("riskboss@example.com", role="admin")
    o = m.get("/api/admin/risk/overview").json()
    c = o["register_clusters"][0]
    assert c["ip_prefix"] == "10.9.8.0/24" and c["count"] == 6 and o["qr_abuse"] is None
    risk_admin.scan(force=True)
    with SessionLocal() as s:
        a = s.scalar(select(Alert).where(Alert.key == "risk:register:10.9.8.0/24"))
        assert a is not None and a.source == "risk"
    ops.sync(force=True)  # 风控告警不会被自动恢复
    with SessionLocal() as s:
        assert s.scalar(select(Alert).where(Alert.key == "risk:register:10.9.8.0/24")).status == "open"
    sup = login_client("risksup@example.com", role="support")
    assert sup.get("/api/admin/risk/overview").status_code == 403


def test_code_limits(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    m = login_client("riskboss@example.com", role="admin")
    t = m.get("/api/admin/code-limits").json()
    assert t["threshold"] == {"resend_seconds": settings.code_resend_seconds, "per_email_daily": settings.code_per_email_daily,
                              "per_ip_daily": settings.code_per_ip_daily, "per_account_hour": 8}
    monkeypatch.setattr(settings, "admin_verify_required", False)
    assert m.put("/api/admin/code-limits/threshold", json={"per_email_daily": 0, "reason": "测试"}).json()["detail"]["code"] == "bad_range"
    r = m.put("/api/admin/code-limits/threshold", json={"per_email_daily": 1, "resend_seconds": 10, "reason": "收紧"}).json()
    assert r["threshold"]["per_email_daily"] == 1
    # 新阈值生效：同一邮箱第二次就被拦，并记一次「被限制」
    c = TestClient(app)

    def send(email):
        ch = c.get("/api/auth/challenge").json()
        return c.post("/api/auth/code", json={"email": email, "purpose": "login", "pow_token": ch["token"], "pow_nonce": solve_pow(ch)})

    assert send("limit-me@example.com").status_code == 200
    with SessionLocal() as s:  # 绕过重发间隔
        from app.models import EmailCode

        for e in s.scalars(select(EmailCode).where(EmailCode.email == "limit-me@example.com")):
            e.created_at = utcnow() - timedelta(minutes=5)
        s.commit()
    r2 = send("limit-me@example.com")
    assert r2.status_code == 429
    st = m.get("/api/admin/code-limits").json()
    assert st["stats"]["limited"] >= 1 and any(x["kind"] == "email" for x in st["limited"])
    m.put("/api/admin/code-limits/threshold", json={"per_email_daily": settings.code_per_email_daily, "resend_seconds": settings.code_resend_seconds,
                                                     "reason": "改回"})
    u = m.get(f"/api/admin/code-limits/user/{S['bots'][0]}").json()
    assert u["sent"] == 0 and u["limited"] == 0
    monkeypatch.setattr(settings, "admin_verify_required", True)
    assert m.put("/api/admin/code-limits/threshold", json={"per_ip_daily": 20, "reason": "x改"}).json()["detail"]["code"] == "verify_required"


def test_schedules(monkeypatch):
    m = login_client("riskboss@example.com", role="admin")
    items = {x["key"]: x for x in m.get("/api/admin/schedules").json()["items"]}
    assert set(items) == {"daily_crawl", "daily_notify", "db_backup"} and not items["db_backup"]["controllable"]
    monkeypatch.setattr(settings, "admin_verify_required", False)
    assert m.post("/api/admin/schedules/daily_notify/pause", json={}).json()["detail"]["code"] == "reason_required"
    r = m.post("/api/admin/schedules/daily_notify/pause", json={"reason": "排查推送问题"}).json()
    assert r["item"]["paused"]
    # 暂停超过 24 小时会告警
    p = scheduler._paused()
    p["daily_notify"]["at"] = (utcnow() - timedelta(hours=30)).isoformat()
    scheduler._save_paused(p)
    risk_admin.scan(force=True)
    with SessionLocal() as s:
        assert s.scalar(select(Alert).where(Alert.key == "schedule:paused:daily_notify")) is not None
    assert not m.post("/api/admin/schedules/daily_notify/resume", json={"reason": "已排查"}).json()["item"]["paused"]
    called = {}
    monkeypatch.setattr(scheduler, "run_now", lambda key: called.setdefault("k", key) and "started")
    assert m.post("/api/admin/schedules/daily_notify/run", json={"reason": "补发"}).json()["status"] == "started"
    assert m.post("/api/admin/schedules/db_backup/run", json={"reason": "x"}).status_code == 404
    monkeypatch.setattr(settings, "admin_verify_required", True)
    assert m.post("/api/admin/schedules/daily_crawl/pause", json={"reason": "测试"}).json()["detail"]["code"] == "verify_required"
