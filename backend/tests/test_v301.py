"""v3.0.1：首页置顶权重、内容管理按日期筛选 / 日历计数、反馈回复（文字 + 图片 + 状态）。"""

import io
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Category, Feedback, Item, User
from app.seed import seed_categories
from conftest import login_client


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def _items(*specs):
    with SessionLocal() as db:
        cat = db.scalar(select(Category).where(Category.parent_id.is_not(None)))
        ids = []
        for name, collected in specs:
            it = Item(name=name, category_id=cat.id, status="published", locked_fields=[], install_steps=[], collected_at=collected)
            db.add(it)
            db.flush()
            ids.append(it.id)
        db.commit()
        return ids


def test_pin_puts_item_first_on_home_and_only_admin_can_pin():
    ids = _items(*[(f"x{k}", datetime(2026, 1, 1, tzinfo=timezone.utc)) for k in range(6)])
    target = ids[4]
    assert login_client("plain301@example.com").put(f"/api/admin/items/{target}/pin", json={"weight": 50}).status_code in (401, 403)
    boss = login_client("boss301@example.com", role="admin")
    r = boss.put(f"/api/admin/items/{target}/pin", json={"weight": 50})
    assert r.status_code == 200 and r.json()["pin_weight"] == 50
    boss.put(f"/api/admin/items/{ids[1]}/pin", json={"weight": 10})
    home = TestClient(app).get("/api/items?sort=today&size=10").json()["items"]
    assert [x["id"] for x in home[:2]] == [target, ids[1]] and home[0]["pinned"] is True and home[2]["pinned"] is False
    pinned = boss.get("/api/admin/items?pinned=1&sort=pinned").json()
    assert [x["id"] for x in pinned["items"]] == [target, ids[1]] and pinned["pinned_count"] == 2
    boss.put(f"/api/admin/items/{target}/pin", json={"weight": 0})
    assert TestClient(app).get("/api/items?sort=today&size=10").json()["items"][0]["id"] == ids[1]


def test_admin_items_filter_by_beijing_day_and_calendar_counts():
    # 北京时间 11-03 00:30 = UTC 11-02 16:30，应算在 11-03
    _items(("a", datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc)),
           ("b", datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)),
           ("c", datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)))
    boss = login_client("boss301b@example.com", role="admin")
    one_day = boss.get("/api/admin/items?date_from=2026-11-03&date_to=2026-11-03").json()
    assert sorted(x["name"] for x in one_day["items"]) == ["a", "b"]
    span = boss.get("/api/admin/items?date_from=2026-11-04&date_to=2026-11-30").json()
    assert [x["name"] for x in span["items"]] == ["c"]
    days = boss.get("/api/admin/items/days?month=2026-11").json()
    assert days == {"2026-11-03": 2, "2026-11-05": 1}


def test_feedback_reply_with_image_and_status_reaches_user():
    user = login_client("fbuser301@example.com")
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "fbuser301@example.com"))
        f = Feedback(user_id=uid, category="bug", content="按钮点不动", images=[], diagnostics={}, status="new", ai_status="done", ai_analysis={})
        db.add(f)
        db.commit()
        fid = f.id
    boss = login_client("boss301c@example.com", role="admin")
    png = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (8, 8), "blue").save(png, "PNG")
    r = boss.post(f"/api/admin/feedback/{fid}/replies", data={"text": "已修复，刷新试试", "status": "resolved"},
                  files=[("images", ("fix.png", png.getvalue(), "image/png"))])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "resolved" and out["replies"][0]["text"] == "已修复，刷新试试" and out["replies"][0]["images"][0].startswith("/media/feedback/")
    boss.post(f"/api/admin/feedback/{fid}/replies", data={"text": "补充一句"})
    mine = user.get("/api/me/feedback").json()["items"][0]
    assert [x["text"] for x in mine["replies"]] == ["已修复，刷新试试", "补充一句"]
    assert mine["user_unread"] is True and mine["status_label"]
    assert boss.post(f"/api/admin/feedback/{fid}/replies", data={}).status_code == 400
