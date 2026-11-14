"""v3.3.42 后台批次 1：用户「内容与行为」、保存的筛选视图、全局搜索。

- GET /api/admin/users/{id}/content：六个分区一次返回（每个分区 total + 最近 10 条）
- GET /api/admin/users/{id}/content/{section}?page=&page_size=：submissions / comments / feedback / compares 翻页
- /api/admin/views：管理员个人的筛选视图（按 scope 区分，query 原样存取）
- GET /api/admin/search?q=&limit=：用户、条目、反馈
"""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import (AdminView, Category, CategorySubscription, Comment, CompareRun, FavDimension, Favorite,
                      FavFolder, FavoriteFolderLink, Feedback, Item, Repo, User)
from ..services import users
from .feedback import CATEGORIES as FB_CATEGORIES
from .feedback import STATUSES as FB_STATUSES
from .manage import ITEM_STATUS, STATUS_LABEL

router = APIRouter(prefix="/api/admin", tags=["admin-batch1"], dependencies=[Depends(require_admin)])

RECENT = 10
COMMENT_STATUS = {"visible": "已公开", "pending": "待审核"}
COMPARE_STATUS = {"running": "进行中", "done": "已完成", "failed": "失败"}


def _err(status: int, code: str, message: str):
    raise HTTPException(status, {"code": code, "message": message})


def _user_or_404(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        _err(404, "not_found", "用户不存在")
    return u


# ---------------------------------------------------------------- 内容与行为
def _q_submissions(uid):
    return select(Item).where(Item.created_by == uid)


def _row_submission(it: Item):
    return {"id": it.id, "name": it.name, "status": it.status, "status_label": ITEM_STATUS.get(it.status, it.status),
            "review_state": it.review_state or "", "created_at": it.collected_at}


def _q_comments(uid):
    return select(Comment).where(Comment.user_id == uid)


def _row_comment(db: Session):
    def f(c: Comment):
        it = db.get(Item, c.item_id)
        return {"id": c.id, "item": {"id": c.item_id, "name": it.name if it else "（已删除）"},
                "content": c.content[:120] + ("…" if len(c.content) > 120 else ""), "rating": c.rating,
                "status": c.status, "status_label": COMMENT_STATUS.get(c.status, c.status),
                "review_reason": c.review_reason or "", "input_type": c.input_type, "created_at": c.created_at}
    return f


def _q_feedback(uid):
    return select(Feedback).where(Feedback.user_id == uid)


def _row_feedback(f: Feedback):
    return {"id": f.id, "category": f.category, "category_label": FB_CATEGORIES.get(f.category, f.category),
            "status": f.status, "status_label": FB_STATUSES.get(f.status, f.status), "priority": f.priority or "",
            "summary": f.content[:80] + ("…" if len(f.content) > 80 else ""), "created_at": f.created_at}


def _q_compares(uid):
    return select(CompareRun).where(CompareRun.user_id == uid)


def _row_compare(r: CompareRun):
    return {"id": r.id, "count": len(r.entries or []), "names": [s.get("name", "") for s in (r.subjects or [])][:6],
            "status": r.status, "status_label": COMPARE_STATUS.get(r.status, r.status), "created_at": r.created_at}


SECTIONS = {
    "submissions": (_q_submissions, Item.id, lambda db: _row_submission),
    "comments": (_q_comments, Comment.id, _row_comment),
    "feedback": (_q_feedback, Feedback.id, lambda db: _row_feedback),
    "compares": (_q_compares, CompareRun.id, lambda db: _row_compare),
}


def _section(db: Session, uid: int, name: str, page: int = 1, page_size: int = RECENT):
    q, order, row = SECTIONS[name]
    stmt = q(uid)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(order.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [row(db)(r) for r in rows]}


def _favorites(db: Session, uid: int):
    total = db.scalar(select(func.count()).select_from(Favorite).where(Favorite.owner_id == uid)) or 0
    by_cat = Counter()
    for (name,) in db.execute(select(Category.name).select_from(Favorite).join(Item, Item.id == Favorite.item_id)
                              .join(Category, Category.id == Item.category_id).where(Favorite.owner_id == uid)).all():
        by_cat[name] += 1
    counts = dict(db.execute(select(FavoriteFolderLink.folder_id, func.count()).join(Favorite, Favorite.id == FavoriteFolderLink.favorite_id)
                             .where(Favorite.owner_id == uid).group_by(FavoriteFolderLink.folder_id)).all())
    folders = db.execute(select(FavFolder, FavDimension.name).join(FavDimension, FavDimension.id == FavFolder.dimension_id)
                         .where(FavDimension.owner_id == uid).order_by(FavDimension.sort, FavFolder.sort)).all()
    return {
        "total": total,
        "by_category": [{"name": k, "count": v} for k, v in by_cat.most_common()],
        "folders": [{"id": f.id, "name": f.name, "emoji": f.emoji or "", "dimension": dim, "count": counts.get(f.id, 0),
                     "shared": bool(f.share_token), "share_status": "sharing" if f.share_token else "private"}
                    for f, dim in folders],
    }


def _subscriptions(db: Session, uid: int):
    rows = db.execute(select(CategorySubscription, Category).join(Category, Category.id == CategorySubscription.category_id)
                      .where(CategorySubscription.user_id == uid).order_by(CategorySubscription.created_at)).all()
    # 订阅即开启每日上新汇总（站内消息）；没有单独的开关
    return {"total": len(rows), "daily_push": bool(rows),
            "items": [{"category_id": c.id, "name": c.name, "is_parent": c.parent_id is None,
                       "last_notified_at": s.last_notified_at, "created_at": s.created_at} for s, c in rows]}


@router.get("/users/{user_id}/content")
def user_content(user_id: int, db: Session = Depends(get_db)):
    u = _user_or_404(db, user_id)
    out = {name: _section(db, u.id, name) for name in SECTIONS}
    avg = db.scalar(select(func.avg(Comment.rating)).where(Comment.user_id == u.id, Comment.rating.is_not(None)))
    rated = db.scalar(select(func.count()).select_from(Comment).where(Comment.user_id == u.id, Comment.rating.is_not(None))) or 0
    out["comments"]["avg_rating"] = round(float(avg), 2) if avg is not None else None
    out["comments"]["rated_count"] = rated
    out["favorites"] = _favorites(db, u.id)
    out["subscriptions"] = _subscriptions(db, u.id)
    return {"id": u.id, "label": users.label(u), **out}


@router.get("/users/{user_id}/content/{section}")
def user_content_page(user_id: int, section: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      db: Session = Depends(get_db)):
    if section not in SECTIONS:
        _err(404, "unknown_section", "没有这个分区")
    u = _user_or_404(db, user_id)
    return _section(db, u.id, section, page, page_size)


# ---------------------------------------------------------------- 保存的筛选视图
VIEW_SCOPES = {"users"}
VIEW_MAX = 20


class ViewIn(BaseModel):
    scope: str
    name: str = Field(min_length=1, max_length=40)
    query: dict[str, str] = Field(default_factory=dict)


class ViewPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    query: dict[str, str] | None = None
    position: int | None = None


def _view_out(v: AdminView):
    return {"id": v.id, "scope": v.scope, "name": v.name, "query": v.query or {}, "position": v.position,
            "created_at": v.created_at, "updated_at": v.updated_at}


def _check_name(db: Session, me: User, scope: str, name: str, exclude: int | None = None):
    q = select(AdminView.id).where(AdminView.user_id == me.id, AdminView.scope == scope, AdminView.name == name)
    if exclude:
        q = q.where(AdminView.id != exclude)
    if db.scalar(q):
        _err(400, "duplicate_name", "已经有同名的视图")


def _my_view(db: Session, me: User, view_id: int) -> AdminView:
    v = db.get(AdminView, view_id)
    if v is None or v.user_id != me.id:
        _err(404, "not_found", "视图不存在")
    return v


@router.get("/views")
def list_views(scope: str = Query(...), db: Session = Depends(get_db), me: User = Depends(require_admin)):
    rows = db.scalars(select(AdminView).where(AdminView.user_id == me.id, AdminView.scope == scope)
                      .order_by(AdminView.position, AdminView.id)).all()
    return {"items": [_view_out(v) for v in rows], "max": VIEW_MAX}


@router.post("/views")
def create_view(body: ViewIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    if body.scope not in VIEW_SCOPES:
        _err(400, "bad_scope", "不支持的页面")
    name = body.name.strip()
    if not name:
        _err(400, "bad_name", "请填写视图名称")
    n = db.scalar(select(func.count()).select_from(AdminView).where(AdminView.user_id == me.id, AdminView.scope == body.scope)) or 0
    if n >= VIEW_MAX:
        _err(400, "too_many", f"每个页面最多保存 {VIEW_MAX} 个视图")
    _check_name(db, me, body.scope, name)
    top = db.scalar(select(func.max(AdminView.position)).where(AdminView.user_id == me.id, AdminView.scope == body.scope))
    v = AdminView(user_id=me.id, scope=body.scope, name=name, query={k: str(x) for k, x in body.query.items()},
                  position=(top or 0) + 1)
    db.add(v)
    db.commit()
    return _view_out(v)


@router.put("/views/{view_id}")
def update_view(view_id: int, body: ViewPatch, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    v = _my_view(db, me, view_id)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            _err(400, "bad_name", "请填写视图名称")
        _check_name(db, me, v.scope, name, exclude=v.id)
        v.name = name
    if body.query is not None:
        v.query = {k: str(x) for k, x in body.query.items()}
    if body.position is not None:
        v.position = body.position
    db.commit()
    return _view_out(v)


@router.delete("/views/{view_id}")
def delete_view(view_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    v = _my_view(db, me, view_id)
    db.delete(v)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 全局搜索
@router.get("/search")
def global_search(q: str = Query(""), limit: int = Query(5, ge=1, le=10), db: Session = Depends(get_db)):
    q = q.strip()
    num = int(q.lstrip("#")) if q.lstrip("#").isdigit() else None
    if num is None and len(q) < 2:
        return {"q": q, "users": [], "items": [], "feedback": []}
    like = f"%{q}%"

    def merge(exact, fuzzy):
        seen, out = set(), []
        for r in list(exact) + list(fuzzy):
            if r.id not in seen:
                seen.add(r.id)
                out.append(r)
        return out[:limit]

    u_exact = [x for x in [db.get(User, num)] if x] if num is not None else []
    u_fuzzy = db.scalars(select(User).where(or_(User.email.ilike(like), User.nickname.ilike(like), User.remark.ilike(like),
                                                User.username.ilike(like))).order_by(User.id.desc()).limit(limit)).all()
    i_exact = [x for x in [db.get(Item, num)] if x] if num is not None else []
    i_fuzzy = db.scalars(select(Item).outerjoin(Repo, Repo.id == Item.repo_id)
                         .where(or_(Item.name.ilike(like), Repo.full_name.ilike(like))).order_by(Item.id.desc()).limit(limit)).all()
    f_exact = [x for x in [db.get(Feedback, num)] if x] if num is not None else []
    f_fuzzy = db.scalars(select(Feedback).where(Feedback.content.ilike(like)).order_by(Feedback.id.desc()).limit(limit)).all()
    return {
        "q": q,
        "users": [{"id": u.id, "label": u.remark or u.nickname or users.account_id(u), "sub": users.account_id(u),
                   "status": u.status, "status_label": STATUS_LABEL.get(u.status, u.status)} for u in merge(u_exact, u_fuzzy)],
        "items": [{"id": it.id, "label": it.name, "sub": it.repo.full_name if it.repo else "",
                   "status": it.status, "status_label": ITEM_STATUS.get(it.status, it.status)} for it in merge(i_exact, i_fuzzy)],
        "feedback": [{"id": f.id, "label": f.content[:40] + ("…" if len(f.content) > 40 else ""),
                      "sub": FB_CATEGORIES.get(f.category, f.category),
                      "status": f.status, "status_label": FB_STATUSES.get(f.status, f.status)} for f in merge(f_exact, f_fuzzy)],
    }
