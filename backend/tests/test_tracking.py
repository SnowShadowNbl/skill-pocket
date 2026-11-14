import pytest
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Category, IngestLog, Item, Repo, Task, TaskItem
from app.seed import seed_categories
from app.services import ingest, tracking
from app.services.extract import Extracted
from app.services.github import BudgetExhausted, GitHubError


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        yield s


def make_item(db, name="demo", sub=""):
    repo = Repo(github_id=hash(name) % 10**9, full_name=f"o/{name}", html_url=f"https://github.com/o/{name}")
    db.add(repo)
    db.flush()
    cat = db.scalar(select(Category).where(Category.code == "other-misc"))
    it = Item(repo_id=repo.id, sub_path=sub, name=name, category_id=cat.id, source="manual", locked_fields=[], install_steps=[])
    db.add(it)
    db.commit()
    return it.id


class FakeGH:
    def __init__(self, fail=None):
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def file_text(self, *a):
        raise GitHubError("not found")

    def readme(self, full_name):
        if self.fail:
            raise self.fail
        return "# Demo\n\nA demo tool for testing.\n\n![shot](https://x/img.png)\n", "sha", "README.md"

    def download(self, url):
        return None  # 图片都不可用


def logs(db):
    db.expire_all()
    return db.scalars(select(IngestLog).order_by(IngestLog.id)).all()


def test_doc_failure_is_logged_at_doc_stage(db, monkeypatch):
    iid = make_item(db)
    monkeypatch.setattr(ingest, "GitHub", lambda: FakeGH(fail=GitHubError("仓库或文件不存在")))
    ok, msg = ingest.process_item(iid, trigger="github")
    assert not ok and "读取文档失败" in msg
    errs = [l for l in logs(db) if l.level == "error"]
    assert len(errs) == 1 and errs[0].stage == "doc" and errs[0].trigger == "github" and errs[0].source == "manual"
    assert db.get(Item, iid).ai_status == "failed"


def test_success_with_warnings_for_ai_and_cover(db, monkeypatch):
    iid = make_item(db)
    monkeypatch.setattr(ingest, "GitHub", lambda: FakeGH())
    monkeypatch.setattr(ingest, "extract", lambda doc, cats: Extracted("一句话", "介绍", [], "other-misc", 0.5, True, error="AI 调用失败：timeout"))
    monkeypatch.setattr(ingest, "generate_cover", lambda *a: None)
    ok, msg = ingest.process_item(iid, trigger="crawl")
    assert ok and "入库成功" in msg
    rows = logs(db)
    stages = {(l.stage, l.level) for l in rows}
    assert ("ai", "warn") in stages            # AI 失败、规则兜底
    assert ("cover_readme", "warn") in stages  # README 图片都不可用
    assert ("cover_ai", "warn") in stages      # AI 封面也失败
    assert ("save", "success") in stages
    assert all(l.source == "auto" for l in rows)  # 自动采集触发的记为系统


def test_task_progress_counts_and_item_status(db, monkeypatch):
    ids = [make_item(db, f"t{i}") for i in range(3)]
    tid = tracking.create_task("screenshot", "截图导入 · 3 个", [(i, f"t{n}") for n, i in enumerate(ids)])
    results = {ids[0]: (True, "ok"), ids[1]: (False, "读取文档失败"), ids[2]: (True, "ok")}
    tracking.run_task(tid, ids, lambda i, t: results[i])
    db.expire_all()
    task = db.get(Task, tid)
    assert (task.total, task.done, task.failed, task.status) == (3, 3, 1, "partial")
    st = [ti.status for ti in db.scalars(select(TaskItem).where(TaskItem.task_id == tid).order_by(TaskItem.seq))]
    assert st == ["ok", "failed", "ok"]


def test_budget_exhausted_defers_rest(db):
    ids = [make_item(db, f"b{i}") for i in range(3)]
    tid = tracking.create_task("crawl", "采集", [(i, "x") for i in ids])

    def fn(i, t):
        if i == ids[1]:
            raise BudgetExhausted("额度用完")
        return True, "ok"

    with pytest.raises(BudgetExhausted):
        tracking.run_task(tid, ids, fn, stop_on=(BudgetExhausted,))
    db.expire_all()
    st = [ti.status for ti in db.scalars(select(TaskItem).where(TaskItem.task_id == tid).order_by(TaskItem.seq))]
    assert st == ["ok", "deferred", "deferred"]
    assert db.get(Task, tid).status == "partial"


def test_stage_is_visible_while_running(db, monkeypatch):
    iid = make_item(db)
    tid = tracking.create_task("github", "导入", [(iid, "demo")])
    seen = []
    monkeypatch.setattr(ingest, "GitHub", lambda: FakeGH())

    def fake_extract(doc, cats):
        with SessionLocal() as s:
            seen.append(s.scalar(select(TaskItem.stage).where(TaskItem.task_id == tid)))
        return Extracted("a", "b", [], "other-misc", 0.5, True)

    monkeypatch.setattr(ingest, "extract", fake_extract)
    monkeypatch.setattr(ingest, "generate_cover", lambda *a: None)
    tracking.run_task(tid, [iid], lambda i, t: ingest.process_item(i, task_id=t, trigger="github"))
    assert seen == ["ai"]
