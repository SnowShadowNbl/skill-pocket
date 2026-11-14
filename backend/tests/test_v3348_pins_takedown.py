"""v3.3.48 后台批次 3b：推荐位排期、黑名单、下架申请。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import BlockEntry, Category, Item, Notification, Repo, TakedownRequest
from app.seed import seed_categories
from app.services import blocklist, ingest
from app.services.github import GitHubError
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        r = Repo(github_id=11, full_name="Owner/Thing", html_url="https://github.com/Owner/Thing", stars=50)
        s.add(r)
        s.flush()
        a = Item(name="条目甲", repo_id=r.id, category_id=cat.id, status="published")
        b = Item(name="条目乙", category_id=cat.id, status="published")
        c = Item(name="条目丙", category_id=cat.id, status="published")
        s.add_all([a, b, c])
        s.commit()
        S.update(a=a.id, b=b.id, c=c.id)


def test_pin_schedule():
    m = login_client("pboss@example.com", role="admin")
    now = utcnow()
    r = m.put(f"/api/admin/items/{S['b']}/pin", json={"weight": 50, "starts_at": (now + timedelta(days=1)).isoformat()}).json()
    assert r["pin"]["state"] == "scheduled"
    m.put(f"/api/admin/items/{S['c']}/pin", json={"weight": 10, "ends_at": (now + timedelta(days=1)).isoformat()})
    m.put(f"/api/admin/items/{S['a']}/pin", json={"weight": 90, "starts_at": (now - timedelta(days=3)).isoformat(),
                                                   "ends_at": (now - timedelta(days=1)).isoformat()})
    bad = m.put(f"/api/admin/items/{S['a']}/pin", json={"weight": 5, "starts_at": now.isoformat(), "ends_at": (now - timedelta(hours=1)).isoformat()})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_range"
    p = m.get("/api/admin/pins").json()
    assert [x["id"] for x in p["items"]] == [S["c"], S["b"], S["a"]] and p["counts"] == {"active": 1, "scheduled": 1, "expired": 1}
    # 首页「今日」只有生效中的置顶排最前，卡片 pinned 只对生效中的为 true
    home = TestClient(app).get("/api/items?sort=today").json()["items"]
    assert home[0]["id"] == S["c"] and home[0]["pinned"] and not next(x for x in home if x["id"] == S["b"])["pinned"]
    ch = m.get(f"/api/admin/items/{S['b']}/changes").json()["items"][0]
    assert {c["field"] for c in ch["changes"]} == {"pin_weight", "pin_starts_at"}
    for k in ("a", "b", "c"):
        m.put(f"/api/admin/items/{S[k]}/pin", json={"weight": 0})
    assert m.get("/api/admin/pins").json()["items"] == []


def test_blocklist():
    m = login_client("pboss@example.com", role="admin")
    assert m.post("/api/admin/blocklist", json={"kind": "repo", "value": "nope", "reason": "测试"}).json()["detail"]["code"] == "bad_value"
    e = m.post("/api/admin/blocklist", json={"kind": "owner", "value": "https://github.com/OWNER", "reason": "作者要求"}).json()
    assert e["value"] == "owner" and e["published_items"] == 1
    assert m.post("/api/admin/blocklist", json={"kind": "owner", "value": "owner", "reason": "再加"}).json()["detail"]["code"] == "duplicate"
    with SessionLocal() as s:
        assert blocklist.match(s, "owner/other-repo") is not None and blocklist.match(s, "someone/else") is None
        with pytest.raises(GitHubError):
            ingest.import_items(s, "https://github.com/Owner/NewOne", [])
    assert m.get("/api/admin/blocklist?kind=owner").json()["total"] == 1
    assert m.delete(f"/api/admin/blocklist/{e['id']}").json()["ok"]
    with SessionLocal() as s:
        assert blocklist.match(s, "owner/other-repo") is None


def test_takedown_flow():
    u = login_client("author@example.com")
    v = login_client("author2@example.com")
    m1 = login_client("pboss@example.com", role="admin")
    m2 = login_client("psub@example.com", role="subadmin")
    assert u.get(f"/api/items/{S['a']}/takedown").json()["request"] is None
    r = u.post(f"/api/items/{S['a']}/takedown", json={"relation": "author", "reason": "我是作者，不希望被收录", "contact": "a@x.com"})
    assert r.json()["request"]["status"] == "pending"
    assert u.post(f"/api/items/{S['a']}/takedown", json={"reason": "再申请一次试试"}).json()["detail"]["code"] == "duplicate_pending"
    v.post(f"/api/items/{S['a']}/takedown", json={"relation": "maintainer", "reason": "我也是维护者，同意下架"})
    assert TestClient(app).post(f"/api/items/{S['a']}/takedown", json={"reason": "匿名申请"}).status_code == 401
    lst = m1.get("/api/admin/takedowns").json()
    assert lst["total"] == 2 and lst["items"][0]["requests_for_item"] == 2 and lst["counts"]["pending"] == 2
    assert m1.get("/api/admin/summary").json()["pending"]["takedowns"] == 2
    tid = lst["items"][1]["id"]
    out = m1.post(f"/api/admin/takedowns/{tid}/approve", json={"reason": "核实为作者", "expected_status": "pending", "block": True}).json()
    assert out["status"] == "approved" and out["handled"]["blocked"] and out["item"]["status"] == "hidden"
    # 另一个管理员拿旧状态处理同条目的另一份申请：已经一并结案 → 409
    other = lst["items"][0]["id"]
    r = m2.post(f"/api/admin/takedowns/{other}/reject", json={"reason": "不同意", "expected_status": "pending"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_handled"
    with SessionLocal() as s:
        assert s.scalar(select(BlockEntry).where(BlockEntry.value == "owner/thing")).source == "takedown"
        assert s.get(Repo, s.get(Item, S["a"]).repo_id).repo_status == "rejected"
        assert s.scalar(select(Notification).where(Notification.title.like("%已下架%"))) is not None
        assert s.scalar(select(TakedownRequest).where(TakedownRequest.status == "pending")) is None
    assert u.get(f"/api/items/{S['a']}/takedown").json()["request"]["status"] == "approved"
    # 驳回需要原因，用户能看到驳回理由
    with SessionLocal() as s:
        s.get(Item, S["b"]).status = "published"
        s.commit()
    tb = u.post(f"/api/items/{S['b']}/takedown", json={"reason": "这个也申请一下"}).json()["request"]["id"]
    assert m1.post(f"/api/admin/takedowns/{tb}/reject", json={"reason": ""}).json()["detail"]["code"] == "reason_required"
    m1.post(f"/api/admin/takedowns/{tb}/reject", json={"reason": "无法证明是作者"})
    assert u.get(f"/api/items/{S['b']}/takedown").json()["request"]["handle_reason"] == "无法证明是作者"
