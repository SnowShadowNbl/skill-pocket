"""v3.3.89 额度用完弹窗 + 成本核算：每个扣额度的入口都返回 quota_exhausted；联系方式设置；单价表与成本快照。"""

from datetime import datetime, timezone
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import AiCall, FinderJob, Upload, User
from app.seed import seed_categories
from app.services import billing, extract, pricing
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)
        s.commit()


def _broke():
    c = login_client("empty89@example.com")
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == "empty89@example.com"))
        u.quota_balance = 0
        s.add(FinderJob(kind="search", user_id=u.id, query="x", status="done", result={"candidates": []}))
        s.add(Upload(image_path="uploads/z.png", status="recognized", user_id=u.id, ai_result={"items": []}))
        s.commit()
        job = s.scalar(select(FinderJob.id).where(FinderJob.user_id == u.id))
        up = s.scalar(select(Upload.id).where(Upload.user_id == u.id))
    return c, job, up


def test_every_billed_entry_returns_quota_exhausted():
    c, job, up = _broke()
    png = BytesIO()
    Image.new("RGB", (4, 4)).save(png, "PNG")
    calls = {
        "compare": lambda: c.post("/api/compare", json={"entries": [{"full_name": "a/b"}, {"full_name": "c/d"}]}),
        "finder.search": lambda: c.post("/api/finder/search", json={"q": "会议纪要"}),
        "finder.text": lambda: c.post("/api/finder/text", json={"text": "这是一段足够长的文章正文，用来测试长文识别是否被额度拦下来。"}),
        "finder.import": lambda: c.post(f"/api/finder/{job}/import", json={"picks": [{"full_name": "a/b"}]}),
        "items.import": lambda: c.post("/api/import", json={"url": "https://github.com/a/b", "picks": [{"name": "b"}]}),
        "items.create": lambda: c.post("/api/items", json={"name": "x", "category_id": 1}),
        "uploads.create": lambda: c.post("/api/uploads", files={"file": ("a.png", png.getvalue(), "image/png")}),
        "uploads.import": lambda: c.post(f"/api/uploads/{up}/import", json={"picks": [{"full_name": "a/b"}]}),
    }
    for name, call in calls.items():
        r = call()
        assert r.status_code == 402, (name, r.status_code, r.text)
        d = r.json()["detail"]
        assert d["code"] == "quota_exhausted", name
        assert "AI" not in d["message"] and "充值" not in d["message"], name  # 小程序老版本会直接显示这句


def test_contact_settings_and_meta():
    a = login_client("boss89@example.com", role="admin")
    r = a.put("/api/admin/quota/settings", json={"contact_wechat": " 837946408 "})
    assert r.status_code == 200 and r.json()["contact"]["wechat"] == "837946408"
    assert r.json()["default_free"] == billing.STANDARD_FREE  # 只改微信号，不动默认额度
    img = BytesIO()
    Image.new("RGB", (1200, 900), "white").save(img, "JPEG")
    r = a.post("/api/admin/quota/contact-qr", files={"file": ("card.jpg", img.getvalue(), "image/jpeg")})
    qr = r.json()["contact"]["qr"]
    assert qr.startswith("/media/contact/qr-") and qr.endswith(".png")
    path = settings.media_dir / qr.removeprefix("/media/")
    assert path.exists() and max(Image.open(path).size) == 720
    meta = login_client("u89@example.com").get("/api/meta").json()
    assert meta["quota_contact"] == {"wechat": "837946408", "qr": qr}
    r = a.delete("/api/admin/quota/contact-qr")
    assert r.json()["contact"]["qr"] is None and not path.exists()
    assert login_client("u89@example.com").put("/api/admin/quota/settings", json={"contact_wechat": "x"}).status_code == 403


def test_pricing_peak_idle_and_cache_hit(monkeypatch):
    monkeypatch.setattr(settings, "ai_text_model", "ds-test")
    t = pricing.defaults()
    t["models"]["ds-test"] = {"in_peak": 3, "in_idle": 1.5, "hit_peak": 0.5, "hit_idle": 0.25, "out_peak": 9, "out_idle": 4.5}
    tue_10 = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)  # 北京时间周二 10:00，高峰
    tue_13 = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)  # 午休，闲时
    sat_10 = datetime(2026, 11, 21, 2, 0, tzinfo=timezone.utc)  # 周末，闲时
    worst, actual = pricing.cost("ds-test", 1_000_000, 1_000_000, 400_000, tue_10, t)
    assert worst == 12.0 and actual == round(0.6 * 3 + 0.4 * 0.5 + 9, 6)
    assert pricing.cost("ds-test", 1_000_000, 0, 0, tue_13, t) == (3.0, 1.5)
    assert pricing.cost("ds-test", 1_000_000, 0, 0, sat_10, t)[1] == 1.5
    assert pricing.cost("unknown", 1, 1, 0, tue_10, t) == (None, None)


def test_price_table_api_and_snapshot(monkeypatch):
    a = login_client("boss89@example.com", role="admin")
    monkeypatch.setattr(settings, "ai_text_model", "ds-snap")
    body = {"models": {"ds-snap": {"in_peak": 2, "in_idle": 2, "hit_peak": 2, "hit_idle": 2, "out_peak": 8, "out_idle": 8}},
            "peak": [[9, 12], [14, 18]], "peak_weekdays_only": True}
    r = a.put("/api/admin/ai/prices", json=body)
    assert r.status_code == 200 and r.json()["models"]["ds-snap"]["out_peak"] == 8
    extract._log_call("AI-1", True, 10, {"prompt_tokens": 500_000, "completion_tokens": 250_000, "prompt_cache_hit_tokens": 100_000})
    with SessionLocal() as s:
        row = s.scalars(select(AiCall).where(AiCall.model == "ds-snap")).one()
    assert row.cache_hit_tokens == 100_000 and row.cost_max_yuan == 3.0 and row.cost_actual_yuan == 3.0
    # 改单价后，已有记录仍按调用当时的快照
    body["models"]["ds-snap"]["out_peak"] = body["models"]["ds-snap"]["out_idle"] = 100
    a.put("/api/admin/ai/prices", json=body)
    r = a.get("/api/admin/ai/usage?days=1&group=model").json()
    by = {x["key"]: x for x in r["items"]}
    assert by["ds-snap"]["est_cost_yuan"] == 3.0 and r["basis"] == "max"
    assert a.get("/api/admin/ai/usage?days=1&group=model&basis=actual").json()["basis"] == "actual"


def test_favorites_organize_is_billed(monkeypatch):
    from app.models import Category, Favorite, Item
    from app.services import judge

    c = login_client("org90@example.com")
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.email == "org90@example.com"))
        cat = s.scalars(select(Category).where(Category.parent_id.is_not(None))).first()
        it = Item(name="整理测试", category_id=cat.id, status="published")
        s.add(it)
        s.flush()
        s.add(Favorite(owner_id=u.id, item_id=it.id))
        s.commit()
        uid_, iid = u.id, it.id
    dim = c.get("/api/favorites/structure").json()["dimensions"][0]["id"]
    seen = {}

    def fake(name, folders, items):
        seen["owner"] = billing.owner()
        return [{"item_id": iid, "folder": "工具"}]
    monkeypatch.setattr(judge, "suggest_folders", fake)
    assert c.post("/api/favorites/organize/suggest", json={"dimension_id": dim}).status_code == 200
    assert seen["owner"] == uid_  # 消耗记到这个账号
    with SessionLocal() as s:
        s.get(User, uid_).quota_balance = 0
        s.commit()
    r = c.post("/api/favorites/organize/suggest", json={"dimension_id": dim})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "quota_exhausted"
