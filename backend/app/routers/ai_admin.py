"""v3.3.59 后台批次 5a：AI 消耗与成本、额度账本、额度总览。

成本是估算：按 settings.ai_prices（JSON：{"模型名": [每百万输入 token 元, 每百万输出 token 元]}）计算；
没有单价的模型给 null（前端显示「未知」）。向量模型默认按 embedding_price_per_1k_tokens 估算。
实际充值金额（QuotaLedger.amount_yuan）和估算成本分开返回，不混算。
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..config import settings
from ..db import get_db, utcnow
from ..models import AiCall, QuotaDaily, QuotaLedger, User
from ..services import activity, billing, pricing, users
from ..services.resources import EMB, PURPOSES

router = APIRouter(prefix="/api/admin/ai", tags=["admin-ai"], dependencies=[Depends(require_admin)])
CN = ZoneInfo("Asia/Shanghai")
PURPOSE_LABELS = {**PURPOSES, EMB: "语义向量"}


def _cost(model: str, tin: int, tout: int, hit: int | None, at, stored_max, stored_actual, basis: str, table: dict) -> float | None:
    """v3.3.89 有调用当时的成本快照就用快照；老记录（没有快照）按现在的单价表算。"""
    stored = stored_max if basis == "max" else stored_actual
    if stored is not None:
        return stored
    c = pricing.cost(model, tin, tout, hit, at, table)
    return c[0] if basis == "max" else c[1]


def _acc() -> dict:
    return {"calls": 0, "ok": 0, "fail": 0, "tokens_in": 0, "tokens_out": 0, "lat": 0, "cost": 0.0, "cost_known": True}


def _add(a: dict, ok: bool, tin: int, tout: int, lat: int, cost: float | None) -> None:
    a["calls"] += 1
    a["ok" if ok else "fail"] += 1
    a["tokens_in"] += tin or 0
    a["tokens_out"] += tout or 0
    a["lat"] += lat or 0
    if cost is None:
        a["cost_known"] = False
    else:
        a["cost"] += cost


def _fin(a: dict) -> dict:
    return {"calls": a["calls"], "ok": a["ok"], "fail": a["fail"], "tokens_in": a["tokens_in"], "tokens_out": a["tokens_out"],
            "avg_latency_ms": int(a["lat"] / a["calls"]) if a["calls"] else None,
            "est_cost_yuan": round(a["cost"], 4) if a["cost_known"] and a["calls"] else (None if a["calls"] else 0.0)}


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), group: str = Query("purpose", pattern="^(purpose|model|user|day)$"),
          user_id: int | None = None, purpose: str = "", model: str = "", basis: str = Query("max", pattern="^(max|actual)$"),
          db: Session = Depends(get_db)):
    since = (datetime.now(CN) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(AiCall.purpose, AiCall.model, AiCall.user_id, AiCall.tokens_in, AiCall.tokens_out, AiCall.latency_ms, AiCall.ok,
                  AiCall.created_at, AiCall.cache_hit_tokens, AiCall.cost_max_yuan, AiCall.cost_actual_yuan).where(AiCall.created_at >= since)
    if user_id:
        stmt = stmt.where(AiCall.user_id == user_id)
    if purpose:
        stmt = stmt.where(AiCall.purpose == purpose)
    if model:
        stmt = stmt.where(AiCall.model == model)
    table = pricing.table()
    total, groups, series = _acc(), defaultdict(_acc), defaultdict(_acc)
    for p, m, uid, tin, tout, lat, ok, at, hit, c_max, c_act in db.execute(stmt).all():
        c = _cost(m, tin, tout, hit, at, c_max, c_act, basis, table)
        day = at.astimezone(CN).strftime("%Y-%m-%d")
        key = {"purpose": p, "model": m, "user": uid or 0, "day": day}[group]
        for a in (total, groups[key], series[day]):
            _add(a, ok, tin, tout, lat, c)
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_([k for k in groups if group == "user" and k] or [-1])))}

    def label(k):
        if group == "purpose":
            return PURPOSE_LABELS.get(k, k)
        if group == "user":
            return users.label(who[k]) if k in who else ("系统任务" if k == 0 else f"用户 #{k}")
        return k

    items = sorted(({"key": k, "label": label(k), **_fin(a)} for k, a in groups.items()), key=lambda x: -x["calls"])
    if group == "day":
        items.sort(key=lambda x: x["key"])
    dates = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return {"days": days, "group": group, "totals": _fin(total), "items": items,
            "series": [{"date": d, **{k: v for k, v in _fin(series[d]).items() if k in ("calls", "tokens_in", "tokens_out", "fail")}}
                       for d in dates],
            "priced_models": sorted(table["models"]), "purposes": PURPOSE_LABELS, "estimated": True, "basis": basis}


# ---------------------------------------------------------------- v3.3.89 单价表

class PriceTableIn(BaseModel):
    models: dict[str, dict[str, float]]
    peak: list[list[float]] = []
    peak_weekdays_only: bool = True


@router.get("/prices")
def get_prices():
    return {**pricing.table(), "defaults": pricing.defaults(), "fields": list(pricing.FIELDS)}


@router.put("/prices")
def put_prices(body: PriceTableIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    v = pricing.save(db, body.model_dump())
    db.commit()
    activity.record("ai_prices", f"AI 单价表：{'、'.join(v['models'])}", user=me, ip=client_ip(request))
    return get_prices()


@router.get("/ledger")
def ledger(kind: str = Query("", pattern="^(|grant|recharge|adjust|reset)$"), user_id: int | None = None, created_from: str = "",
           created_to: str = "", page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    from .admin import _parse_day

    stmt = select(QuotaLedger)
    if kind:
        stmt = stmt.where(QuotaLedger.kind == kind)
    if user_id:
        stmt = stmt.where(QuotaLedger.user_id == user_id)
    d = _parse_day(created_from)
    if d is not None:
        stmt = stmt.where(QuotaLedger.created_at >= d)
    d = _parse_day(created_to)
    if d is not None:
        stmt = stmt.where(QuotaLedger.created_at < d + timedelta(days=1))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    recharged = db.scalar(select(func.coalesce(func.sum(QuotaLedger.amount_yuan), 0)).where(QuotaLedger.kind == "recharge")) or 0
    rows = db.scalars(stmt.order_by(QuotaLedger.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    ids = {x for r in rows for x in (r.user_id, r.operator_id) if x}
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids or {-1})))}
    lab = lambda uid: {"id": uid, "label": users.label(who[uid])} if uid in who else None  # noqa: E731
    return {"total": total, "page": page, "page_size": page_size, "kinds": billing.KIND_LABEL,
            "recharged_yuan_total": round(float(recharged), 2),
            "items": [{"id": r.id, "user": lab(r.user_id), "kind": r.kind, "kind_label": billing.KIND_LABEL.get(r.kind, r.kind),
                       "delta": r.delta, "balance_after": r.balance_after, "amount_yuan": r.amount_yuan, "note": r.note,
                       "operator": lab(r.operator_id), "created_at": r.created_at} for r in rows]}


@router.get("/quota-overview")
def quota_overview(db: Session = Depends(get_db)):
    low = settings.quota_low_threshold
    rows = db.execute(select(User.id, User.quota_balance).where(User.quota_balance.is_not(None), User.role == "user",
                                                                  User.status == "active")).all()
    today = datetime.now(CN).date()
    since30 = today - timedelta(days=29)
    used = dict(db.execute(select(QuotaDaily.user_id, func.sum(QuotaDaily.used)).where(QuotaDaily.day >= since30)
                           .group_by(QuotaDaily.user_id).order_by(func.sum(QuotaDaily.used).desc()).limit(10)).all())
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(used) or [-1])))}
    start = datetime.combine(today, datetime.min.time(), tzinfo=CN)
    return {"low_threshold": low, "users_with_quota": len(rows), "total_balance": int(sum(b or 0 for _, b in rows)),
            "low_balance_users": sum(1 for _, b in rows if 0 < (b or 0) < low), "exhausted_users": sum(1 for _, b in rows if (b or 0) <= 0),
            "today_calls": db.scalar(select(func.count()).select_from(AiCall).where(AiCall.created_at >= start)) or 0,
            # v3.3.91 只有邮箱、还没领免费额度（要先绑定微信）的账号
            "needs_wechat_users": db.scalar(select(func.count()).select_from(User).where(
                User.role == "user", User.status == "active", User.quota_balance.is_(None), User.wx_openid.is_(None))) or 0,
            "top_users": [{"user": {"id": k, "label": users.label(who[k])} if k in who else {"id": k, "label": f"用户 #{k}"},
                           "used_30d": int(v or 0), "balance": who[k].quota_balance if k in who else None}
                          for k, v in sorted(used.items(), key=lambda x: -(x[1] or 0))]}
