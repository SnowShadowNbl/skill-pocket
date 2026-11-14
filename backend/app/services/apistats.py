"""v3.3.66 接口请求统计：中间件把每个 /api 请求记进内存，按「小时 + 方法 + 路由模板」聚合，每分钟写一次库。

不存逐条请求；耗时按桶计数，用来估算 p50 / p95。进程重启会丢最后不到一分钟的数据。
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import SessionLocal
from ..models import ApiStat

log = logging.getLogger(__name__)
BUCKETS = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000)  # 毫秒；超过最后一档记在 "inf"
FLUSH_SECONDS = 60
SKIP = ("/api/health", "/api/track")

_lock = threading.Lock()
_pending: dict[tuple, dict] = {}
_last_flush = time.time()


def _bucket(ms: int) -> str:
    for b in BUCKETS:
        if ms <= b:
            return str(b)
    return "inf"


def record(method: str, path: str, status: int, ms: int) -> None:
    global _last_flush
    if not path.startswith("/api/") or path in SKIP:
        return
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    key = (hour, method, path[:200])
    with _lock:
        a = _pending.get(key)
        if a is None:
            a = _pending[key] = {"requests": 0, "e4": 0, "e5": 0, "total": 0, "max": 0, "buckets": defaultdict(int), "err_at": None, "status": None}
        a["requests"] += 1
        a["total"] += ms
        a["max"] = max(a["max"], ms)
        a["buckets"][_bucket(ms)] += 1
        if status >= 500:
            a["e5"] += 1
        elif status >= 400:
            a["e4"] += 1
        if status >= 400:
            a["err_at"], a["status"] = datetime.now(timezone.utc), status
        due = time.time() - _last_flush >= FLUSH_SECONDS
    if due:
        threading.Thread(target=flush, daemon=True, name="apistats-flush").start()


def flush() -> None:
    global _last_flush
    with _lock:
        if not _pending:
            _last_flush = time.time()
            return
        batch = dict(_pending)
        _pending.clear()
        _last_flush = time.time()
    try:
        with SessionLocal() as db:
            for (hour, method, path), a in batch.items():
                row = db.scalar(select(ApiStat).where(ApiStat.hour == hour, ApiStat.method == method, ApiStat.path == path))
                if row is None:
                    row = ApiStat(hour=hour, method=method, path=path, requests=0, errors_4xx=0, errors_5xx=0, total_ms=0, max_ms=0, buckets={})
                    db.add(row)
                row.requests += a["requests"]
                row.errors_4xx += a["e4"]
                row.errors_5xx += a["e5"]
                row.total_ms += a["total"]
                row.max_ms = max(row.max_ms or 0, a["max"])
                b = dict(row.buckets or {})
                for k, v in a["buckets"].items():
                    b[k] = b.get(k, 0) + v
                row.buckets = b
                if a["err_at"]:
                    row.last_error_at, row.last_status = a["err_at"], a["status"]
            db.commit()
    except Exception:  # noqa: BLE001  统计写失败不影响业务
        log.warning("apistats flush failed", exc_info=True)


def percentile(buckets: dict, q: float) -> int | None:
    total = sum(buckets.values())
    if not total:
        return None
    need = total * q
    acc = 0
    for b in [*map(str, BUCKETS), "inf"]:
        acc += buckets.get(b, 0)
        if acc >= need:
            return int(b) if b != "inf" else BUCKETS[-1] + 1
    return None
