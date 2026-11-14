"""v3.3.50 后台批次 3c（P35）：收录任务监控。

把四类来源统一成一张列表，id 带类型前缀（全局唯一）：
- finder:<id>   查找任务（FinderJob：搜索添加 / 长文识别）
- upload:<id>   截图识别（Upload）
- task:<id>     后台任务（Task）。kind=manual：用户提交后的提炼（github / search / text / screenshot）；kind=extract：其余（重新提炼、补封面、采集等）
状态统一为 running / stuck（进行中超过 10 分钟）/ failed / done。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..db import get_db, utcnow
from ..models import FinderJob, IngestLog, Item, Task, TaskItem, Upload, UploadItem, User
from ..services import activity, ingest, tracking, users

router = APIRouter(prefix="/api/admin", tags=["admin-ingest"], dependencies=[Depends(require_admin)])

STUCK_MIN = 10
SCAN_LIMIT = 3000  # 每类最多取最近这么多条再合并分页
KINDS = {"finder": "查找", "screenshot": "截图识别", "manual": "手动提交", "extract": "后台提炼"}
STATUS = {"running": "进行中", "stuck": "卡住", "failed": "失败", "done": "完成"}
MANUAL_TASKS = ("github", "search", "text", "screenshot", "manual_form")
UPLOAD_RUNNING = ("recognizing", "resolving", "importing")
# v3.3.59 采集 / 榜单详解 / 补图片集也能重试失败的条目；重新分类、补标签、抽检、审核仍需到对应页面重新发起
NO_RETRY_TASKS = ("reclassify", "tags", "audit", "review", "liveness")
UPLOAD_STAGE = {"recognizing": "AI 识别截图", "resolving": "对应 GitHub 仓库", "importing": "加入中", "recognized": "识别完成",
                "imported": "已加入", "failed": "失败"}
FINDER_STAGE = {"plan": "AI 拆解需求", "search": "搜索 GitHub", "read": "AI 通读长文", "rank": "AI 排序"}


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _dur(a: datetime | None, b: datetime | None) -> int | None:
    return int((b - a).total_seconds()) if a and b else None


def _who(u: User | None) -> dict | None:
    return {"id": u.id, "label": users.label(u)} if u else None


def _st(running: bool, failed: bool, since: datetime | None, now: datetime) -> str:
    if running:
        return "stuck" if since and now - since > timedelta(minutes=STUCK_MIN) else "running"
    return "failed" if failed else "done"


def _finder_row(j: FinderJob, u: User | None, now: datetime) -> dict:
    r = j.result or {}
    st = _st(j.status == "running", j.status == "failed", j.created_at, now)
    title = (j.source_url or j.query or "")[:80] if j.kind == "text" else j.query[:80]
    return {"id": f"finder:{j.id}", "kind": "finder", "kind_label": "搜索添加" if j.kind == "search" else "长文识别", "user": _who(u),
            "title": title, "status": st, "status_label": STATUS[st], "stage": r.get("stage", ""),
            "stage_label": FINDER_STAGE.get(r.get("stage", ""), r.get("message", "")[:40]), "created_at": j.created_at,
            "started_at": j.created_at, "finished_at": None, "duration_s": None, "stuck": st == "stuck",
            "error": r.get("error", "") if j.status == "failed" else "", "item": None,
            "can_retry": st in ("failed", "stuck"), "can_abort": st == "stuck"}


def _upload_row(up: Upload, u: User | None, now: datetime, item: Item | None) -> dict:
    ai = up.ai_result or {}
    st = _st(up.status in UPLOAD_RUNNING, up.status == "failed", up.created_at, now)
    names = [x.get("name") or x.get("full_name") or "" for x in (ai.get("items") or [])][:3]
    return {"id": f"upload:{up.id}", "kind": "screenshot", "kind_label": KINDS["screenshot"], "user": _who(u),
            "title": "、".join(n for n in names if n) or "截图", "status": st, "status_label": STATUS[st], "stage": up.status,
            "stage_label": UPLOAD_STAGE.get(up.status, up.status), "created_at": up.created_at, "started_at": up.created_at,
            "finished_at": None, "duration_s": None, "stuck": st == "stuck", "error": ai.get("error", "") if up.status == "failed" else "",
            "item": {"id": item.id, "name": item.name} if item else None, "can_retry": False, "can_abort": st == "stuck"}


def _task_row(t: Task, u: User | None, now: datetime, last_activity: datetime | None) -> dict:
    running = t.status == "running"
    failed = t.status == "failed" or (t.status == "partial" and t.failed > 0) or (t.status == "partial" and t.done < t.total)
    st = _st(running, failed, last_activity or t.created_at, now)
    kind = "manual" if t.kind in MANUAL_TASKS else "extract"
    err = ""
    if failed:
        err = f"{t.failed} 个失败" if t.failed else f"中断，完成 {t.done}/{t.total}"
    return {"id": f"task:{t.id}", "kind": kind, "kind_label": tracking.TRIGGERS.get(t.kind, KINDS[kind]), "task_kind": t.kind,
            "user": _who(u), "title": t.title, "status": st, "status_label": STATUS[st], "stage": "",
            "stage_label": f"{t.done}/{t.total}", "created_at": t.created_at, "started_at": t.created_at, "finished_at": t.finished_at,
            "duration_s": _dur(t.created_at, t.finished_at), "stuck": st == "stuck", "error": err, "item": None,
            "progress": {"total": t.total, "done": t.done, "failed": t.failed},
            "can_retry": st in ("failed", "stuck") and t.kind not in NO_RETRY_TASKS, "can_abort": st == "stuck"}


def _collect(db: Session, kind: str, user_id: int | None, q: str, since: datetime | None, until: datetime | None,
             task_kind: str = "") -> list[dict]:
    now = utcnow()
    out: list[dict] = []

    def rng(stmt, col):
        if user_id:
            stmt = stmt.where(getattr(stmt.column_descriptions[0]["entity"], "user_id") == user_id)
        if since:
            stmt = stmt.where(col >= since)
        if until:
            stmt = stmt.where(col < until)
        return stmt.order_by(col.desc()).limit(SCAN_LIMIT)

    uids: set[int] = set()
    finders = db.scalars(rng(select(FinderJob), FinderJob.created_at)).all() if kind in ("", "finder") and not task_kind else []
    uploads = db.scalars(rng(select(Upload), Upload.created_at)).all() if kind in ("", "screenshot") and not task_kind else []
    tasks = []
    if kind in ("", "manual", "extract"):
        ts = select(Task)
        if kind == "manual":
            ts = ts.where(Task.kind.in_(MANUAL_TASKS))
        elif kind == "extract":
            ts = ts.where(Task.kind.not_in(MANUAL_TASKS))
        if task_kind:
            ts = ts.where(Task.kind == task_kind)
        tasks = db.scalars(rng(ts, Task.created_at)).all()
    for x in (*finders, *uploads, *tasks):
        if x.user_id:
            uids.add(x.user_id)
    who = {u.id: u for u in db.scalars(select(User).where(User.id.in_(uids or {-1})))}
    first_item = dict(db.execute(select(UploadItem.upload_id, func.min(UploadItem.item_id)).where(
        UploadItem.upload_id.in_([u.id for u in uploads] or [-1])).group_by(UploadItem.upload_id)).all())
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_(list(first_item.values()) or [-1])))}
    running_ids = [t.id for t in tasks if t.status == "running"]
    last = dict(db.execute(select(TaskItem.task_id, func.max(func.coalesce(TaskItem.finished_at, TaskItem.started_at)))
                           .where(TaskItem.task_id.in_(running_ids or [-1])).group_by(TaskItem.task_id)).all())
    out += [_finder_row(j, who.get(j.user_id), now) for j in finders]
    out += [_upload_row(u, who.get(u.user_id), now, items.get(first_item.get(u.id))) for u in uploads]
    out += [_task_row(t, who.get(t.user_id), now, last.get(t.id)) for t in tasks]
    if q.strip():
        k = q.strip().lower()
        out = [r for r in out if k in (r["title"] or "").lower() or (r["user"] and k in r["user"]["label"].lower())]
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out


def _parse_day(v: str) -> datetime | None:
    from .admin import _parse_day as p

    return p(v)


@router.get("/ingest-tasks")
def list_tasks(kind: str = Query("", pattern="^(|finder|screenshot|manual|extract)$"),
               status: str = Query("", pattern="^(|running|stuck|failed|done)$"), user_id: int | None = None, q: str = "",
               created_from: str = "", created_to: str = "", task_kind: str = "", page: int = Query(1, ge=1),
               page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    since = _parse_day(created_from)
    until = _parse_day(created_to)
    rows = _collect(db, kind, user_id, q, since, until + timedelta(days=1) if until else None, task_kind)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS}
    if status:
        rows = [r for r in rows if r["status"] == status]
    start = (page - 1) * page_size
    present = [k for (k,) in db.execute(select(Task.kind).distinct()).all()]
    return {"total": len(rows), "page": page, "page_size": page_size, "counts": counts, "kinds": KINDS, "stuck_minutes": STUCK_MIN,
            "task_kinds": {k: tracking.TRIGGERS.get(k, k) for k in sorted(set(present) | set(tracking.TRIGGERS))},
            "items": rows[start:start + page_size]}


def _split(task_id: str) -> tuple[str, int]:
    try:
        prefix, n = task_id.split(":", 1)
        return prefix, int(n)
    except ValueError:
        _err(404, "not_found", "任务不存在")


def _one(db: Session, task_id: str) -> tuple[str, object, dict]:
    prefix, n = _split(task_id)
    now = utcnow()
    if prefix == "finder" and (j := db.get(FinderJob, n)):
        return prefix, j, _finder_row(j, db.get(User, j.user_id) if j.user_id else None, now)
    if prefix == "upload" and (up := db.get(Upload, n)):
        iid = db.scalar(select(func.min(UploadItem.item_id)).where(UploadItem.upload_id == up.id))
        return prefix, up, _upload_row(up, db.get(User, up.user_id) if up.user_id else None, now, db.get(Item, iid) if iid else None)
    if prefix == "task" and (t := db.get(Task, n)):
        last = db.scalar(select(func.max(func.coalesce(TaskItem.finished_at, TaskItem.started_at))).where(TaskItem.task_id == t.id))
        return prefix, t, _task_row(t, db.get(User, t.user_id) if t.user_id else None, now, last)
    _err(404, "not_found", "任务不存在")


@router.get("/ingest-tasks/{task_id}")
def task_detail(task_id: str, db: Session = Depends(get_db)):
    prefix, obj, row = _one(db, task_id)
    stages, logs, extra = [], [], {}
    if prefix == "finder":
        r = obj.result or {}
        cands = r.get("candidates") or []
        extra = {"mode": obj.kind, "query": obj.query[:2000], "source_url": obj.source_url, "candidates": len(cands),
                 "imported": sum(1 for c in cands if c.get("state") == "imported" or c.get("imported")), "message": r.get("message", ""),
                 "plan": r.get("plan")}
        stages = [{"stage": r.get("stage", ""), "label": row["stage_label"], "status": row["status"], "started_at": obj.created_at,
                   "ended_at": None, "duration_s": None, "message": r.get("message", "")}]
        logs = [{"at": x.created_at, "level": x.level, "stage": x.stage, "message": x.message} for x in db.scalars(
            select(IngestLog).where(IngestLog.trigger.in_(("search", "text")), IngestLog.user_id == obj.user_id,
                                    IngestLog.created_at >= obj.created_at, IngestLog.created_at < obj.created_at + timedelta(hours=1))
            .order_by(IngestLog.id).limit(100))]
    elif prefix == "upload":
        ai = obj.ai_result or {}
        extra = {"image_url": f"/media/{obj.image_path}", "items": [
            {k: x.get(k) for k in ("name", "full_name", "state", "confidence", "item_id", "error") if k in x} for x in (ai.get("items") or [])][:30],
            "error": ai.get("error", ""), "import": ai.get("import")}
        stages = [{"stage": obj.status, "label": UPLOAD_STAGE.get(obj.status, obj.status), "status": row["status"], "started_at": obj.created_at,
                   "ended_at": None, "duration_s": None, "message": ai.get("error", "")}]
    else:
        tis = db.scalars(select(TaskItem).where(TaskItem.task_id == obj.id).order_by(TaskItem.seq)).all()
        extra = {"task_kind": obj.kind, "items": [{"id": ti.item_id, "name": ti.name, "status": ti.status, "stage": ti.stage,
                                                   "stage_label": tracking.STAGES.get(ti.stage, ti.stage), "error": ti.message if ti.status == "failed" else "",
                                                   "duration_s": _dur(ti.started_at, ti.finished_at)} for ti in tis[:200]]}
        by_stage: dict[str, dict] = {}
        for x in db.scalars(select(IngestLog).where(IngestLog.task_id == obj.id).order_by(IngestLog.id).limit(2000)):
            s = by_stage.setdefault(x.stage, {"stage": x.stage, "label": tracking.STAGES.get(x.stage, x.stage), "status": "done",
                                              "started_at": x.created_at, "ended_at": x.created_at, "duration_ms": 0, "message": ""})
            s["ended_at"] = x.created_at
            s["duration_ms"] += x.duration_ms or 0
            if x.level == "error":
                s["status"], s["message"] = "failed", x.message[:200]
            logs.append({"at": x.created_at, "level": x.level, "stage": x.stage, "message": x.message})
        stages = [{**{k: v for k, v in s.items() if k != "duration_ms"}, "duration_s": round(s["duration_ms"] / 1000, 1) if s["duration_ms"] else None}
                  for s in by_stage.values()]
        logs = logs[-200:]
    return {**row, "stages": stages, "logs": logs, "extra": extra}


class ActIn(BaseModel):
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


def _check(row: dict, body: ActIn, allowed: tuple[str, ...]):
    if (body.expected_status and body.expected_status != row["status"]) or row["status"] not in allowed:
        _err(409, "already_handled", f"任务当前是「{row['status_label']}」，不能执行这个操作", handled_by=None, handled_at=None,
             status=row["status"])
    if len((body.reason or "").strip()) < 2:
        _err(400, "reason_required", "请填写原因")


def _start_items(obj: Task, ids: list[int], db: Session) -> int:
    """按原任务类型另起一个任务处理这些条目（管理员发起，不计入任何用户的 AI 额度）。"""
    names = dict(db.execute(select(Item.id, Item.name).where(Item.id.in_(ids))).all())
    rows = [(i, names.get(i, str(i))) for i in ids]
    title = f"重试 · {obj.title}"[:200]
    if obj.kind == "cover":
        new_id = tracking.create_task("cover", title, rows)
        tracking.start_task(new_id, ids, lambda i, t: ingest.cover_for(i, t), workers=2)
    elif obj.kind == "gallery":
        new_id = tracking.create_task("gallery", title, rows)
        tracking.start_task(new_id, ids, lambda i, t: ingest.gallery_for(i, t), workers=2)
    elif obj.kind == "blurb":
        from ..services import blurbs
        from ..services.github import GitHub

        def one(item_id: int, tid: int):
            with GitHub() as gh:
                return blurbs.generate(item_id, gh, force=True, task_id=tid)

        new_id = tracking.create_task("blurb", title, rows)
        tracking.start_task(new_id, ids, one, workers=1)
    elif obj.kind in NO_RETRY_TASKS:
        _err(400, "not_supported", "这类任务请到对应页面重新发起")
    else:
        new_id = ingest.start_process_task("reextract", title, ids, workers=2, force=True)
    return new_id


def _retry(db: Session, task_id: str, body: ActIn, me: User, only_failed: bool = False) -> dict:
    prefix, obj, row = _one(db, task_id)
    _check(row, body, ("failed", "stuck"))
    if prefix == "task":
        states = ("failed", "deferred") if only_failed else ("failed", "pending", "running", "deferred")
        ids = list(db.scalars(select(TaskItem.item_id).where(TaskItem.task_id == obj.id, TaskItem.status.in_(states),
                                                             TaskItem.item_id.is_not(None))))
        done = db.scalar(select(func.count()).select_from(TaskItem).where(TaskItem.task_id == obj.id, TaskItem.status == "ok")) or 0
        if not ids:
            _err(400, "nothing_to_retry", "没有可以重试的条目")
        new_id = _start_items(obj, ids, db)
        if row["status"] == "stuck":
            tracking.finish_task(obj.id, "partial")
        # charged：这次重试实际消耗的 AI 调用要等新任务跑完才知道，在新任务详情里看；这里给 null
        return {"id": task_id, "ok": True, "code": "queued", "new_task_id": f"task:{new_id}", "count": len(ids),
                "retried": len(ids), "skipped_done": done, "charged": None}
    if prefix == "finder":
        from ..services import finder

        new = finder.create_job(obj.kind, obj.query, obj.source_url, obj.user_id)
        import threading

        threading.Thread(target=finder.run_search if obj.kind == "search" else finder.run_text, args=(new,), daemon=True).start()
        if row["status"] == "stuck":
            obj.status = "failed"
            obj.result = {**(obj.result or {}), "error": "管理员重试，已另起任务"}
            db.commit()
        return {"id": task_id, "ok": True, "code": "queued", "new_task_id": f"finder:{new}"}
    _err(400, "not_supported", "截图识别请让用户重新上传")


@router.post("/ingest-tasks/{task_id}/retry")
def retry(task_id: str, body: ActIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    out = _retry(db, task_id, body, me)
    activity.record("ingest_retry", f"重试收录任务 {task_id}", user=me, ip=client_ip(request), reason=body.reason.strip(),
                    detail={"task": task_id, "new": out.get("new_task_id")})
    return out


@router.post("/ingest-tasks/{task_id}/retry-failed")
def retry_failed(task_id: str, body: ActIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """只重试失败（含额度用完留到下次）的条目，成功的不动。只支持后台任务（task:）。"""
    if not task_id.startswith("task:"):
        _err(400, "not_supported", "只有后台任务可以只重试失败项")
    out = _retry(db, task_id, body, me, only_failed=True)
    activity.record("ingest_retry", f"只重试失败项 {task_id}：{out['retried']} 个", user=me, ip=client_ip(request), reason=body.reason.strip(),
                    detail={"task": task_id, "new": out.get("new_task_id")})
    return out


@router.post("/ingest-tasks/{task_id}/abort")
def abort(task_id: str, body: ActIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """把卡住的任务标记为失败（后台线程若仍在运行，结果会被忽略或覆盖；不会真的杀线程）。"""
    prefix, obj, row = _one(db, task_id)
    _check(row, body, ("stuck",))
    reason = body.reason.strip()
    if prefix == "task":
        for ti in db.scalars(select(TaskItem).where(TaskItem.task_id == obj.id, TaskItem.status.in_(("pending", "running")))):
            ti.status, ti.message, ti.finished_at = "failed", f"管理员终止：{reason}", utcnow()
        obj.failed = db.scalar(select(func.count()).select_from(TaskItem).where(TaskItem.task_id == obj.id, TaskItem.status == "failed")) or 0
        obj.status, obj.finished_at = "failed", utcnow()
    elif prefix == "finder":
        obj.status = "failed"
        obj.result = {**(obj.result or {}), "error": f"管理员终止：{reason}"}
    else:
        obj.status = "failed"
        obj.ai_result = {**(obj.ai_result or {}), "error": f"管理员终止：{reason}"}
    db.commit()
    activity.record("ingest_abort", f"终止收录任务 {task_id}", user=me, ip=client_ip(request), reason=reason, detail={"task": task_id})
    return {"id": task_id, "ok": True, "code": "ok", "status": "failed"}


class BulkIn(BaseModel):
    action: str = Field(pattern="^retry$")
    reason: str = Field("", max_length=300)
    ids: list[str] = Field(min_length=1, max_length=50)


@router.post("/ingest-tasks/bulk")
def bulk(body: BulkIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    if len(body.reason.strip()) < 2:
        _err(400, "reason_required", "请填写原因")
    results = []
    for tid in dict.fromkeys(body.ids):
        try:
            r = _retry(db, tid, ActIn(reason=body.reason), me)
            results.append({**r, "label": tid, "message": ""})
        except HTTPException as e:
            d = e.detail if isinstance(e.detail, dict) else {"code": "error", "message": str(e.detail)}
            code = "bad_state" if d.get("code") == "already_handled" else d.get("code")
            results.append({"id": tid, "label": tid, "ok": False, "code": code, "message": d.get("message", "")})
    activity.record("ingest_retry", f"批量重试收录任务 {sum(1 for r in results if r['ok'])} 个", user=me, ip=client_ip(request),
                    reason=body.reason.strip(), detail={"ids": body.ids})
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok}


def summary_counts(db: Session) -> dict:
    """概览「待处理」：卡住数、近 24 小时失败数。"""
    rows = _collect(db, "", None, "", utcnow() - timedelta(days=2), None)
    day = utcnow() - timedelta(hours=24)
    return {"ingest_stuck": sum(1 for r in rows if r["status"] == "stuck"),
            "ingest_failed": sum(1 for r in rows if r["status"] == "failed" and r["created_at"] >= day)}
