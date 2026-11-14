"""更新日志接口。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import ChangelogEntry

router = APIRouter(prefix="/api/changelog", tags=["changelog"])

CATEGORIES = {"feature": "新增功能", "change": "修改功能", "fix": "修复 Bug"}


class EntryIn(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    category: str = Field(pattern="^(feature|change|fix)$")
    title: str = Field(min_length=1, max_length=200)
    detail: str = ""
    released_at: datetime | None = None


@router.get("")
def list_changelog(db: Session = Depends(get_db)):
    """按版本分组，最新的在前。"""
    rows = db.scalars(select(ChangelogEntry).order_by(ChangelogEntry.released_at.desc(), ChangelogEntry.id)).all()
    releases: list[dict] = []
    for r in rows:
        if not releases or releases[-1]["version"] != r.version:
            releases.append({"version": r.version, "released_at": r.released_at, "entries": []})
        releases[-1]["entries"].append({"id": r.id, "category": r.category, "category_label": CATEGORIES.get(r.category, r.category),
                                        "title": r.title, "detail": r.detail})
    return {"latest": releases[0]["version"] if releases else None, "categories": CATEGORIES, "releases": releases}


@router.post("", dependencies=[Depends(require_admin)])
def add_entry(body: EntryIn, db: Session = Depends(get_db)):
    # 同一版本沿用该版本已有的发布时间，新版本默认用当前时间
    when = body.released_at or db.scalar(select(ChangelogEntry.released_at).where(ChangelogEntry.version == body.version).limit(1)) \
        or datetime.now(timezone.utc)
    e = ChangelogEntry(version=body.version.strip(), category=body.category, title=body.title.strip(), detail=body.detail.strip(), released_at=when)
    db.add(e)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "这个版本里已有同名的更新记录")
    return {"id": e.id}


@router.delete("/{entry_id}", dependencies=[Depends(require_admin)])
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    e = db.get(ChangelogEntry, entry_id)
    if e is None:
        raise HTTPException(404, "记录不存在")
    db.delete(e)
    db.commit()
    return {"ok": True}
