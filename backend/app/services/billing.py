"""v2.6 AI 额度：按账号记录 AI 消耗的 token，额度用完要充值。

- 计费范围：由用户操作触发的 AI——AI 智能对比、搜索添加、长文识别、截图识别，以及用户新增条目时的提炼、翻译、封面。
  站内搜索、内容审核、昵称审核、反馈分析等平台自己的 AI 不计费。
- 用户侧额度 = 真实 token × RATE（默认 2 倍）。
- 每个账号第一次用到时发放免费额度（管理员可改默认值，系统给的标准值约够普通用户用 2~3 个月）。
- 余额 ≤ 0 时不能再发起新的 AI 操作；已经在跑的任务会跑完，余额可能变成负数，充值后补上。
- 管理员和子管理员照常记录用量，但不受余额限制。
- 记账方式：额度变动（发放 / 充值 / 调整 / 重置）每次一条 QuotaLedger；AI 消耗按天汇总在 QuotaDaily，
  同时记下当天结束时的余额，用来画剩余额度的历史。

谁的消耗：后台线程开始干活前用 charged_to(user_id) 标明，AI 调用记账时读这个标记（contextvar，跨不了线程，
所以每个后台线程 / 线程池任务都要在自己里面设置）。
"""

import contextvars
import logging
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..models import AiCall, AppMeta, QuotaDaily, QuotaLedger, User

log = logging.getLogger(__name__)
CN = ZoneInfo("Asia/Shanghai")
RATE = 2  # 用户侧额度 = 真实 token × 2
STANDARD_FREE = 2_000_000  # 系统标准免费额度（见 standard_free_explain）
META_DEFAULT = "quota_default_free"
STAFF = ("admin", "subadmin", "moderator", "support", "viewer")
# 平台自己的 AI，不计入用户额度
NOT_BILLED = {"AI-18", "AI-12", "AI-13", "AI-14", "AI-15", "AI-16", "AI-geo"}
KIND_LABEL = {"grant": "发放免费额度", "recharge": "充值", "adjust": "手动调整", "reset": "重置额度"}

_owner: contextvars.ContextVar[int | None] = contextvars.ContextVar("billing_owner", default=None)


def standard_free_explain() -> str:
    return ("按线上实测的单次用量估算（真实 token）：AI 对比约 7k、搜索添加约 11k、截图识别约 4k、长文识别约 4k、"
            "新增一个条目的提炼约 10k。普通用户一个月大约对比 8 次、搜索添加 10 次、截图 4 次、长文 2 次、新增 15 个条目，"
            "约 34 万 token，按 2 倍计约 68 万额度；200 万额度约够用 2.5~3 个月。")


# ---------------------------------------------------------------- 谁在消耗

@contextmanager
def charged_to(user_id: int | None):
    tok = _owner.set(user_id)
    try:
        yield
    finally:
        _owner.reset(tok)


def owner() -> int | None:
    return _owner.get()


def wrap(user_id: int | None, fn):
    """给后台任务里每个条目的处理函数包一层，让线程池里的 AI 调用也记到这个账号上。"""
    if not user_id:
        return fn

    def inner(*a, **kw):
        with charged_to(user_id):
            return fn(*a, **kw)

    return inner


# ---------------------------------------------------------------- 设置

def default_free(db: Session) -> int:
    row = db.get(AppMeta, META_DEFAULT)
    try:
        return max(0, int(row.value)) if row and row.value else STANDARD_FREE
    except ValueError:
        return STANDARD_FREE


def set_default_free(db: Session, value: int) -> None:
    row = db.get(AppMeta, META_DEFAULT) or AppMeta(key=META_DEFAULT)
    row.value = str(max(0, int(value)))
    db.merge(row)


def today_cn() -> date:
    return datetime.now(CN).date()


# ---------------------------------------------------------------- 余额与记账

def _daily(db: Session, user_id: int, day: date) -> QuotaDaily:
    row = db.scalar(select(QuotaDaily).where(QuotaDaily.user_id == user_id, QuotaDaily.day == day))
    if row is None:
        row = QuotaDaily(user_id=user_id, day=day, calls=0, tokens=0, used=0, balance_end=0)
        db.add(row)
        db.flush()
    return row


def _grant_once(db: Session, user_id: int) -> bool:
    """还没发放过免费额度的账号按默认值发放。用一条带条件的 UPDATE 抢占，几个线程同时第一次用 AI 也只发一次。"""
    amount = default_free(db)
    res = db.execute(update(User).where(User.id == user_id, User.quota_balance.is_(None)).values(quota_balance=amount)
                     .execution_options(synchronize_session=False))
    if res.rowcount != 1:
        return False
    db.add(QuotaLedger(user_id=user_id, kind="grant", delta=amount, balance_after=amount, note="注册赠送的免费额度"))
    _daily(db, user_id, today_cn()).balance_end = amount
    db.flush()
    return True


def ensure(db: Session, user: User) -> int:
    """返回余额；还没发放过免费额度的账号先按默认值发放。调用方负责 commit。"""
    if user.quota_balance is None:
        _grant_once(db, user.id)
        db.refresh(user)
    return user.quota_balance


def change(db: Session, user: User, kind: str, *, delta: int | None = None, set_to: int | None = None, note: str = "",
           amount_yuan: float | None = None, operator: User | None = None) -> QuotaLedger:
    """充值 / 调整 / 重置：delta 加减，或 set_to 直接设成某个值。调用方负责 commit。"""
    before = ensure(db, user)
    if set_to is not None:
        db.execute(update(User).where(User.id == user.id).values(quota_balance=set_to).execution_options(synchronize_session=False))
    else:  # 加减用原子更新，不会冲掉同时发生的 AI 扣减
        db.execute(update(User).where(User.id == user.id).values(quota_balance=User.quota_balance + int(delta or 0))
                   .execution_options(synchronize_session=False))
    db.refresh(user)
    after = user.quota_balance
    if set_to is None:
        before = after - int(delta or 0)
    row = QuotaLedger(user_id=user.id, kind=kind, delta=after - before, balance_after=after, note=note[:200],
                      amount_yuan=amount_yuan, operator_id=operator.id if operator else None)
    db.add(row)
    _daily(db, user.id, today_cn()).balance_end = after
    db.flush()
    return row


def consume(user_id: int, tokens: int, purpose: str) -> None:
    """一次 AI 调用结束后扣额度（真实 token × RATE），并累计到当天的用量里。
    全部用 SQL 原子加减：同一个账号的几个线程同时记账也不会丢；当天第一条记录并发插入冲突时重试。"""
    if not user_id or tokens <= 0 or purpose in NOT_BILLED:
        return
    used = tokens * RATE
    for attempt in range(4):
        try:
            with SessionLocal() as db:
                if db.get(User, user_id) is None:
                    return
                _grant_once(db, user_id)
                db.execute(update(User).where(User.id == user_id).values(quota_balance=User.quota_balance - used)
                           .execution_options(synchronize_session=False))
                bal = db.scalar(select(User.quota_balance).where(User.id == user_id))
                day = today_cn()
                res = db.execute(update(QuotaDaily).where(QuotaDaily.user_id == user_id, QuotaDaily.day == day)
                                 .values(calls=QuotaDaily.calls + 1, tokens=QuotaDaily.tokens + tokens, used=QuotaDaily.used + used,
                                         balance_end=bal).execution_options(synchronize_session=False))
                if res.rowcount == 0:
                    db.add(QuotaDaily(user_id=user_id, day=day, calls=1, tokens=tokens, used=used, balance_end=bal))
                db.commit()
                return
        except (IntegrityError, OperationalError):
            time.sleep(0.05 * (attempt + 1))  # 当天第一条并发插入 / SQLite 写锁：稍等重试
        except Exception:  # 记账失败不能影响 AI 结果本身
            log.exception("billing consume failed for user %s", user_id)
            return
    log.error("billing consume gave up for user %s (%s tokens)", user_id, tokens)


def check(db: Session, user: User) -> None:
    """发起 AI 操作前：余额用完了就拦下（管理员不限）。"""
    balance = ensure(db, user)
    db.commit()
    if user.role in STAFF:
        return
    if balance <= 0:
        raise HTTPException(402, "你的 AI 额度已经用完了。AI 对比、搜索添加、截图和长文识别都要消耗额度，请联系管理员充值后再用。")


# ---------------------------------------------------------------- 查询

def _int(v) -> int:
    return int(v or 0)


def user_summary(db: Session, user: User, days: int = 30) -> dict:
    """用户自己看：余额、今天和近 N 天用了多少、最近的充值 / 调整记录。"""
    balance = ensure(db, user)
    db.commit()
    today = today_cn()
    since = today - timedelta(days=days - 1)
    rows = db.scalars(select(QuotaDaily).where(QuotaDaily.user_id == user.id, QuotaDaily.day >= since).order_by(QuotaDaily.day)).all()
    by_day = {r.day: r for r in rows}
    series = [{"day": d.isoformat(), "used": _int(by_day[d].used) if d in by_day else 0}
              for d in (since + timedelta(days=i) for i in range(days))]
    ledger = db.scalars(select(QuotaLedger).where(QuotaLedger.user_id == user.id).order_by(QuotaLedger.id.desc()).limit(20)).all()
    granted = _int(db.scalar(select(func.sum(QuotaLedger.delta)).where(QuotaLedger.user_id == user.id, QuotaLedger.delta > 0)))
    return {
        "balance": balance, "rate": RATE, "unlimited": user.role in STAFF,
        "used_today": _int(by_day[today].used) if today in by_day else 0,
        "used_30d": sum(x["used"] for x in series), "granted_total": granted,
        "series": series, "ledger": [ledger_out(r) for r in ledger],
    }


def ledger_out(r: QuotaLedger, names: dict | None = None) -> dict:
    return {"id": r.id, "kind": r.kind, "kind_label": KIND_LABEL.get(r.kind, r.kind), "delta": r.delta, "balance_after": r.balance_after,
            "amount_yuan": r.amount_yuan, "note": r.note, "created_at": r.created_at,
            "operator": (names or {}).get(r.operator_id, "") if r.operator_id else ""}


def admin_detail(db: Session, user: User, days: int = 60) -> dict:
    """管理员看一个账号：每天用量（含按用途拆分）、每天结束时的剩余额度、全部额度变动记录。"""
    from .resources import PURPOSES

    base = user_summary(db, user, days=days)
    since = today_cn() - timedelta(days=days - 1)
    rows = db.scalars(select(QuotaDaily).where(QuotaDaily.user_id == user.id, QuotaDaily.day >= since).order_by(QuotaDaily.day.desc())).all()
    # 剩余额度的历史：没有变动的日子沿用前一天的余额
    all_rows = db.scalars(select(QuotaDaily).where(QuotaDaily.user_id == user.id).order_by(QuotaDaily.day)).all()
    hist, last, k = [], None, 0
    first = all_rows[0].day if all_rows else today_cn()
    start = max(first, since)
    while k < len(all_rows) and all_rows[k].day < start:
        last = all_rows[k].balance_end
        k += 1
    d = start
    while d <= today_cn():
        if k < len(all_rows) and all_rows[k].day == d:
            last = all_rows[k].balance_end
            k += 1
        if last is not None:
            hist.append({"day": d.isoformat(), "balance": _int(last)})
        d += timedelta(days=1)
    t0 = datetime.combine(since, datetime.min.time(), CN)
    purposes = db.execute(select(AiCall.purpose, func.count(), func.sum(func.coalesce(AiCall.tokens_in, 0) + func.coalesce(AiCall.tokens_out, 0)))
                          .where(AiCall.user_id == user.id, AiCall.ok.is_(True), AiCall.created_at >= t0).group_by(AiCall.purpose)).all()
    ops = {u.id: u.nickname for u in db.scalars(select(User).where(User.role.in_(STAFF)))}
    ledger = db.scalars(select(QuotaLedger).where(QuotaLedger.user_id == user.id).order_by(QuotaLedger.id.desc()).limit(200)).all()
    return {
        **base,
        "daily": [{"day": r.day.isoformat(), "calls": r.calls, "tokens": _int(r.tokens), "used": _int(r.used), "balance_end": _int(r.balance_end)}
                  for r in rows],
        "balance_history": hist,
        "by_purpose": sorted(({"purpose": p, "label": PURPOSES.get(p, p), "calls": c, "tokens": _int(t), "used": _int(t) * RATE,
                               "billed": p not in NOT_BILLED} for p, c, t in purposes), key=lambda x: -x["tokens"]),
        "ledger": [ledger_out(r, ops) for r in ledger],
        "recharged_yuan": round(sum(r.amount_yuan or 0 for r in ledger if r.kind == "recharge"), 2),
    }


def usage_board(db: Session, days: int = 14) -> dict:
    """管理员看全部账号：最近 N 天每个账号每天的用量（只列有用量的账号）。"""
    since = today_cn() - timedelta(days=days - 1)
    rows = db.execute(select(QuotaDaily.user_id, QuotaDaily.day, QuotaDaily.used).where(QuotaDaily.day >= since, QuotaDaily.used > 0)).all()
    per: dict[int, dict] = {}
    for uid, day, used in rows:
        per.setdefault(uid, {})[day.isoformat()] = _int(used)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(per))))} if per else {}
    out = []
    for uid, m in per.items():
        u = users.get(uid)
        if u is None:
            continue
        out.append({"id": uid, "nickname": u.nickname, "remark": u.remark, "email": u.email or u.username or "", "role": u.role,
                    "balance": _int(u.quota_balance), "total": sum(m.values()), "days": m})
    out.sort(key=lambda x: -x["total"])
    return {"days": [(since + timedelta(days=i)).isoformat() for i in range(days)], "users": out,
            "total": {d: sum(x["days"].get(d, 0) for x in out) for d in ((since + timedelta(days=i)).isoformat() for i in range(days))}}


def recharges(db: Session, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(QuotaLedger).where(QuotaLedger.kind.in_(("recharge", "adjust", "reset")))
                      .order_by(QuotaLedger.id.desc()).limit(limit)).all()
    ids = {r.user_id for r in rows} | {r.operator_id for r in rows if r.operator_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(ids))))} if ids else {}
    ops = {i: u.nickname for i, u in users.items()}
    out = []
    for r in rows:
        u = users.get(r.user_id)
        out.append({**ledger_out(r, ops), "user_id": r.user_id, "nickname": u.nickname if u else "（已删除）", "remark": u.remark if u else ""})
    return out
