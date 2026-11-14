"""v3.2：口袋里的 AI 对比卡片带封面；入库日志只对管理员开放。"""

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import CompareRun, User
from app.seed import seed_categories
from conftest import login_client


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def test_my_compares_returns_covers():
    c = login_client("cmp32@example.com")
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "cmp32@example.com"))
        subs = [{"name": f"n{k}", "cover_url": f"/media/c{k}.png" if k != 1 else ""} for k in range(5)]
        db.add(CompareRun(key="k", entries=[], subjects=subs, status="done", result={"summary": "s"}, model="", user_id=uid))
        db.commit()
    r = c.get("/api/me/compares").json()[0]
    assert r["covers"] == ["/media/c0.png", "", "/media/c2.png", "/media/c3.png"]
    assert r["names"] == [f"n{k}" for k in range(5)] and r["model"] == ""


def test_logs_admin_only():
    assert login_client("u32@example.com").get("/api/logs").status_code == 403
    assert login_client("a32@example.com", role="admin").get("/api/logs").status_code == 200


def test_meta_today_offline():
    from datetime import datetime, timedelta, timezone
    from app.models import Category, Item
    with SessionLocal() as db:
        cid = db.scalar(select(Category.id).where(Category.parent_id.is_not(None)))
        now = datetime.now(timezone.utc)
        db.add_all([Item(name="a", category_id=cid, status="offline", offline_at=now, locked_fields=[], install_steps=[]),
                    Item(name="b", category_id=cid, status="offline", offline_at=now - timedelta(days=3), locked_fields=[], install_steps=[]),
                    Item(name="c", category_id=cid, status="published", offline_at=now, locked_fields=[], install_steps=[])])
        db.commit()
    assert login_client("off32@example.com").get("/api/meta").json()["today_offline"] == 1
