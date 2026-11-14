"""v3.3.66 后台批次 6c：接口健康统计、客户端报错上报、版本与部署记录。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import ApiStat, ChangelogEntry, ClientError
from app.routers import observability
from app.seed import seed_categories
from app.services import apistats
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
    observability._rate.clear()


def test_api_health(monkeypatch):
    with apistats._lock:
        apistats._pending.clear()
    for ms in (10, 20, 30, 40, 600):
        apistats.record("GET", "/api/items/{item_id}", 200, ms)
    apistats.record("GET", "/api/items/{item_id}", 500, 3000)
    apistats.record("POST", "/api/feedback", 404, 5)
    apistats.record("GET", "/media/x.png", 200, 1)  # 非 /api 不记
    apistats.flush()
    with SessionLocal() as s:
        rows = s.scalars(select(ApiStat)).all()
        assert {(r.method, r.path) for r in rows} >= {("GET", "/api/items/{item_id}"), ("POST", "/api/feedback")}
    m = login_client("obsboss@example.com", role="admin")
    h = m.get("/api/admin/api-health?days=1").json()
    assert h["totals"]["errors_5xx"] >= 1 and h["totals"]["error_rate"] is not None
    slow = next(x for x in h["slow"] if x["path"] == "/api/items/{item_id}")
    assert slow["count"] == 6 and slow["p50_ms"] == 50 and slow["p95_ms"] == 5000 and slow["max_ms"] == 3000
    err = next(x for x in h["errors"] if x["path"] == "/api/items/{item_id}")
    assert err["errors_5xx"] == 1 and err["status"] == 500
    # 中间件真的会记：请求一个路由模板
    TestClient(app).get("/api/categories")
    apistats.flush()
    with SessionLocal() as s:
        assert s.scalar(select(ApiStat).where(ApiStat.path == "/api/categories")) is not None


def test_client_errors():
    c = TestClient(app)
    c.headers.update({"x-client": "web", "x-client-version": "3.3.66", "user-agent": "Mozilla/5.0 (Windows) Chrome/120"})
    body = {"kind": "js_error", "message": "TypeError: x is undefined at item 12345", "page": "/items/12?from=home", "stack": "at foo"}
    assert c.post("/api/client-errors", json=body).json()["ok"]
    body2 = {**body, "message": "TypeError: x is undefined at item 999"}  # 数字不同 → 同一指纹
    c.post("/api/client-errors", json=body2)
    u = login_client("errorer@example.com")
    u.headers.update({"x-client": "web", "x-client-version": "3.3.66"})
    u.post("/api/client-errors", json={"kind": "api_fail", "message": "GET /api/items 502", "page": "/"})
    with SessionLocal() as s:
        rows = s.scalars(select(ClientError)).all()
        assert len(rows) == 2
        js = next(r for r in rows if r.kind == "js_error")
        assert js.count == 2 and js.page == "/items/12" and js.version == "3.3.66"
    m = login_client("obsboss@example.com", role="admin")
    lst = m.get("/api/admin/client-errors?kind=api_fail").json()
    assert lst["total"] == 1 and lst["items"][0]["user"]["label"] and lst["items"][0]["kind_label"] == "接口失败"
    sm = m.get("/api/admin/client-errors/summary?days=7").json()
    assert sm["total"] == 3 and sm["distinct"] == 2 and sm["by_version"][0]["version"] == "3.3.66"
    # 限频
    observability._rate.clear()
    for _ in range(observability.RATE_PER_MIN):
        c.post("/api/client-errors", json=body)
    assert c.post("/api/client-errors", json=body).json().get("throttled")
    observability._rate.clear()
    sup = login_client("obssup@example.com", role="support")
    assert sup.get("/api/admin/client-errors").status_code == 403


def test_releases():
    now = utcnow()
    with SessionLocal() as s:
        s.add_all([ChangelogEntry(version="v9.9.1", released_at=now - timedelta(hours=1), category="fix", title="修了个问题", detail="x"),
                   ChangelogEntry(version="v9.9.0", released_at=now - timedelta(days=400), category="feature", title="很早的版本", detail="x")])
        s.commit()
    m = login_client("obsboss@example.com", role="admin")
    r = m.get("/api/admin/releases").json()
    by = {x["version"]: x for x in r["items"]}
    assert by["v9.9.1"]["changes"][0]["title"] == "修了个问题" and by["v9.9.1"]["client_errors_after"] >= 0
    assert by["v9.9.0"]["error_rate_before"] is None  # 统计开始之前的版本
