"""v2.6：AI 额度（按账号计 token、2 倍扣减、用完拦截、充值 / 调整 / 重置、每日用量）、管理员备注名。"""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import AiCall, QuotaDaily, QuotaLedger, User
from app.seed import seed_categories
from app.services import billing
from app.services.extract import _log_call
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def admin():
    c = login_client("boss26@example.com")
    with SessionLocal() as s:
        s.scalar(select(User).where(User.email == "boss26@example.com")).role = "admin"
        s.commit()
    return c


def uid(email):
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.email == email))


def balance(user_id):
    with SessionLocal() as s:
        return s.get(User, user_id).quota_balance


def test_ai_call_is_charged_twice_the_tokens():
    c = login_client("spender@example.com")
    me = uid("spender@example.com")
    q = c.get("/api/auth/me/quota").json()
    assert q["balance"] == billing.STANDARD_FREE and q["rate"] == 2 and q["used_today"] == 0
    with billing.charged_to(me):
        _log_call("AI-17", True, 100, {"prompt_tokens": 1000, "completion_tokens": 500})
        _log_call("AI-13", True, 100, {"prompt_tokens": 9999, "completion_tokens": 1})  # 内容审核不计费
        _log_call("AI-17", False, 100, None, "boom")  # 失败的调用不扣
    _log_call("AI-17", True, 100, {"prompt_tokens": 5000, "completion_tokens": 0})  # 没有归属的系统调用
    assert balance(me) == billing.STANDARD_FREE - 3000
    q = c.get("/api/auth/me/quota").json()
    assert q["used_today"] == 3000 and q["ledger"][0]["kind"] == "grant"
    with SessionLocal() as s:
        assert s.scalar(select(AiCall).where(AiCall.purpose == "AI-13")).user_id == me
        d = s.scalar(select(QuotaDaily).where(QuotaDaily.user_id == me))
        assert (d.calls, d.tokens, d.used, d.balance_end) == (1, 1500, 3000, billing.STANDARD_FREE - 3000)


def test_wrap_carries_owner_into_thread_pool():
    login_client("pool@example.com")
    me = uid("pool@example.com")

    def work(n):
        _log_call("AI-8", True, 1, {"prompt_tokens": n, "completion_tokens": 0})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(billing.wrap(me, work), [100] * 8))
    assert balance(me) == billing.STANDARD_FREE - 1600


def test_exhausted_balance_blocks_ai_but_not_staff():
    c = login_client("broke@example.com")
    me = uid("broke@example.com")
    c.get("/api/auth/me/quota")
    with SessionLocal() as s:
        s.get(User, me).quota_balance = 0
        s.commit()
    r = c.post("/api/compare", json={"entries": [{"full_name": "a/b"}, {"full_name": "c/d"}]})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "quota_exhausted" and "管理员" in r.json()["detail"]["message"]
    a = admin()
    with SessionLocal() as s:
        boss = s.scalar(select(User).where(User.email == "boss26@example.com"))
        boss.quota_balance = -5
        s.commit()
        billing.check(s, boss)  # 管理员不受限制


def test_admin_recharge_adjust_set_reset_and_settings():
    login_client("vip@example.com")
    me = uid("vip@example.com")
    a = admin()
    r = a.post(f"/api/admin/users/{me}/quota", json={"action": "recharge", "amount": 1_000_000, "yuan": 10, "note": "微信转账"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["balance"] == billing.STANDARD_FREE + 1_000_000 and d["recharged_yuan"] == 10
    assert d["ledger"][0]["kind"] == "recharge" and d["ledger"][0]["operator"]
    assert a.post(f"/api/admin/users/{me}/quota", json={"action": "adjust", "amount": -500_000}).json()["balance"] == billing.STANDARD_FREE + 500_000
    assert a.post(f"/api/admin/users/{me}/quota", json={"action": "set", "amount": 42}).json()["balance"] == 42
    assert a.post(f"/api/admin/users/{me}/quota", json={"action": "recharge", "amount": 0}).status_code == 400
    s = a.put("/api/admin/quota/settings", json={"default_free": 3_000_000}).json()
    assert s["default_free"] == 3_000_000 and s["standard_free"] == billing.STANDARD_FREE
    assert a.post(f"/api/admin/users/{me}/quota", json={"action": "reset"}).json()["balance"] == 3_000_000
    # 新账号按新的默认值发放
    c2 = login_client("newbie26@example.com")
    assert c2.get("/api/auth/me/quota").json()["balance"] == 3_000_000
    a.put("/api/admin/quota/settings", json={"default_free": billing.STANDARD_FREE})
    recs = a.get("/api/admin/quota/records").json()
    assert [x["kind"] for x in recs[:4]] == ["reset", "adjust", "adjust", "recharge"] and recs[-1]["amount_yuan"] == 10
    with SessionLocal() as db:
        assert db.scalar(select(QuotaLedger).where(QuotaLedger.user_id == me, QuotaLedger.kind == "recharge")).amount_yuan == 10
    assert login_client("nope26@example.com").post(f"/api/admin/users/{me}/quota", json={"action": "reset"}).status_code == 403


def test_admin_quota_detail_and_board():
    login_client("heavy@example.com")
    me = uid("heavy@example.com")
    with billing.charged_to(me):
        _log_call("AI-8", True, 1, {"prompt_tokens": 2000, "completion_tokens": 500})
    a = admin()
    d = a.get(f"/api/admin/users/{me}/quota").json()
    assert d["daily"][0]["used"] == 5000 and d["balance_history"][-1]["balance"] == billing.STANDARD_FREE - 5000
    assert d["by_purpose"][0]["purpose"] == "AI-8" and d["by_purpose"][0]["used"] == 5000
    b = a.get("/api/admin/quota/board?days=7").json()
    row = next(x for x in b["users"] if x["id"] == me)
    assert row["total"] == 5000 and len(b["days"]) == 7


def test_admin_remark():
    login_client("nick26@example.com")
    me = uid("nick26@example.com")
    a = admin()
    r = a.put(f"/api/admin/users/{me}/remark", json={"remark": "老客户·张三"})
    assert r.status_code == 200 and r.json()["remark"] == "老客户·张三"
    found = a.get("/api/admin/users?q=张三").json()
    assert any(x["id"] == me for x in found["items"])
    # 用户自己看不到备注
    assert "remark" not in login_client("nick26@example.com").get("/api/auth/me").json()["user"]
