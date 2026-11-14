"""v3.3.64 后台批次 6a：服务状态、告警、备份、小程序配置、存储与清理。"""

import gzip
import os
import time
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.main import ensure_admin
from app.models import ActivityLog, Alert, Notification, User
from app.seed import seed_categories
from app.services import ops, resources
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def test_health_and_backup(tmp_path, monkeypatch):
    m = login_client("opsboss@example.com", role="admin")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "nope"))
    h = {x["key"]: x for x in m.get("/api/admin/health").json()["services"]}
    assert h["db"]["status"] == "ok" and h["backup"]["status"] == "unknown" and h["push"]["status"] == "unknown"
    assert h["ai"]["status"] == "unknown"  # 测试环境没配 AI
    # 备份目录可见：一个新备份 → ok；改成 40 小时前 → warn 并产生告警
    d = tmp_path / "backups"
    d.mkdir()
    p = d / "skillhub-2026-11-13.sql.gz"
    with gzip.open(p, "wb") as f:
        f.write(b"-- dump")
    monkeypatch.setattr(settings, "backup_dir", str(d))
    b = m.get("/api/admin/backup").json()
    assert b["status"] == "ok" and b["last_ok"] and b["history"][0]["note"] == "每日备份"
    old = time.time() - 40 * 3600
    os.utime(p, (old, old))
    assert m.get("/api/admin/backup").json()["status"] == "warn"
    ops.sync(force=True)
    with SessionLocal() as s:
        a = s.scalar(select(Alert).where(Alert.key == "backup:stale"))
        assert a is not None and a.status == "open" and a.level == "critical"
        boss = s.scalar(select(User).where(User.email == "opsboss@example.com"))
        assert s.scalar(select(Notification).where(Notification.user_id == boss.id, Notification.title.like("告警：%"))) is not None
    # 备份恢复 → 自动恢复告警
    os.utime(p, None)
    ops.sync(force=True)
    with SessionLocal() as s:
        a = s.scalar(select(Alert).where(Alert.key == "backup:stale"))
        assert a.status == "resolved" and a.resolved_auto


def test_alerts_flow(monkeypatch):
    monkeypatch.setattr(resources, "alerts", lambda fetch_remote=False: [{"level": "bad", "key": "deepseek", "text": "DeepSeek 余额只剩 ¥3.00，请尽快充值"}])
    monkeypatch.setattr(settings, "backup_dir", "/definitely/not/here")
    m = login_client("opsboss@example.com", role="admin")
    sup = login_client("opssupport@example.com", role="support")
    assert sup.get("/api/admin/alerts").status_code == 403
    ops.sync(force=True)
    ops.sync(force=True)  # 持续成立：不重复建、不累加次数
    r = m.get("/api/admin/alerts").json()
    a = next(x for x in r["items"] if x["key"] == "resource:deepseek")
    assert a["level"] == "critical" and a["count"] == 1 and r["counts"]["open"] >= 1
    s = m.get("/api/admin/summary").json()
    assert s["pending"]["alerts"]["critical"] >= 1 and s["resource_alerts"] >= 1
    assert m.post(f"/api/admin/alerts/{a['id']}/ack", json={"expected_status": "open"}).json()["status"] == "acked"
    assert m.post(f"/api/admin/alerts/{a['id']}/ack", json={}).status_code == 409
    assert m.post(f"/api/admin/alerts/{a['id']}/resolve", json={}).json()["detail"]["code"] == "reason_required"
    out = m.post(f"/api/admin/alerts/{a['id']}/resolve", json={"reason": "已充值"}).json()
    assert out["status"] == "resolved" and out["resolved_by"]["label"]
    # 条件仍成立 → 下一次同步会重新打开一条新的
    ops.sync(force=True)
    with SessionLocal() as s:
        assert s.scalar(select(Alert).where(Alert.key == "resource:deepseek", Alert.status == "open")) is not None
    ids = [x["id"] for x in m.get("/api/admin/alerts?status=all").json()["items"]]
    b = m.post("/api/admin/alerts/bulk", json={"action": "resolve", "reason": "批量处理", "ids": ids}).json()
    assert b["fail_count"] == 0


def test_miniapp_storage_retention_cleanup(monkeypatch):
    m = login_client("opsboss@example.com", role="admin")
    monkeypatch.setattr(settings, "wx_appid", "wx1234567890abcd")
    monkeypatch.setattr(settings, "wx_secret", "secret-value")
    c = m.get("/api/admin/miniapp-config").json()
    assert c["appid"] == "wx12…abcd" and c["secret_configured"] and "secret-value" not in str(c)
    st = m.get("/api/admin/storage").json()
    assert st["retention"]["activity_days"] == 180 and any(t["name"] == "users" for t in st["db"]["tables"])
    monkeypatch.setattr(settings, "admin_verify_required", False)
    assert m.put("/api/admin/storage/retention", json={"activity_days": 3, "reason": "缩短"}).json()["detail"]["code"] == "bad_range"
    r = m.put("/api/admin/storage/retention", json={"activity_days": 30, "reason": "日志太多"}).json()
    assert r["retention"]["activity_days"] == 30
    with SessionLocal() as s:
        s.add(ActivityLog(action="login", summary="老日志", created_at=utcnow() - timedelta(days=60)))
        s.commit()
    pv = m.post("/api/admin/storage/cleanup", json={"target": "activity", "dry_run": True}).json()
    assert pv["rows"] >= 1 and "30 天" in pv["summary"]
    done = m.post("/api/admin/storage/cleanup", json={"target": "activity", "dry_run": False, "reason": "清理"}).json()
    assert done["rows"] == pv["rows"]
    assert m.post("/api/admin/storage/cleanup", json={"target": "orphan_uploads", "dry_run": True}).json()["rows"] == 0
    monkeypatch.setattr(settings, "admin_verify_required", True)
    r = m.put("/api/admin/storage/retention", json={"activity_days": 60, "reason": "改回"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "verify_required"
