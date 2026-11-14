"""语义搜索。

条目向量：名称 + 一句话 + 介绍 + 使用类型 + 分类 + 搜索标签 → Embedding（阿里云百炼 text-embedding-v4）→ 存库，载入内存。
搜索分两段：① 问题直接向量化 → 余弦相似度取前 50（名称 / 仓库名精确命中置顶），约 0.4 秒先返回；
② 后台一次 AI 调用理解需求并精排前 12 个、写推荐理由，完成后前端原地重排。
Embedding 或 AI 不可用时，调用方退回关键词搜索。
"""

import hashlib
import logging
import math
import threading
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import Item, ItemEmbedding
from ..seed import KINDS
from . import cache, judge, tracking

log = logging.getLogger(__name__)

BATCH = 10  # 百炼 Embedding 每次最多 10 条
TOP_VECTOR = 50
TOP_RERANK = 12
MIN_SCORE = 45
RESULT_TTL = timedelta(hours=24)
SEARCHABLE = ("published", "offline")


class SearchUnavailable(Exception):
    pass


def enabled() -> bool:
    return bool(settings.embedding_api_key)


# ---------------------------------------------------------------- 向量

def _embed(texts: list[str]) -> list[list[float]]:
    if not enabled():
        raise SearchUnavailable("未配置 Embedding 接口")
    from . import resources

    t0 = time.monotonic()
    try:
        r = httpx.post(
            settings.embedding_base_url.rstrip("/") + "/embeddings",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={"model": settings.embedding_model, "input": texts, "dimensions": settings.embedding_dims},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        data = sorted(body["data"], key=lambda x: x["index"])
    except (httpx.HTTPError, KeyError, ValueError) as e:
        resources.record_embedding(0, ok=False, latency_ms=int((time.monotonic() - t0) * 1000), error=str(e))
        raise SearchUnavailable(f"Embedding 调用失败：{e.__class__.__name__}") from e
    # 用量记到 ai_calls（资源监控里统计百炼向量的 token 消耗）；接口没返回用量时按字数估算
    usage = (body.get("usage") or {}).get("total_tokens") or sum(len(t) for t in texts)
    resources.record_embedding(int(usage), latency_ms=int((time.monotonic() - t0) * 1000))
    return [_normalize(d["embedding"]) for d in data]


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def basis_text(item: Item) -> str:
    kind = KINDS.get(item.kind, ("",))[0]
    cat = f"{item.category.parent.name if item.category and item.category.parent else ''} {item.category.name if item.category else ''}"
    parts = [item.name, item.summary, kind, cat, " ".join(item.search_tags or []), item.description[:1200]]
    if item.repo:
        parts.insert(1, item.repo.full_name)
    return "\n".join(p for p in parts if p)


_index: dict[int, list[float]] = {}
_index_lock = threading.Lock()
_loaded = False


def _load_index() -> None:
    global _loaded
    with _index_lock:
        if _loaded:
            return
        with SessionLocal() as db:
            for e in db.scalars(select(ItemEmbedding).where(ItemEmbedding.model == settings.embedding_model)):
                _index[e.item_id] = e.vector
        _loaded = True


def embed_items(item_ids: list[int]) -> int:
    """给条目生成 / 更新向量（内容没变就跳过）。返回实际调用的条数。"""
    if not enabled() or not item_ids:
        return 0
    _load_index()
    done = 0
    with SessionLocal() as db:
        items = db.scalars(select(Item).where(Item.id.in_(item_ids))).all()
        todo = []
        for it in items:
            text = basis_text(it)
            h = hashlib.sha256(f"{settings.embedding_model}:{text}".encode()).hexdigest()
            e = db.get(ItemEmbedding, it.id)
            if e is None or e.basis_hash != h or e.model != settings.embedding_model:
                todo.append((it.id, text, h))
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            vecs = _embed([t for _, t, _ in part])
            for (iid, _, h), v in zip(part, vecs):
                db.merge(ItemEmbedding(item_id=iid, model=settings.embedding_model, dims=len(v), vector=v,
                                       basis_hash=h, updated_at=utcnow()))
                with _index_lock:
                    _index[iid] = v
            db.commit()
            done += len(part)
    return done


def forget(item_id: int) -> None:
    with _index_lock:
        _index.pop(item_id, None)


# ---------------------------------------------------------------- 存量补齐：搜索标签 + 向量（后台任务）

def start_backfill() -> int | None:
    """给还没有搜索标签 / 向量的条目补齐。启动时和管理员手动都可以触发。"""
    with SessionLocal() as db:
        rows = db.execute(select(Item.id, Item.name, Item.search_tags).where(Item.status.in_(SEARCHABLE + ("hidden",)))).all()
        have = set(db.scalars(select(ItemEmbedding.item_id).where(ItemEmbedding.model == settings.embedding_model)).all())
    todo = [(i, n) for i, n, tags in rows if not tags or i not in have]
    if not todo or not (enabled() or settings.ai_enabled):
        return None
    task_id = tracking.create_task("tags", f"语义搜索准备 · {len(todo)} 个条目（搜索标签 + 向量）", todo)
    ids = [i for i, _ in todo]

    def run():
        for k in range(0, len(ids), 12):
            chunk = ids[k:k + 12]
            for i in chunk:
                tracking._start_item(task_id, i)
            ok_msg = "已完成"
            try:
                with SessionLocal() as db:
                    need_tags = [it for it in db.scalars(select(Item).where(Item.id.in_(chunk))) if not it.search_tags]
                    if need_tags and settings.ai_enabled:
                        got = judge.tags_for_items([{"id": it.id, "name": it.name, "summary": it.summary,
                                                     "description": it.description[:600], "kind": it.kind,
                                                     "category": it.category.name if it.category else ""} for it in need_tags])
                        for it in need_tags:
                            if got.get(it.id):
                                it.search_tags = got[it.id]
                        db.commit()
                embed_items(chunk)
                ok = True
            except (judge.JudgeUnavailable, SearchUnavailable) as e:
                ok, ok_msg = False, str(e)
            for i in chunk:
                tracking._finish_item(task_id, i, ok, ok_msg)
        tracking.finish_task(task_id)

    threading.Thread(target=run, daemon=True, name="search-backfill").start()
    return task_id


# ---------------------------------------------------------------- 搜索

def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


VECTOR_TTL = timedelta(days=7)
MIN_SIM = 0.35


def _query_vector(q: str) -> list[float]:
    """问题直接向量化（同一问题缓存 7 天），不再先让 AI 改写，省掉一次大模型调用。"""
    key = cache.make_key("qvec", q)
    v = cache.get(key)
    if v is None:
        v = _embed([q])[0]
        cache.put(key, v, VECTOR_TTL)
    return v


def vector_search(q: str, allowed_ids: set[int], exact_ids: list[int]) -> list[dict]:
    """第一段（约 0.4 秒）：向量检索，按相似度排序。名称 / 仓库名精确命中的置顶。"""
    _load_index()
    qvec = _query_vector(q)
    with _index_lock:
        scored = sorted(((iid, _cos(qvec, v)) for iid, v in _index.items() if iid in allowed_ids), key=lambda x: -x[1])
    out = [{"id": i, "score": 95, "reason": ""} for i in exact_ids if i in allowed_ids]
    seen = {x["id"] for x in out}
    for i, sim in scored[:TOP_VECTOR]:
        if i not in seen and sim >= MIN_SIM:
            out.append({"id": i, "score": int(sim * 100), "reason": ""})
    return out


def refine(q: str, candidates: list[dict], exact_ids: list[int], cached_only: bool = False) -> dict | None:
    """第二段（后台，约 2~3 秒）：一次 AI 调用同时「理解需求 + 精排前 TOP_RERANK 个」，写推荐理由。

    返回 {understanding, ranked}；AI 不可用时 ranked 就是向量结果。cached_only=True 时只查缓存，没有就返回 None。
    """
    head = candidates[:TOP_RERANK]
    # 缓存键带上候选集合：同一个问题在不同筛选（类型 / 分类 / 只看收藏）下候选不同
    key = cache.make_key("semrefine", q + "|" + ",".join(str(x["id"]) for x in head))
    hit = cache.get(key)
    if hit is None and cached_only:
        return None
    if hit is None:
        if not settings.ai_enabled or not head:
            return {"understanding": "", "ranked": candidates}
        with SessionLocal() as db:
            items = {it.id: it for it in db.scalars(select(Item).where(Item.id.in_([x["id"] for x in head])))}
        brief = [{"id": x["id"], "name": items[x["id"]].name, "summary": (items[x["id"]].summary or "")[:80],
                  "kind": KINDS.get(items[x["id"]].kind, ("",))[0], "tags": (items[x["id"]].search_tags or [])[:8]}
                 for x in head if x["id"] in items]
        try:
            got = judge.refine_search(q, brief)
        except judge.JudgeUnavailable:
            return {"understanding": "", "ranked": candidates}
        hit = {"understanding": got["understanding"], "results": {str(k): v for k, v in got["results"].items()}}
        cache.put(key, hit, RESULT_TTL)

    scored, rest = [], []
    for x in candidates:
        r = hit["results"].get(str(x["id"]))
        if r is None:
            rest.append(x)  # 没经过精排（排在后面）：保留向量顺序，放在精排结果之后
        elif r["score"] >= MIN_SCORE or x["id"] in exact_ids:
            scored.append({"id": x["id"], "score": max(r["score"], 95 if x["id"] in exact_ids else 0), "reason": r["reason"]})
    scored.sort(key=lambda x: (-(x["id"] in exact_ids), -x["score"]))
    return {"understanding": hit["understanding"], "ranked": scored + rest}
