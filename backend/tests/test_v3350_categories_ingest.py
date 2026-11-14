"""v3.3.50 后台批次 3c：分类健康度 / 合并 / 拆分 / AI 抽检、收录任务监控。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import Category, CategoryAudit, FinderJob, Item, Task, TaskItem, Upload
from app.routers import category_admin
from app.seed import seed_categories
from app.services import ingest, judge
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        subs = s.scalars(select(Category).where(Category.parent_id.is_not(None)).order_by(Category.id)).all()
        a, b = subs[0], subs[1]
        sib = next(c for c in subs if c.id not in (a.id, b.id))
        items = [Item(name=f"甲{i}", category_id=a.id, status="published", locked_fields=["category_id"] if i == 0 else [])
                 for i in range(5)]
        items.append(Item(name="甲隐藏", category_id=a.id, status="hidden"))
        s.add_all(items)
        s.commit()
        now = utcnow()
        u = login_client("ingestuser@example.com")  # noqa: F841  建用户
        s.add_all([
            FinderJob(kind="search", query="pdf 工具", status="running", result={"stage": "search"}, created_at=now - timedelta(minutes=30)),
            FinderJob(kind="search", query="正在找", status="running", result={"stage": "plan"}, created_at=now - timedelta(minutes=1)),
            FinderJob(kind="text", query="长文", status="failed", result={"error": "读取失败"}, created_at=now - timedelta(hours=1)),
            Upload(image_path="uploads/x.png", status="recognized", ai_result={"items": [{"name": "md2pdf"}]}, created_at=now - timedelta(hours=2)),
        ])
        t = Task(kind="reextract", title="重新提炼 · 2 个条目", source="manual", total=2, done=2, failed=1, status="partial",
                 created_at=now - timedelta(hours=3), finished_at=now - timedelta(hours=3) + timedelta(seconds=40))
        s.add(t)
        s.flush()
        s.add_all([TaskItem(task_id=t.id, item_id=items[1].id, seq=1, name="甲1", status="ok"),
                   TaskItem(task_id=t.id, item_id=items[2].id, seq=2, name="甲2", status="failed", message="AI 超时")])
        s.commit()
        S.update(a=a.id, b=b.id, sib=sib.id, a_code=a.code, b_name=b.name, items=[i.id for i in items], task=t.id)


def test_health_merge():
    m = login_client("catboss@example.com", role="admin")
    h = {x["id"]: x for x in m.get("/api/admin/categories/health").json()["items"]}
    assert h[S["a"]]["published_count"] == 5 and h[S["a"]]["total_count"] == 6 and h[S["a"]]["status"] == "ok"
    assert h[S["b"]]["status"] == "empty"
    assert m.post(f"/api/admin/categories/{S['a']}/merge", json={"target_id": S["a"]}).json()["detail"]["code"] == "bad_target"
    pv = m.post(f"/api/admin/categories/{S['a']}/merge", json={"target_id": S["b"], "dry_run": True}).json()
    assert pv["moved_count"] == 6 and pv["locked_count"] == 1 and len(pv["sample"]) == 6
    with SessionLocal() as s:
        assert s.scalar(select(Item.category_id).where(Item.id == S["items"][0])) == S["a"]  # 预览不改数据
    r = m.post(f"/api/admin/categories/{S['a']}/merge", json={"target_id": S["b"], "dry_run": False, "reason": "两类重复"}).json()
    assert r["moved_count"] == 6 and r["task_id"] is None
    with SessionLocal() as s:
        src = s.get(Category, S["a"])
        assert not src.enabled and src.merged_into_id == S["b"]
        it0 = s.get(Item, S["items"][0])
        assert it0.category_id == S["b"] and "category_id" in it0.locked_fields
    # 旧分类 code 重定向
    got = TestClient(app).get(f"/api/items?category={S['a_code']}").json()
    assert got["total"] == 5


def test_split():
    m = login_client("catboss@example.com", role="admin")
    ids = S["items"]
    bad = m.post(f"/api/admin/categories/{S['b']}/split", json={"parts": [{"name": "新一", "item_ids": [99999]}]})
    assert bad.json()["detail"]["code"] == "bad_items"
    dup = m.post(f"/api/admin/categories/{S['b']}/split", json={"parts": [{"name": S["b_name"], "item_ids": ids[:1]}]})
    assert dup.json()["detail"]["code"] == "duplicate_name"
    pv = m.post(f"/api/admin/categories/{S['b']}/split", json={"parts": [{"name": "新一", "item_ids": ids[:2]}, {"name": "新二", "item_ids": ids[2:3]}]}).json()
    assert [p["count"] for p in pv["parts"]] == [2, 1] and pv["remaining_count"] == 3
    r = m.post(f"/api/admin/categories/{S['b']}/split", json={"dry_run": False, "reason": "太杂了",
                                                             "parts": [{"name": "新一", "item_ids": ids[:2]}]}).json()
    new = r["created"][0]
    with SessionLocal() as s:
        c = s.get(Category, new["id"])
        assert c.parent_id == s.get(Category, S["b"]).parent_id and c.enabled
        assert s.get(Item, ids[1]).category_id == c.id and "category_id" in s.get(Item, ids[1]).locked_fields


def test_audit(monkeypatch):
    m = login_client("catboss@example.com", role="admin")
    monkeypatch.setattr(type(ingest.settings), "ai_enabled", property(lambda self: True))
    with SessionLocal() as s:
        sib_code = s.get(Category, S["sib"]).code
    monkeypatch.setattr(judge, "classify_items", lambda briefs, choices: {
        b["id"]: {"category_code": sib_code if b["name"] == "甲3" else None, "confidence": 0.9, "kind": "", "kind_confidence": 0.5}
        for b in briefs})
    started = {}
    monkeypatch.setattr(category_admin.threading, "Thread", lambda target, args, **kw: started.setdefault("t", (target, args)) and type(
        "T", (), {"start": lambda self: target(*args)})())
    r = m.post("/api/admin/category-audit/run", json={"sample": 50}).json()
    assert r["sample"] == 5
    lst = m.get("/api/admin/category-audit").json()
    assert lst["total"] == 5 and lst["counts"]["open"] == 5
    first = lst["items"][0]
    assert first["agree"] is False and first["item"]["name"] == "甲3" and first["suggested"]["id"] == S["sib"]
    d = m.post(f"/api/admin/category-audit/{first['id']}/decide", json={"decision": "move", "reason": "AI 说得对", "expected_status": "open"}).json()
    assert d["status"] == "moved"
    with SessionLocal() as s:
        assert s.get(Item, first["item"]["id"]).category_id == S["sib"]
    again = m.post(f"/api/admin/category-audit/{first['id']}/decide", json={"decision": "keep", "expected_status": "open"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "already_handled"
    other = lst["items"][1]["id"]
    assert m.post(f"/api/admin/category-audit/{other}/decide", json={"decision": "keep"}).json()["status"] == "kept"
    assert m.get("/api/admin/category-audit?status=decided").json()["total"] == 2
    with SessionLocal() as s:
        assert s.scalar(select(CategoryAudit).where(CategoryAudit.status == "open")) is not None


def test_ingest_monitor(monkeypatch):
    m = login_client("catboss@example.com", role="admin")
    r = m.get("/api/admin/ingest-tasks").json()
    st = {x["id"]: x["status"] for x in r["items"]}
    finder_stuck = next(k for k, v in st.items() if k.startswith("finder:") and v == "stuck")
    assert r["counts"]["stuck"] >= 1 and st[f"task:{S['task']}"] == "failed"
    assert any(k.startswith("upload:") and v == "done" for k, v in st.items())
    assert {x["kind"] for x in m.get("/api/admin/ingest-tasks?kind=finder").json()["items"]} == {"finder"}
    assert m.get("/api/admin/ingest-tasks?status=stuck").json()["total"] == r["counts"]["stuck"]
    d = m.get(f"/api/admin/ingest-tasks/task:{S['task']}").json()
    assert d["duration_s"] == 40 and [x["status"] for x in d["extra"]["items"]] == ["ok", "failed"]
    assert m.get("/api/admin/ingest-tasks/nope:1").status_code == 404
    # 重试：只重试失败的条目
    got = {}
    monkeypatch.setattr(ingest, "start_process_task", lambda kind, title, ids, **kw: got.setdefault("ids", ids) and 501)
    rr = m.post(f"/api/admin/ingest-tasks/task:{S['task']}/retry", json={"reason": "AI 恢复了", "expected_status": "failed"}).json()
    assert rr["new_task_id"] == "task:501" and got["ids"] == [S["items"][2]]
    # 终止卡住的查找任务；已完成的不能终止
    ab = m.post(f"/api/admin/ingest-tasks/{finder_stuck}/abort", json={"reason": "卡死了", "expected_status": "stuck"}).json()
    assert ab["status"] == "failed"
    no = m.post(f"/api/admin/ingest-tasks/{finder_stuck}/abort", json={"reason": "再来"})
    assert no.status_code == 409
    # 批量重试：截图不支持、完成的 bad_state
    up = next(k for k in st if k.startswith("upload:"))
    b = m.post("/api/admin/ingest-tasks/bulk", json={"action": "retry", "reason": "批量", "ids": [up]}).json()
    assert b["results"][0]["code"] == "bad_state"
    p = m.get("/api/admin/summary").json()["pending"]
    assert p["ingest_failed"] >= 1 and isinstance(p["ingest_stuck"], int)
