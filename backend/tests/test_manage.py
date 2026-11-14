"""v2.4 管理端：用户管理（详情 / 停用 / 删除）、IP 封禁、内容管理（列表 / 全部字段 / 图片集）、子管理员候选列表。"""

import io

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import Category, Item, User
from app.seed import seed_categories
from app.services import ipban
from conftest import login_client

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
    ipban.refresh()


def admin():
    c = login_client("boss@example.com")
    with SessionLocal() as s:
        s.scalar(select(User).where(User.email == "boss@example.com")).role = "admin"
        s.commit()
    return c


def uid(email):
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.email == email))


def test_staff_candidates_browse():
    for i in range(3):
        login_client(f"member{i}@example.com")
    a = admin()
    r = a.get("/api/admin/staff/candidates").json()  # 不输入也能看到注册用户列表
    assert r["total"] >= 3 and any(u["email"] == "member2@example.com" for u in r["items"])
    assert a.get("/api/admin/staff/candidates", params={"q": "member1"}).json()["total"] == 1


def test_users_disable_and_delete():
    victim = login_client("victim@example.com")
    victim.post("/api/items/1/favorite", json={"on": True})
    a = admin()
    lst = a.get("/api/admin/users", params={"q": "victim"}).json()
    assert lst["total"] == 1 and lst["items"][0]["status"] == "active" and lst["counts"]["users"] >= 1
    vid = uid("victim@example.com")
    d = a.get(f"/api/admin/users/{vid}").json()
    assert d["email"] == "victim@example.com" and "sessions" in d and "stats" in d

    # 停用：所有会话立即失效，不能再用接口
    assert victim.get("/api/auth/me").status_code == 200
    r = a.post(f"/api/admin/users/{vid}/status", json={"status": "disabled", "reason": "刷屏广告"})
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    assert victim.get("/api/me/compares").status_code == 401
    assert a.post(f"/api/admin/users/{vid}/status", json={"status": "active", "reason": "核实后恢复"}).json()["status"] == "active"

    # 不能对自己、对管理员操作
    assert a.post(f"/api/admin/users/{uid('boss@example.com')}/status", json={"status": "disabled", "reason": "测试管理员"}).status_code == 400
    with SessionLocal() as s:
        admin_id = s.scalar(select(User.id).where(User.username == "admin"))
    assert a.delete(f"/api/admin/users/{admin_id}").status_code == 400

    # 删除：邮箱释放，显示为已注销用户
    assert a.delete(f"/api/admin/users/{vid}").status_code == 200
    with SessionLocal() as s:
        u = s.get(User, vid)
        assert u.status == "deleted" and u.email is None and u.nickname == "已注销用户"
    assert a.get("/api/admin/users", params={"q": "victim"}).json()["total"] == 0
    assert login_client("plain@example.com").get("/api/admin/users").status_code == 403


def test_ip_bans_block_requests():
    a = admin()
    a.headers["X-Forwarded-For"] = "10.9.9.9"
    assert a.post("/api/admin/ip-bans", json={"ip": "10.9.9.9"}).status_code == 400  # 不能封自己
    assert a.post("/api/admin/ip-bans", json={"ip": "not-an-ip"}).status_code == 400
    assert a.post("/api/admin/ip-bans", json={"ip": "1.0.0.0/4"}).status_code == 400  # 网段太大
    r = a.post("/api/admin/ip-bans", json={"ip": "203.0.113.0/24", "reason": "爬虫", "days": 7})
    assert r.status_code == 200 and r.json()["cidr"] == "203.0.113.0/24"
    assert a.post("/api/admin/ip-bans", json={"ip": "203.0.113.0/24"}).status_code == 400

    guest = TestClient(app)
    blocked = guest.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.77"})
    assert blocked.status_code == 403 and "禁止" in blocked.json()["detail"]
    assert guest.get("/api/meta", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200

    bans = a.get("/api/admin/ip-bans").json()
    assert a.delete(f"/api/admin/ip-bans/{bans[0]['id']}").status_code == 200
    assert guest.get("/api/meta", headers={"X-Forwarded-For": "203.0.113.77"}).status_code == 200


def test_content_list_detail_and_images():
    with SessionLocal() as s:
        cat = s.scalar(select(Category).where(Category.code == "coding-gen"))
        it = Item(name="gallery-skill", category_id=cat.id, status="published", summary="图片集测试", kind="agent_skill",
                  locked_fields=[], install_steps=[], source="manual", cover_path="covers/old.png", images=["covers/old.png"])
        s.add(it)
        s.commit()
        iid = it.id
    a = admin()
    lst = a.get("/api/admin/items", params={"q": "gallery"}).json()
    assert lst["total"] == 1 and lst["items"][0]["image_count"] == 1 and lst["statuses"]["published"] == "已上线"
    full = a.get(f"/api/admin/items/{iid}").json()
    assert full["images"][0]["path"] == "covers/old.png" and "description" in full and "locked_fields" in full

    up = a.post(f"/api/admin/items/{iid}/images", files={"file": ("x.png", io.BytesIO(PNG), "image/png")})
    assert up.status_code == 200, up.text
    paths = [i["path"] for i in up.json()["images"]]
    assert len(paths) == 2 and "cover_path" in up.json()["locked_fields"]
    assert a.post(f"/api/admin/items/{iid}/images", files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")}).status_code == 400

    # 换顺序 = 换封面；只保留一张 = 删除其他
    r = a.put(f"/api/admin/items/{iid}/images", json={"paths": [paths[1], paths[0]]}).json()
    assert r["cover_url"] == f"/media/{paths[1]}"
    r = a.put(f"/api/admin/items/{iid}/images", json={"paths": [paths[1]]}).json()
    assert [i["path"] for i in r["images"]] == [paths[1]]
    assert a.put(f"/api/admin/items/{iid}/images", json={"paths": ["covers/evil.png"]}).status_code == 400

    # 详情页拿到图片集
    assert TestClient(app).get(f"/api/items/{iid}").json()["images"] == [f"/media/{paths[1]}"]
