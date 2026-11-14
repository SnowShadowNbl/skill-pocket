"""v3.3 搜索增强：热门搜索（用户侧可见）、搜索联想。搜索历史存在浏览器本机，不经过服务器。"""

import time
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db, utcnow
from ..models import Category, Event, Item, Repo
from ..services import search_terms

router = APIRouter(prefix="/api/search", tags=["search"])

@router.get("/hot")
def hot(db: Session = Depends(get_db)):
    """大家在搜：最近 14 天站内搜索词，至少 2 位访客搜过；去掉敏感 / 广告词和后台屏蔽的词；缓存 10 分钟。"""
    return search_terms.hot_public(db)


@router.get("/suggest")
def suggest(q: str = Query("", max_length=60), db: Session = Depends(get_db)):
    """搜索联想：名称（或仓库名）包含输入的已发布条目，名称开头匹配的排前面，同等按星标。"""
    q = q.strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    rows = db.scalars(
        select(Item).outerjoin(Repo, Repo.id == Item.repo_id)
        .options(joinedload(Item.category).joinedload(Category.parent))
        .where(Item.status == "published", or_(func.lower(Item.name).like(like), func.lower(Repo.full_name).like(like)))
        .order_by(func.lower(Item.name).like(f"{q.lower()}%").desc(), func.coalesce(Repo.stars, 0).desc())
        .limit(6)
    ).unique().all()
    return [{"id": it.id, "name": it.name, "summary": (it.summary or "")[:40],
             "category": it.category.name if it.category else ""} for it in rows]
