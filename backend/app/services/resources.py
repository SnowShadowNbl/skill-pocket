"""资源监控：第三方服务用量与余额（DeepSeek、腾讯云邮件推送、阿里云百炼向量）和服务器状态（内存、磁盘、图片增长）。

- DeepSeek：用量来自 ai_calls（每次调用都记了 token）；余额调官方 /user/balance（缓存 5 分钟），每天记一次用来估算日均花费。
- 腾讯云邮件：按 email_logs 统计发送量（SES 没有可用 API Key 直接查的余额，按免费额度 / 发送量提示）。
- 阿里云百炼：用 API Key 查不到余额，按记录的 token 用量估算免费额度还剩多少；记录之前的历史用量按已向量化的文本估算。
- 服务器：/proc/meminfo、磁盘占用、图片目录大小、数据库大小；每天记一次，估算按现在的增长速度多久会满。
"""

import json
import logging
import os
import shutil
import threading
import time
from datetime import date, timedelta

import httpx
from sqlalchemy import func, select, text

from ..config import settings
from ..db import SessionLocal, engine, utcnow
from ..models import AiCall, AppMeta, EmailLog, ItemEmbedding

log = logging.getLogger(__name__)
EMB = "EMB"  # ai_calls 里向量调用的 purpose

PURPOSES = {
    "AI-1": "条目提炼", "AI-2": "分类", "AI-3": "AI 封面", "AI-4": "截图识别", "AI-6": "采集筛选", "AI-7": "翻译",
    "AI-8": "搜索添加", "AI-9": "长文识别", "AI-10": "榜单详解", "AI-11": "收藏整理", "AI-12": "昵称审核",
    "AI-13": "内容审核", "AI-14": "搜索标签", "AI-15": "站内搜索", "AI-16": "反馈分析", "AI-17": "AI 智能对比", "AI-18": "评论审核",
    "AI-geo": "地名翻译",
}

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _meta_json(db, key: str, default):
    m = db.get(AppMeta, key)
    try:
        return json.loads(m.value) if m else default
    except ValueError:
        return default


def _set_meta_json(db, key: str, value) -> None:
    db.merge(AppMeta(key=key, value=json.dumps(value, ensure_ascii=False)))


def _today() -> str:
    return date.today().isoformat()


def _trim(history: dict, days: int = 90) -> dict:
    keep = sorted(history)[-days:]
    return {k: history[k] for k in keep}


# ---------------------------------------------------------------- 记录向量调用

def record_embedding(tokens: int, ok: bool = True, latency_ms: int = 0, error: str = "") -> None:
    try:
        with SessionLocal() as db:
            db.add(AiCall(purpose=EMB, model=settings.embedding_model, tokens_in=tokens, tokens_out=0, ok=ok,
                          latency_ms=latency_ms, error=error[:500]))
            db.commit()
    except Exception:
        log.exception("record embedding usage failed")


# ---------------------------------------------------------------- DeepSeek

def _fetch_deepseek_balance() -> dict:
    if not settings.ai_enabled:
        return {"supported": False, "error": "未配置 AI 接口"}
    base = settings.ai_base_url.rstrip("/")
    if "deepseek" not in base:
        return {"supported": False, "error": "当前 AI 接口不是 DeepSeek，无法查询余额"}
    root = base[:-3] if base.endswith("/v1") else base
    try:
        r = httpx.get(f"{root}/user/balance", headers={"Authorization": f"Bearer {settings.ai_api_key}"}, timeout=10)
        r.raise_for_status()
        d = r.json()
        info = next((x for x in d.get("balance_infos") or [] if x.get("currency") == "CNY"), (d.get("balance_infos") or [{}])[0])
        out = {"supported": True, "available": bool(d.get("is_available")), "currency": info.get("currency", "CNY"),
               "total": float(info.get("total_balance") or 0), "granted": float(info.get("granted_balance") or 0),
               "topped_up": float(info.get("topped_up_balance") or 0), "checked_at": utcnow().isoformat()}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"supported": True, "error": f"查询失败：{e.__class__.__name__}"}
    # 每天记一次余额，用来算日均花费
    with SessionLocal() as db:
        hist = _meta_json(db, "ai_balance_history", {})
        hist[_today()] = out["total"]
        _set_meta_json(db, "ai_balance_history", _trim(hist))
        db.commit()
    return out


def deepseek_balance(force: bool = False) -> dict:
    if force:
        _cache.pop("ds_balance", None)
    return _cached("ds_balance", 300, _fetch_deepseek_balance)


def _usage(db, conds, since) -> dict:
    row = db.execute(select(func.count(), func.coalesce(func.sum(AiCall.tokens_in), 0), func.coalesce(func.sum(AiCall.tokens_out), 0),
                            func.count().filter(AiCall.ok.is_(False))).where(*conds, AiCall.created_at >= since)).one()
    return {"calls": row[0], "tokens_in": int(row[1]), "tokens_out": int(row[2]), "failed": row[3]}


def ai_usage() -> dict:
    now = utcnow()
    start_today = (now + timedelta(hours=8)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)  # 北京时间零点
    conds = [AiCall.purpose != EMB]
    with SessionLocal() as db:
        out = {
            "today": _usage(db, conds, start_today),
            "d7": _usage(db, conds, now - timedelta(days=7)),
            "d30": _usage(db, conds, now - timedelta(days=30)),
            "all": _usage(db, conds, now - timedelta(days=3650)),
        }
        rows = db.execute(select(AiCall.purpose, func.count(), func.coalesce(func.sum(AiCall.tokens_in), 0) + func.coalesce(func.sum(AiCall.tokens_out), 0))
                          .where(*conds, AiCall.created_at >= now - timedelta(days=30)).group_by(AiCall.purpose)).all()
        out["by_purpose"] = sorted(({"purpose": p, "label": PURPOSES.get(p, p), "calls": c, "tokens": int(t)} for p, c, t in rows),
                                   key=lambda x: -x["tokens"])
        series = []
        for i in range(13, -1, -1):
            d0 = start_today - timedelta(days=i)
            u = db.execute(select(func.coalesce(func.sum(AiCall.tokens_in), 0) + func.coalesce(func.sum(AiCall.tokens_out), 0), func.count())
                           .where(*conds, AiCall.created_at >= d0, AiCall.created_at < d0 + timedelta(days=1))).one()
            series.append({"day": (d0 + timedelta(hours=8)).date().isoformat(), "tokens": int(u[0]), "calls": u[1]})
        out["series"] = series
        out["first_at"] = db.scalar(select(func.min(AiCall.created_at)).where(*conds))
        hist = _meta_json(db, "ai_balance_history", {})
    out["model"] = settings.ai_text_model
    bal = deepseek_balance()
    out["balance"] = bal
    # 日均花费：按最近余额变化估算（充值那天会让余额变多，跳过上涨的日子）
    days = sorted(hist)
    drops = [hist[a] - hist[b] for a, b in zip(days, days[1:]) if hist[a] >= hist[b]]
    out["daily_spend"] = round(sum(drops[-7:]) / len(drops[-7:]), 2) if drops else None
    if bal.get("total") is not None and out["daily_spend"]:
        out["days_left"] = int(bal["total"] / out["daily_spend"]) if out["daily_spend"] > 0 else None
    return out


# ---------------------------------------------------------------- 腾讯云邮件推送

def email_usage() -> dict:
    now = utcnow()
    bj = now + timedelta(hours=8)
    month_start = bj.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    day_start = bj.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    with SessionLocal() as db:
        def cnt(*conds):
            return db.scalar(select(func.count()).select_from(EmailLog).where(EmailLog.provider == "ses", *conds)) or 0
        by_purpose = dict(db.execute(select(EmailLog.purpose, func.count()).where(EmailLog.provider == "ses", EmailLog.created_at >= month_start)
                                     .group_by(EmailLog.purpose)).all())
        out = {"today": cnt(EmailLog.created_at >= day_start), "month": cnt(EmailLog.created_at >= month_start),
               "month_failed": cnt(EmailLog.created_at >= month_start, EmailLog.ok.is_(False)), "total": cnt(),
               "by_purpose": by_purpose, "configured": bool(settings.ses_secret_id and settings.ses_secret_key),
               "monthly_quota": settings.ses_monthly_quota or None}
    if out["monthly_quota"]:
        out["quota_used_pct"] = round(out["month"] / out["monthly_quota"] * 100, 1)
    return out


# ---------------------------------------------------------------- 阿里云百炼向量

def _historical_embedding_tokens() -> int:
    """开始记录之前已经花掉的 token：按已向量化条目的文本长度估算（中文约 1 字 1 token，英文约 4 字母 1 token），只算一次。"""
    with SessionLocal() as db:
        cached = db.get(AppMeta, "emb_tokens_before_log")
        if cached and cached.value.isdigit():
            return int(cached.value)
        from .search import basis_text
        from ..models import Item

        total = 0
        for it in db.scalars(select(Item).join(ItemEmbedding, ItemEmbedding.item_id == Item.id)):
            t = basis_text(it)
            cjk = sum(1 for ch in t if "一" <= ch <= "鿿")
            total += cjk + (len(t) - cjk) // 4
        total = int(total * 1.15)  # 加上搜索标签生成后重算、用户搜索等零散用量
        db.merge(AppMeta(key="emb_tokens_before_log", value=str(total)))
        db.commit()
        return total


def embedding_usage() -> dict:
    now = utcnow()
    with SessionLocal() as db:
        logged = _usage(db, [AiCall.purpose == EMB], now - timedelta(days=3650))
        today = _usage(db, [AiCall.purpose == EMB], now - timedelta(days=1))
        d30 = _usage(db, [AiCall.purpose == EMB], now - timedelta(days=30))
        first = db.scalar(select(func.min(AiCall.created_at)).where(AiCall.purpose == EMB))
        vectors = db.scalar(select(func.count()).select_from(ItemEmbedding)) or 0
    before = _cached("emb_before", 3600, _historical_embedding_tokens)
    used = before + logged["tokens_in"]
    free = settings.embedding_free_tokens
    out = {"configured": bool(settings.embedding_api_key), "model": settings.embedding_model, "vectors": vectors,
           "tokens_logged": logged["tokens_in"], "calls_logged": logged["calls"], "failed": logged["failed"],
           "tokens_before_log": before, "tokens_used_estimate": used, "logged_since": first,
           "tokens_24h": today["tokens_in"], "tokens_30d": d30["tokens_in"], "free_tokens": free,
           "price_per_1k": settings.embedding_price_per_1k_tokens}
    if free:
        out["free_left"] = max(0, free - used)
        out["free_used_pct"] = round(min(100.0, used / free * 100), 1)
    over = max(0, used - free) if free else used
    out["estimated_cost"] = round(over / 1000 * settings.embedding_price_per_1k_tokens, 2)
    return out


# ---------------------------------------------------------------- 服务器

def _meminfo() -> dict:
    vals = {}
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                k, v = line.split(":", 1)
                vals[k] = int(v.strip().split()[0]) * 1024
    except OSError:
        return {}
    total, avail = vals.get("MemTotal", 0), vals.get("MemAvailable", 0)
    swap_t, swap_f = vals.get("SwapTotal", 0), vals.get("SwapFree", 0)
    return {"total": total, "available": avail, "used": total - avail, "used_pct": round((total - avail) / total * 100, 1) if total else None,
            "swap_total": swap_t, "swap_used": swap_t - swap_f}


def _dir_size(path) -> tuple[int, int]:
    size = files = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                size += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return size, files


def _media_sizes() -> dict:
    media = settings.media_dir
    out = {}
    if media.exists():
        for sub in sorted(p for p in media.iterdir() if p.is_dir()):
            out[sub.name] = dict(zip(("bytes", "files"), _dir_size(sub)))
    return out


def _db_size() -> int | None:
    try:
        with engine.connect() as c:
            if engine.dialect.name == "postgresql":
                return int(c.execute(text("select pg_database_size(current_database())")).scalar())
        path = engine.url.database
        return os.path.getsize(path) if path and os.path.exists(path) else None
    except Exception:
        return None


LABEL_DIRS = {"covers": "条目图片", "uploads": "截图识别上传", "avatars": "用户头像", "feedback": "反馈截图"}


def server_status() -> dict:
    disk = shutil.disk_usage(settings.media_dir if settings.media_dir.exists() else "/")
    mem = _meminfo()
    media = _cached("media_sizes", 600, _media_sizes)
    media_total = sum(v["bytes"] for v in media.values())
    try:
        load = os.getloadavg()
    except (OSError, AttributeError):
        load = None
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            uptime = int(float(f.read().split()[0]))
    except OSError:
        uptime = None
    out = {
        "memory": mem, "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "used_pct": round(disk.used / disk.total * 100, 1)},
        "media": [{"name": k, "label": LABEL_DIRS.get(k, k), **v} for k, v in media.items()], "media_total": media_total,
        "db_size": _cached("db_size", 600, _db_size), "cpus": os.cpu_count(), "load": [round(x, 2) for x in load] if load else None,
        "uptime": uptime,
    }
    # 增长趋势：每天记一次（夜间巡检也会记），按最近两周算每天增加多少
    with SessionLocal() as db:
        hist = _meta_json(db, "server_history", {})
        hist[_today()] = {"disk_used": disk.used, "media": media_total, "db": out["db_size"] or 0, "mem_pct": mem.get("used_pct")}
        _set_meta_json(db, "server_history", _trim(hist))
        db.commit()
    days = sorted(hist)[-15:]
    out["history"] = [{"day": d, **hist[d]} for d in days]
    if len(days) >= 2:
        span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days or 1
        growth = (hist[days[-1]]["disk_used"] - hist[days[0]]["disk_used"]) / span
        out["disk_growth_per_day"] = int(growth)
        limit = disk.total * 0.85
        out["days_until_85"] = int((limit - disk.used) / growth) if growth > 0 and disk.used < limit else None
    out["advice"] = _server_advice(out)
    return out


def _server_advice(s: dict) -> list[dict]:
    tips = []
    mem, disk = s["memory"], s["disk"]
    if mem.get("used_pct") is not None:
        if mem["used_pct"] >= 90:
            tips.append({"level": "bad", "text": f"内存已用 {mem['used_pct']}%，接近饱和，容易导致服务变慢或被系统杀掉，建议尽快升级内存（如 4G → 8G）。"})
        elif mem["used_pct"] >= 80:
            tips.append({"level": "warn", "text": f"内存已用 {mem['used_pct']}%，偏高；如果经常这样，建议升级内存。"})
    if mem.get("swap_used", 0) > 512 * 1024 * 1024:
        tips.append({"level": "warn", "text": "已经在用较多交换分区（swap），说明内存不够用，会拖慢速度。"})
    if disk["used_pct"] >= 90:
        tips.append({"level": "bad", "text": f"磁盘已用 {disk['used_pct']}%，马上要满了，请尽快扩容云硬盘或清理旧备份。"})
    elif disk["used_pct"] >= 80:
        tips.append({"level": "warn", "text": f"磁盘已用 {disk['used_pct']}%，建议准备扩容。"})
    if s.get("days_until_85") is not None and s["days_until_85"] < 90:
        tips.append({"level": "warn", "text": f"按最近的增长速度，约 {s['days_until_85']} 天后磁盘用到 85%，建议提前扩容。"})
    if s.get("load") and s.get("cpus") and s["load"][1] > s["cpus"] * 1.5:
        tips.append({"level": "warn", "text": f"近 5 分钟负载 {s['load'][1]}，超过 CPU 核数（{s['cpus']}）的 1.5 倍，服务器比较忙。"})
    if not tips:
        tips.append({"level": "ok", "text": "内存、磁盘和负载都在正常范围，暂时不需要升级服务器。"})
    return tips


# ---------------------------------------------------------------- 提醒（概览和侧栏角标用）

def alerts(fetch_remote: bool = False) -> list[dict]:
    """需要管理员处理的资源提醒。fetch_remote=False 时只用缓存的余额，不发外部请求。"""
    out = []
    bal = deepseek_balance() if fetch_remote else (_cache.get("ds_balance") or (0, None))[1]
    if bal is None:
        # 这个进程还没查过余额：用最近一次记录的余额（夜间巡检每天记一次）
        with SessionLocal() as db:
            hist = _meta_json(db, "ai_balance_history", {})
        if hist:
            bal = {"total": hist[max(hist)]}
    if bal and bal.get("total") is not None and bal["total"] < settings.ai_balance_warn:
        out.append({"level": "bad", "key": "deepseek", "text": f"DeepSeek 余额只剩 ¥{bal['total']:.2f}，请尽快充值，否则 AI 功能会停止。"})
    elif bal and bal.get("available") is False:
        out.append({"level": "bad", "key": "deepseek", "text": "DeepSeek 账户不可用（余额不足），请充值。"})
    e = _cached("emb_usage", 300, embedding_usage) if settings.embedding_api_key else None
    if e and e.get("free_tokens") and e.get("free_used_pct", 0) >= 80:
        out.append({"level": "bad" if e["free_used_pct"] >= 100 else "warn", "key": "embedding",
                    "text": f"阿里云百炼向量免费额度已用约 {e['free_used_pct']}%（估算），" + ("请到百炼控制台确认余额并充值。" if e["free_used_pct"] >= 100 else "快用完了，请留意余额。")})
    try:
        disk = shutil.disk_usage(settings.media_dir if settings.media_dir.exists() else "/")
        pct = disk.used / disk.total * 100
        if pct >= 85:
            out.append({"level": "bad" if pct >= 90 else "warn", "key": "disk", "text": f"服务器磁盘已用 {pct:.0f}%，请扩容。"})
    except OSError:
        pass
    mem = _meminfo()
    if mem.get("used_pct") and mem["used_pct"] >= 90:
        out.append({"level": "warn", "key": "memory", "text": f"服务器内存已用 {mem['used_pct']}%，接近饱和。"})
    return out


def overview() -> dict:
    emb = embedding_usage()
    _cache["emb_usage"] = (time.time(), emb)
    return {"ai": ai_usage(), "email": email_usage(), "embedding": emb, "server": server_status(), "alerts": alerts(fetch_remote=True),
            "thresholds": {"ai_balance_warn": settings.ai_balance_warn}}
