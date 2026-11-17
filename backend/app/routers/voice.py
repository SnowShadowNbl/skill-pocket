"""v3.3.103 语音输入的文字整理：语音转出的原话 → 按 prompts/voice_normalize.md 的规则整理成书面搜索描述。

- 平台成本，不扣用户额度（purpose = AI-voice，在 billing.NOT_BILLED 里）；要求登录，按账号限流。
- 为了快：规则作为固定的 system 提示（DeepSeek 前缀缓存命中）、纯文本输出（不用 JSON 模式）、温度 0、按原文长度限制输出 token、不重试。
- AI 不可用或调用失败时原样返回，前端照常显示原话。
"""

import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import current_user
from ..config import settings
from ..models import User
from ..services import billing
from ..services.extract import _log_call

router = APIRouter(prefix="/api/voice", tags=["voice"])
PURPOSE = "AI-voice"
RULES = (Path(__file__).resolve().parent.parent / "prompts" / "voice_normalize.md").read_text(encoding="utf-8")
LIMIT_PER_MIN = 30
_hits: dict[int, deque] = defaultdict(deque)
_lock = threading.Lock()
_client = httpx.Client(timeout=httpx.Timeout(60, connect=5))  # 复用连接，省掉每次的握手


class NormalizeIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


def _throttle(uid: int) -> None:
    now = time.monotonic()
    with _lock:
        q = _hits[uid]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= LIMIT_PER_MIN:
            raise HTTPException(429, "说得太快了，请稍后再试")
        q.append(now)


def _clean(out: str) -> str:
    out = out.strip().strip("“”\"'「」")
    out = re.sub(r"^(输出|整理后)[:：]\s*", "", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return re.sub(r"[。．.]+$", "", out)  # 末尾不要句号（问号、感叹号保留）


def normalize(text: str, uid: int | None) -> str:
    if not settings.ai_enabled:
        return text
    body = {
        "model": settings.ai_text_model,
        "messages": [{"role": "system", "content": RULES}, {"role": "user", "content": text}],
        "temperature": 0,
        "max_tokens": min(800, len(text) * 2 + 60),
        "stream": False,
    }
    t0 = time.monotonic()
    try:
        r = _client.post(settings.ai_base_url.rstrip("/") + "/chat/completions", json=body,
                         headers={"Authorization": f"Bearer {settings.ai_api_key}"})
        r.raise_for_status()
        data = r.json()
        out = _clean(data["choices"][0]["message"]["content"] or "")
        with billing.charged_to(uid):
            _log_call(PURPOSE, True, int((time.monotonic() - t0) * 1000), data.get("usage"))
    except Exception as e:  # noqa: BLE001 —— 整理失败就用原话
        with billing.charged_to(uid):
            _log_call(PURPOSE, False, int((time.monotonic() - t0) * 1000), None, str(e)[:300])
        return text
    # 结果明显不对（空的、或长度暴涨像是在回答问题）时用原话
    if not out or len(out) > len(text) * 1.6 + 40:
        return text
    return out


@router.post("/normalize")
def normalize_text(body: NormalizeIn, me: User = Depends(current_user)):
    text = re.sub(r"[。．.]+$", "", body.text.strip()) or body.text.strip()
    _throttle(me.id)
    out = normalize(text, me.id)
    return {"text": out, "changed": out != text}
