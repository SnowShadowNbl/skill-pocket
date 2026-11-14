from fastapi.testclient import TestClient

from conftest import login_client
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Category, Item
from app.seed import seed_categories

c = None


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        asr = s.scalar(select(Category).where(Category.code == "model-asr"))
        doc = s.scalar(select(Category).where(Category.code == "office-docs"))
        s.add_all([
            Item(name="sensevoice", category_id=asr.id, kind="model", locked_fields=[], install_steps=[]),
            Item(name="pdf-skill", category_id=doc.id, kind="agent_skill", locked_fields=[], install_steps=[]),
            Item(name="docx-skill", category_id=doc.id, kind="agent_skill", locked_fields=[], install_steps=[]),
        ])
        s.commit()


def ids():
    return {i["name"]: i["id"] for i in c.get("/api/items?sort=collected").json()["items"]}


def listing(**params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return sorted(i["name"] for i in c.get(f"/api/items?{q}").json()["items"])


def test_folders_flow():
    global c
    c = login_client('folders@example.com')
    n = ids()
    for name in n:
        c.post(f"/api/items/{n[name]}/favorite", json={"on": True})

    st = c.get("/api/favorites/structure").json()
    assert st["total"] == 3
    dim = st["dimensions"][0]
    assert dim["name"] == "我的分类" and dim["unsorted"] == 3
    groups = {f["name"]: f["count"] for f in st["system"][0]["folders"]}
    assert groups == {"文档办公": 2, "语音与音频": 1}
    kinds = {f["key"]: f["count"] for f in st["system"][1]["folders"]}
    assert kinds == {"agent_skill": 2, "model": 1}

    work = c.post("/api/favorites/folders", json={"dimension_id": dim["id"], "name": "写周报", "emoji": "📝"}).json()
    voice = c.post("/api/favorites/folders", json={"dimension_id": dim["id"], "name": "语音"}).json()
    assert c.post("/api/favorites/folders", json={"dimension_id": dim["id"], "name": "语音"}).status_code == 409

    # 批量放入；同一维度下可多选
    c.post("/api/favorites/move", json={"item_ids": [n["pdf-skill"], n["docx-skill"]], "add": [work["id"]]})
    r = c.put(f"/api/favorites/{n['sensevoice']}/folders", json={"dimension_id": dim["id"], "folder_ids": [voice["id"], work["id"]]})
    assert sorted(r.json()["folder_ids"]) == sorted([voice["id"], work["id"]])

    assert listing(fav_folder=work["id"]) == ["docx-skill", "pdf-skill", "sensevoice"]
    assert listing(fav_folder=voice["id"]) == ["sensevoice"]
    c.post("/api/favorites/move", json={"item_ids": [n["sensevoice"]], "remove": [work["id"]]})
    assert listing(fav_folder=work["id"]) == ["docx-skill", "pdf-skill"]
    assert listing(fav_folder="none", fav_dim=dim["id"]) == []

    # 删除分类不取消收藏，条目回到未整理；撤销时原样建回
    snap = c.delete(f"/api/favorites/folders/{work['id']}").json()
    assert sorted(snap["item_ids"]) == sorted([n["pdf-skill"], n["docx-skill"]])
    assert listing(fav_folder="none", fav_dim=dim["id"]) == ["docx-skill", "pdf-skill"]
    assert c.get("/api/favorites/structure").json()["total"] == 3
    restored = c.post("/api/favorites/folders", json=snap).json()
    assert listing(fav_folder=restored["id"]) == ["docx-skill", "pdf-skill"]

    # 第二个维度互不影响
    stage = c.post("/api/favorites/dimensions", json={"name": "试用进度"}).json()
    st = c.get("/api/favorites/structure").json()
    assert {d["name"]: d["unsorted"] for d in st["dimensions"]} == {"我的分类": 0, "试用进度": 3}
    assert c.delete(f"/api/favorites/dimensions/{stage['id']}").json() == {"ok": True}
    assert c.delete(f"/api/favorites/dimensions/{dim['id']}").status_code == 400  # 至少保留一个

    # 备注与详情
    c.put(f"/api/favorites/{n['sensevoice']}/note", json={"note": "会议录音转写"})
    d = c.get(f"/api/items/{n['sensevoice']}").json()
    assert d["favorited"] and d["favorite"]["note"] == "会议录音转写" and d["favorite"]["folder_ids"] == [voice["id"]]

    # 使用类型筛选
    assert listing(kind="agent_skill") == ["docx-skill", "pdf-skill"]
    assert c.get("/api/items?kind=bogus").status_code == 400

    # 取消收藏后分类里也看不到
    c.post(f"/api/items/{n['sensevoice']}/favorite", json={"on": False})
    assert listing(fav_folder=voice["id"]) == []
    assert c.get(f"/api/items/{n['sensevoice']}").json()["favorite"] is None
