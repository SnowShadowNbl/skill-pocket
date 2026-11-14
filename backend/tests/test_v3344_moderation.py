"""v3.3.44 后台批次 2a：评论处置（软删 / 评分重算 / 历史 / 并发）、理由模板、分享关闭、搜索词。"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, utcnow
from app.main import app, ensure_admin
from app.models import Category, Comment, Event, FavDimension, Favorite, FavFolder, FavoriteFolderLink, Item, User
from app.seed import seed_categories
from app.services import search_terms
from conftest import login_client

S = {}


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        a = User(email="r1@example.com", nickname="甲", role="user", status="active")
        b = User(email="r2@example.com", nickname="乙", role="user", status="active")
        s.add_all([a, b])
        s.flush()
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        it = Item(name="评分条目", category_id=cat.id, status="published")
        s.add(it)
        s.flush()
        c1 = Comment(item_id=it.id, user_id=a.id, content="很好用", rating=5)
        c2 = Comment(item_id=it.id, user_id=b.id, content="一般般", rating=1)
        c3 = Comment(item_id=it.id, user_id=b.id, content="待审的广告", status="pending", review_reason="疑似广告")
        s.add_all([c1, c2, c3])
        dim = FavDimension(owner_id=a.id, name="我的")
        s.add(dim)
        s.flush()
        f = FavFolder(dimension_id=dim.id, name="精选", share_token="sharetok1")
        s.add(f)
        fav = Favorite(owner_id=a.id, item_id=it.id)
        s.add(fav)
        s.flush()
        s.add(FavoriteFolderLink(favorite_id=fav.id, folder_id=f.id))
        s.commit()
        from app.services import ratings
        ratings.recompute(s, it.id)
        S.update(item=it.id, c1=c1.id, c2=c2.id, c3=c3.id, folder=f.id, a=a.id)


def test_comment_actions_and_history():
    m1 = login_client("modboss@example.com", role="admin")
    m2 = login_client("modsub@example.com", role="subadmin")
    lst = m1.get("/api/admin/comments?status=pending").json()
    assert lst["total"] == 1 and lst["counts"]["visible"] == 2 and lst["items"][0]["review_reason"] == "疑似广告"
    assert m1.get(f"/api/admin/comments?id={S['c2']}").json()["items"][0]["id"] == S["c2"]
    # 删除差评需要原因；评分 3.0 → 5.0
    assert m1.post(f"/api/admin/comments/{S['c2']}/delete", json={"reason": ""}).json()["detail"]["code"] == "reason_required"
    r = m1.post(f"/api/admin/comments/{S['c2']}/delete", json={"reason": "恶意差评", "expected_status": "visible"}).json()
    assert r["item_rating"] == {"before": {"avg": 3.0, "count": 2}, "after": {"avg": 5.0, "count": 1}}
    # 另一个管理员按旧状态再处理：409 already_handled
    r2 = m2.post(f"/api/admin/comments/{S['c2']}/reject", json={"reason": "重复处理", "expected_status": "visible"})
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "already_handled"
    assert r2.json()["detail"]["handled_by"]["id"] and r2.json()["detail"]["status"] == "deleted"
    # 软删：内容还在，前台看不到
    with SessionLocal() as s:
        assert s.get(Comment, S["c2"]).content == "一般般"
    pub = TestClient(app).get(f"/api/items/{S['item']}/comments").json()
    assert {c["id"] for c in pub} == {S["c1"]}
    # 恢复后评分回到 3.0；历史有发表、删除、恢复
    r = m1.post(f"/api/admin/comments/{S['c2']}/restore", json={"reason": "误删"}).json()
    assert r["item_rating"]["after"] == {"avg": 3.0, "count": 2}
    h = m1.get(f"/api/admin/comments/{S['c2']}/history").json()
    assert [x["action"] for x in h["items"]] == ["create", "delete", "restore"]
    assert h["items"][1]["reason"] == "恶意差评" and h["items"][1]["rating"]["after"]["avg"] == 5.0
    # 待审的通过不需要原因
    assert m1.post(f"/api/admin/comments/{S['c3']}/approve").json()["comment"]["status"] == "visible"


def test_author_delete_is_soft():
    a = login_client("r1@example.com")
    assert a.delete(f"/api/comments/{S['c1']}").json()["ok"]
    with SessionLocal() as s:
        c = s.get(Comment, S["c1"])
        assert c.status == "deleted" and c.handle_reason == "作者删除"
    m = login_client("modboss@example.com", role="admin")
    assert m.get("/api/admin/comments?status=deleted").json()["total"] == 1
    assert a.get("/api/me/stats").json()["comments"] == 0


def test_templates():
    sup = login_client("modboss@example.com", role="admin")
    sub = login_client("modsub@example.com", role="subadmin")
    r = sub.get("/api/admin/reason-templates?scope=comment_delete").json()
    assert len(r["items"]) == 3 and r["scopes"]["share_close"] == "关闭分享"
    assert sub.post("/api/admin/reason-templates", json={"scope": "comment_delete", "text": "x"}).status_code == 403
    t = sup.post("/api/admin/reason-templates", json={"scope": "comment_delete", "text": "刷屏"}).json()
    assert sup.post("/api/admin/reason-templates", json={"scope": "comment_delete", "text": "刷屏"}).json()["detail"]["code"] == "duplicate"
    assert sup.put(f"/api/admin/reason-templates/{t['id']}", json={"text": "刷屏灌水"}).json()["text"] == "刷屏灌水"
    assert sup.delete(f"/api/admin/reason-templates/{t['id']}").json()["ok"]


def test_shares():
    m = login_client("modboss@example.com", role="admin")
    pub = TestClient(app)
    assert pub.get("/api/shared/sharetok1").status_code == 200
    lst = m.get("/api/admin/shares?q=精选").json()
    assert lst["total"] == 1 and lst["items"][0]["views"] == 1 and lst["items"][0]["count"] == 1
    r = m.post(f"/api/admin/shares/{S['folder']}/close", json={"reason": "名称不当", "expected_status": "sharing"}).json()
    assert r["status"] == "closed" and r["closed"]["reason"] == "名称不当"
    assert pub.get("/api/shared/sharetok1").status_code == 404
    assert m.post(f"/api/admin/shares/{S['folder']}/close", json={"reason": "再关"}).status_code == 409
    owner = login_client("r1@example.com")
    r = owner.post(f"/api/favorites/folders/{S['folder']}/share")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "share_closed_by_admin"
    assert m.get(f"/api/admin/shares/{S['folder']}/preview").json()["items"][0]["name"] == "评分条目"
    assert m.get("/api/admin/shares?status=closed").json()["total"] == 1
    assert m.post(f"/api/admin/shares/{S['folder']}/reopen", json={"reason": "已改名"}).json()["status"] == "sharing"
    assert pub.get("/api/shared/sharetok1").status_code == 200


def test_search_terms():
    search_terms.record("不存在的东西", 0)
    search_terms.record("不存在的东西", 0)
    search_terms.record("评分", 3)
    now = utcnow()
    with SessionLocal() as s:
        for vid in ("v1", "v2", "v3"):
            s.add(Event(vid=vid, name="search", category="search", props={"q": "推广链接"}, created_at=now))
            s.add(Event(vid=vid, name="search", category="search", props={"q": "评分"}, created_at=now - timedelta(days=1)))
        s.add(Event(vid="v1", name="search", category="search", props={"q": "孤单"}, created_at=now))
        s.commit()
    m = login_client("modboss@example.com", role="admin")
    e = m.get("/api/admin/search-terms/empty").json()
    assert e["total"] == 1 and e["items"][0]["term"] == "不存在的东西" and e["items"][0]["empty_count"] == 2
    tid = e["items"][0]["id"]
    assert m.post(f"/api/admin/search-terms/{tid}/cover", json={"note": "已收录 #1"}).json()["covered"]["note"] == "已收录 #1"
    assert m.get("/api/admin/search-terms/empty").json()["total"] == 0
    assert m.get("/api/admin/search-terms/empty?status=covered").json()["total"] == 1
    search_terms.invalidate_hot()
    pub = TestClient(app)
    assert {x["q"] for x in pub.get("/api/search/hot").json()} == {"推广链接", "评分"}
    b = m.post("/api/admin/search-blocklist", json={"term": "推广链接", "reason": "引流"}).json()
    assert [x["q"] for x in pub.get("/api/search/hot").json()] == ["评分"]
    hot = {x["term"]: x for x in m.get("/api/admin/search-terms/hot").json()["items"]}
    assert hot["推广链接"]["reason"] == "blocked" and hot["孤单"]["reason"] == "few_people" and hot["评分"]["status"] == "shown"
    assert m.post("/api/admin/search-blocklist", json={"term": "推广链接"}).json()["detail"]["code"] == "duplicate"
    assert len(m.get("/api/admin/search-blocklist").json()["items"]) == 1
    assert m.delete(f"/api/admin/search-blocklist/{b['id']}").json()["ok"]
    assert {x["q"] for x in pub.get("/api/search/hot").json()} == {"推广链接", "评分"}


def test_summary_pending_and_item_conflict():
    m = login_client("modboss@example.com", role="admin")
    p = m.get("/api/admin/summary").json()["pending"]
    assert p["reports"] is None and p["shares_reported"] is None and isinstance(p["comments"], int)
    r = m.post(f"/api/admin/items/{S['item']}/review", json={"decision": "approve", "expected_status": "awaiting"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_handled" and r.json()["detail"]["status"] == "published"


def test_takedown_template_scopes_seeded_for_old_db():
    """v3.3.49 老库（已有 5 类模板）只补新加的下架申请两类，不重复放。"""
    from app.models import AppMeta, ReasonTemplate

    with SessionLocal() as s:
        s.query(ReasonTemplate).filter(ReasonTemplate.scope.like("takedown_%")).delete()
        meta = s.get(AppMeta, "reason_template_scopes")
        if meta:
            s.delete(meta)
        s.commit()
        before = s.query(ReasonTemplate).filter(ReasonTemplate.scope == "comment_delete").count()
    m = login_client("modboss@example.com", role="admin")
    r = m.get("/api/admin/reason-templates").json()
    by = {}
    for t in r["items"]:
        by[t["scope"]] = by.get(t["scope"], 0) + 1
    assert by["takedown_reject"] == 3 and by["takedown_approve"] == 2 and by["comment_delete"] == before
    m.get("/api/admin/reason-templates")
    assert len(m.get("/api/admin/reason-templates?scope=takedown_reject").json()["items"]) == 3
