"""v3.3.44 站内搜索词：服务端按实际结果数汇总（次数、无结果次数），以及首页「大家在搜」的候选计算与屏蔽。"""

import logging
import time
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..models import Event, SearchTerm
from .moderation import _RISK

log = logging.getLogger(__name__)

HOT_DAYS = 14
HOT_MIN_PEOPLE = 2
HOT_SHOWN = 8
_hot_cache: tuple[float, list] = (0.0, [])


def _key(q: str) -> str:
    return " ".join((q or "").split()).lower()[:100]


def get_or_create(db: Session, q: str) -> SearchTerm | None:
    k = _key(q)
    if not k:
        return None
    t = db.scalar(select(SearchTerm).where(SearchTerm.term == k))
    if t is None:
        t = SearchTerm(term=k, shown=" ".join(q.split())[:100], searches=0, empty_count=0)
        db.add(t)
        db.flush()
    return t


def record(q: str, results: int) -> None:
    """记一次站内搜索（第一页 / 第一段的结果数）。失败不影响搜索本身。"""
    k = _key(q)
    if not k or len(k) > 100:
        return
    try:
        with SessionLocal() as db:
            t = get_or_create(db, q)
            t.searches = (t.searches or 0) + 1
            if results == 0:
                t.empty_count = (t.empty_count or 0) + 1
            t.last_results, t.last_at, t.shown = results, utcnow(), " ".join(q.split())[:100]
            db.commit()
    except Exception:  # noqa: BLE001  并发首次插入同一个词时可能撞唯一约束，丢一次计数无妨
        log.debug("search term record failed", exc_info=True)


def invalidate_hot() -> None:
    global _hot_cache
    _hot_cache = (0.0, [])


def hot_candidates(db: Session, limit: int = 50) -> list[dict]:
    """最近 HOT_DAYS 天站内搜索词按搜索人数排序；标出展示中 / 被过滤及原因。"""
    since = utcnow() - timedelta(days=HOT_DAYS)
    who: dict[str, set] = defaultdict(set)
    shown: dict[str, str] = {}
    rows = db.execute(select(Event.vid, Event.props).where(Event.name == "search", Event.created_at >= since)
                      .order_by(Event.id.desc()).limit(20000)).all()
    for vid, props in rows:
        p = props or {}
        if p.get("scope") == "github":
            continue
        q = str(p.get("q") or "").strip()
        if not q:
            continue
        k = q.lower()
        who[k].add(vid)
        shown.setdefault(k, q)
    blocked = {t.term: t for t in db.scalars(select(SearchTerm).where(SearchTerm.blocked.is_(True)))}
    ids = {t.term: t.id for t in db.scalars(select(SearchTerm).where(SearchTerm.term.in_(list(who)[:5000])))} if who else {}
    out, n_shown = [], 0
    for people, k in sorted(((len(v), k) for k, v in who.items()), reverse=True):
        q = shown[k]
        reason = ""
        if k in blocked:
            reason = "blocked"
        elif not (2 <= len(q) <= 24):
            reason = "length"
        elif _RISK.search(q):
            reason = "risk"
        elif people < HOT_MIN_PEOPLE:
            reason = "few_people"
        elif n_shown >= HOT_SHOWN:
            reason = "rank"
        if not reason:
            n_shown += 1
        out.append({"term": q, "key": k, "term_id": ids.get(k), "people": people, "status": "filtered" if reason else "shown",
                    "reason": reason, "reason_label": REASONS.get(reason, ""),
                    "block_reason": blocked[k].block_reason if k in blocked else ""})
        if len(out) >= limit:
            break
    return out


REASONS = {"blocked": "已屏蔽", "length": "长度不合适（2–24 字）", "risk": "命中敏感 / 广告词", "few_people": f"搜索人数少于 {HOT_MIN_PEOPLE}",
           "rank": f"排在前 {HOT_SHOWN} 之后"}


def hot_public(db: Session) -> list[dict]:
    """首页「大家在搜」：展示中的前 HOT_SHOWN 个，缓存 10 分钟。"""
    global _hot_cache
    if time.time() - _hot_cache[0] < 600:
        return _hot_cache[1]
    out = [{"q": x["term"], "count": x["people"]} for x in hot_candidates(db, limit=500) if x["status"] == "shown"][:HOT_SHOWN]
    _hot_cache = (time.time(), out)
    return out
