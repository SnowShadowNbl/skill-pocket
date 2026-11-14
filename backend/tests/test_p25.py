"""v2.0（P2.5）：用户提交审核三档、可见范围、失效巡检下线逻辑、反馈、管理员接口、语义搜索。AI / GitHub / Embedding 用替身。"""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import ActivityLog, AppMeta, Category, Feedback, Item, ItemReview, Repo, User
from app.seed import seed_categories
from app.services import judge, liveness, review, search
from conftest import login_client, solve_pow


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def admin_client():
    c = login_client("admin-p25@example.com")
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == "admin-p25@example.com"))
        u.role = "admin"
        s.commit()
    return c


def make_item(name, status="published", created_by=None, repo=None, sub_path="", review_state=""):
    with SessionLocal() as s:
        cat = s.scalar(select(Category).where(Category.code == "coding-gen"))
        it = Item(name=name, category_id=cat.id, status=status, created_by=created_by, repo_id=repo, sub_path=sub_path,
                  review_state=review_state, summary=f"{name} 的简介", locked_fields=[], install_steps=[], source="manual")
        s.add(it)
        s.commit()
        return it.id


def user_id(email):
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.email == email))


def set_mode(mode, threshold=0.8):
    with SessionLocal() as s:
        review.set_settings(s, mode, threshold)


# ---------------------------------------------------------------- 审核三档

def test_review_modes(monkeypatch):
    login_client("sub@example.com")
    uid = user_id("sub@example.com")
    verdict = {"decision": "approve", "confidence": 0.95, "reason": "AI 相关的 Skill", "duplicate_of": None}
    monkeypatch.setattr(judge, "review_item", lambda info, similar, must_decide: dict(verdict))

    set_mode("medium")
    a = make_item("approve-me", "awaiting", uid, review_state="ai")
    assert review.ai_review(a) == "approve"
    verdict.update(confidence=0.6)
    b = make_item("unsure-me", "awaiting", uid, review_state="ai")
    assert review.ai_review(b) == "admin"  # 中等档：把握不足转交管理员
    set_mode("off")
    verdict.update(confidence=0.99)
    c = make_item("off-me", "awaiting", uid, review_state="ai")
    assert review.ai_review(c) == "admin"  # 关闭：AI 只给意见
    set_mode("max")
    verdict.update(decision="reject", confidence=0.7, reason="与 AI 无关")
    d = make_item("reject-me", "awaiting", uid, review_state="ai")
    assert review.ai_review(d) == "reject"

    with SessionLocal() as s:
        st = {i.name: (i.status, i.review_state) for i in s.scalars(select(Item).where(Item.id.in_([a, b, c, d])))}
        assert st == {"approve-me": ("published", ""), "unsure-me": ("awaiting", "admin"), "off-me": ("awaiting", "admin"),
                      "reject-me": ("declined", "")}
        assert s.scalar(select(ItemReview).where(ItemReview.item_id == d)).reason == "与 AI 无关"

    # 管理员二次审核 + 撤回；上线日志
    adm = admin_client()
    assert adm.post(f"/api/admin/items/{b}/review", json={"decision": "approve"}).status_code == 200
    assert adm.post(f"/api/admin/items/{a}/review", json={"decision": "revoke"}).status_code == 400  # 撤回要写理由
    assert adm.post(f"/api/admin/items/{a}/review", json={"decision": "revoke", "reason": "搬运副本"}).status_code == 200
    log = adm.get("/api/admin/reviews/log").json()
    assert {x["decision"] for x in log["items"]} >= {"approve", "reject", "revoke", "unsure"}
    assert adm.get("/api/admin/reviews/pending").json()[0]["name"] == "off-me"
    set_mode("medium")


def test_visibility_of_submissions():
    owner, other = login_client("own@example.com"), login_client("other@example.com")
    uid = user_id("own@example.com")
    i = make_item("secret-pending", "awaiting", uid, review_state="admin")
    assert owner.get(f"/api/items/{i}").status_code == 200
    assert other.get(f"/api/items/{i}").status_code == 404
    assert TestClient(app).get(f"/api/items/{i}").status_code == 404
    assert all(x["name"] != "secret-pending" for x in other.get("/api/items?q=secret").json()["items"])
    subs = owner.get("/api/me/submissions").json()["items"]
    assert subs[0]["name"] == "secret-pending" and subs[0]["status"] == "awaiting" and subs[0]["review_state"] == "admin"
    assert other.get("/api/me/submissions").json()["total"] == 0


def test_admin_only_endpoints():
    u = login_client("nobody-admin@example.com")
    for path in ("/api/admin/feed", "/api/admin/summary", "/api/review", "/api/jobs", "/api/admin/activity"):
        assert u.get(path).status_code == 403, path
        assert TestClient(app).get(path).status_code == 401, path
    assert admin_client().get("/api/admin/summary").status_code == 200
    assert TestClient(app).post("/api/auth/login", json={"password": "x"}).status_code == 410


# ---------------------------------------------------------------- 失效巡检

class FakeResp:
    def __init__(self, code, data):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


def test_liveness_offline_and_restore(monkeypatch):
    with SessionLocal() as s:
        alive = Repo(github_id=1, full_name="o/alive", html_url="https://github.com/o/alive")
        gone = Repo(github_id=2, full_name="o/gone", html_url="https://github.com/o/gone")
        skills = Repo(github_id=3, full_name="o/skills", html_url="https://github.com/o/skills")
        s.add_all([alive, gone, skills])
        s.commit()
        ids = (alive.id, gone.id, skills.id)
    a = make_item("alive-item", repo=ids[0])
    g = make_item("gone-item", repo=ids[1])
    k1 = make_item("skill-kept", repo=ids[2], sub_path="skills/a")
    k2 = make_item("skill-removed", repo=ids[2], sub_path="skills/b")
    state = {"gone": True}

    monkeypatch.setattr(liveness.settings, "github_token", "x")
    monkeypatch.setattr(liveness, "_gql_repos", lambda client, names: {
        n: (None if n == "o/gone" and state["gone"] else {"nameWithOwner": n, "isEmpty": False, "isArchived": n == "o/alive",
                                                           "isDisabled": False, "defaultBranchRef": {"name": "main"}}) for n in names})
    monkeypatch.setattr(liveness, "_request", lambda client, m, url, **kw: FakeResp(200, {"tree": [{"type": "blob", "path": "skills/a/SKILL.md"}]}))

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url):
            return FakeResp(200, {"full_name": "o/gone", "html_url": "x"}) if not state["gone"] else FakeResp(404, {})

    monkeypatch.setattr(liveness, "_client", FakeClient)
    liveness.run("test")
    with SessionLocal() as s:
        st = {i.name: i.status for i in s.scalars(select(Item).where(Item.id.in_([a, g, k1, k2])))}
        assert st == {"alive-item": "published", "gone-item": "offline", "skill-kept": "published", "skill-removed": "offline"}
        assert s.get(Repo, ids[0]).archived is True

    c = TestClient(app)
    # 主页不出现；搜索能搜到并标记已下线；详情不展示
    assert all(x["name"] != "gone-item" for x in c.get("/api/items?size=100").json()["items"])
    found = [x for x in c.get("/api/items?q=gone-item").json()["items"]]
    assert found and found[0]["offline"] is True
    d = c.get(f"/api/items/{g}").json()
    assert d["offline"] is True and "description" not in d
    # 恢复后自动重新上线
    state["gone"] = False
    liveness.run("test")
    with SessionLocal() as s:
        assert s.get(Item, g).status == "published"


# ---------------------------------------------------------------- 反馈

def test_feedback_flow(monkeypatch):
    monkeypatch.setattr(judge, "analyze_feedback", lambda fb, logs, recent: {
        "suggested_category": "bug", "priority": "P1", "priority_reason": "登录不可用", "cause": "验证码邮件发送失败",
        "modules": ["登录"], "impact": "部分用户", "steps": ["查看发信日志"], "summary": "收不到验证码", "similar_ids": []})
    import app.routers.feedback as fbmod
    monkeypatch.setattr(fbmod.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())

    guest = TestClient(app)
    assert guest.post("/api/feedback", data={"category": "account", "content": "收不到验证码"}).status_code == 400  # 未登录要人机校验
    ch = guest.get("/api/auth/challenge").json()
    r = guest.post("/api/feedback", data={"category": "account", "content": "收不到验证码", "pow_token": ch["token"],
                                          "pow_nonce": solve_pow(ch), "diagnostics": '{"page": "/"}'})
    assert r.status_code == 200
    u = login_client("fb@example.com")
    fid = u.post("/api/feedback", data={"category": "bug", "content": "收藏点了没反应", "input_type": "voice"}).json()["id"]
    with SessionLocal() as s:
        f = s.get(Feedback, fid)
        assert f.ai_status == "done" and f.priority == "P1" and f.input_type == "voice"

    adm = admin_client()
    lst = adm.get("/api/admin/feedback").json()
    assert lst["items"][0]["priority"] == "P1"
    adm.patch(f"/api/admin/feedback/{fid}", json={"status": "resolved", "reply": "已修复，谢谢反馈"})
    mine = u.get("/api/me/feedback").json()
    assert mine["unread"] == 1 and mine["items"][0]["admin_reply"] == "已修复，谢谢反馈" and "priority" not in mine["items"][0]
    u.post("/api/me/feedback/read")
    assert u.get("/api/me/feedback").json()["unread"] == 0


def test_activity_feed():
    adm = admin_client()
    u = login_client("feed@example.com")
    i = make_item("feed-item")
    u.post(f"/api/items/{i}/comments", json={"content": "很好用"})
    feed = adm.get("/api/admin/feed").json()
    top = feed["items"][0]
    assert top["action"] == "comment" and top["user"]["email"] == "feed@example.com" and top["unseen"]
    unseen = adm.get("/api/admin/summary").json()["feed_unseen"]
    adm.post("/api/admin/feed/seen", json={"last_id": top["id"]})
    assert adm.get("/api/admin/summary").json()["feed_unseen"] < unseen


# ---------------------------------------------------------------- 语义搜索

def test_semantic_search(monkeypatch):
    h5 = make_item("mobile-ui-kit")
    other = make_item("db-backup")
    monkeypatch.setattr(search.settings, "embedding_api_key", "x")
    vecs = {"mobile-ui-kit": [1.0, 0.0], "db-backup": [0.0, 1.0]}

    def fake_embed(texts):
        out = []
        for t in texts:
            if "mobile-ui-kit" in t:
                out.append(vecs["mobile-ui-kit"])
            elif "db-backup" in t:
                out.append(vecs["db-backup"])
            else:
                out.append([0.9, 0.1])  # 「H5 设计」的查询向量更接近 UI
        return [search._normalize(v) for v in out]

    monkeypatch.setattr(search, "_embed", fake_embed)
    monkeypatch.setattr(search, "_index", {})
    monkeypatch.setattr(search, "_loaded", True)
    search.embed_items([h5, other])
    calls = []

    def fake_refine(q, items):
        calls.append([x["id"] for x in items])
        return {"understanding": "找 H5 页面设计的 Skill", "results": {x["id"]: {"score": 92, "reason": "移动端 UI 组件"} for x in items}}

    monkeypatch.setattr(judge, "refine_search", fake_refine)
    monkeypatch.setattr(type(search.settings), "ai_enabled", property(lambda self: True))
    c = TestClient(app)
    # 第一段：只有向量结果，立刻返回，AI 还没做
    fast = c.get("/api/search?q=H5设计类的skill").json()
    assert fast["mode"] == "semantic" and fast["ai_pending"] is True and fast["understanding"] == ""
    assert fast["items"][0]["name"] == "mobile-ui-kit" and fast["items"][0]["match"]["reason"] == ""
    assert all(x["name"] != "db-backup" for x in fast["items"])
    assert not calls
    # 第二段：一次 AI 调用补上理解和理由
    ai = c.get("/api/search?q=H5设计类的skill&stage=ai").json()
    assert ai["ai_pending"] is False and ai["understanding"] == "找 H5 页面设计的 Skill"
    assert ai["items"][0]["match"]["reason"] == "移动端 UI 组件" and len(calls) == 1
    # 之后同样的搜索第一段就直接带上 AI 结果（缓存），不再调用 AI
    again = c.get("/api/search?q=H5设计类的skill").json()
    assert again["ai_pending"] is False and again["understanding"] and len(calls) == 1
    # 精确命中项目名的永远第一
    other_first = c.get("/api/search?q=db-backup").json()
    assert other_first["items"][0]["name"] == "db-backup"
