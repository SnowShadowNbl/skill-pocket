"""v3.3.59 后台批次 5a：AI 消耗与成本、额度账本与总览、收录任务按类型筛选与只重试失败项。"""

from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import AiCall, Category, Item, QuotaDaily, QuotaLedger, Task, TaskItem, User
from app.seed import seed_categories
from app.services import ingest
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        rich = User(email="rich@example.com", nickname="大户", role="user", status="active", quota_balance=5_000_000)
        low = User(email="low@example.com", nickname="余额少", role="user", status="active", quota_balance=1000)
        zero = User(email="zero@example.com", nickname="用完了", role="user", status="active", quota_balance=0)
        s.add_all([rich, low, zero])
        s.flush()
        now = utcnow()
        s.add_all([
            AiCall(purpose="AI-1", model="deepseek-flash", tokens_in=1_000_000, tokens_out=500_000, latency_ms=2000, ok=True, user_id=rich.id, created_at=now),
            AiCall(purpose="AI-1", model="deepseek-flash", tokens_in=0, tokens_out=0, latency_ms=100, ok=False, error="timeout", created_at=now),
            AiCall(purpose="EMB", model="text-embedding-v4", tokens_in=2_000_000, tokens_out=0, latency_ms=50, ok=True, created_at=now - timedelta(days=1)),
            AiCall(purpose="AI-17", model="mystery-model", tokens_in=10, tokens_out=10, latency_ms=10, ok=True, user_id=low.id, created_at=now),
        ])
        s.add(QuotaLedger(user_id=rich.id, kind="recharge", delta=3_000_000, balance_after=5_000_000, amount_yuan=30.0, note="微信转账"))
        s.add(QuotaDaily(user_id=rich.id, day=(now + timedelta(hours=8)).date(), calls=1, tokens=1_500_000, used=3_000_000, balance_end=5_000_000))
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        items = [Item(name=f"条目{i}", category_id=cat.id, status="published") for i in range(3)]
        s.add_all(items)
        s.flush()
        t = Task(kind="gallery", title="补图片集 · 3 个条目", source="manual", total=3, done=3, failed=2, status="partial",
                 created_at=now - timedelta(hours=1), finished_at=now)
        s.add(t)
        s.flush()
        s.add_all([TaskItem(task_id=t.id, item_id=items[0].id, seq=1, name="条目0", status="ok"),
                   TaskItem(task_id=t.id, item_id=items[1].id, seq=2, name="条目1", status="failed", message="404"),
                   TaskItem(task_id=t.id, item_id=items[2].id, seq=3, name="条目2", status="deferred")])
        s.commit()
        S.update(rich=rich.id, task=t.id, items=[i.id for i in items])


def test_usage_and_cost(monkeypatch):
    monkeypatch.setattr(settings, "ai_text_model", "deepseek-flash")  # v3.3.89 文本模型默认有单价（最高价 3 / 9）
    m = login_client("aiboss@example.com", role="admin")
    r = m.get("/api/admin/ai/usage?days=7").json()
    assert r["totals"]["calls"] == 4 and r["totals"]["fail_calls" if "fail_calls" in r["totals"] else "fail"] == 1
    assert r["totals"]["est_cost_yuan"] is None  # 有没配单价的模型
    by = {x["key"]: x for x in r["items"]}
    assert by["AI-1"]["label"] == "条目提炼" and by["AI-1"]["est_cost_yuan"] == 7.5 and by["EMB"]["est_cost_yuan"] == 1.0
    monkeypatch.setattr(settings, "ai_prices", '{"deepseek-flash": [2, 8], "mystery-model": [0, 0]}')
    r = m.get("/api/admin/ai/usage?days=7&group=model").json()
    by = {x["key"]: x for x in r["items"]}
    assert by["deepseek-flash"]["est_cost_yuan"] == 6.0 and r["totals"]["est_cost_yuan"] == 7.0
    u = m.get("/api/admin/ai/usage?days=7&group=user").json()
    assert any(x["label"] == "系统任务" for x in u["items"]) and any("大户" in x["label"] for x in u["items"])
    d = m.get("/api/admin/ai/usage?days=7&group=day").json()
    assert len(d["series"]) == 7 and sum(x["calls"] for x in d["series"]) == 4
    assert m.get(f"/api/admin/ai/usage?days=7&user_id={S['rich']}").json()["totals"]["calls"] == 1


def test_ledger_overview_and_permissions():
    m = login_client("aiboss@example.com", role="admin")
    lg = m.get("/api/admin/ai/ledger?kind=recharge").json()
    assert lg["total"] == 1 and lg["items"][0]["amount_yuan"] == 30.0 and lg["recharged_yuan_total"] == 30.0
    ov = m.get("/api/admin/ai/quota-overview").json()
    assert ov["users_with_quota"] == 3 and ov["low_balance_users"] == 1 and ov["exhausted_users"] == 1
    assert ov["top_users"][0]["used_30d"] == 3_000_000 and ov["today_calls"] >= 2
    sup = login_client("aisupport@example.com", role="support")
    assert sup.get("/api/admin/ai/usage").status_code == 403


def test_task_kind_and_retry_failed(monkeypatch):
    m = login_client("aiboss@example.com", role="admin")
    r = m.get("/api/admin/ingest-tasks?task_kind=gallery").json()
    assert r["total"] == 1 and r["items"][0]["can_retry"] and r["task_kinds"]["gallery"] == "补图片集"
    started = {}
    monkeypatch.setattr(ingest, "gallery_for", lambda i, t: (True, "ok"))
    from app.services import tracking

    monkeypatch.setattr(tracking, "start_task", lambda tid, ids, fn, workers=1: started.setdefault("ids", ids))
    out = m.post(f"/api/admin/ingest-tasks/task:{S['task']}/retry-failed", json={"reason": "源站恢复了", "expected_status": "failed"}).json()
    assert out["retried"] == 2 and out["skipped_done"] == 1 and out["charged"] is None and started["ids"] == S["items"][1:]
    with SessionLocal() as s:
        assert s.scalar(select(Task).where(Task.kind == "gallery", Task.title.like("重试%"))) is not None
    assert m.post("/api/admin/ingest-tasks/finder:1/retry-failed", json={"reason": "x"}).json()["detail"]["code"] == "not_supported"
