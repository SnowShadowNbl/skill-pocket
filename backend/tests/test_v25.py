"""v2.5：上传头像（压缩）、管理员改用户邮箱、资源监控、批量补图片集、任务浮窗的条目窗口。"""

import io
import time

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import AiCall, Category, Item, Repo, User
from app.routers.tasks import _window
from app.seed import seed_categories
from app.services import ingest
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def admin():
    c = login_client("boss25@example.com")
    with SessionLocal() as s:
        s.scalar(select(User).where(User.email == "boss25@example.com")).role = "admin"
        s.commit()
    return c


def photo(w=1600, h=1200) -> bytes:
    img = Image.new("RGB", (w, h))
    for x in range(0, w, 8):  # 加点纹理，避免压缩得过于理想
        for y in range(0, h, 8):
            img.putpixel((x, y), ((x * 7) % 255, (y * 3) % 255, (x + y) % 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_avatar_upload_is_compressed():
    c = login_client("face@example.com")
    raw = photo()
    r = c.post("/api/auth/me/avatar", files={"file": ("me.png", io.BytesIO(raw), "image/png")})
    assert r.status_code == 200, r.text
    d = r.json()
    path = d["user"]["avatar"]
    assert path.startswith("avatars/") and path.endswith(".webp") and d["bytes"] < 40_000 < d["original_bytes"]
    with Image.open(settings.media_dir / path) as saved:
        assert saved.size == (256, 256)
    # 换回预设颜色时删掉旧图片
    assert c.patch("/api/auth/me", json={"avatar": "teal"}).json()["user"]["avatar"] == "teal"
    assert not (settings.media_dir / path).exists()
    assert c.post("/api/auth/me/avatar", files={"file": ("x.png", io.BytesIO(b"not an image"), "image/png")}).status_code == 400


def test_admin_change_email():
    login_client("old.addr@example.com")
    login_client("taken@example.com")
    a = admin()
    with SessionLocal() as s:
        uid = s.scalar(select(User.id).where(User.email == "old.addr@example.com"))
    assert a.put(f"/api/admin/users/{uid}/email", json={"email": "bad"}).status_code == 400
    assert a.put(f"/api/admin/users/{uid}/email", json={"email": "taken@example.com"}).status_code == 400
    r = a.put(f"/api/admin/users/{uid}/email", json={"email": "New.Addr@Example.com"})
    assert r.status_code == 200 and r.json()["email"] == "new.addr@example.com"
    assert login_client("x25@example.com").put(f"/api/admin/users/{uid}/email", json={"email": "z@example.com"}).status_code == 403


def test_resources_overview():
    with SessionLocal() as s:
        s.add(AiCall(purpose="AI-15", model="m", tokens_in=100, tokens_out=50, ok=True))
        s.add(AiCall(purpose="EMB", model="text-embedding-v4", tokens_in=300, tokens_out=0, ok=True))
        s.commit()
    a = admin()
    d = a.get("/api/admin/resources").json()
    assert d["ai"]["all"]["tokens_in"] >= 100 and d["ai"]["by_purpose"][0]["label"] == "站内搜索"
    assert d["ai"]["balance"]["supported"] is False  # 测试里没配 AI 接口，不会去查余额
    assert "EMB" not in [p["purpose"] for p in d["ai"]["by_purpose"]]
    assert d["server"]["disk"]["total"] > 0 and d["server"]["advice"]
    assert "resource_alerts" in a.get("/api/admin/summary").json()
    assert login_client("y25@example.com").get("/api/admin/resources").status_code == 403


def test_images_backfill(monkeypatch):
    with SessionLocal() as s:
        cat = s.scalar(select(Category).where(Category.code == "coding-gen"))
        repo = Repo(github_id=999001, full_name="acme/pics", html_url="https://github.com/acme/pics", stars=5)
        s.add(repo)
        s.flush()
        s.add(Item(name="pics", category_id=cat.id, repo_id=repo.id, status="published", locked_fields=[], install_steps=[], source="auto"))
        s.add(Item(name="locked", category_id=cat.id, repo_id=repo.id, sub_path="x", status="published", locked_fields=["cover_path"],
                   install_steps=[], source="auto"))
        s.commit()
    done = []
    monkeypatch.setattr(ingest, "gallery_for", lambda i, t=None: (done.append(i), (True, "新增 2 张"))[1])
    r = admin().post("/api/admin/items/images-backfill").json()
    assert r["queued"] == 1 and r["task_id"]
    for _ in range(50):
        if done:
            break
        time.sleep(0.05)
    assert len(done) == 1


def test_task_window_trims_big_tasks():
    class TI:
        def __init__(self, seq, status):
            self.seq, self.status = seq, status
    items = [TI(i, "ok") for i in range(1, 201)] + [TI(201, "running")] + [TI(i, "pending") for i in range(202, 481)]
    items[9].status = "failed"
    w = _window(items)
    seqs = [i.seq for i in w]
    assert 201 in seqs and 10 in seqs and len(w) <= 17


def test_super_can_change_subadmin_email_only():
    login_client("sub.email@example.com")
    a = admin()
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == "sub.email@example.com"))
        u.role = "subadmin"
        s.commit()
        uid = u.id
    assert a.post(f"/api/admin/users/{uid}/status", json={"status": "disabled"}).status_code == 400
    r = a.put(f"/api/admin/users/{uid}/email", json={"email": "sub.new@example.com"})
    assert r.status_code == 200 and r.json()["email"] == "sub.new@example.com"


def test_doc_404_rechecks_and_takes_item_offline(monkeypatch):
    """抓文档时 404（Skill 目录被删）→ 立即复查原地址 → 确认失效就下线，前台显示「原文已下线」。"""
    from app.services import liveness
    from app.services.github import NotFound

    with SessionLocal() as s:
        cat = s.scalar(select(Category).where(Category.code == "coding-gen"))
        repo = Repo(github_id=999002, full_name="acme/ctx", html_url="https://github.com/acme/ctx", stars=5)
        s.add(repo)
        s.flush()
        it = Item(name="ctx-search", category_id=cat.id, repo_id=repo.id, sub_path="skills/ctx-search", status="published",
                  locked_fields=[], install_steps=[], source="auto")
        keep = Item(name="ctx-stats", category_id=cat.id, repo_id=repo.id, sub_path="skills/ctx-stats", status="published",
                    locked_fields=[], install_steps=[], source="auto")
        s.add_all([it, keep])
        s.commit()
        gone_id, keep_id = it.id, keep.id

    class FakeResp:
        def __init__(self, code, data):
            self.status_code, self._d = code, data

        def json(self):
            return self._d

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    class FakeGH:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(liveness.settings, "github_token", "x")
    monkeypatch.setattr(liveness, "_client", FakeClient)
    monkeypatch.setattr(liveness, "_gql_repos", lambda client, names: {
        n: {"nameWithOwner": n, "isEmpty": False, "isArchived": False, "isDisabled": False, "defaultBranchRef": {"name": "main"}} for n in names})
    monkeypatch.setattr(liveness, "_request", lambda client, m, url, **kw: FakeResp(200, {"tree": [{"type": "blob", "path": "skills/ctx-stats/SKILL.md"}]}))
    monkeypatch.setattr(ingest, "GitHub", FakeGH)

    def boom(*a, **k):
        raise NotFound("仓库或文件不存在（或为私有仓库）")

    monkeypatch.setattr(ingest, "fetch_doc", boom)
    ok, msg = ingest.gallery_for(gone_id)
    assert not ok and "已下线" in msg
    with SessionLocal() as s:
        assert s.get(Item, gone_id).status == "offline"
        assert s.get(Item, keep_id).status == "published"  # 只复查出错的条目
    card = [x for x in TestClient(app).get("/api/items?q=ctx-search").json()["items"] if x["id"] == gone_id]
    assert card and card[0]["offline"] is True
