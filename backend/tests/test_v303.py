"""v3.0.3：搜索结果「加入」改为后台逐个加入，接口立即返回；每加好一个，结果列表里那一行变成「已收录」并带条目 id。"""

from unittest import mock

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import FinderJob, User
from app.routers import finder as finder_router
from app.seed import seed_categories
from app.services import finder, ingest
from conftest import login_client


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def _job(uid):
    jid = finder.create_job("search", "脚本和文案创作", user_id=uid)
    cands = [{"full_name": f"o/r{k}", "name": f"r{k}", "sub_path": None, "state": "matched",
              "match": {"full_name": f"o/r{k}"}} for k in range(3)]
    finder._update(jid, status="done", stage="done", candidates=cands)
    return jid


def test_import_returns_immediately_and_marks_rows_existing():
    c = login_client("imp303@example.com")
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "imp303@example.com"))
    jid = _job(uid)
    later = []
    results = {"o/r0": ([101], [], []), "o/r2": ([], [], ["o/r2：仓库不存在"])}
    with mock.patch.object(finder_router, "_start", lambda fn, *a: later.append((fn, a))), \
         mock.patch.object(finder_router.quota, "check_new_items", lambda *a, **k: None):
        r = c.post(f"/api/finder/{jid}/import", json={"picks": [
            {"full_name": "o/r0", "name": "r0", "index": 0}, {"full_name": "o/r2", "name": "r2", "index": 2}]})
    assert r.status_code == 200, r.text
    states = [x["state"] for x in r.json()["job"]["candidates"]]
    assert states == ["importing", "matched", "importing"] and r.json()["job"]["importing"] is True
    # v3.3.7：上一批没加完时也能继续加别的行；已经在加入中的行不能重复加
    with mock.patch.object(finder_router, "_start", lambda fn, *a: later.append((fn, a))), \
         mock.patch.object(finder_router.quota, "check_new_items", lambda *a, **k: None):
        assert c.post(f"/api/finder/{jid}/import", json={"picks": [{"full_name": "o/r0", "index": 0}]}).status_code == 409
        r2 = c.post(f"/api/finder/{jid}/import", json={"picks": [{"full_name": "o/r1", "name": "r1", "index": 1}]})
        assert r2.status_code == 200 and [x["state"] for x in r2.json()["job"]["candidates"]] == ["importing"] * 3
    results["o/r1"] = ([102], [], [])
    # 后台跑完：第一批完成后第二批还在加入，importing 仍为真
    with mock.patch.object(ingest, "import_picks", lambda db, picks, *a, **k: results[picks[0]["full_name"]]), \
         mock.patch.object(ingest, "start_process_task", lambda *a, **k: 7):
        fn, args = later[0]
        fn(*args)
        assert c.get(f"/api/finder/{jid}").json()["importing"] is True
        fn, args = later[1]
        fn(*args)
    job = c.get(f"/api/finder/{jid}").json()
    assert job["candidates"][1]["state"] == "existing"
    by = {x["full_name"]: x for x in job["candidates"]}
    assert by["o/r0"]["state"] == "existing" and by["o/r0"]["existing_item_id"] == 101
    assert by["o/r2"]["state"] == "matched" and "仓库不存在" in by["o/r2"]["import_error"]
    assert job["importing"] is False and job["last_import"] == {"created": [102], "task_id": 7}
    with SessionLocal() as db:
        assert db.get(FinderJob, jid).status == "imported"
