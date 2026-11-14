"""v3.3.64 后台批次 6a：运行监控——服务状态、告警历史、备份状态、小程序配置（只读）、存储与清理。

没有可靠数据的一律给 unknown / null，不给 ok / 0。
"""

import shutil
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..config import settings
from ..db import engine, get_db, utcnow
from ..models import (ActivityLog, AiCall, Alert, AppMeta, EmailLog, Event, IngestLog, JobRun, LivenessRun, Upload, UploadItem,
                      User, Visitor)
from ..services import activity, admin_security, ops, users

router = APIRouter(prefix="/api/admin", tags=["admin-ops"], dependencies=[Depends(require_admin)])
JOB_LABEL = {"ok": "成功", "done": "成功", "failed": "失败", "running": "进行中", "partial": "部分完成", "interrupted": "中断"}
ALERT_STATUS = {"open": "未处理", "acked": "已确认", "resolved": "已恢复"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < 2:
        _err(400, "reason_required", "请填写原因")
    return r


def _who(db: Session, uid):
    if not uid:
        return None
    u = db.get(User, uid)
    return {"id": uid, "label": users.label(u) if u else f"用户 #{uid}"}


# ================================================================ 服务状态
def _svc(key, name, status, summary, checked_at=None, detail=None):
    return {"key": key, "name": name, "status": status, "summary": summary, "checked_at": checked_at, "detail": detail or {}}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    import json

    from ..services import anim, mailer, wechat

    now = utcnow()
    day = now - timedelta(hours=24)
    out = []
    # 数据库
    t0 = time.time()
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        out.append(_svc("db", "数据库", "ok", f"响应 {int((time.time() - t0) * 1000)} ms", now))
    except Exception as e:  # noqa: BLE001
        out.append(_svc("db", "数据库", "down", str(e)[:200], now))
    # 磁盘
    try:
        du = shutil.disk_usage(settings.media_dir if settings.media_dir.exists() else "/")
        pct = du.used / du.total * 100
        out.append(_svc("disk", "磁盘", "down" if pct >= 95 else "warn" if pct >= 80 else "ok", f"已用 {pct:.0f}%，剩余 {du.free / 1024 ** 3:.1f} GB", now,
                        {"used_pct": round(pct, 1), "free_bytes": du.free}))
    except OSError:
        out.append(_svc("disk", "磁盘", "unknown", "读不到磁盘信息", now))
    # 邮件
    sent = db.scalar(select(func.count()).select_from(EmailLog).where(EmailLog.created_at >= day, EmailLog.ok.is_(True))) or 0
    failed = db.scalar(select(func.count()).select_from(EmailLog).where(EmailLog.created_at >= day, EmailLog.ok.is_(False))) or 0
    last_mail = db.scalar(select(EmailLog.created_at).order_by(EmailLog.id.desc()).limit(1))
    if not settings.ses_enabled:
        out.append(_svc("mail", "邮件", "unknown", "没有配置邮件服务", last_mail))
    else:
        st = "warn" if failed and failed >= sent else "ok" if (sent or not failed) else "warn"
        out.append(_svc("mail", "邮件", st, f"24 小时内发送 {sent} 封、失败 {failed} 封" + ("" if mailer.email_login_ready() else "，验证码模板未就绪"),
                        last_mail, {"sent_24h": sent, "failed_24h": failed}))
    # 采集
    job = db.scalar(select(JobRun).order_by(JobRun.id.desc()).limit(1))
    if job is None:
        out.append(_svc("crawl", "每日采集", "unknown", "还没有采集记录"))
    else:
        stale = now - job.started_at > timedelta(hours=30)
        st = "down" if job.status == "failed" else "warn" if (stale or job.status not in ("ok", "running")) else "ok"
        out.append(_svc("crawl", "每日采集", st, f"最近一次：{JOB_LABEL.get(job.status, job.status)}" + ("（超过 30 小时没有新的采集）" if stale else ""), job.finished_at or job.started_at,
                        {"status": job.status, "error": (job.error or "")[:200]}))
    # AI
    if not settings.ai_enabled:
        out.append(_svc("ai", "AI 接口", "unknown", "没有配置 AI 接口"))
    else:
        rows = db.execute(select(AiCall.ok, AiCall.created_at).where(AiCall.created_at >= now - timedelta(hours=1), AiCall.purpose != "EMB")).all()
        last = db.scalar(select(AiCall.created_at).where(AiCall.purpose != "EMB").order_by(AiCall.id.desc()).limit(1))
        if not rows:
            out.append(_svc("ai", "AI 接口", "unknown", "最近 1 小时没有调用", last))
        else:
            fail = sum(1 for ok, _ in rows if not ok)
            rate = fail / len(rows)
            out.append(_svc("ai", "AI 接口", "down" if rate >= 0.5 else "warn" if rate >= 0.1 else "ok",
                            f"最近 1 小时 {len(rows)} 次调用，失败 {fail} 次", last, {"calls_1h": len(rows), "failed_1h": fail}))
    # 微信
    if not wechat.ready():
        out.append(_svc("wechat", "微信接口", "unknown", "没有配置小程序 AppID / Secret"))
    else:
        ok = bool(wechat._access[0]) and time.time() < wechat._access[1]
        out.append(_svc("wechat", "微信接口", "ok" if ok else "unknown", "调用凭证有效" if ok else "这个进程还没取过调用凭证（有人扫码登录后会更新）"))
    # 推送
    m = db.get(AppMeta, "push_last_run")
    if m is None:
        out.append(_svc("push", "每日上新推送", "unknown", "还没有执行记录"))
    else:
        r = json.loads(m.value)
        from datetime import datetime

        at = datetime.fromisoformat(r["at"])
        out.append(_svc("push", "每日上新推送", "ok" if r["ok"] else "down",
                        f"上新汇总 {r['digests']} 条、版本提醒 {r['releases']} 条" if r["ok"] else f"失败：{r.get('error', '')}", at, r))
    # 失效巡检
    lv = db.scalar(select(LivenessRun).order_by(LivenessRun.id.desc()).limit(1))
    out.append(_svc("liveness", "失效巡检", "unknown", "还没有巡检记录") if lv is None else
               _svc("liveness", "失效巡检", "down" if lv.status == "failed" else "ok" if lv.status in ("ok", "done", "running") else "warn",
                    f"最近一次：{JOB_LABEL.get(lv.status, lv.status)}", lv.finished_at or lv.started_at))
    # 封面队列
    w = anim._worker
    q = anim.pending()
    out.append(_svc("cover_queue", "封面缩略图 / 动图队列", "ok" if (q == 0 or (w and w.is_alive())) else "warn",
                    f"队列 {q} 张" + ("，处理线程在运行" if w and w.is_alive() else "，处理线程未运行" if q else ""), now,
                    {"queue_length": q, "worker_alive": bool(w and w.is_alive())}))
    # 备份
    b = ops.backup_status()
    out.append(_svc("backup", "数据库备份", b["status"], "看不到备份目录" if not b["dir_visible"] else
                    (f"最近一次 {b['last_size_bytes'] / 1024 / 1024:.1f} MB" if b["last_at"] else "还没有备份"), b["last_at"]))
    ops.sync()
    return {"services": out, "checked_at": now}


# ================================================================ 告警
def _alert_out(db: Session, a: Alert) -> dict:
    return {"id": a.id, "key": a.key, "source": a.source, "level": a.level, "title": a.title, "detail": a.detail, "count": a.count,
            "first_at": a.first_at, "last_at": a.last_at, "status": a.status, "status_label": ALERT_STATUS[a.status],
            "acked_by": _who(db, a.acked_by), "acked_at": a.acked_at, "resolved_at": a.resolved_at,
            "resolved_by": "auto" if a.resolved_auto else _who(db, a.resolved_by)}


@router.get("/alerts")
def list_alerts(status: str = Query("open", pattern="^(open|acked|resolved|active|all)$"), level: str = "", source: str = "",
                page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    ops.sync()
    stmt = select(Alert)
    if status == "active":
        stmt = stmt.where(Alert.status != "resolved")
    elif status != "all":
        stmt = stmt.where(Alert.status == status)
    if level:
        stmt = stmt.where(Alert.level == level)
    if source:
        stmt = stmt.where(Alert.source == source)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Alert.last_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    counts = dict(db.execute(select(Alert.status, func.count()).group_by(Alert.status)).all())
    return {"total": total, "page": page, "page_size": page_size, "counts": {k: counts.get(k, 0) for k in ALERT_STATUS},
            "items": [_alert_out(db, a) for a in rows]}


class AlertActIn(BaseModel):
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


def _alert_act(db: Session, alert_id: int, body: AlertActIn, me: User, action: str) -> dict:
    a = db.get(Alert, alert_id)
    if a is None:
        _err(404, "not_found", "告警不存在")
    allowed = ("open",) if action == "ack" else ("open", "acked")
    if (body.expected_status and body.expected_status != a.status) or a.status not in allowed:
        _err(409, "already_handled", f"这条告警已是「{ALERT_STATUS[a.status]}」", status=a.status,
             handled_by=_who(db, a.resolved_by or a.acked_by), handled_at=a.resolved_at or a.acked_at)
    now = utcnow()
    if action == "ack":
        a.status, a.acked_by, a.acked_at = "acked", me.id, now
    else:
        _reason(body.reason)
        a.status, a.resolved_by, a.resolved_at, a.resolved_auto = "resolved", me.id, now, False
    db.commit()
    activity.record(f"alert_{action}", f"{'确认' if action == 'ack' else '关闭'}告警：{a.title}", user=me, target_type="alert", target_id=a.id,
                    reason=body.reason.strip(), target_label=a.title)
    return _alert_out(db, a)


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, body: AlertActIn | None = None, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    return _alert_act(db, alert_id, body or AlertActIn(), me, "ack")


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, body: AlertActIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    return _alert_act(db, alert_id, body, me, "resolve")


class AlertBulkIn(BaseModel):
    action: str = Field(pattern="^(ack|resolve)$")
    reason: str = Field("", max_length=300)
    ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/alerts/bulk")
def bulk(body: AlertBulkIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    if body.action == "resolve":
        _reason(body.reason)
    results = []
    for i in dict.fromkeys(body.ids):
        try:
            a = _alert_act(db, i, AlertActIn(reason=body.reason), me, body.action)
            results.append({"id": i, "label": a["title"], "ok": True, "code": "ok", "message": ""})
        except HTTPException as e:
            d = e.detail if isinstance(e.detail, dict) else {}
            code = d.get("code", "error")
            results.append({"id": i, "label": f"告警 #{i}", "ok": code == "already_handled", "code": "noop" if code == "already_handled" else code,
                            "message": d.get("message", "")})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok}


# ================================================================ 备份 / 小程序配置
@router.get("/backup")
def backup():
    return ops.backup_status()


@router.get("/miniapp-config")
def miniapp_config():
    from ..services import wechat

    a = settings.wx_appid or ""
    return {"configured": wechat.ready(), "appid": f"{a[:4]}…{a[-4:]}" if len(a) > 8 else ("已配置" if a else ""),
            "secret_configured": bool(settings.wx_secret), "env_version": settings.wx_qr_env, "wx_qr_enabled": wechat.ready(),
            "subscribe_templates": [], "review_mode": None, "version_hint": None}


# ================================================================ 存储与清理
CLEANUP = {"activity": ("操作日志", ActivityLog, ActivityLog.created_at, "activity_days"),
           "events": ("行为事件", Event, Event.created_at, "events_days"),
           "logs": ("入库日志", IngestLog, IngestLog.created_at, "logs_days"),
           "visitors": ("访客记录", Visitor, Visitor.last_seen, "visitors_days")}


def _table_stats(db: Session) -> list[dict]:
    out = []
    for name, model in (("items", None), ("users", User), ("activity_logs", ActivityLog), ("events", Event), ("ingest_logs", IngestLog),
                        ("visitors", Visitor), ("ai_calls", AiCall), ("email_logs", EmailLog)):
        size = None
        if engine.dialect.name == "postgresql":
            try:
                size = int(db.execute(text("select pg_total_relation_size(:t)"), {"t": name}).scalar() or 0)
            except Exception:  # noqa: BLE001
                db.rollback()
        rows = db.execute(text(f"select count(*) from {name}")).scalar()  # noqa: S608  表名是固定白名单
        out.append({"name": name, "rows": int(rows or 0), "size_bytes": size})
    return out


@router.get("/storage")
def storage(db: Session = Depends(get_db)):
    from ..services import resources

    media = resources._cached("media_sizes", 600, resources._media_sizes)
    pick = lambda k: media.get(k, {}).get("bytes")  # noqa: E731
    known = {"covers", "thumb", "anim", "uploads"}
    try:
        du = shutil.disk_usage(settings.media_dir if settings.media_dir.exists() else "/")
        disk = {"total_bytes": du.total, "free_bytes": du.free, "used_pct": round(du.used / du.total * 100, 1)}
    except OSError:
        disk = {"total_bytes": None, "free_bytes": None, "used_pct": None}
    return {"db": {"size_bytes": resources._db_size(), "tables": _table_stats(db)},
            "media": {"covers_bytes": pick("covers"), "thumb_bytes": pick("thumb"), "anim_bytes": pick("anim"), "uploads_bytes": pick("uploads"),
                      "other_bytes": sum(v["bytes"] for k, v in media.items() if k not in known) if media else None},
            "disk": disk, "retention": ops.retention(db), "retention_range": ops.RETENTION_RANGE,
            "cleanup_targets": {k: v[0] for k, v in CLEANUP.items()} | {"orphan_uploads": "没有用到的截图上传"}}


class RetentionIn(BaseModel):
    activity_days: int | None = None
    events_days: int | None = None
    logs_days: int | None = None
    visitors_days: int | None = None
    reason: str = Field("", max_length=300)


@router.put("/storage/retention")
def put_retention(body: RetentionIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    reason = _reason(body.reason)
    admin_security.check_token(me, "retention", admin_security.token_from(request))
    lo, hi = ops.RETENTION_RANGE
    vals = {k: v for k, v in body.model_dump(exclude={"reason"}).items() if v is not None}
    bad = [k for k, v in vals.items() if not lo <= v <= hi]
    if bad:
        _err(400, "bad_range", f"保留天数要在 {lo}–{hi} 天之间", fields=bad)
    before = ops.retention(db)
    after = ops.set_retention(db, vals)
    diff = [k for k in after if before[k] != after[k]]
    activity.record("retention", "修改数据保留天数", user=me, target_type="maintenance", ip=client_ip(request), reason=reason,
                    before={k: before[k] for k in diff}, after={k: after[k] for k in diff}, target_label="retention")
    return {"retention": after}


class CleanupIn(BaseModel):
    target: str = Field(pattern="^(activity|events|logs|visitors|orphan_uploads)$")
    dry_run: bool = True
    reason: str = Field("", max_length=300)


def _orphans(db: Session) -> list[Upload]:
    used = select(UploadItem.upload_id)
    return list(db.scalars(select(Upload).where(Upload.id.not_in(used), Upload.created_at < utcnow() - timedelta(days=30))))


@router.post("/storage/cleanup")
def cleanup(body: CleanupIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    if body.target == "orphan_uploads":
        rows = _orphans(db)
        size = 0
        for u in rows:
            p = settings.media_dir / u.image_path
            size += p.stat().st_size if p.is_file() else 0
        if body.dry_run:
            return {"dry_run": True, "target": body.target, "rows": len(rows), "freed_bytes": size,
                    "summary": f"将删除 {len(rows)} 张 30 天前上传、没有加入任何条目的截图，约 {size / 1024 / 1024:.1f} MB"}
        reason = _reason(body.reason)
        for u in rows:
            (settings.media_dir / u.image_path).unlink(missing_ok=True)
            db.delete(u)
        db.commit()
        n, freed = len(rows), size
    else:
        label, model, col, rkey = CLEANUP[body.target]
        days = ops.retention(db)[rkey]
        cond = col < utcnow() - timedelta(days=days)
        n = db.scalar(select(func.count()).select_from(model).where(cond)) or 0
        if body.dry_run:
            return {"dry_run": True, "target": body.target, "rows": n, "freed_bytes": None,
                    "summary": f"将删除 {n} 条超过 {days} 天的{label}"}
        reason = _reason(body.reason)
        db.execute(delete(model).where(cond))
        db.commit()
        freed = None
    activity.record("storage_cleanup", f"清理存储：{body.target}，{n} 条", user=me, target_type="maintenance", ip=client_ip(request),
                    reason=reason, target_label=f"cleanup:{body.target}", detail={"rows": n, "freed_bytes": freed})
    return {"dry_run": False, "target": body.target, "rows": n, "freed_bytes": freed, "summary": f"已删除 {n} 条"}
