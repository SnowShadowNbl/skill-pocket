"""v3.3.91 免费额度只发给绑定了微信的账号，每个微信只发一次。"""

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import QuotaLedger, QuotaWxGrant, User
from app.seed import seed_categories
from app.services import billing, wechat
from conftest import login_client

COMPARE = {"entries": [{"full_name": "a/b"}, {"full_name": "c/d"}]}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        s.commit()


def _user(email):
    with SessionLocal() as s:
        return s.scalar(select(User).where(User.email == email))


def test_email_only_must_bind_wechat():
    c = login_client("mail91@example.com", wechat=False)
    r = c.post("/api/compare", json=COMPARE)
    assert r.status_code == 402
    d = r.json()["detail"]
    assert d["code"] == "wechat_bind_required" and "绑定微信" in d["message"] and "50 万" in d["message"]
    assert "AI" not in d["message"] and "充值" not in d["message"]
    q = c.get("/api/auth/me/quota").json()
    assert q["needs_wechat"] is True and q["balance"] == 0 and q["free_amount"] == billing.STANDARD_FREE == 500_000
    assert _user("mail91@example.com").quota_balance is None  # 看额度不会把它变成「已领过」


def test_binding_wechat_grants_once():
    login_client("mail92@example.com", wechat=False)
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == "mail92@example.com"))
        u.wx_openid, u.wx_unionid = "oid-92", "uid-92"
        s.commit()
        assert billing.ensure(s, u) == 500_000
        s.commit()
        assert {g.wx_key for g in s.scalars(select(QuotaWxGrant).where(QuotaWxGrant.user_id == u.id))} == {"oid-92", "uid-92"}
        # 同一个微信（unionid 相同）换个账号：不再发
        other = User(nickname="换号", role="user", status="active", wx_openid="oid-92b", wx_unionid="uid-92")
        s.add(other)
        s.flush()
        assert billing.ensure(s, other) == 0
        s.commit()
        note = s.scalars(select(QuotaLedger).where(QuotaLedger.user_id == other.id)).one().note
    assert "已经领取过" in note
    q = login_client("mail92@example.com").get("/api/auth/me/quota").json()
    assert q["needs_wechat"] is False and q["estimates"][0]["times"] == 500_000 // q["estimates"][0]["per_use"]


def test_wechat_register_grants_immediately(monkeypatch):
    monkeypatch.setattr(wechat, "code2session", lambda code: {"openid": "oid-new-91"})
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).post("/api/auth/wx/login", json={"code": "x"})
    assert r.status_code == 200 and r.json()["is_new"]
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.wx_openid == "oid-new-91"))
        assert u.quota_balance == 500_000 and s.get(QuotaWxGrant, "oid-new-91").user_id == u.id


def test_legacy_email_accounts_and_staff_unaffected():
    login_client("legacy91@example.com", wechat=False)
    with SessionLocal() as s:
        s.scalar(select(User).where(User.email == "legacy91@example.com")).quota_balance = 1_800_000  # 以前已经领过
        s.commit()
    c = login_client("legacy91@example.com")
    assert c.get("/api/auth/me/quota").json()["needs_wechat"] is False
    assert c.post("/api/compare", json=COMPARE).status_code != 402
    boss = login_client("boss91@example.com", role="admin", wechat=False)
    assert boss.post("/api/compare", json=COMPARE).status_code != 402


def test_admin_recharge_email_only_and_overview():
    login_client("paid91@example.com", wechat=False)
    a = login_client("boss91@example.com", role="admin", wechat=False)
    ov = a.get("/api/admin/ai/quota-overview").json()
    assert ov["needs_wechat_users"] >= 2
    u = _user("paid91@example.com")
    with SessionLocal() as s:
        user = s.get(User, u.id)
        row = billing.change(s, user, "recharge", delta=1_000_000, amount_yuan=10.0)
        s.commit()
        assert row.delta == 1_000_000 and user.quota_balance == 1_000_000


def test_mp_bind_wechat_endpoint(monkeypatch):
    """v3.3.92 小程序里给邮箱账号绑定当前微信：新微信直接绑定并发放；微信属于有数据的纯微信账号时先给合并预览。"""
    from app.models import Comment, Item, Category

    c = login_client("mpbind92@example.com", wechat=False)
    monkeypatch.setattr(wechat, "code2session", lambda code: {"openid": f"oid-{code}", "unionid": None})
    r = c.post("/api/auth/me/wechat", json={"code": "fresh92"}).json()
    assert r["status"] == "bound" and r["granted"] == 500_000 and r["user"]["wechat_bound"]
    assert c.post("/api/auth/me/wechat", json={"code": "again"}).status_code == 400  # 已经绑过

    c2 = login_client("mpbind93@example.com", wechat=False)
    with SessionLocal() as s:
        w = User(nickname="小程序用户", role="user", status="active", wx_openid="oid-w93", quota_balance=420_000)
        s.add(w)
        s.flush()
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        it = Item(name="合并用", category_id=cat.id, status="published")
        s.add(it)
        s.flush()
        s.add(Comment(item_id=it.id, user_id=w.id, content="有数据"))
        s.commit()
    assert c2.post("/api/auth/me/wechat", json={"code": "w93"}).json()["status"] == "merge"
    r = c2.post("/api/auth/me/wechat", json={"code": "w93", "merge": True}).json()
    assert r["status"] == "merged" and r["granted"] == 0 and r["token"]  # 沿用微信账号已有的余额，不另发
    me = _user("mpbind93@example.com")
    assert me.wx_openid == "oid-w93" and me.quota_balance == 420_000

    c3 = login_client("mpbind94@example.com", wechat=False)
    with SessionLocal() as s:
        s.add(User(email="owner94@example.com", nickname="别人", role="user", status="active", wx_openid="oid-o94"))
        s.commit()
    assert c3.post("/api/auth/me/wechat", json={"code": "o94"}).status_code == 409


def test_user_out_has_needs_wechat():
    c = login_client("tip100@example.com", wechat=False)
    assert c.get("/api/auth/me").json()["user"]["needs_wechat"] is True
    w = login_client("tip100w@example.com")
    assert w.get("/api/auth/me").json()["user"]["needs_wechat"] is False
    legacy = login_client("tip100l@example.com", wechat=False)
    with SessionLocal() as s:
        s.scalar(select(User).where(User.email == "tip100l@example.com")).quota_balance = 100
        s.commit()
    assert legacy.get("/api/auth/me").json()["user"]["needs_wechat"] is False  # 以前领过的老邮箱账号不提示
