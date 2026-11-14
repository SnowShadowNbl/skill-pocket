"""对比（v2.3）：发起对比需要登录并计入每天的 AI 次数；结果页任何人都能打开（可以分享）。"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import client_ip, current_user
from ..db import get_db
from ..models import CompareRun, User
from ..services import activity, compare, quota
from ..services.extract import model_label

router = APIRouter(prefix="/api", tags=["compare"])


@router.post("/compare")
def start_compare(request: Request, entries: list[dict] = Body(..., embed=True), db: Session = Depends(get_db),
                  me: User = Depends(current_user)):
    quota.check_ai(db, me)
    try:
        run_id = compare.start(entries, me.id)
    except compare.CompareError as e:
        raise HTTPException(400, str(e)) from e
    run = db.get(CompareRun, run_id)
    activity.record("compare", f"对比：{'、'.join(s['name'] for s in run.subjects)}"[:300], user=me, target_type="compare",
                    target_id=run_id, ip=client_ip(request))
    return compare.run_out(run)


@router.get("/compare/{run_id}")
def get_compare(run_id: int, db: Session = Depends(get_db)):
    run = db.get(CompareRun, run_id)
    if run is None:
        raise HTTPException(404, "对比记录不存在")
    return compare.run_out(run)


@router.get("/me/compares")
def my_compares(page: int = Query(1, ge=1), db: Session = Depends(get_db), me: User = Depends(current_user)):
    rows = db.scalars(select(CompareRun).where(CompareRun.user_id == me.id).order_by(CompareRun.id.desc())
                      .offset((page - 1) * 20).limit(20)).all()
    # v3.2 口袋里的对比卡片：带上各条目封面拼缩略图
    return [{"id": r.id, "status": r.status, "names": [s["name"] for s in r.subjects], "summary": (r.result or {}).get("summary", ""),
             "covers": [s.get("cover_url") or "" for s in r.subjects][:4],
             "cover_thumbs": [compare.subject_thumb(s) for s in r.subjects][:4], "model": model_label(r.model) if r.model else "",
             "created_at": r.created_at} for r in rows]
