"""v3.1 小程序账号：微信登录、绑定邮箱、账号合并、解绑。code2session 全部 mock。"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import (Category, Comment, CompareRun, EmailCode, FavDimension, FavFolder, Favorite, FavoriteFolderLink, Item,
                        QuotaDaily, User)
from app.seed import seed_categories
from app.services import merge, wechat
from conftest import solve_pow

ITEMS: list[int] = []


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        cat = s.scalar(select(Category).where(Category.code == "other-misc"))
        for n in range(4):
            it = Item(name=f"it{n}", category_id=cat.id, locked_fields=[], install_steps=[])
            s.add(it)
            s.flush()
            ITEMS.append(it.id)
        s.commit()


@pytest.fixture(autouse=True)
def fake_wx(monkeypatch):
    monkeypatch.setattr(wechat, "ready", lambda: True)
    monkeypatch.setattr(wechat, "code2session", lambda code: {"openid": f"oid-{code}", "unionid": None})


def wx_client(code: str) -> tuple[TestClient, dict]:
    c = TestClient(app)
    r = c.post("/api/auth/wx/login", json={"code": code})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c, r.json()


def allow_resend(email: str) -> None:
    from datetime import timedelta
    with SessionLocal() as s:
        for rec in s.scalars(select(EmailCode).where(EmailCode.email == email)):
            rec.created_at = rec.created_at - timedelta(minutes=5)
        s.commit()


def email_code(c: TestClient, email: str) -> str:
    allow_resend(email)
    ch = c.get("/api/auth/challenge").json()
    r = c.post("/api/auth/code", json={"email": email, "purpose": "login", "pow_token": ch["token"], "pow_nonce": solve_pow(ch)})
    assert r.status_code == 200, r.text
    return r.json()["dev_code"]


def web_user(email: str) -> int:
    c = TestClient(app)
    r = c.post("/api/auth/login/code", json={"email": email, "code": email_code(c, email)})
    assert r.status_code == 200, r.text
    return r.json()["user"]["id"]


def test_wx_login_creates_then_reuses():
    c, out = wx_client("a1")
    assert out["is_new"] is True and out["user"]["wechat_bound"] is True and out["user"]["has_email"] is False
    assert "session_key" not in out
    me = c.get("/api/auth/me").json()["user"]
    assert me["wechat_bound"] and not me["has_email"] and me["has_password"] is False
    _, again = wx_client("a1")
    assert again["is_new"] is False and again["user"]["id"] == out["user"]["id"]


def test_wx_login_not_configured(monkeypatch):
    monkeypatch.setattr(wechat, "ready", lambda: False)
    monkeypatch.setattr(wechat, "code2session", lambda code: (_ for _ in ()).throw(wechat.WechatError("未配置")))
    assert TestClient(app).post("/api/auth/wx/login", json={"code": "x"}).status_code == 503


def test_bind_unregistered_email():
    c, out = wx_client("b1")
    code = email_code(c, "fresh@example.com")
    r = c.post("/api/auth/me/email", json={"email": "fresh@example.com", "code": code})
    assert r.status_code == 200 and r.json()["status"] == "bound"
    assert r.json()["user"]["has_email"] and r.json()["user"]["wechat_bound"]
    # 网页用这个邮箱登录到的是同一个账号
    assert web_user("fresh@example.com") == out["user"]["id"]
    # 已有邮箱不能再绑
    assert c.post("/api/auth/me/email", json={"email": "x@example.com", "code": "123456"}).status_code == 400


def test_bind_wrong_code_rejected():
    c, _ = wx_client("b2")
    email_code(c, "wrong@example.com")
    assert c.post("/api/auth/me/email", json={"email": "wrong@example.com", "code": "000000"}).status_code == 400


def _seed_merge_data(primary_id: int, secondary_id: int) -> None:
    a, b, c_, d = ITEMS
    with SessionLocal() as s:
        # 同名维度「工作」，其中同名文件夹「AI」，另有各自独有的文件夹
        pd = FavDimension(owner_id=primary_id, name="工作", sort=0)
        sd = FavDimension(owner_id=secondary_id, name="工作", sort=0)
        sd2 = FavDimension(owner_id=secondary_id, name="个人", sort=1)
        s.add_all([pd, sd, sd2])
        s.flush()
        p_ai, p_x = FavFolder(dimension_id=pd.id, name="AI", sort=0), FavFolder(dimension_id=pd.id, name="只主", sort=1)
        s_ai, s_y = FavFolder(dimension_id=sd.id, name="AI", sort=0), FavFolder(dimension_id=sd.id, name="只副", sort=1)
        s_z = FavFolder(dimension_id=sd2.id, name="随便", sort=0)
        s.add_all([p_ai, p_x, s_ai, s_y, s_z])
        s.flush()
        # 条目 a 两边都收藏（备注不同）；b 只在主；c 只在副
        pa = Favorite(owner_id=primary_id, item_id=a, note="主备注")
        sa_ = Favorite(owner_id=secondary_id, item_id=a, note="副备注")
        pb = Favorite(owner_id=primary_id, item_id=b)
        sc = Favorite(owner_id=secondary_id, item_id=c_)
        s.add_all([pa, sa_, pb, sc])
        s.flush()
        s.add_all([FavoriteFolderLink(favorite_id=pa.id, folder_id=p_ai.id),
                   FavoriteFolderLink(favorite_id=sa_.id, folder_id=s_ai.id),  # 合并后与上面重复，去重
                   FavoriteFolderLink(favorite_id=sa_.id, folder_id=s_y.id),
                   FavoriteFolderLink(favorite_id=sc.id, folder_id=s_z.id)])
        s.add(Comment(item_id=d, user_id=secondary_id, content="副评论"))
        s.add(CompareRun(key="k", user_id=secondary_id))
        s.add_all([QuotaDaily(user_id=primary_id, day=date(2026, 11, 1), calls=1, tokens=10, used=20, balance_end=5),
                   QuotaDaily(user_id=secondary_id, day=date(2026, 11, 1), calls=2, tokens=30, used=60, balance_end=9),
                   QuotaDaily(user_id=secondary_id, day=date(2026, 11, 2), calls=1, tokens=1, used=2, balance_end=1)])
        s.commit()


def _start_merge(code: str, email: str):
    pid = web_user(email)
    c, out = wx_client(code)
    sid = out["user"]["id"]
    _seed_merge_data(pid, sid)
    r = c.post("/api/auth/me/email", json={"email": email, "code": email_code(c, email)})
    assert r.status_code == 200 and r.json()["status"] == "merge", r.text
    return c, pid, sid, r.json()


def test_merge_full():
    c, pid, sid, out = _start_merge("m1", "main@example.com")
    pv = out["preview"]
    assert pv["primary"]["id"] == pid and pv["primary"]["favorites"] == 2 and pv["primary"]["folders"] == 2
    assert pv["secondary"]["favorites"] == 2 and pv["secondary"]["folders"] == 3 and pv["secondary"]["comments"] == 1 and pv["secondary"]["compares"] == 1
    old_token = c.headers["Authorization"]
    r = c.post("/api/auth/me/merge", json={"ticket": out["ticket"]})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == pid and r.json()["user"]["wechat_bound"] and r.json()["user"]["email"] == "main@example.com"
    a, b, c_, d = ITEMS
    with SessionLocal() as s:
        sec = s.get(User, sid)
        assert sec.status == "merged" and sec.merged_into == pid and sec.wx_openid is None
        assert s.get(User, pid).wx_openid == "oid-m1"
        favs = {f.item_id: f for f in s.scalars(select(Favorite).where(Favorite.owner_id == pid))}
        assert set(favs) == {a, b, c_}
        assert favs[a].note == "主备注\n副备注"
        assert s.scalar(select(Favorite).where(Favorite.owner_id == sid)) is None
        dims = {d_.name: d_ for d_ in s.scalars(select(FavDimension).where(FavDimension.owner_id == pid))}
        assert set(dims) == {"工作", "个人"} and dims["个人"].sort > dims["工作"].sort
        work = {f.name: f for f in s.scalars(select(FavFolder).where(FavFolder.dimension_id == dims["工作"].id))}
        assert set(work) == {"AI", "只主", "只副"}
        links_a = set(s.scalars(select(FavoriteFolderLink.folder_id).where(FavoriteFolderLink.favorite_id == favs[a].id)))
        assert links_a == {work["AI"].id, work["只副"].id}
        assert s.scalar(select(FavDimension).where(FavDimension.owner_id == sid)) is None
        assert s.scalar(select(Comment.user_id).where(Comment.item_id == d)) == pid
        q = {x.day: x for x in s.scalars(select(QuotaDaily).where(QuotaDaily.user_id == pid))}
        assert q[date(2026, 11, 1)].calls == 3 and q[date(2026, 11, 1)].used == 80 and date(2026, 11, 2) in q
    # 副账号旧令牌作废；凭证不能再用；微信再次登录进入主账号
    assert TestClient(app).get("/api/auth/me", headers={"Authorization": old_token}).json()["user"] is None
    assert c.post("/api/auth/me/merge", json={"ticket": out["ticket"]}).status_code == 401  # 副账号会话已作废
    _, again = wx_client("m1")
    assert again["user"]["id"] == pid and again["is_new"] is False


def test_merge_rollback(monkeypatch):
    c, pid, sid, out = _start_merge("r1", "rollback@example.com")

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(merge, "_merge_quota", boom)
    r = c.post("/api/auth/me/merge", json={"ticket": out["ticket"]})
    assert r.status_code == 500
    with SessionLocal() as s:
        assert s.get(User, sid).status == "active" and s.get(User, sid).wx_openid == "oid-r1"
        assert s.get(User, pid).wx_openid is None
        assert s.scalar(select(FavDimension).where(FavDimension.owner_id == sid)) is not None
        assert len(s.scalars(select(Favorite).where(Favorite.owner_id == sid)).all()) == 2
    # 修好后同一凭证还能完成合并
    monkeypatch.undo()
    monkeypatch.setattr(wechat, "ready", lambda: True)
    assert c.post("/api/auth/me/merge", json={"ticket": out["ticket"]}).status_code == 200


def test_merge_ticket_belongs_to_caller():
    c, pid, sid, out = _start_merge("t1", "ticket@example.com")
    other, _ = wx_client("t2")
    assert other.post("/api/auth/me/merge", json={"ticket": out["ticket"]}).status_code == 403
    assert other.post("/api/auth/me/merge", json={"ticket": "garbage"}).status_code == 400


def test_email_bound_to_other_wechat():
    c1, _ = wx_client("o1")
    c1.post("/api/auth/me/email", json={"email": "taken@example.com", "code": email_code(c1, "taken@example.com")})
    c2, _ = wx_client("o2")
    r = c2.post("/api/auth/me/email", json={"email": "taken@example.com", "code": email_code(c2, "taken@example.com")})
    assert r.status_code == 409 and "其他微信" in r.json()["detail"]


def test_unbind_rules():
    c, out = wx_client("u1")
    assert c.post("/api/auth/me/wechat/unbind").status_code == 400  # 只有微信，不能解绑
    c.post("/api/auth/me/email", json={"email": "unbind@example.com", "code": email_code(c, "unbind@example.com")})
    r = c.post("/api/auth/me/wechat/unbind")
    assert r.status_code == 200 and r.json()["user"]["wechat_bound"] is False
    assert c.post("/api/auth/me/wechat/unbind").status_code == 400
    _, again = wx_client("u1")  # 解绑后同一微信登录是一个新账号
    assert again["is_new"] is True and again["user"]["id"] != out["user"]["id"]


def test_merged_account_cannot_login():
    with SessionLocal() as s:
        u = User(email="gone@example.com", nickname="gone", status="merged", password_hash=auth.hash_password("abc12345"))
        s.add(u)
        s.commit()
    r = TestClient(app).post("/api/auth/login/password", json={"account": "gone@example.com", "password": "abc12345"})
    assert r.status_code == 403


def test_admin_binds_with_username_password():
    with SessionLocal() as s:
        admin = s.scalar(select(User).where(User.username == "admin"))
        admin.password_hash = auth.hash_password("Admin12345")
        s.commit()
        admin_id = admin.id
    c, _ = wx_client("adm")
    assert c.post("/api/auth/me/email", json={"email": "admin", "password": "wrong999"}).status_code == 400
    r = c.post("/api/auth/me/email", json={"email": "admin", "password": "Admin12345"})
    assert r.status_code == 200 and r.json()["status"] == "merge", r.text
    r = c.post("/api/auth/me/merge", json={"ticket": r.json()["ticket"]})
    assert r.status_code == 200 and r.json()["user"]["id"] == admin_id and r.json()["user"]["role"] == "admin"


def test_every_user_fk_is_handled_by_merge():
    handled = {(m.__tablename__, col) for m, col in merge.REASSIGN} | merge.SPECIAL
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == "users":
                assert (table.name, fk.parent.name) in handled, f"{table.name}.{fk.parent.name} 指向 users，合并时未处理"


def test_logged_in_code_skips_pow():
    """v3.3.11 已登录用户发验证码不用人机校验；未登录必须带；已登录按用户限频。"""
    from app.routers import account
    anon = TestClient(app)
    r = anon.post("/api/auth/code", json={"email": "nopow@example.com", "purpose": "login"})
    assert r.status_code == 400 and "安全校验" in r.json()["detail"]

    c, _ = wx_client("nopow")
    r = c.post("/api/auth/code", json={"email": "nopow@example.com", "purpose": "login"})
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"ok", "cooldown", "ttl_minutes"}

    uid = c.get("/api/auth/me").json()["user"]["id"]
    import time
    account._user_code_hits[uid] = [time.time()] * account.USER_CODE_PER_HOUR
    allow_resend("nopow@example.com")
    r = c.post("/api/auth/code", json={"email": "nopow@example.com", "purpose": "login"})
    assert r.status_code == 429
    account._user_code_hits.pop(uid, None)


def test_wechat_only_account_without_email():
    """v3.3.17 微信优先：没有邮箱的账号能正常使用、后台日志不出现 None、可以输入「注销」注销。"""
    from app.models import ActivityLog
    from app.services import users
    c, data = wx_client("only-wx")
    me = c.get("/api/auth/me").json()["user"]
    assert me["email"] is None and me["wechat_bound"] and not me["has_email"]
    assert c.get("/api/me/stats").status_code == 200
    with SessionLocal() as s:
        u = s.get(User, me["id"])
        assert "None" not in users.label(u) and "微信用户" in users.label(u)
    from conftest import login_client
    admin = login_client("boss-v3317@example.com", role="admin")
    if True:
        assert admin.post(f"/api/admin/users/{me['id']}/status", json={"status": "active", "reason": "测试启用账号"}).status_code == 200
        with SessionLocal() as s:
            log = s.scalars(select(ActivityLog).where(ActivityLog.action == "user_status").order_by(ActivityLog.id.desc())).first()
            assert log is None or "None" not in log.summary
    assert c.post("/api/auth/delete", json={"confirm": "删除"}).status_code == 400
    assert c.post("/api/auth/delete", json={"confirm": "注销"}).status_code == 200
    with SessionLocal() as s:
        u = s.get(User, me["id"])
        assert u.status == "deleted" and u.wx_openid is None
