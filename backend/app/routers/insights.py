"""v3.3.70 后台批次 7a：数据分析（D01–D06）。

口径：
- 游客按设备（vid）计，只能当「设备数」，不当真实人数；登录用户按账号计，已合并账号算在保留下来的账号上（合并时行为记录已迁移）。
- 观察期未满的留存给 null，并标 pending=true（前端显示「待观察」）。
- 没有可靠数据给 null，不给 0。
- channel 按事件发生的端拆分（web-pc / web-mobile / miniprogram）；AI 调用没有记录端，不能按端拆。
- 每个指标带 drill（可点进的后台页面和筛选参数，D05）；表格可加 ?format=csv 导出当前筛选结果（D06）。
"""

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..db import get_db
from ..models import (AiCall, Category, CompareRun, Event, Favorite, FinderJob, Item, SearchTerm, Upload, User)
from ..services import activity
from ..services.client import CHANNELS
from ..services.resources import EMB, PURPOSES

router = APIRouter(prefix="/api/admin/insights", tags=["admin-insights"], dependencies=[Depends(require_admin)])
CN = ZoneInfo("Asia/Shanghai")
ITEM_PAGE = re.compile(r"^/items/(\d+)")
EVENT_LIMIT = 200_000


def _since(days: int) -> datetime:
    return (datetime.now(CN) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _day(at) -> str:
    return at.astimezone(CN).strftime("%Y-%m-%d")


def _dates(since: datetime, days: int) -> list[str]:
    return [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]


def _events(db: Session, since, names: tuple[str, ...], channel: str):
    stmt = select(Event.name, Event.vid, Event.user_id, Event.props, Event.page, Event.client, Event.created_at).where(
        Event.created_at >= since, Event.name.in_(names))
    if channel:
        stmt = stmt.where(Event.client == ("" if channel == "unknown" else channel))
    return db.execute(stmt.order_by(Event.id).limit(EVENT_LIMIT)).all()


def _csv(name: str, header: list[str], rows: list[list], request: Request, me) -> Response:
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    activity.record("insights_export", f"导出分析数据：{name}（{len(rows)} 行）", user=me, ip=client_ip(request))
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''insights-{name}.csv", "X-Export-Count": str(len(rows))})


# ================================================================ D01 增长与活跃
@router.get("/growth")
def growth(days: int = Query(30, ge=7, le=180), channel: str = Query("", pattern="^(|web-pc|web-mobile|miniprogram|unknown)$"),
           db: Session = Depends(get_db)):
    since = _since(days)
    dates = _dates(since, days)
    # 新增账号（按注册渠道；历史账号没记渠道的算「未知」）
    ustmt = select(User.id, User.created_at, User.signup_channel).where(User.created_at >= since, User.role == "user",
                                                                         User.status.not_in(("merged",)))
    new = Counter()
    for _, at, ch in db.execute(ustmt).all():
        if channel and (ch or "unknown") != channel:
            continue
        new[_day(at)] += 1
    # 活跃：有任意行为事件
    act_users, act_devices = defaultdict(set), defaultdict(set)
    for _, vid, uid, _, _, _, at in _events(db, since, ("page_view", "item_view", "search", "favorite", "compare_add", "copy_prompt",
                                                         "outbound", "share", "login"), channel):
        d = _day(at)
        act_devices[d].add(vid)
        if uid:
            act_users[d].add(uid)
    # 回访：当天活跃的登录用户里，注册超过 7 天的
    created = dict(db.execute(select(User.id, User.created_at).where(User.id.in_({u for s in act_users.values() for u in s} or {-1}))).all())
    returning = {d: sum(1 for u in s if u in created and (datetime.fromisoformat(d).replace(tzinfo=CN) - created[u]).days > 7)
                 for d, s in act_users.items()}
    # 留存：窗口内注册的人，第 1 天 / 第 2–7 天是否回来（观察期未满给 null）
    cohort = db.execute(select(User.id, User.created_at).where(User.created_at >= since, User.role == "user")).all()
    seen_days: dict[int, set] = defaultdict(set)
    for d, s in act_users.items():
        for u in s:
            seen_days[u].add(d)
    today = datetime.now(CN).date()
    start = {u: at.astimezone(CN).date() for u, at in cohort}
    d1 = [u for u, d in start.items() if (today - d).days >= 2]  # 第 1 天已经完整过去
    d7 = [u for u, d in start.items() if (today - d).days >= 8]

    def came_back(u, lo, hi):
        return any(lo <= (datetime.fromisoformat(x).date() - start[u]).days <= hi for x in seen_days.get(u, ()))

    r1 = round(sum(1 for u in d1 if came_back(u, 1, 1)) / len(d1), 3) if d1 else None
    r7 = round(sum(1 for u in d7 if came_back(u, 1, 7)) / len(d7), 3) if d7 else None
    totals = {"new_users": sum(new.values()), "active_users": len(set().union(*act_users.values())) if act_users else 0,
              "active_devices": len(set().union(*act_devices.values())) if act_devices else 0,
              "retention_d1": r1, "retention_d1_pending": r1 is None, "retention_d7": r7, "retention_d7_pending": r7 is None,
              "cohort_d1": len(d1), "cohort_d7": len(d7)}
    by_channel = []
    if not channel:
        for ch in ("web-pc", "web-mobile", "miniprogram"):
            n = db.scalar(select(func.count()).select_from(User).where(User.created_at >= since, User.signup_channel == ch, User.role == "user")) or 0
            a = db.scalar(select(func.count(func.distinct(Event.user_id))).where(Event.created_at >= since, Event.client == ch,
                                                                                   Event.user_id.is_not(None))) or 0
            dv = db.scalar(select(func.count(func.distinct(Event.vid))).where(Event.created_at >= since, Event.client == ch)) or 0
            by_channel.append({"channel": ch, "label": CHANNELS[ch], "new_users": n, "active_users": a, "active_devices": dv,
                               "drill": {"module": "users", "query": {"channel": ch}}})
    return {"days": days, "channel": channel or None, "totals": totals, "by_channel": by_channel,
            "series": [{"date": d, "new_users": new.get(d, 0), "active_users": len(act_users.get(d, ())), "active_devices": len(act_devices.get(d, ())),
                        "returning_users": returning.get(d, 0)} for d in dates],
            "drill": {"new_users": {"module": "users", "query": {"channel": channel} if channel else {}},
                      "active_devices": {"module": "visitors", "query": {}}},
            "notes": ["游客按设备计，同一个人换设备会算多次", "回访：当天活跃、注册超过 7 天的登录用户", "留存观察期未满时显示「待观察」"]}


# ================================================================ D02 内容表现
CONTENT_SORTS = ("views", "favorites", "copies", "compares", "outbound", "shares")


@router.get("/content")
def content(request: Request, days: int = Query(30, ge=1, le=180), channel: str = Query("", pattern="^(|web-pc|web-mobile|miniprogram|unknown)$"),
            sort: str = Query("views", pattern="^(views|favorites|copies|compares|outbound|shares)$"), category: str = "",
            limit: int = Query(50, ge=1, le=500), format: str = Query("", pattern="^(|csv)$"), db: Session = Depends(get_db),
            me: User = Depends(require_admin)):
    since = _since(days)
    stat: dict[int, Counter] = defaultdict(Counter)
    viewers: dict[int, set] = defaultdict(set)
    for name, vid, _, props, page, _, _ in _events(db, since, ("item_view", "favorite", "copy_prompt", "outbound", "share", "compare_add"), channel):
        p = props or {}
        iid = p.get("item_id")
        if iid is None:
            m = ITEM_PAGE.match(page or "")
            iid = int(m.group(1)) if m else None
        if not isinstance(iid, int):
            try:
                iid = int(iid)
            except (TypeError, ValueError):
                continue
        key = {"item_view": "views", "favorite": "favorites", "copy_prompt": "copies", "outbound": "outbound", "share": "shares",
               "compare_add": "compares"}[name]
        stat[iid][key] += 1
        if name == "item_view":
            viewers[iid].add(vid)
    # 对比：以实际发起的对比为准（compare_add 只在详情页时能定位条目）
    for (entries,) in db.execute(select(CompareRun.entries).where(CompareRun.created_at >= since)).all():
        for e in entries or []:
            if e.get("item_id"):
                stat[int(e["item_id"])]["compares"] += 1
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(list(stat) or [-1])))}
    cat_ids = None
    if category:
        c = db.scalar(select(Category).where(Category.code == category))
        cat_ids = {c.id, *[x.id for x in c.children]} if c else set()
    rows = []
    for iid, c in stat.items():
        it = items.get(iid)
        if it is None or (cat_ids is not None and it.category_id not in cat_ids):
            continue
        rows.append({"item": {"id": iid, "name": it.name, "status": it.status}, "views": c["views"], "viewers": len(viewers[iid]),
                     "favorites": c["favorites"], "copies": c["copies"], "compares": c["compares"], "outbound": c["outbound"], "shares": c["shares"],
                     "favorite_rate": round(c["favorites"] / len(viewers[iid]), 3) if viewers[iid] else None,
                     "drill": {"module": "content", "query": {"id": iid}}})
    rows.sort(key=lambda r: -r[sort])
    rows = rows[:limit]
    if format == "csv":
        return _csv("content", ["条目编号", "名称", "浏览", "浏览设备", "收藏", "复制指令", "对比", "去原站", "分享", "收藏率"],
                    [[r["item"]["id"], r["item"]["name"], r["views"], r["viewers"], r["favorites"], r["copies"], r["compares"], r["outbound"], r["shares"],
                      r["favorite_rate"] if r["favorite_rate"] is not None else ""] for r in rows], request, me)
    published = db.scalar(select(func.count()).select_from(Item).where(Item.status == "published")) or 0
    viewed = sum(1 for i, c in stat.items() if c["views"] and items.get(i) is not None)
    return {"days": days, "channel": channel or None, "sort": sort,
            "totals": {k: sum(c[k] for c in stat.values()) for k in CONTENT_SORTS} | {
                "published_items": published, "viewed_items": viewed, "never_viewed_items": max(published - viewed, 0),
                "new_favorites": db.scalar(select(func.count()).select_from(Favorite).where(Favorite.created_at >= since)) or 0},
            "items": rows, "notes": ["对比按实际发起的 AI 对比计", "复制指令按详情页里的复制计"]}


# ================================================================ D03 搜索质量
@router.get("/search")
def search_quality(request: Request, days: int = Query(30, ge=1, le=180), channel: str = Query("", pattern="^(|web-pc|web-mobile|miniprogram|unknown)$"),
                   limit: int = Query(50, ge=1, le=500), format: str = Query("", pattern="^(|csv)$"), db: Session = Depends(get_db),
                   me: User = Depends(require_admin)):
    since = _since(days)
    evs = _events(db, since, ("search", "item_view", "favorite", "compare_add"), channel)
    by_vid: dict[str, list] = defaultdict(list)
    for name, vid, _, props, _, _, at in evs:
        by_vid[vid].append((at, name, props or {}))
    q_stat: dict[str, Counter] = defaultdict(Counter)
    shown: dict[str, str] = {}
    series = Counter()
    for vid, lst in by_vid.items():
        for i, (at, name, p) in enumerate(lst):
            if name != "search" or p.get("scope") == "github":
                continue
            q = str(p.get("q") or "").strip()
            if not q:
                continue
            k = q.lower()
            shown.setdefault(k, q)
            q_stat[k]["searches"] += 1
            series[_day(at)] += 1
            follow = [n for t, n, _ in lst[i + 1:] if (t - at) <= timedelta(minutes=10) and n != "search"]
            if "item_view" in follow:
                q_stat[k]["clicked"] += 1
            if "favorite" in follow or "compare_add" in follow:
                q_stat[k]["acted"] += 1
    terms = {t.term: t for t in db.scalars(select(SearchTerm).where(SearchTerm.term.in_(list(q_stat) or [""])))}
    rows = []
    for k, c in sorted(q_stat.items(), key=lambda x: -x[1]["searches"])[:limit]:
        t = terms.get(k)
        rows.append({"term": shown[k], "searches": c["searches"], "click_rate": round(c["clicked"] / c["searches"], 3),
                     "action_rate": round(c["acted"] / c["searches"], 3), "last_results": t.last_results if t else None,
                     "empty_count": t.empty_count if t else None, "blocked": bool(t and t.blocked),
                     "drill": {"module": "search-terms", "query": {"tab": "empty"} if t and t.empty_count else {}}})
    if format == "csv":
        return _csv("search", ["搜索词", "搜索次数", "点击率", "后续收藏或对比率", "最近结果数", "无结果次数"],
                    [[r["term"], r["searches"], r["click_rate"], r["action_rate"], r["last_results"] if r["last_results"] is not None else "",
                      r["empty_count"] if r["empty_count"] is not None else ""] for r in rows], request, me)
    total = sum(c["searches"] for c in q_stat.values())
    clicked = sum(c["clicked"] for c in q_stat.values())
    empty = db.execute(select(SearchTerm).where(SearchTerm.empty_count > 0, SearchTerm.last_at >= since, SearchTerm.covered_at.is_(None))
                       .order_by(SearchTerm.empty_count.desc()).limit(20)).scalars().all()
    since_dates = _dates(since, days)
    return {"days": days, "channel": channel or None,
            "totals": {"searches": total, "distinct_terms": len(q_stat), "click_rate": round(clicked / total, 3) if total else None,
                       "empty_terms": db.scalar(select(func.count()).select_from(SearchTerm).where(SearchTerm.empty_count > 0, SearchTerm.last_at >= since)) or 0},
            "terms": rows, "empty": [{"id": t.id, "term": t.shown or t.term, "empty_count": t.empty_count, "last_at": t.last_at} for t in empty],
            "series": [{"date": d, "searches": series.get(d, 0)} for d in since_dates],
            "drill": {"empty": {"module": "search-terms", "query": {"tab": "empty"}}},
            "notes": ["点击率：搜索后 10 分钟内打开了条目详情", "后续操作：搜索后 10 分钟内收藏或加入对比", "无结果清单从 v3.3.44 起统计"]}


# ================================================================ D04 AI 功能效果
@router.get("/ai")
def ai_effect(days: int = Query(30, ge=1, le=180), db: Session = Depends(get_db)):
    since = _since(days)
    rows = db.execute(select(AiCall.purpose, AiCall.user_id, AiCall.ok, AiCall.latency_ms, AiCall.tokens_in, AiCall.tokens_out)
                      .where(AiCall.created_at >= since)).all()
    agg: dict[str, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "users": set(), "lat": 0, "tokens": 0})
    for p, uid, ok, lat, ti, to in rows:
        a = agg[p]
        a["calls"] += 1
        a["ok"] += 1 if ok else 0
        a["lat"] += lat or 0
        a["tokens"] += (ti or 0) + (to or 0)
        if uid:
            a["users"].add(uid)
    features = [{"purpose": p, "label": {**PURPOSES, EMB: "语义向量"}.get(p, p), "calls": a["calls"], "users": len(a["users"]),
                 "success_rate": round(a["ok"] / a["calls"], 3) if a["calls"] else None, "avg_latency_ms": int(a["lat"] / a["calls"]) if a["calls"] else None,
                 "tokens": a["tokens"], "drill": {"module": "quota", "query": {"tab": "usage", "purpose": p}}}
                for p, a in sorted(agg.items(), key=lambda x: -x[1]["calls"])]

    def done_rate(rows, ok_states, bad_states):
        ok = sum(1 for (s,) in rows if s in ok_states)
        bad = sum(1 for (s,) in rows if s in bad_states)
        return {"total": len(rows), "done": ok, "failed": bad, "completion_rate": round(ok / (ok + bad), 3) if ok + bad else None}

    compare = db.execute(select(CompareRun.status, CompareRun.created_at, CompareRun.finished_at, CompareRun.user_id).where(CompareRun.created_at >= since)).all()
    durs = [(f - c).total_seconds() for _, c, f, _ in compare if f]
    tasks = {
        "compare": {"label": "AI 智能对比", **done_rate([(s,) for s, *_ in compare], ("done",), ("failed",)),
                    "users": len({u for *_, u in compare if u}), "avg_duration_s": int(sum(durs) / len(durs)) if durs else None,
                    "drill": {"module": "ingest-tasks", "query": {}}},
        "finder": {"label": "搜索添加 / 长文识别", **done_rate(db.execute(select(FinderJob.status).where(FinderJob.created_at >= since)).all(),
                                                        ("done", "imported"), ("failed",)),
                   "users": db.scalar(select(func.count(func.distinct(FinderJob.user_id))).where(FinderJob.created_at >= since)) or 0,
                   "avg_duration_s": None, "drill": {"module": "ingest-tasks", "query": {"kind": "finder"}}},
        "screenshot": {"label": "截图识别", **done_rate(db.execute(select(Upload.status).where(Upload.created_at >= since)).all(),
                                                     ("recognized", "imported"), ("failed",)),
                       "users": db.scalar(select(func.count(func.distinct(Upload.user_id))).where(Upload.created_at >= since)) or 0,
                       "avg_duration_s": None, "drill": {"module": "ingest-tasks", "query": {"kind": "screenshot"}}},
    }
    return {"days": days, "channel": None, "features": features, "tasks": tasks,
            "notes": ["AI 调用没有记录发生在哪一端，不能按端拆分", "查找和截图识别没有记录结束时间，耗时未知", "系统任务（采集、补封面）没有对应用户，不计人数"]}
