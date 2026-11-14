from fastapi.testclient import TestClient

from app.changelog import RELEASES, seed_changelog
from app.db import Base, SessionLocal, engine
from app.main import app


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_seed_is_idempotent_and_grouped_newest_first():
    with SessionLocal() as s:
        seed_changelog(s)
        seed_changelog(s)  # 重复执行不重复插入
    d = TestClient(app).get("/api/changelog").json()
    assert d["latest"] == RELEASES[0]["version"]
    assert [r["version"] for r in d["releases"]] == [r["version"] for r in RELEASES]
    assert sum(len(r["entries"]) for r in d["releases"]) == sum(len(r["entries"]) for r in RELEASES)
    assert {e["category"] for r in d["releases"] for e in r["entries"]} <= {"feature", "change", "fix"}


def test_admin_required_to_add():
    r = TestClient(app).post("/api/changelog", json={"version": "v9", "category": "fix", "title": "x"})
    assert r.status_code == 401
