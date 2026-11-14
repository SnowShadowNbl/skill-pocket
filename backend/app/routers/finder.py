"""新增 Skill：搜索添加 / 长文识别。查找在后台跑，前端轮询 GET /api/finder/{id} 看进度和结果。"""

import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..models import FinderJob, User
from ..services import activity, finder, ingest, quota, review

router = APIRouter(prefix="/api/finder", tags=["finder"])

# 按账号限流（每分钟），再加每日额度（quota.check_ai）
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _throttle(user: User) -> None:
    ip, now = f"user:{user.id}", time.monotonic()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.finder_per_minute:
            raise HTTPException(429, "操作太频繁了，请过一分钟再试")
        q.append(now)


def _out(job: FinderJob) -> dict:
    data = dict(job.result or {})
    return {
        "id": job.id, "kind": job.kind, "status": job.status, "created_at": job.created_at,
        "query": job.query if job.kind == "search" else job.query[:300],
        "source_url": job.source_url, **data,
    }


def _start(target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


class SearchIn(BaseModel):
    q: str = Field(min_length=1, max_length=300)


class TextIn(BaseModel):
    text: str = ""
    url: str = Field("", max_length=1000)


class Pick(BaseModel):
    full_name: str
    name: str = ""
    sub_path: str | None = None
    kind: str = ""
    index: int | None = None  # 在结果列表里的序号，后台加入时按它原地更新


class ImportIn(BaseModel):
    picks: list[Pick]


@router.post("/search")
def start_search(body: SearchIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    _throttle(me)
    quota.check_ai(db, me)
    job_id = finder.create_job("search", body.q.strip(), user_id=me.id)
    activity.record("recognize", f"搜索添加：{body.q.strip()[:80]}", user=me, target_type="finder", target_id=job_id)
    _start(finder.run_search, job_id)
    return _out(db.get(FinderJob, job_id))


@router.post("/text")
def start_text(body: TextIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    text, url = body.text.strip(), body.url.strip()
    if not text and not url:
        raise HTTPException(400, "请粘贴正文，或填写文章链接")
    if text and len(text) < 20:
        raise HTTPException(400, "内容太短了")
    _throttle(me)
    quota.check_ai(db, me)
    truncated = len(text) > settings.text_max_chars
    job_id = finder.create_job("text", text[: settings.text_max_chars], "" if text else url, user_id=me.id)
    activity.record("recognize", f"长文识别：{url[:100] if url else f'{len(text)} 字的正文'}", user=me, target_type="finder", target_id=job_id)
    if truncated:
        finder._update(job_id, warning=f"原文超过 {settings.text_max_chars} 字，只识别了前面部分")
    _start(finder.run_text, job_id)
    return _out(db.get(FinderJob, job_id))


@router.get("/recent")
def recent(kind: str = "", db: Session = Depends(get_db), me: User = Depends(current_user)):
    q = select(FinderJob).where(FinderJob.user_id == me.id).order_by(FinderJob.created_at.desc()).limit(10)
    if kind:
        q = q.where(FinderJob.kind == kind)
    return [{"id": j.id, "kind": j.kind, "status": j.status, "created_at": j.created_at,
             "query": j.query[:80], "source_url": j.source_url,
             "count": len((j.result or {}).get("candidates") or [])} for j in db.scalars(q)]


def _own_job(db: Session, job_id: int, me: User) -> FinderJob | None:
    job = db.get(FinderJob, job_id)
    if job is None or (job.user_id != me.id and not auth.is_admin(me)):
        return None
    return job


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    job = _own_job(db, job_id, me)
    if job is None:
        raise HTTPException(404, "记录不存在")
    return _out(job)


@router.post("/{job_id}/more")
def search_more(job_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """换一批说法再搜，结果追加在后面。"""
    job = _own_job(db, job_id, me)
    if job is None or job.kind != "search":
        raise HTTPException(404, "搜索记录不存在")
    if job.status == "running":
        raise HTTPException(409, "上一轮搜索还没结束")
    _throttle(me)
    job.status = "running"
    db.commit()
    _start(finder.run_search, job_id, True)
    return _out(job)


@router.post("/{job_id}/import")
def import_found(job_id: int, body: ImportIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    job = _own_job(db, job_id, me)
    if job is None:
        raise HTTPException(404, "记录不存在")
    if not body.picks:
        raise HTTPException(400, "请至少选择一个")
    quota.check_ai(db, me)
    quota.check_new_items(db, me, len(body.picks))
    picks = [p.model_dump() for p in body.picks]
    # v3.3.7：上一批还在加入时也可以继续加入别的行（多批并行）；已经在加入 / 已收录的行跳过。
    # 先把勾选的行标成「加入中」，接口立即返回；后台逐个加入，前端轮询这个任务看进度
    with_index = [p for p in picks if p.get("index") is not None]
    ok = set(finder.mark_importing(job.id, [p["index"] for p in with_index]))
    picks = [p for p in picks if p.get("index") is None or p["index"] in ok]
    if not picks:
        raise HTTPException(409, "勾选的条目已经在加入中或已收录")
    _start(finder.run_import, job.id, picks, me.id, review.needs_review(me))
    db.expire_all()
    return {"queued": len(picks), "job": _out(db.get(FinderJob, job.id))}
