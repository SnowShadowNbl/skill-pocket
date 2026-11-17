"""v3.3.103 语音文字整理：要求登录、不扣额度、失败用原话、限流。"""

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import User
from app.routers import voice
from app.services import billing
from conftest import login_client


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._c}}], "usage": {"prompt_tokens": 900, "completion_tokens": 30}}


def test_requires_login():
    assert TestClient(app).post("/api/voice/normalize", json={"text": "嗯"}).status_code == 401


def test_normalize_not_billed(monkeypatch):
    monkeypatch.setattr(settings, "ai_base_url", "http://ai.test")
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_text_model", "m")
    sent = {}

    def post(url, json, headers):
        sent.update(json)
        return _Resp("找一个把会议录音转成文字的工具：\n1. 自动分段\n2. 区分说话人")
    monkeypatch.setattr(voice._client, "post", post)
    c = login_client("voice103@example.com")
    c.get("/api/auth/me/quota")
    with SessionLocal() as s:
        before = s.query(User).filter_by(email="voice103@example.com").one().quota_balance
    r = c.post("/api/voice/normalize", json={"text": "嗯我想找一个那个能把会议录音转成文字的然后第一点自动分段第二点区分说话人"}).json()
    assert r["changed"] and r["text"].startswith("找一个") and "1. 自动分段" in r["text"]
    assert sent["temperature"] == 0 and sent["messages"][0]["content"] == voice.RULES and "response_format" not in sent
    with SessionLocal() as s:
        assert s.query(User).filter_by(email="voice103@example.com").one().quota_balance == before  # 不扣额度
    assert "AI-voice" in billing.NOT_BILLED


def test_falls_back_to_original(monkeypatch):
    monkeypatch.setattr(settings, "ai_base_url", "http://ai.test")
    monkeypatch.setattr(settings, "ai_api_key", "k")
    monkeypatch.setattr(settings, "ai_text_model", "m")

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(voice._client, "post", boom)
    c = login_client("voice103b@example.com")
    r = c.post("/api/voice/normalize", json={"text": "PDF 转 PPT"}).json()
    assert r == {"text": "PDF 转 PPT", "changed": False}
    # 结果长度暴涨（像在回答问题）也用原话
    monkeypatch.setattr(voice._client, "post", lambda url, json, headers: _Resp("好的，" + "很多解释" * 50))
    assert c.post("/api/voice/normalize", json={"text": "PDF 转 PPT"}).json()["changed"] is False


def test_throttle(monkeypatch):
    monkeypatch.setattr(voice, "LIMIT_PER_MIN", 2)
    monkeypatch.setattr(settings, "ai_base_url", "")
    c = login_client("voice103c@example.com")
    codes = [c.post("/api/voice/normalize", json={"text": "你好"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
