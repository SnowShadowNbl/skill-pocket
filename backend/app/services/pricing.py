"""v3.3.89 AI 单价表与真实成本。

- 单价表存在 AppMeta（后台可改），没改过时用默认值：文本模型按 DeepSeek 最高报价（高峰输入 3 元 / 输出 9 元每百万，
  闲时减半；缓存命中默认按未命中计，保守），向量模型按 embedding_price_per_1k_tokens。
- 每次 AI 调用记账时按当时的单价算两种成本存进 ai_calls：
  cost_max_yuan（全部按最高价，经营核算用的保守口径）、cost_actual_yuan（按调用时段的峰谷价和缓存命中）。
- 高峰时段按北京时间，默认工作日 9:00–12:00、14:00–18:00。
"""

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import AppMeta

CN = ZoneInfo("Asia/Shanghai")
META = "ai_price_table"
FIELDS = ("in_peak", "in_idle", "hit_peak", "hit_idle", "out_peak", "out_idle")
_TTL = 60
_cache: dict = {"at": 0.0, "v": None, "key": None}


def _flat(p_in: float, p_out: float, p_hit: float | None = None) -> dict:
    hit = p_in if p_hit is None else p_hit
    return {"in_peak": p_in, "in_idle": p_in, "hit_peak": hit, "hit_idle": hit, "out_peak": p_out, "out_idle": p_out}


def defaults() -> dict:
    models: dict[str, dict] = {}
    if settings.ai_text_model:
        models[settings.ai_text_model] = {"in_peak": 3.0, "in_idle": 1.5, "hit_peak": 3.0, "hit_idle": 1.5,
                                          "out_peak": 9.0, "out_idle": 4.5}
    if settings.embedding_model:
        models[settings.embedding_model] = _flat(settings.embedding_price_per_1k_tokens * 1000, 0.0)
    try:  # 兼容老的 AI_PRICES 环境变量：{"模型": [输入, 输出]}
        for k, v in (json.loads(settings.ai_prices or "{}") or {}).items():
            models[k] = _flat(float(v[0]), float(v[1]))
    except (ValueError, TypeError, IndexError):
        pass
    return {"models": models, "peak": [[9, 12], [14, 18]], "peak_weekdays_only": True}


def _clean(data: dict) -> dict:
    out = defaults()
    models = {}
    for name, p in (data.get("models") or {}).items():
        name = str(name).strip()[:100]
        if not name or not isinstance(p, dict):
            continue
        models[name] = {f: max(0.0, min(10000.0, float(p.get(f) or 0))) for f in FIELDS}
    if models:
        out["models"] = models
    peak = []
    for w in data.get("peak") or []:
        try:
            a, b = float(w[0]), float(w[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= a < b <= 24:
            peak.append([a, b])
    if "peak" in data:
        out["peak"] = peak
    if "peak_weekdays_only" in data:
        out["peak_weekdays_only"] = bool(data["peak_weekdays_only"])
    return out


def table() -> dict:
    now = time.monotonic()
    key = (settings.ai_text_model, settings.ai_prices, settings.embedding_model, settings.embedding_price_per_1k_tokens)
    if _cache["v"] is not None and now - _cache["at"] < _TTL and _cache["key"] == key:
        return _cache["v"]
    with SessionLocal() as db:
        row = db.get(AppMeta, META)
    v = defaults()
    if row and row.value:
        try:
            v = _clean(json.loads(row.value))
        except (ValueError, TypeError):
            pass
    _cache.update(at=now, v=v, key=key)
    return v


def save(db: Session, data: dict) -> dict:
    v = _clean(data)
    db.merge(AppMeta(key=META, value=json.dumps(v, ensure_ascii=False)))
    _cache.update(at=0.0, v=None)
    return v


def is_peak(at: datetime, t: dict | None = None) -> bool:
    t = t or table()
    local = at.astimezone(CN)
    if t.get("peak_weekdays_only", True) and local.weekday() >= 5:
        return False
    h = local.hour + local.minute / 60
    return any(a <= h < b for a, b in t.get("peak") or [])


def cost(model: str, tokens_in: int | None, tokens_out: int | None, cache_hit: int | None, at: datetime,
         t: dict | None = None) -> tuple[float | None, float | None]:
    """返回 (按最高价, 按实际时段) 的成本（元）；没有这个模型的单价返回 (None, None)。"""
    t = t or table()
    p = t["models"].get(model)
    if p is None:
        return None, None
    tin, tout = tokens_in or 0, tokens_out or 0
    hit = min(max(cache_hit or 0, 0), tin)
    high_in = max(p["in_peak"], p["in_idle"], p["hit_peak"], p["hit_idle"])
    high_out = max(p["out_peak"], p["out_idle"])
    worst = (tin * high_in + tout * high_out) / 1e6
    k = "peak" if is_peak(at, t) else "idle"
    actual = ((tin - hit) * p[f"in_{k}"] + hit * p[f"hit_{k}"] + tout * p[f"out_{k}"]) / 1e6
    return round(worst, 6), round(actual, 6)
