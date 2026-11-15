"""v3.3.37 后台批次 0：渠道与客户端版本、操作日志留痕、用户状态字段、停用 / 启用必须填原因、新错误格式。"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from app.db import Base, SessionLocal, engine
from app.main import app, ensure_admin
from app.models import ActivityLog, AuthSession, User
from app.seed import seed_categories
from app.services import wechat
from app.services.client import client_of
from conftest import login_client, solve_pow

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        s.commit()


def _req(headers: dict) -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                    "client": ("127.0.0.1", 0)})


def test_client_of():
    assert client_of(_req({"referer": "https://servicewechat.com/wx0000000000000000/12/page-frame.html"})) == ("miniprogram", "12")
    assert client_of(_req({"referer": "https://servicewechat.com/wx0000000000000000/0/page-frame.html"}))[1] == "开发版 / 体验版"
    assert client_of(_req({"x-client": "miniprogram", "x-client-version": "1.2.0 release"})) == ("miniprogram", "1.2.0 release")
    assert client_of(_req({"user-agent": MOBILE_UA, "x-client": "web", "x-client-version": "web-20261112.1900"})) == ("web-mobile", "web-20261112.1900")
    assert client_of(_req({"user-agent": PC_UA}))[0] == "web-pc"


def test_signup_channel_and_session_method(monkeypatch):
    c = TestClient(app, headers={"user-agent": MOBILE_UA, "x-client": "web", "x-client-version": "web-test"})
    ch = c.get("/api/auth/challenge").json()
    code = c.post("/api/auth/code", json={"email": "ch@example.com", "purpose": "login", "pow_token": ch["token"],
                                          "pow_nonce": solve_pow(ch)}).json()["dev_code"]
    r = c.post("/api/auth/login/code", json={"email": "ch@example.com", "code": code}).json()
    with SessionLocal() as s:
        u = s.get(User, r["user"]["id"])
        assert u.signup_channel == "web-mobile" and u.last_client == "web-mobile" and u.last_client_version == "web-test"
        sess = s.scalars(select(AuthSession).where(AuthSession.user_id == u.id)).first()
        assert (sess.client, sess.method) == ("web-mobile", "email_code")

    monkeypatch.setattr(wechat, "ready", lambda: True)
    monkeypatch.setattr(wechat, "code2session", lambda code: {"openid": "oid-ch", "unionid": None})
    mp = TestClient(app, headers={"referer": "https://servicewechat.com/wx0000000000000000/7/page-frame.html"})
    r = mp.post("/api/auth/wx/login", json={"code": "x"}).json()
    with SessionLocal() as s:
        u = s.get(User, r["user"]["id"])
        assert u.signup_channel == "miniprogram" and u.last_client_version == "7"


def test_status_needs_reason_and_logs_diff():
    admin = login_client("boss0@example.com", role="admin")
    target = login_client("victim0@example.com", wechat=False)
    uid = target.get("/api/auth/me").json()["user"]["id"]
    r = admin.post(f"/api/admin/users/{uid}/status", json={"status": "disabled", "reason": "短"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "reason_required"
    r = admin.post(f"/api/admin/users/{uid}/status", json={"status": "disabled", "reason": "发布违规内容"})
    assert r.status_code == 200
    row = r.json()
    assert row["status"] == "disabled" and row["account_label"] == "victim0@example.com" and row["display_label"].startswith("victim0") and row["login_methods"] == ["email"]
    logs = admin.get(f"/api/admin/activity?target_user_id={uid}&result=ok").json()
    first = logs["items"][0]
    assert first["reason"] == "发布违规内容" and first["before"] == {"status": "active"} and first["after"] == {"status": "disabled"}
    assert first["fields"] == {"status": "状态"} and first["result"] == "ok" and first["target_label"]
    assert admin.get("/api/admin/activity?result=failed").json()["total"] == 0


def test_merged_account_cannot_toggle():
    admin = login_client("boss1@example.com", role="admin")
    with SessionLocal() as s:
        keep = User(email="keep@example.com", nickname="keep", role="user", status="active")
        s.add(keep)
        s.flush()
        gone = User(nickname="gone", role="user", status="merged", merged_into=keep.id, wx_openid="oid-gone")
        s.add(gone)
        s.commit()
        gid, kid = gone.id, keep.id
    r = admin.post(f"/api/admin/users/{gid}/status", json={"status": "active", "reason": "误操作恢复"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "merged_account"
    rows = admin.get("/api/admin/users?status=merged").json()["items"]
    m = next(x for x in rows if x["id"] == gid)
    assert m["merged_into"]["id"] == kid and m["status_label"] == "已合并" and m["login_methods"] == ["wechat"]
    assert m["account_label"] == f"微信用户 #{gid}" and m["display_label"] == f"gone（微信用户 #{gid}）"
    assert m["signup_channel_label"] == "未知"
    with SessionLocal() as s:
        assert s.scalar(select(ActivityLog).where(ActivityLog.target_id == gid)) is None


def test_bulk_status_and_export():
    """v3.3.39 批量停用 / 启用（按 ids、按筛选 + total 校验、逐项结果、幂等）与 CSV 导出。"""
    admin = login_client("boss2@example.com", role="admin")
    sub = login_client("sub2@example.com", role="subadmin")
    ids = []
    for n in range(3):
        c = login_client(f"bulk{n}@example.com")
        ids.append(c.get("/api/auth/me").json()["user"]["id"])
    with SessionLocal() as s:
        gone = User(nickname="合并掉的", role="user", status="merged", wx_openid="oid-bulk-gone")
        s.add(gone)
        s.commit()
        gid = gone.id
    staff_id = sub.get("/api/auth/me").json()["user"]["id"]

    r = admin.post("/api/admin/users/bulk", json={"action": "disable", "reason": "短", "ids": ids})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "reason_required"

    r = admin.post("/api/admin/users/bulk", json={"action": "disable", "reason": "批量清理测试", "ids": ids + [gid, staff_id]}).json()
    assert r["ok_count"] == 3 and r["fail_count"] == 2
    codes = {x["id"]: x.get("code") for x in r["results"]}
    assert codes[gid] == "merged_account" and codes[staff_id] == "staff_account"
    # 重试：已经是目标状态 → noop 也算成功
    r = admin.post("/api/admin/users/bulk", json={"action": "disable", "reason": "批量清理测试", "ids": ids[:1]}).json()
    assert r["ok_count"] == 1 and r["results"][0]["code"] == "noop"
    logs = admin.get(f"/api/admin/activity?target_user_id={ids[0]}").json()["items"]
    assert logs[0]["reason"] == "批量清理测试" and "原因" not in logs[0]["summary"]

    # 按筛选：数量对不上 → 409；对上 → 执行，exclude 生效
    flt = {"q": "bulk", "status": "disabled"}
    total = admin.get("/api/admin/users?q=bulk&status=disabled").json()["total"]
    r = admin.post("/api/admin/users/bulk", json={"action": "enable", "reason": "批量恢复测试", "filter": flt, "total": total + 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "count_changed"
    r = admin.post("/api/admin/users/bulk", json={"action": "enable", "reason": "批量恢复测试", "filter": flt, "total": total,
                                                  "exclude": [ids[2]]}).json()
    assert r["ok_count"] == total - 1 and ids[2] not in {x["id"] for x in r["results"]}

    # 导出：子管理员不能带完整邮箱；超管可以；默认邮箱打码
    assert sub.get("/api/admin/users/export?q=bulk&with_email=1").status_code == 403
    e = admin.get("/api/admin/users/export?q=bulk")
    assert e.status_code == 200 and e.headers["content-type"].startswith("text/csv") and "attachment" in e.headers["content-disposition"]
    text = e.content.decode("utf-8")
    assert text.startswith("﻿") and "bu***@example.com" in text and "bulk0@example.com" not in text
    full = admin.get("/api/admin/users/export?q=bulk&with_email=1").content.decode("utf-8")
    assert "bulk0@example.com" in full and e.headers["x-export-count"] == "3"
