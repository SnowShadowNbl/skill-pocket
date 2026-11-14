"""v2.3 对比：入参校验、登录与额度、本站条目 + 外站仓库、AI 结果校验与代号映射、7 天复用。AI / GitHub 用替身。"""

import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import Category, CompareRun, Item, Repo
from app.seed import seed_categories
from app.services import compare, judge
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def make_item(name, full_name=None, status="published"):
    with SessionLocal() as s:
        cat = s.scalar(select(Category).where(Category.code == "coding-gen"))
        repo = None
        if full_name:
            repo = Repo(github_id=abs(hash(full_name)) % 10**9, full_name=full_name, html_url=f"https://github.com/{full_name}", stars=1200)
            s.add(repo)
            s.flush()
        it = Item(name=name, category_id=cat.id, status=status, repo_id=repo.id if repo else None, summary=f"{name} 的简介",
                  kind="agent_skill", locked_fields=[], install_steps=["npx skills add x"], source="manual")
        s.add(it)
        s.commit()
        return it.id


class FakeGH:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def repo(self, ref):
        return {"stargazers_count": 321, "pushed_at": "2026-10-01T00:00:00Z", "archived": False, "license": {"spdx_id": "MIT"},
                "description": "Turn web pages into Markdown", "language": "Python", "topics": ["llm"]}

    def readme(self, full_name, sub_path=""):
        return "# crawler\n<img src=x>\nUsage: pip install crawler", "sha", "README.md"


def wait(c, rid):
    for _ in range(50):
        r = c.get(f"/api/compare/{rid}").json()
        if r["status"] != "running":
            return r
        time.sleep(0.05)
    raise AssertionError("对比没有结束")


def test_validation_and_login():
    a = make_item("tdd-skill", "acme/tdd")
    assert TestClient(app).post("/api/compare", json={"entries": [{"item_id": a}, {"full_name": "x/y"}]}).status_code == 401
    c = login_client("cmp1@example.com")
    assert c.post("/api/compare", json={"entries": [{"item_id": a}]}).status_code == 400
    assert c.post("/api/compare", json={"entries": [{"item_id": a}, {"item_id": a}]}).status_code == 400  # 去重后只剩 1 个
    assert c.post("/api/compare", json={"entries": [{"full_name": "bad name"}, {"item_id": a}]}).status_code == 400
    hidden = make_item("draft", status="awaiting")
    assert c.post("/api/compare", json={"entries": [{"item_id": a}, {"item_id": hidden}]}).status_code == 400


def test_compare_site_and_github(monkeypatch):
    a = make_item("tdd-skill-2", "acme/tdd2")
    b = make_item("test-writer", "acme/tw")
    monkeypatch.setattr(compare, "GitHub", FakeGH)
    seen = {}

    def fake_compare(subjects):
        seen["subjects"] = subjects
        return judge_result()

    def judge_result():
        return {"summary": "A、B 都写测试，C 是网页转换工具", "groups": [
            {"type": "same", "title": "自动写测试", "ids": ["A", "B"], "note": "",
             "dimensions": [{"name": "上手难度", "values": {"A": "一条命令", "B": "需要配置"}, "better": "A"}]},
            {"type": "different", "title": "网页转 Markdown", "ids": ["C"], "dimensions": [], "note": "类型不同、作用不同"}],
            "usage": {"A": ["安装", "运行"]}, "recommendations": [{"scenario": "快速上手", "id": "A", "reason": "最简单"}], "warnings": []}

    monkeypatch.setattr(judge, "compare_items", fake_compare)
    c = login_client("cmp2@example.com")
    r = c.post("/api/compare", json={"entries": [{"item_id": a}, {"item_id": b}, {"full_name": "web/crawler"}]})
    assert r.status_code == 200, r.text
    assert [s["name"] for s in r.json()["subjects"]] == ["tdd-skill-2", "test-writer", "crawler"]
    done = wait(c, r.json()["id"])
    assert done["status"] == "done" and done["result"]["groups"][0]["ids"] == ["A", "B"]
    gh = next(s for s in done["subjects"] if s["code"] == "C")
    assert gh["source"] == "github" and gh["stars"] == 321 and gh["license"] == "MIT"
    sent = {s["code"]: s for s in seen["subjects"]}
    assert "<img" not in sent["C"]["readme"] and sent["A"]["source"] == "本站收录" and "cover_url" not in sent["A"]

    # 同一组（顺序不同）7 天内复用，不再调用 AI
    seen.clear()
    again = c.post("/api/compare", json={"entries": [{"full_name": "web/crawler"}, {"item_id": b}, {"item_id": a}]}).json()
    assert again["id"] == r.json()["id"] and not seen
    # 结果可以分享：未登录也能看
    assert TestClient(app).get(f"/api/compare/{again['id']}").json()["status"] == "done"
    mine = c.get("/api/me/compares").json()
    assert mine[0]["names"] == ["tdd-skill-2", "test-writer", "crawler"] and mine[0]["summary"]


def test_already_collected_repo_counts_as_site_item(monkeypatch):
    a = make_item("collected", "acme/collected")
    b = make_item("other", "acme/other")
    monkeypatch.setattr(judge, "compare_items", lambda s: {"summary": "", "groups": [], "usage": {}, "recommendations": [], "warnings": []})
    c = login_client("cmp3@example.com")
    r = c.post("/api/compare", json={"entries": [{"full_name": "acme/collected"}, {"item_id": b}]}).json()
    assert r["subjects"][0]["source"] == "site" and r["subjects"][0]["item_id"] == a


def test_ai_unavailable_marks_failed(monkeypatch):
    a = make_item("x1", "acme/x1")
    b = make_item("x2", "acme/x2")

    def boom(_):
        raise judge.JudgeUnavailable("未配置 AI 接口")

    monkeypatch.setattr(judge, "compare_items", boom)
    c = login_client("cmp4@example.com")
    r = c.post("/api/compare", json={"entries": [{"item_id": a}, {"item_id": b}]}).json()
    done = wait(c, r["id"])
    assert done["status"] == "failed" and "AI" in done["error"]
    with SessionLocal() as s:
        assert s.get(CompareRun, r["id"]).status == "failed"


def test_compare_items_sanitizes(monkeypatch):
    monkeypatch.setattr(judge, "_ask", lambda *a, **k: {
        "summary": "x", "groups": [{"type": "same", "ids": ["A", "Z"], "dimensions": [{"name": "成本", "values": {"A": "免费", "Q": "?"}, "better": "Q"}]}],
        "usage": {"A": ["s"], "Z": ["bad"]}, "recommendations": [{"id": "Z", "reason": "bad"}, {"id": "B", "scenario": "s", "reason": "ok"}]})
    out = judge.compare_items([{"code": "A"}, {"code": "B"}])
    # 只有 1 个有效 id 的「同类组」降为单独一组；AI 漏掉的 B 补成单独一组；无效代号全部丢掉
    assert out["groups"][0]["type"] == "different" and out["groups"][0]["ids"] == ["A"]
    assert any(g["ids"] == ["B"] for g in out["groups"])
    assert "Z" not in out["usage"] and [r["id"] for r in out["recommendations"]] == ["B"]
