"""用户反馈：所有人可提交（未登录需人机校验），提交后 AI 立即分析类别、原因与 P0~P4 优先级；用户在「我的反馈」看进度。"""

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db import SessionLocal, get_db, utcnow
from ..models import ActivityLog, Feedback, IngestLog, User
from ..services import activity, judge, vision

router = APIRouter(prefix="/api", tags=["feedback"])

CATEGORIES = {"bug": "Bug", "feature": "功能建议", "ux": "体验问题", "content": "内容问题", "account": "账号问题", "other": "其他"}
STATUSES = {"new": "新提交", "processing": "处理中", "resolved": "已解决", "closed": "已关闭", "wontfix": "不处理"}
MAX_IMAGES = 3

_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _throttle(key: str, limit: int) -> None:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "反馈提交得太频繁了，请稍后再试")
        q.append(now)


def replies_out(f: Feedback) -> list[dict]:
    """管理员回复记录；老数据只有 admin_reply 一条时也按记录返回。"""
    rows = list(f.replies or [])
    if not rows and f.admin_reply:
        rows = [{"text": f.admin_reply, "images": [], "at": f.replied_at.isoformat() if f.replied_at else None, "by": ""}]
    return [{**r, "images": [f"/media/{p}" for p in r.get("images") or []]} for r in rows]


async def save_images(images: list[UploadFile], folder_name: str = "feedback") -> list[str]:
    """保存上传的截图（统一转码、10MB 以内），返回 media 下的相对路径。"""
    paths = []
    folder = settings.media_dir / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    for up in images:
        raw = await up.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(400, "图片不能超过 10MB")
        try:
            img, mime = vision.prepare_image(raw)
        except Exception:
            raise HTTPException(400, "有一张图片无法读取")
        name = f"{uuid.uuid4().hex}.{'png' if mime == 'image/png' else 'jpg'}"
        (folder / name).write_bytes(img)
        paths.append(f"{folder_name}/{name}")
    return paths


def feedback_out(f: Feedback, admin: bool = False, users: dict | None = None) -> dict:
    out = {
        "id": f.id, "category": f.category, "category_label": CATEGORIES.get(f.category, f.category),
        "content": f.content, "input_type": f.input_type, "images": [f"/media/{p}" for p in f.images or []],
        "item_id": f.item_id, "status": f.status, "status_label": STATUSES.get(f.status, f.status),
        "admin_reply": f.admin_reply, "replied_at": f.replied_at, "user_unread": f.user_unread,
        "replies": replies_out(f),
        "created_at": f.created_at, "updated_at": f.updated_at,
    }
    if admin:
        u = (users or {}).get(f.user_id)
        out.update(
            priority=f.priority, ai_status=f.ai_status, ai_analysis=f.ai_analysis or {}, diagnostics=f.diagnostics or {},
            page_url=f.page_url, contact_email=f.contact_email,
            user={"id": u.id, "nickname": u.nickname, "email": u.email} if u else None,
        )
    return out


def _analyze(fb_id: int) -> None:
    """后台 AI 分析：建议类别、原因、影响面、P0~P4、处理步骤、相似反馈。"""
    with SessionLocal() as db:
        f = db.get(Feedback, fb_id)
        if f is None:
            return
        since = f.created_at - timedelta(hours=24)
        logs = []
        if f.user_id:
            logs += [{"time": r.created_at.isoformat(), "stage": r.stage, "level": r.level, "message": r.message[:200]}
                     for r in db.scalars(select(IngestLog).where(IngestLog.user_id == f.user_id, IngestLog.created_at >= since,
                                                                 IngestLog.level.in_(("error", "warn"))).order_by(IngestLog.id.desc()).limit(15))]
            logs += [{"time": r.created_at.isoformat(), "action": r.action, "summary": r.summary}
                     for r in db.scalars(select(ActivityLog).where(ActivityLog.user_id == f.user_id, ActivityLog.created_at >= since)
                                         .order_by(ActivityLog.id.desc()).limit(15))]
        recent = [{"id": r.id, "category": r.category, "summary": (r.ai_analysis or {}).get("summary") or r.content[:80]}
                  for r in db.scalars(select(Feedback).where(Feedback.id != f.id, Feedback.status.in_(("new", "processing")))
                                      .order_by(Feedback.id.desc()).limit(30))]
        brief = {"category": CATEGORIES.get(f.category), "content": f.content, "page": f.page_url,
                 "diagnostics": f.diagnostics, "has_images": bool(f.images), "logged_in": bool(f.user_id)}
        try:
            a = judge.analyze_feedback(brief, logs, recent)
        except judge.JudgeUnavailable as e:
            f.ai_status, f.ai_analysis = "failed", {"error": str(e)}
            db.commit()
            return
        f.ai_status, f.ai_analysis = "done", a
        if a["priority"] and f.category in ("bug", "account"):
            f.priority = a["priority"]
        db.commit()


@router.post("/feedback")
async def submit_feedback(
    request: Request,
    category: str = Form(...),
    content: str = Form(..., min_length=2, max_length=5000),
    input_type: str = Form("text"),
    contact_email: str = Form(""),
    item_id: int | None = Form(None),
    page_url: str = Form(""),
    diagnostics: str = Form("{}"),
    pow_token: str = Form(""),
    pow_nonce: str = Form(""),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    me: User | None = Depends(auth.current_user_optional),
):
    if category not in CATEGORIES:
        raise HTTPException(400, "请选择反馈类别")
    if me is None:
        auth.verify_pow(pow_token, pow_nonce)
        _throttle(f"ip:{auth.client_ip(request)}", 5)
    else:
        _throttle(f"user:{me.id}", 20)
    if len(images) > MAX_IMAGES:
        raise HTTPException(400, f"最多上传 {MAX_IMAGES} 张截图")
    try:
        diag = json.loads(diagnostics or "{}")
        diag = diag if isinstance(diag, dict) else {}
    except ValueError:
        diag = {}
    if len(json.dumps(diag, ensure_ascii=False)) > 20000:  # 诊断信息过大时只留页面信息
        diag = {"truncated": True, "page": diag.get("page"), "ua": diag.get("ua")}
    paths = await save_images(images)
    f = Feedback(user_id=me.id if me else None, contact_email=contact_email.strip()[:254], category=category,
                 content=content.strip(), input_type="voice" if input_type == "voice" else "text", images=paths,
                 diagnostics=diag, item_id=item_id, page_url=page_url[:500], status="new", priority="",
                 ai_status="pending", ai_analysis={}, admin_reply="", user_unread=False)
    db.add(f)
    db.commit()
    activity.record("feedback", f"提交反馈（{CATEGORIES[category]}）：{content.strip()[:60]}", user=me,
                    target_type="feedback", target_id=f.id, ip=auth.client_ip(request))
    threading.Thread(target=_analyze, args=(f.id,), daemon=True).start()
    return {"id": f.id, "ok": True}


@router.get("/me/feedback")
def my_feedback(me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Feedback).where(Feedback.user_id == me.id).order_by(Feedback.created_at.desc()).limit(50)).all()
    return {"items": [feedback_out(f) for f in rows], "unread": sum(f.user_unread for f in rows)}


@router.post("/me/feedback/read")
def read_feedback(me: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    for f in db.scalars(select(Feedback).where(Feedback.user_id == me.id, Feedback.user_unread.is_(True))):
        f.user_unread = False
    db.commit()
    return {"ok": True}


def unread_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Feedback).where(Feedback.user_id == user_id, Feedback.user_unread.is_(True)))
