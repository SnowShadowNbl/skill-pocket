"""v3.3：评论内容审核。AI 判断 pass / block / review；AI 不可用时敏感词兜底（只送审，不拦）。"""

from unittest import mock

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Category, Comment, Item
from app.seed import seed_categories
from app.services import judge
from conftest import login_client


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def _item():
    with SessionLocal() as db:
        cid = db.scalar(select(Category.id).where(Category.parent_id.is_not(None)))
        it = Item(name="demo", category_id=cid, status="published", locked_fields=[], install_steps=[])
        db.add(it)
        db.commit()
        return it.id


def _ai(decision, reason="r"):
    return mock.patch.object(judge, "moderate_comment", lambda content, name: {"decision": decision, "category": "", "reason": reason})


def test_pass_block_review():
    iid = _item()
    a, b = login_client("ca@example.com"), login_client("cb@example.com")
    with _ai("pass"):
        assert a.post(f"/api/items/{iid}/comments", json={"content": "很好用"}).json()["status"] == "visible"
    with _ai("block", "广告引流"):
        r = a.post(f"/api/items/{iid}/comments", json={"content": "加微信领资料"})
        assert r.status_code == 422 and "广告引流" in r.json()["detail"]
    with _ai("review", "疑似广告"):
        assert a.post(f"/api/items/{iid}/comments", json={"content": "可能是广告"}).json()["status"] == "pending"
    with SessionLocal() as db:
        assert db.scalar(select(Comment).where(Comment.content == "加微信领资料")) is None  # 拦下的不保存
    # 待审核的只有作者和管理员看得到
    assert len(a.get(f"/api/items/{iid}/comments").json()) == 2
    assert [c["content"] for c in b.get(f"/api/items/{iid}/comments").json()] == ["很好用"]
    admin = login_client("cadm@example.com", role="admin")
    assert admin.get("/api/admin/summary").json()["pending_comments"] == 1
    pend = admin.get("/api/admin/comments").json()["items"]
    assert len(pend) == 1 and pend[0]["review_reason"] == "疑似广告"
    assert admin.post(f"/api/admin/comments/{pend[0]['id']}/approve").json()["ok"]
    assert len(b.get(f"/api/items/{iid}/comments").json()) == 2
    assert login_client("cb@example.com").get("/api/admin/comments").status_code == 403


def test_fallback_when_ai_unavailable():
    iid = _item()
    a = login_client("cf@example.com")

    def boom(*_):
        raise judge.JudgeUnavailable("off")

    with mock.patch.object(judge, "moderate_comment", boom):
        assert a.post(f"/api/items/{iid}/comments", json={"content": "安装后跑通了，赞"}).json()["status"] == "visible"
        assert a.post(f"/api/items/{iid}/comments", json={"content": "要资料加微信号 abc123"}).json()["status"] == "pending"
        # 技术链接不算广告
        assert a.post(f"/api/items/{iid}/comments", json={"content": "参考 https://github.com/a/b 的 issue"}).json()["status"] == "visible"


def test_hot_searches_and_suggest():
    from app.models import Event, Repo
    from app.routers import search_assist
    search_assist._hot_cache = (0.0, [])
    with SessionLocal() as db:
        for vid, q in [("v1", "PPT 生成"), ("v2", "ppt 生成"), ("v3", "PPT 生成"), ("v1", "语音识别"), ("v2", "语音识别"),
                       ("v1", "只有一人"), ("v1", "加微信领资料"), ("v2", "加微信领资料"), ("v3", "x")]:
            db.add(Event(vid=vid, name="search", category="action", props={"q": q}))
        db.add(Event(vid="v4", name="search", category="action", props={"q": "github 搜的", "scope": "github"}))
        db.add(Event(vid="v5", name="search", category="action", props={"q": "github 搜的", "scope": "github"}))
        cid = db.scalar(select(Category.id).where(Category.parent_id.is_not(None)))
        r1 = Repo(github_id=1, full_name="o/pptx-maker", html_url="https://github.com/o/pptx-maker", stars=50)
        r2 = Repo(github_id=2, full_name="o/slides", html_url="https://github.com/o/slides", stars=900)
        db.add_all([r1, r2])
        db.flush()
        db.add_all([Item(name="pptx-maker", repo_id=r1.id, category_id=cid, status="published", summary="做 PPT", locked_fields=[], install_steps=[]),
                    Item(name="Slides PPT", repo_id=r2.id, category_id=cid, status="published", locked_fields=[], install_steps=[]),
                    Item(name="ppt-hidden", category_id=cid, status="offline", locked_fields=[], install_steps=[])])
        db.commit()
    c = login_client("hot@example.com")
    hot = c.get("/api/search/hot").json()
    assert [h["q"] for h in hot] == ["PPT 生成", "语音识别"]  # 至少 2 人；敏感词、GitHub 搜索、单人词不算
    names = [s["name"] for s in c.get("/api/search/suggest?q=ppt").json()]
    assert names == ["pptx-maker", "Slides PPT"]  # 开头匹配优先；已下线的不出现
    assert c.get("/api/search/suggest?q=").json() == []


def test_related_items():
    from app.models import Favorite, Repo, User
    with SessionLocal() as db:
        cats = db.scalars(select(Category.id).where(Category.parent_id.is_not(None)).limit(2)).all()
        mk = lambda name, cat, stars, status="published": Item(name=name, category_id=cat, status=status, locked_fields=[], install_steps=[],
                                                                repo=Repo(github_id=hash(name) % 10**8, full_name=f"o/{name}", html_url="x", stars=stars))
        a, b, c, d, e, off = mk("a", cats[0], 10), mk("b", cats[0], 500), mk("c", cats[0], 50), mk("d", cats[1], 1), mk("e", cats[1], 2), mk("off", cats[0], 999, "offline")
        db.add_all([a, b, c, d, e, off])
        db.commit()
        ids = {x.name: x.id for x in (a, b, c, d, e, off)}
    u1, u2 = login_client("r1@example.com"), login_client("r2@example.com")
    with SessionLocal() as db:
        uid = {x.email: x.id for x in db.scalars(select(User))}
        for who, items in (("r1@example.com", "ade"), ("r2@example.com", "ad")):
            for n in items:
                db.add(Favorite(owner_id=uid[who], item_id=ids[n]))
        db.commit()
    r = u1.get(f"/api/items/{ids['a']}/related").json()
    assert [(x["name"], x["co_count"]) for x in r["also"]] == [("d", 2), ("e", 1)]
    assert [x["name"] for x in r["similar"]] == ["b", "c"]  # 同子类按星标，已下线的不推荐


def test_ratings_latest_per_user():
    iid = _item()
    a, b = login_client("ra@example.com"), login_client("rb@example.com")
    with _ai("pass"):
        a.post(f"/api/items/{iid}/comments", json={"content": "一般", "rating": 2})
        a.post(f"/api/items/{iid}/comments", json={"content": "更新后好用了", "rating": 5})
        cb = b.post(f"/api/items/{iid}/comments", json={"content": "还行", "rating": 4}).json()
        b.post(f"/api/items/{iid}/comments", json={"content": "只写日志不打分"})
        assert a.post(f"/api/items/{iid}/comments", json={"content": "x", "rating": 6}).status_code == 422
    d = a.get(f"/api/items/{iid}").json()
    assert (d["rating_avg"], d["rating_count"]) == (4.5, 2)  # a 取最近的 5，b 取 4
    with _ai("review"):
        login_client("rc@example.com").post(f"/api/items/{iid}/comments", json={"content": "待审", "rating": 1})
    assert a.get(f"/api/items/{iid}").json()["rating_count"] == 2  # 待审核的不计入
    b.delete(f"/api/comments/{cb['id']}")
    d = a.get(f"/api/items/{iid}").json()
    assert (d["rating_avg"], d["rating_count"]) == (5.0, 1)


def test_for_you_sort():
    from app.models import Favorite, Repo, User
    with SessionLocal() as db:
        groups = db.scalars(select(Category).where(Category.parent_id.is_(None))).all()
        g1, g2 = [g for g in groups if len(g.children) >= 2][:2]
        c11, c12, c21 = g1.children[0].id, g1.children[1].id, g2.children[0].id
        mk = lambda n, cat, stars: Item(name=n, category_id=cat, status="published", locked_fields=[], install_steps=[],
                                        repo=Repo(github_id=abs(hash(n)) % 10**8, full_name=f"o/{n}", html_url="x", stars=stars))
        rows = [mk("liked", c11, 1), mk("same-sub", c11, 5), mk("same-group", c12, 3), mk("other-big", c21, 9999)]
        db.add_all(rows)
        db.commit()
        ids = {r.name: r.id for r in rows}
    c = login_client("fy@example.com")
    assert all("match" not in i for i in c.get("/api/items?sort=foryou").json()["items"])  # 没有偏好：退回「今日」，不带推荐理由
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "fy@example.com"))
        db.add(Favorite(owner_id=uid, item_id=ids["liked"]))
        db.commit()
    items = c.get("/api/items?sort=foryou").json()["items"]
    assert [i["name"] for i in items] == ["same-sub", "same-group", "other-big", "liked"]  # 已收藏的放最后
    assert "你常看" in items[0]["match"]["reason"] and "match" not in items[2]
    assert login_client("anon2@example.com").get("/api/items?sort=foryou").status_code == 200


def test_share_export_and_in_use():
    from fastapi.testclient import TestClient

    from app.main import app
    iid = _item()
    c = login_client("sh@example.com")
    assert c.post(f"/api/items/{iid}/favorite").status_code == 200
    s = c.get("/api/favorites/structure").json()
    dim = next(d for d in s["dimensions"] if not d.get("system"))
    f = c.post("/api/favorites/folders", json={"dimension_id": dim["id"], "name": "做 PPT"}).json()
    c.put(f"/api/favorites/{iid}/folders", json={"dimension_id": dim["id"], "folder_ids": [f["id"]]})
    c.put(f"/api/favorites/{iid}/note", json={"note": "开会前用"})
    tok = c.post(f"/api/favorites/folders/{f['id']}/share").json()["token"]
    pub = TestClient(app).get(f"/api/shared/{tok}").json()
    assert pub["folder"]["name"] == "做 PPT" and [i["name"] for i in pub["items"]] == ["demo"] and pub["owner"]["nickname"] == "sh"
    assert login_client("other@example.com").post(f"/api/favorites/folders/{f['id']}/share").status_code == 404  # 别人的分类不能分享
    c.delete(f"/api/favorites/folders/{f['id']}/share")
    assert TestClient(app).get(f"/api/shared/{tok}").status_code == 404
    md = c.get("/api/favorites/export?format=md")
    assert md.status_code == 200 and "**[demo]" in md.text and "备注：开会前用" in md.text and "做 PPT" in md.text
    js = c.get("/api/favorites/export?format=json").json()
    assert js["count"] == 1 and js["items"][0]["folders"] == ["做 PPT"]
    assert "in_use" not in c.get("/api/items?fav=1").json()["items"][0]
    with _ai("pass"):
        c.post(f"/api/items/{iid}/comments", json={"content": "今天又用了"})
    assert c.get("/api/items?fav=1").json()["items"][0]["in_use"] is True


def test_subscriptions_digest_and_releases():
    from datetime import timedelta

    from app.db import utcnow
    from app.models import CategorySubscription, Favorite, Notification, Repo, User
    from app.services import notify

    c = login_client("sub@example.com")
    with SessionLocal() as db:
        sub = db.scalar(select(Category).where(Category.parent_id.is_not(None)))
        code, cid = sub.code, sub.id
    assert c.post(f"/api/subscriptions/{code}").json()["subscribed"]
    assert [s["code"] for s in c.get("/api/subscriptions").json()] == [code]
    with SessionLocal() as db:
        s = db.scalar(select(CategorySubscription))
        s.last_notified_at = utcnow() - timedelta(hours=1)
        repo = Repo(github_id=77, full_name="o/rel", html_url="x", stars=1)
        db.add_all([Item(name=f"n{k}", category_id=cid, status="published", locked_fields=[], install_steps=[]) for k in range(4)])
        it = Item(name="rel-item", category_id=cid, status="published", locked_fields=[], install_steps=[], repo=repo)
        db.add(it)
        db.commit()
        uid = db.scalar(select(User.id).where(User.email == "sub@example.com"))
        db.add(Favorite(owner_id=uid, item_id=it.id))
        db.commit()
        assert notify.digest_new_items(db) == 1
        assert notify.digest_new_items(db) == 0  # 已通知过的不重复

        class FakeGH:
            tag = "v1.0"

            def latest_release(self, name):
                return {"tag_name": self.tag, "name": "大更新"}

        gh = FakeGH()
        assert notify.check_releases(db, gh) == 0  # 第一次只记下
        gh.tag = "v1.1"
        assert notify.check_releases(db, gh) == 1
        assert notify.check_releases(db, gh) == 0
    r = c.get("/api/notifications").json()
    assert r["unread"] == 2
    titles = [n["title"] for n in r["items"]]
    assert any("上新了 5 个" in t for t in titles) and any("新版本 v1.1" in t for t in titles)
    # v3.3.20 单条已读：只去掉这一条；别人的消息标不了
    first = r["items"][0]["id"]
    one = c.post(f"/api/notifications/{first}/read").json()
    assert one["unread"] == 1
    again = c.get("/api/notifications").json()
    assert again["unread"] == 1 and [n["read"] for n in again["items"] if n["id"] == first] == [True]
    assert c.post(f"/api/notifications/{first}/read").json()["unread"] == 1  # 重复点不出错
    assert login_client("sub2@example.com").post(f"/api/notifications/{first}/read").status_code == 404
    assert c.post("/api/notifications/read").json()["unread"] == 0  # 全部已读
    assert c.get("/api/notifications").json()["unread"] == 0
    assert not c.delete(f"/api/subscriptions/{code}").json()["subscribed"]
    assert login_client("sub2@example.com").get("/api/notifications").json()["items"] == []


def test_monthly_and_trends():
    from datetime import date, timedelta

    from app.models import Ranking, Repo, StarSnapshot
    from app.services.rankings import backfill_weekly, compute_rankings, group_trends

    d = date(2026, 11, 20)
    with SessionLocal() as db:
        cid = db.scalar(select(Category.id).where(Category.parent_id.is_not(None)))
        repo = Repo(github_id=5, full_name="o/t", html_url="x", stars=0)
        db.add(Item(name="t", category_id=cid, status="published", locked_fields=[], install_steps=[], repo=repo))
        db.flush()
        for k in range(20):
            db.add(StarSnapshot(repo_id=repo.id, snap_date=d - timedelta(days=k), stars=1000 - (10 * k if k <= 7 else 70 + 5 * (k - 7))))
        db.commit()
        compute_rankings(db, d, "daily")
        assert backfill_weekly(db) == 2  # 周榜 + 月榜
        assert db.scalar(select(Ranking.id).where(Ranking.period == "monthly")) is not None
        t = group_trends(db)
        assert t and t[0]["stars"] == 70 and t[0]["prev"] == 35 and t[0]["change"] == 100
    assert login_client("tr@example.com").get("/api/rankings?period=monthly").json()["period"] == "monthly"
