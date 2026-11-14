"""v3.3.25 截图识别「加入」改到后台线程：快的照旧同步返回结果，慢的先返回 queued，轮询 GET 拿结果。"""

import time

from app.db import Base, SessionLocal, engine
from app.models import Upload
from app.routers import uploads
from app.services import ingest
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _upload(uid: int) -> int:
    with SessionLocal() as db:
        rec = Upload(image_path="uploads/x.png", status="recognized", user_id=uid,
                     ai_result={"items": [{"name": "a", "state": "matched"}]})
        db.add(rec)
        db.commit()
        return rec.id


def _me(c) -> int:
    return c.get("/api/auth/me").json()["user"]["id"]


def test_fast_import_returns_result(monkeypatch):
    c = login_client("upimp1@example.com")
    monkeypatch.setattr(ingest, "import_picks", lambda db, picks, trig, user_id=None, review=False: ([], ["a"], []))
    monkeypatch.setattr(ingest, "start_process_task", lambda *a, **k: None)
    uid = _upload(_me(c))
    r = c.post(f"/api/uploads/{uid}/import", json={"picks": [{"full_name": "o/a", "name": "a"}]}).json()
    assert r["queued"] is False and r["skipped"] == ["a"] and r["errors"] == []
    assert c.get(f"/api/uploads/{uid}").json()["status"] == "imported"


def test_slow_import_is_queued_then_polled(monkeypatch):
    c = login_client("upimp2@example.com")

    def slow(db, picks, trig, user_id=None, review=False):
        time.sleep(1.5)
        return [], [], ["o/b：仓库不存在"]

    monkeypatch.setattr(ingest, "import_picks", slow)
    monkeypatch.setattr(ingest, "start_process_task", lambda *a, **k: None)
    monkeypatch.setattr(uploads, "IMPORT_WAIT", 0.1)
    uid = _upload(_me(c))
    r = c.post(f"/api/uploads/{uid}/import", json={"picks": [{"full_name": "o/b", "name": "b"}]}).json()
    assert r["queued"] is True and r["status"] == "importing"
    # 加入中再点一次：409
    assert c.post(f"/api/uploads/{uid}/import", json={"picks": [{"full_name": "o/b"}]}).status_code == 409
    for _ in range(40):
        g = c.get(f"/api/uploads/{uid}").json()
        if g["status"] == "imported":
            break
        time.sleep(0.1)
    assert g["status"] == "imported" and g["import"]["errors"] == ["o/b：仓库不存在"]


def test_import_marks_rows_importing_then_existing(monkeypatch):
    """v3.3.81 加入中的行标成 importing（不能再勾选），加完后对应到条目的改成 existing 并带 existing_item_id。"""
    c = login_client("upimp3@example.com")
    seen = {}

    def slow(db, picks, trig, user_id=None, review=False):
        time.sleep(0.8)
        return [], ["c"], []

    monkeypatch.setattr(ingest, "import_picks", slow)
    monkeypatch.setattr(ingest, "start_process_task", lambda *a, **k: None)
    monkeypatch.setattr(uploads, "_existing_for", lambda db, fn, sub: 77 if fn == "o/c" else None)
    monkeypatch.setattr(uploads, "IMPORT_WAIT", 0.1)
    with SessionLocal() as db:
        rec = Upload(image_path="uploads/x.png", status="recognized", user_id=_me(c), ai_result={"items": [
            {"name": "c", "state": "matched", "match": {"full_name": "O/c"}, "sub_path": None},
            {"name": "d", "state": "matched", "match": {"full_name": "o/d"}, "sub_path": None}]})
        db.add(rec)
        db.commit()
        uid = rec.id
    c.post(f"/api/uploads/{uid}/import", json={"picks": [{"full_name": "o/c", "name": "c"}]})
    g = c.get(f"/api/uploads/{uid}").json()
    assert [it["state"] for it in g["items"]] == ["importing", "matched"]
    for _ in range(40):
        g = c.get(f"/api/uploads/{uid}").json()
        if g["status"] == "imported":
            break
        time.sleep(0.1)
    assert g["items"][0]["state"] == "existing" and g["items"][0]["existing_item_id"] == 77
    assert g["items"][1]["state"] == "matched"
    assert g["import"]["resolved"] == [{"full_name": "o/c", "sub_path": None, "item_id": 77}]
