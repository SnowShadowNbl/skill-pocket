"""v3.3.68 后台批次 6d：风控概览与风控告警、验证码风控、定时任务控制。

风控口径（窗口默认 7 天，告警扫描看最近 24 小时）：
- 批量注册：同一网段（IPv4 前三段）注册的账号数 ≥ CLUSTER_MIN。注册 IP 取自注册时的操作日志。
- 验证码被刷：同一邮箱 / IP 被限频的次数，以及发送量最多的邮箱 / IP。
- 扫码滥用：扫码登录记录没有存 IP，给 null。
- 星标异常：沿用「疑似刷星」。
风控告警（source=risk）不会自动恢复，需要人工确认或关闭。
"""

import ipaddress
import time
from collections import Counter, defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..db import SessionLocal, get_db, utcnow
from ..models import ActivityLog, EmailCode, Item, Repo, User
from ..services import activity, admin_security, item_quality, ops, scheduler, users

router = APIRouter(prefix="/api/admin", tags=["admin-risk"], dependencies=[Depends(require_admin)])
CLUSTER_MIN = 5
CODE_HOT = 10
PAUSE_ALERT_HOURS = 24
_last_scan = 0.0


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < 2:
        _err(400, "reason_required", "请填写原因")
    return r


def _prefix(ip: str) -> str:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ip or "未知"
    if a.version == 4:
        return ".".join(ip.split(".")[:3]) + ".0/24"
    return str(ipaddress.ip_network(f"{ip}/48", strict=False))


def _clusters(db: Session, since) -> list[dict]:
    rows = db.execute(select(ActivityLog.ip, ActivityLog.user_id).where(ActivityLog.action == "register", ActivityLog.created_at >= since,
                                                                        ActivityLog.ip != "")).all()
    by: dict[str, set] = defaultdict(set)
    for ip, uid in rows:
        if uid:
            by[_prefix(ip)].add(uid)
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_({u for s in by.values() for u in s} or {-1})))}
    out = []
    for p, ids in sorted(by.items(), key=lambda x: -len(x[1])):
        if len(ids) >= CLUSTER_MIN:
            out.append({"ip_prefix": p, "count": len(ids), "users": [{"id": i, "label": users.label(who[i]) if i in who else f"用户 #{i}",
                                                                      "status": who[i].status if i in who else None} for i in sorted(ids)][:50]})
    return out


def _code_abuse(db: Session, since) -> dict:
    limited = Counter()
    for (k,) in db.execute(select(ActivityLog.target_label).where(ActivityLog.action == "code_limited", ActivityLog.created_at >= since)).all():
        limited[k] += 1
    by_email = Counter(e for (e,) in db.execute(select(EmailCode.email).where(EmailCode.created_at >= since)).all())
    by_ip = Counter(i for (i,) in db.execute(select(EmailCode.ip).where(EmailCode.created_at >= since)).all() if i)
    mask = lambda e: f"{e.split('@')[0][:2]}***@{e.split('@')[1]}" if "@" in e else e  # noqa: E731
    return {"limited": [{"key": mask(k.split(":", 1)[1]) if k.startswith("email:") else k.split(":", 1)[-1], "kind": k.split(":", 1)[0],
                         "count": n} for k, n in limited.most_common(20)],
            "top_emails": [{"key": mask(e), "kind": "email", "count": n} for e, n in by_email.most_common(10)],
            "top_ips": [{"key": i, "kind": "ip", "count": n} for i, n in by_ip.most_common(10)],
            "sent": sum(by_email.values()), "limited_total": sum(limited.values())}


def _stars(db: Session) -> list[dict]:
    ids = item_quality.spike_repo_ids(db)
    rows = db.execute(select(Item.id, Item.name, Repo.full_name, Repo.stars, Item.rank_excluded).join(Repo, Repo.id == Item.repo_id)
                      .where(Item.repo_id.in_(list(ids) or [-1]), Item.status == "published")).all()
    return [{"item": {"id": i, "name": n}, "repo": fn, "stars": st, "rank_excluded": bool(ex)} for i, n, fn, st, ex in rows]


def scan(force: bool = False) -> None:
    """最近 24 小时的风控条件写进告警表（最多 10 分钟一次）。"""
    global _last_scan
    if not force and time.time() - _last_scan < 600:
        return
    _last_scan = time.time()
    with SessionLocal() as db:
        since = utcnow() - timedelta(hours=24)
        for c in _clusters(db, since):
            ops.raise_alert(db, f"risk:register:{c['ip_prefix']}", "risk", "warn", f"同一网段 24 小时内注册了 {c['count']} 个账号",
                            f"网段 {c['ip_prefix']}：" + "、".join(u["label"] for u in c["users"][:10]))
        ca = _code_abuse(db, since)
        for x in ca["limited"]:
            if x["count"] >= 3:
                ops.raise_alert(db, f"risk:code:{x['kind']}:{x['key']}"[:64], "risk", "warn", f"验证码请求被频繁拦截（{x['key']}）",
                                f"24 小时内被限制 {x['count']} 次")
        for k, v in scheduler._paused().items():
            from datetime import datetime

            at = datetime.fromisoformat(v["at"])
            if utcnow() - at > timedelta(hours=PAUSE_ALERT_HOURS):
                ops.raise_alert(db, f"schedule:paused:{k}", "system", "warn", f"定时任务「{scheduler.JOBS.get(k, {}).get('name', k)}」已暂停超过 24 小时",
                                "请确认是否需要恢复")
        db.commit()


# ================================================================ 风控概览
@router.get("/risk/overview")
def overview(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    scan()
    since = utcnow() - timedelta(days=days)
    ca = _code_abuse(db, since)
    return {"days": days, "thresholds": {"register_cluster_min": CLUSTER_MIN, "code_hot": CODE_HOT},
            "register_clusters": _clusters(db, since), "code_abuse": ca["limited"] + [x for x in ca["top_emails"] + ca["top_ips"] if x["count"] >= CODE_HOT],
            "qr_abuse": None, "star_anomalies": _stars(db),
            "note": "扫码记录没有保存 IP，暂时无法统计扫码滥用"}


# ================================================================ 验证码风控
@router.get("/code-limits")
def code_limits(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    ca = _code_abuse(db, since)
    return {"days": days, "threshold": ops.code_limits(db), "labels": ops.CODE_LIMIT_KEYS, "ranges": ops.CODE_LIMIT_RANGE,
            "stats": {"sent": ca["sent"], "limited": ca["limited_total"]}, "limited": ca["limited"],
            "top_senders": ca["top_emails"] + ca["top_ips"]}


class LimitsIn(BaseModel):
    resend_seconds: int | None = None
    per_email_daily: int | None = None
    per_ip_daily: int | None = None
    per_account_hour: int | None = None
    reason: str = Field("", max_length=300)


@router.put("/code-limits/threshold")
def put_limits(body: LimitsIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    reason = _reason(body.reason)
    admin_security.check_token(me, "code_limit", admin_security.token_from(request))
    vals = {k: v for k, v in body.model_dump(exclude={"reason"}).items() if v is not None}
    bad = [k for k, v in vals.items() if not ops.CODE_LIMIT_RANGE[k][0] <= v <= ops.CODE_LIMIT_RANGE[k][1]]
    if bad:
        _err(400, "bad_range", "阈值超出允许范围", fields=bad, ranges={k: ops.CODE_LIMIT_RANGE[k] for k in bad})
    before = ops.code_limits(db)
    after = ops.set_code_limits(db, vals)
    diff = [k for k in after if before[k] != after[k]]
    activity.record("code_limit", "修改验证码频率阈值", user=me, target_type="maintenance", ip=client_ip(request), reason=reason,
                    before={k: before[k] for k in diff}, after={k: after[k] for k in diff}, target_label="code_limits")
    return {"threshold": after}


@router.get("/code-limits/user/{user_id}")
def user_codes(user_id: int, days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        _err(404, "not_found", "用户不存在")
    since = utcnow() - timedelta(days=days)
    sent = db.scalar(select(func.count()).select_from(EmailCode).where(EmailCode.email == u.email, EmailCode.created_at >= since)) if u.email else 0
    limited = db.scalar(select(func.count()).select_from(ActivityLog).where(
        ActivityLog.action == "code_limited", ActivityLog.created_at >= since,
        ActivityLog.target_label.in_([f"account:{u.id}"] + ([f"email:{u.email}"] if u.email else [])))) or 0
    return {"user": {"id": u.id, "label": users.label(u)}, "days": days, "sent": sent if u.email else None, "limited": limited}


# ================================================================ 定时任务
def _last_runs(db: Session) -> dict:
    import json

    from ..models import AppMeta, JobRun

    out = {}
    job = db.scalar(select(JobRun).order_by(JobRun.id.desc()).limit(1))
    if job:
        out["daily_crawl"] = {"at": job.started_at, "ok": job.status == "ok", "status": job.status,
                              "duration_ms": int((job.finished_at - job.started_at).total_seconds() * 1000) if job.finished_at else None,
                              "summary": (job.error or "")[:200] or None}
    m = db.get(AppMeta, "push_last_run")
    if m:
        r = json.loads(m.value)
        from datetime import datetime

        st = datetime.fromisoformat(r["started_at"]) if r.get("started_at") else None
        en = datetime.fromisoformat(r["at"])
        out["daily_notify"] = {"at": st or en, "ok": r["ok"], "status": "ok" if r["ok"] else "failed",
                               "duration_ms": int((en - st).total_seconds() * 1000) if st else None,
                               "summary": f"上新汇总 {r['digests']} 条、版本提醒 {r['releases']} 条" if r["ok"] else r.get("error")}
    return out


@router.get("/schedules")
def schedules(db: Session = Depends(get_db)):
    last = _last_runs(db)
    b = ops.backup_status()
    items = [{**j, "last_run": last.get(j["key"]), "controllable": True,
              "paused_by": {"id": j["paused_by"], "label": users.label(db.get(User, j["paused_by"]))} if j["paused_by"] and db.get(User, j["paused_by"]) else None}
             for j in scheduler.info()]
    items.append({"key": "db_backup", "name": "数据库备份", "cron": "每天 08:30（服务器任务）", "enabled": b["dir_visible"], "next_run_at": b["next_expected_at"],
                  "paused": False, "paused_at": None, "paused_by": None, "running": None, "controllable": False,
                  "last_run": {"at": b["last_at"], "ok": b["last_ok"], "status": b["status"], "duration_ms": None,
                               "summary": f"{b['last_size_bytes'] / 1024 / 1024:.1f} MB" if b["last_size_bytes"] else None} if b["last_at"] else None})
    return {"items": items}


class SchedIn(BaseModel):
    reason: str = Field("", max_length=300)


def _job(key: str):
    if key not in scheduler.JOBS:
        _err(404, "not_found", "没有这个定时任务（或不能在后台控制）")


@router.post("/schedules/{key}/run")
def run_schedule(key: str, body: SchedIn, request: Request, me: User = Depends(require_admin)):
    _job(key)
    reason = _reason(body.reason)
    r = scheduler.run_now(key)
    if r == "already_running":
        _err(409, "already_running", "正在执行中，请等这一轮结束")
    activity.record("schedule", f"手动执行定时任务「{scheduler.JOBS[key]['name']}」", user=me, target_type="maintenance", ip=client_ip(request),
                    reason=reason, target_label=f"schedule:{key}")
    return {"ok": True, "task_id": None, "status": r}


@router.post("/schedules/{key}/pause")
def pause_schedule(key: str, body: SchedIn, request: Request, me: User = Depends(require_admin)):
    _job(key)
    reason = _reason(body.reason)
    admin_security.check_token(me, "schedule", admin_security.token_from(request))
    scheduler.pause(key, me.id)
    activity.record("schedule", f"暂停定时任务「{scheduler.JOBS[key]['name']}」", user=me, target_type="maintenance", ip=client_ip(request),
                    reason=reason, before={"paused": False}, after={"paused": True}, target_label=f"schedule:{key}")
    return {"ok": True, "item": next(x for x in scheduler.info() if x["key"] == key)}


@router.post("/schedules/{key}/resume")
def resume_schedule(key: str, body: SchedIn, request: Request, me: User = Depends(require_admin)):
    _job(key)
    reason = _reason(body.reason)
    admin_security.check_token(me, "schedule", admin_security.token_from(request))
    scheduler.resume(key)
    activity.record("schedule", f"恢复定时任务「{scheduler.JOBS[key]['name']}」", user=me, target_type="maintenance", ip=client_ip(request),
                    reason=reason, before={"paused": True}, after={"paused": False}, target_label=f"schedule:{key}")
    return {"ok": True, "item": next(x for x in scheduler.info() if x["key"] == key)}
