"""v3.3.65 后台批次 6b：邮件发送记录、站内消息记录、每日推送执行记录。"""

from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import EmailLog, Notification, User
from app.seed import seed_categories
from app.services import notify
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        u = User(email="mailme@example.com", nickname="收件人", role="user", status="active")
        s.add(u)
        s.flush()
        s.add_all([EmailLog(email="MailMe@example.com", purpose="login", provider="ses", ok=True),
                   EmailLog(email="mailme@example.com", purpose="reset", provider="ses", ok=False, error="Throttling"),
                   EmailLog(email="nobody@example.com", purpose="login", provider="console", ok=True)])
        s.add_all([Notification(user_id=u.id, kind="system", title="系统消息", read_at=utcnow()),
                   Notification(user_id=u.id, kind="feedback_reply", title="回复你了")])
        s.commit()
        S["u"] = u.id


def test_emails():
    m = login_client("commsboss@example.com", role="admin")
    r = m.get("/api/admin/emails").json()
    assert r["total"] == 3 and r["counts"] == {"sent": 2, "failed": 1, "bounced": None}
    first = next(x for x in r["items"] if x["status"] == "failed")
    assert first["email"] == "ma***@example.com" and first["user"]["id"] == S["u"] and first["error"] == "Throttling"
    assert all("***@" in x["email"] for x in r["items"])  # 收件地址打码；用户名称和后台其他地方一样显示账号
    assert m.get("/api/admin/emails?status=failed").json()["total"] == 1
    assert m.get("/api/admin/emails?purpose=login&q=nobody").json()["total"] == 1
    st = m.get("/api/admin/emails/stats?days=7").json()
    assert st["sent"] == 2 and st["failed"] == 1 and st["fail_rate"] == 0.333 and len(st["series"]) == 7
    assert {x["purpose"] for x in st["by_purpose"]} == {"login", "reset"}
    sup = login_client("commssup@example.com", role="support")
    assert sup.get("/api/admin/emails").status_code == 403


def test_notifications_and_push_runs():
    m = login_client("commsboss@example.com", role="admin")
    r = m.get(f"/api/admin/notifications?user_id={S['u']}").json()
    assert r["total"] == 2 and r["items"][0]["source"] == "系统"
    by = {x["kind"]: x for x in r["by_kind"]}
    assert by["system"]["read_rate"] == 1.0 and by["feedback_reply"]["read"] == 0
    assert m.get("/api/admin/notifications?kind=system").json()["total"] == 1
    assert m.get("/api/admin/push-runs").json()["total"] == 0
    with SessionLocal() as s:
        notify._record_run(s, True, 3, 1, started=utcnow())
        notify._record_run(s, False, None, None, "boom", started=utcnow())
    p = m.get("/api/admin/push-runs").json()
    assert p["total"] == 2 and p["items"][0]["ok"] is False and p["items"][0]["error"] == "boom" and p["items"][1]["sent"] == 4
    h = {x["key"]: x for x in m.get("/api/admin/health").json()["services"]}
    assert h["push"]["status"] == "down"
