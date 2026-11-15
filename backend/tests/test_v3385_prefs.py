"""v3.3.85 账号偏好：首页模式、搜索历史。"""

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.seed import seed_categories
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)


def test_guest_cannot_use_prefs():
    c = TestClient(app)
    assert c.get("/api/me/prefs").status_code == 401
    assert c.patch("/api/me/prefs", json={"home_mode": "simple"}).status_code == 401


def test_prefs_roundtrip_and_me():
    c = login_client("prefs@example.com")
    assert c.get("/api/me/prefs").json() == {}
    assert c.patch("/api/me/prefs", json={"home_mode": "simple"}).json() == {"home_mode": "simple"}
    r = c.patch("/api/me/prefs", json={"search_history": ["  会议纪要 ", "会议纪要", "x", "多行\n描述" + "长" * 300] + [f"词{i}" for i in range(20)]})
    h = r.json()["search_history"]
    assert h[0] == "会议纪要" and len(h) == 10 and len(h[1]) == 200
    assert r.json()["home_mode"] == "simple"  # 只改传了的字段
    assert c.get("/api/auth/me").json()["user"]["prefs"]["home_mode"] == "simple"
    assert c.patch("/api/me/prefs", json={"home_mode": "fancy"}).status_code == 400
