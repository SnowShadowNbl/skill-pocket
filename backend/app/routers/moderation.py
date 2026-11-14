"""v3.3.44 后台批次 2a：评论处置、理由模板、分享页管理、搜索词（大家在搜屏蔽 / 无结果搜索）。

并发保护：处置接口的 body 可带 expected_status（前端看到的状态）；与当前状态不一致，或当前状态不能执行这个操作，
返回 409 {code: already_handled, message, handled_by, handled_at, status}。
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..auth import require_admin, require_super
from ..db import get_db, utcnow
from ..models import (ActivityLog, Category, Comment, FavDimension, Favorite, FavFolder, FavoriteFolderLink, Item,
                      ReasonTemplate, Repo, SearchTerm, User)
from ..schemas import comment_out, item_card
from ..services import activity, ratings, users
from ..services import search_terms as terms

router = APIRouter(prefix="/api/admin", tags=["admin-moderation"], dependencies=[Depends(require_admin)])

REASON_MIN = 2


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _who(db: Session, uid: int | None) -> dict | None:
    if not uid:
        return None
    u = db.get(User, uid)
    return {"id": uid, "label": users.label(u) if u else f"用户 #{uid}"}


def _already(db: Session, status: str, by: int | None, at, label: str):
    who = _who(db, by)
    _err(409, "already_handled", f"已被{who['label'] if who else '其他人'}处理（当前：{label}）",
         handled_by=who, handled_at=at, status=status)


def _need_reason(reason: str) -> str:
    r = (reason or "").strip()
    if len(r) < REASON_MIN:
        _err(400, "reason_required", "请填写原因")
    return r


# ================================================================ 评论
COMMENT_STATUS = {"pending": "待审核", "visible": "已公开", "rejected": "已驳回", "deleted": "已删除"}
# 操作 → (允许的当前状态, 目标状态, 是否必填原因)
TRANSITIONS = {
    "approve": (("pending", "rejected"), "visible", False),
    "reject": (("pending", "visible"), "rejected", True),
    "delete": (("pending", "visible", "rejected"), "deleted", True),
    "restore": (("deleted", "rejected"), "visible", True),
}
ACTION_LABEL = {"approve": "通过", "reject": "驳回", "delete": "删除", "restore": "恢复"}


def _rating(item: Item | None) -> dict:
    return {"avg": round(item.rating_avg, 2) if item and item.rating_avg is not None else None,
            "count": item.rating_count if item else 0}


def _comment_row(db: Session, c: Comment, me: User) -> dict:
    return {**comment_out(c, me), "item_name": c.item.name if c.item else "", "review_reason": c.review_reason or "",
            "status_label": COMMENT_STATUS.get(c.status, c.status), "user_label": users.label(c.user) if c.user else "历史用户",
            "handled": {"by": _who(db, c.handled_by), "at": c.handled_at, "reason": c.handle_reason or ""} if c.handled_at else None}


@router.get("/comments")
def list_comments(status: str = Query("pending", pattern="^(pending|visible|rejected|deleted|all)$"), q: str = "",
                  user_id: int | None = None, item_id: int | None = None, id: int | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                  db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """评论审核列表。传 id 时只返回这一条（不管状态），用于从别处直达。"""
    stmt = select(Comment)
    if id is not None:
        stmt = stmt.where(Comment.id == id)
    else:
        if status != "all":
            stmt = stmt.where(Comment.status == status)
        if user_id:
            stmt = stmt.where(Comment.user_id == user_id)
        if item_id:
            stmt = stmt.where(Comment.item_id == item_id)
        if q.strip():
            stmt = stmt.where(Comment.content.ilike(f"%{q.strip()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.options(joinedload(Comment.user), joinedload(Comment.item)).order_by(Comment.created_at.desc(), Comment.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    counts = dict(db.execute(select(Comment.status, func.count()).group_by(Comment.status)).all())
    return {"total": total, "page": page, "page_size": page_size,
            "counts": {k: counts.get(k, 0) for k in COMMENT_STATUS},
            "items": [_comment_row(db, c, me) for c in rows]}


class CommentActIn(BaseModel):
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


def _act(action: str, comment_id: int, body: CommentActIn | None, db: Session, me: User) -> dict:
    body = body or CommentActIn()
    c = db.get(Comment, comment_id)
    if c is None:
        _err(404, "not_found", "评论不存在")
    allowed, target, need = TRANSITIONS[action]
    if (body.expected_status and body.expected_status != c.status) or c.status not in allowed:
        _already(db, c.status, c.handled_by, c.handled_at, COMMENT_STATUS.get(c.status, c.status))
    reason = _need_reason(body.reason) if need else body.reason.strip()
    item = db.get(Item, c.item_id)
    before_rating = _rating(item)
    old = c.status
    c.status, c.handled_by, c.handled_at, c.handle_reason = target, me.id, utcnow(), reason
    db.commit()
    if c.rating is not None:
        ratings.recompute(db, c.item_id)
        db.refresh(item)
    after_rating = _rating(item)
    activity.record(f"comment_{action}", f"{ACTION_LABEL[action]}评论 #{c.id}：{c.content[:60]}", user=me, target_type="comment",
                    target_id=c.id, reason=reason, before={"status": old, "rating": before_rating},
                    after={"status": target, "rating": after_rating},
                    target_label=f"「{item.name if item else ''}」的评论 #{c.id}")
    return {"ok": True, "comment": _comment_row(db, c, me), "item_rating": {"before": before_rating, "after": after_rating}}


@router.post("/comments/{comment_id}/approve")
def approve(comment_id: int, body: CommentActIn | None = None, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    return _act("approve", comment_id, body, db, me)


@router.post("/comments/{comment_id}/reject")
def reject(comment_id: int, body: CommentActIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    return _act("reject", comment_id, body, db, me)


@router.post("/comments/{comment_id}/delete")
def delete(comment_id: int, body: CommentActIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    return _act("delete", comment_id, body, db, me)


@router.post("/comments/{comment_id}/restore")
def restore(comment_id: int, body: CommentActIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    return _act("restore", comment_id, body, db, me)


@router.get("/comments/{comment_id}/history")
def comment_history(comment_id: int, db: Session = Depends(get_db)):
    c = db.get(Comment, comment_id)
    if c is None:
        _err(404, "not_found", "评论不存在")
    logs = db.scalars(select(ActivityLog).where(
        or_((ActivityLog.target_type == "comment") & (ActivityLog.target_id == c.id),
            ActivityLog.action.in_(("comment_approve", "comment_delete")) & (ActivityLog.target_type == "item")
            & (ActivityLog.target_id == c.item_id) & ActivityLog.summary.like(f"%评论 #{c.id}：%")),
    ).order_by(ActivityLog.id)).all()
    out = [{"action": "create", "label": "发表", "by": _who(db, c.user_id), "at": c.created_at,
            "reason": c.review_reason or "", "status": "pending" if c.review_reason else "visible", "rating": None}]
    for r in logs:
        act = r.action.removeprefix("comment_")
        out.append({"action": act, "label": ACTION_LABEL.get(act, act), "by": _who(db, r.user_id), "at": r.created_at,
                    "reason": r.reason or "", "status": (r.after or {}).get("status"),
                    "rating": {"before": (r.before or {}).get("rating"), "after": (r.after or {}).get("rating")} if r.after else None})
    return {"id": c.id, "status": c.status, "items": out}


# ================================================================ 理由模板
TEMPLATE_SCOPES = {"item_reject": "驳回条目", "item_revoke": "下架条目", "comment_reject": "驳回评论", "comment_delete": "删除评论",
                   "share_close": "关闭分享", "takedown_approve": "同意下架申请", "takedown_reject": "驳回下架申请"}
DEFAULT_TEMPLATES = [
    ("item_reject", "与 AI / 开发工具无关"), ("item_reject", "仓库内容过少或无法使用"), ("item_reject", "与已有条目重复"),
    ("item_revoke", "原仓库已删除或不可访问"), ("item_revoke", "内容违规或存在安全风险"),
    ("comment_reject", "广告或引流"), ("comment_reject", "与条目无关"), ("comment_reject", "不友善或人身攻击"),
    ("comment_delete", "广告或引流"), ("comment_delete", "违法违规内容"), ("comment_delete", "用户要求删除"),
    ("share_close", "分享内容涉嫌违规"), ("share_close", "分享名称不当"),
    ("takedown_approve", "已核实为项目作者"), ("takedown_approve", "作者要求不再收录"),
    ("takedown_reject", "无法确认申请人是作者"), ("takedown_reject", "该仓库是公开的开源项目"),
    ("takedown_reject", "证据不足，请补充后再申请"),
]


def seed_templates(db: Session) -> None:
    """每个类型第一次出现时放入它的默认模板（记在 app_meta，之后管理员删光也不会再补）。"""
    from ..models import AppMeta

    meta = db.get(AppMeta, "reason_template_scopes")
    done = set((meta.value if meta else "").split(",")) - {""}
    if not done and db.scalar(select(func.count()).select_from(ReasonTemplate)):
        done = set(db.scalars(select(ReasonTemplate.scope).distinct()))  # v3.3.44 已放过默认模板的老库
    todo = [k for k in TEMPLATE_SCOPES if k not in done]
    if not todo:
        return
    db.add_all([ReasonTemplate(scope=s, text=t, position=i) for i, (s, t) in enumerate(DEFAULT_TEMPLATES) if s in todo])
    db.merge(AppMeta(key="reason_template_scopes", value=",".join(sorted(done | set(TEMPLATE_SCOPES)))))
    db.commit()


def _tpl_out(t: ReasonTemplate) -> dict:
    return {"id": t.id, "scope": t.scope, "scope_label": TEMPLATE_SCOPES.get(t.scope, t.scope), "text": t.text, "position": t.position}


class TemplateIn(BaseModel):
    scope: str
    text: str = Field(min_length=1, max_length=300)


class TemplatePatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=300)
    position: int | None = None


@router.get("/reason-templates")
def list_templates(scope: str = "", db: Session = Depends(get_db)):
    seed_templates(db)
    stmt = select(ReasonTemplate).order_by(ReasonTemplate.scope, ReasonTemplate.position, ReasonTemplate.id)
    if scope:
        stmt = stmt.where(ReasonTemplate.scope == scope)
    return {"scopes": TEMPLATE_SCOPES, "items": [_tpl_out(t) for t in db.scalars(stmt)]}


@router.post("/reason-templates")
def create_template(body: TemplateIn, db: Session = Depends(get_db), me: User = Depends(require_super)):
    if body.scope not in TEMPLATE_SCOPES:
        _err(400, "bad_scope", "不支持的模板类型")
    text = body.text.strip()
    if db.scalar(select(ReasonTemplate.id).where(ReasonTemplate.scope == body.scope, ReasonTemplate.text == text)):
        _err(400, "duplicate", "已经有这条模板")
    top = db.scalar(select(func.max(ReasonTemplate.position)).where(ReasonTemplate.scope == body.scope))
    t = ReasonTemplate(scope=body.scope, text=text, position=(top or 0) + 1, created_by=me.id)
    db.add(t)
    db.commit()
    return _tpl_out(t)


@router.put("/reason-templates/{tpl_id}")
def update_template(tpl_id: int, body: TemplatePatch, db: Session = Depends(get_db), me: User = Depends(require_super)):
    t = db.get(ReasonTemplate, tpl_id)
    if t is None:
        _err(404, "not_found", "模板不存在")
    if body.text is not None:
        t.text = body.text.strip()
    if body.position is not None:
        t.position = body.position
    db.commit()
    return _tpl_out(t)


@router.delete("/reason-templates/{tpl_id}")
def delete_template(tpl_id: int, db: Session = Depends(get_db), me: User = Depends(require_super)):
    t = db.get(ReasonTemplate, tpl_id)
    if t is None:
        _err(404, "not_found", "模板不存在")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ================================================================ 分享页
SHARE_STATUS = {"sharing": "分享中", "closed": "已被关闭"}


def _share_status(f: FavFolder) -> str:
    return "closed" if f.share_closed_at else "sharing"


def _share_out(db: Session, f: FavFolder, owner: User | None, count: int) -> dict:
    st = _share_status(f)
    return {"id": f.id, "name": f.name, "emoji": f.emoji or "", "dimension": f.dimension.name if f.dimension else "",
            "owner": {"id": owner.id, "label": users.label(owner)} if owner else None, "count": count,
            "views": f.share_views, "status": st, "status_label": SHARE_STATUS[st],
            "path": f"/s/{f.share_token}" if f.share_token else "", "created_at": f.created_at,
            "closed": {"by": _who(db, f.share_closed_by), "at": f.share_closed_at, "reason": f.share_closed_reason} if f.share_closed_at else None}


def _folder_counts(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    return dict(db.execute(select(FavoriteFolderLink.folder_id, func.count()).select_from(FavoriteFolderLink)
                           .join(Favorite, Favorite.id == FavoriteFolderLink.favorite_id).join(Item, Item.id == Favorite.item_id)
                           .where(FavoriteFolderLink.folder_id.in_(ids), Item.status == "published")
                           .group_by(FavoriteFolderLink.folder_id)).all())


@router.get("/shares")
def list_shares(status: str = Query("", pattern="^(|sharing|closed)$"), q: str = "", owner_id: int | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    """公开分享过的收藏分类（分享中 + 被管理员关闭的）。q 匹配分类名、分享人邮箱 / 昵称 / 备注名。"""
    stmt = (select(FavFolder, User).join(FavDimension, FavDimension.id == FavFolder.dimension_id)
            .outerjoin(User, User.id == FavDimension.owner_id)
            .where(or_(FavFolder.share_token.is_not(None), FavFolder.share_closed_at.is_not(None))))
    if status == "sharing":
        stmt = stmt.where(FavFolder.share_closed_at.is_(None))
    elif status == "closed":
        stmt = stmt.where(FavFolder.share_closed_at.is_not(None))
    if owner_id:
        stmt = stmt.where(FavDimension.owner_id == owner_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(FavFolder.name.ilike(like), User.email.ilike(like), User.nickname.ilike(like), User.remark.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(FavFolder.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    counts = _folder_counts(db, [f.id for f, _ in rows])
    return {"total": total, "page": page, "page_size": page_size,
            "items": [_share_out(db, f, u, counts.get(f.id, 0)) for f, u in rows]}


def _share(db: Session, folder_id: int) -> FavFolder:
    f = db.get(FavFolder, folder_id)
    if f is None or (not f.share_token and not f.share_closed_at):
        _err(404, "not_found", "分享不存在")
    return f


@router.get("/shares/{folder_id}/preview")
def preview_share(folder_id: int, db: Session = Depends(get_db)):
    """后台预览：和公开页一样的内容（已关闭的也能看）。"""
    f = _share(db, folder_id)
    owner = db.get(User, f.dimension.owner_id)
    items = db.scalars(
        select(Item).join(Favorite, Favorite.item_id == Item.id).join(FavoriteFolderLink, FavoriteFolderLink.favorite_id == Favorite.id)
        .outerjoin(Repo, Repo.id == Item.repo_id)
        .options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
        .where(FavoriteFolderLink.folder_id == f.id, Item.status == "published").order_by(Favorite.created_at.desc())
    ).unique().all()
    return {"share": _share_out(db, f, owner, len(items)), "items": [item_card(it) for it in items]}


class ShareActIn(BaseModel):
    reason: str = Field("", max_length=300)
    expected_status: str | None = None


@router.post("/shares/{folder_id}/close")
def close_share(folder_id: int, body: ShareActIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = _share(db, folder_id)
    st = _share_status(f)
    if (body.expected_status and body.expected_status != st) or st == "closed":
        _already(db, st, f.share_closed_by, f.share_closed_at, SHARE_STATUS[st])
    reason = _need_reason(body.reason)
    f.share_closed_at, f.share_closed_by, f.share_closed_reason = utcnow(), me.id, reason
    db.commit()
    owner = db.get(User, f.dimension.owner_id)
    activity.record("share_close", f"关闭分享「{f.name}」", user=me, target_type="user", target_id=owner.id if owner else None,
                    reason=reason, before={"status": "sharing"}, after={"status": "closed"},
                    target_label=f"{users.label(owner) if owner else ''} 的分享「{f.name}」")
    return _share_out(db, f, owner, _folder_counts(db, [f.id]).get(f.id, 0))


@router.post("/shares/{folder_id}/reopen")
def reopen_share(folder_id: int, body: ShareActIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    f = _share(db, folder_id)
    st = _share_status(f)
    if (body.expected_status and body.expected_status != st) or st != "closed":
        _already(db, st, f.share_closed_by, f.share_closed_at, SHARE_STATUS[st])
    reason = _need_reason(body.reason)
    f.share_closed_at, f.share_closed_by, f.share_closed_reason = None, None, ""
    db.commit()
    owner = db.get(User, f.dimension.owner_id)
    activity.record("share_reopen", f"解除分享关闭「{f.name}」", user=me, target_type="user", target_id=owner.id if owner else None,
                    reason=reason, before={"status": "closed"}, after={"status": "sharing" if f.share_token else "private"},
                    target_label=f"{users.label(owner) if owner else ''} 的分享「{f.name}」")
    if not f.share_token:  # 用户在关闭期间取消了分享：解除后不在列表里
        return {"id": f.id, "status": "private", "status_label": "未分享"}
    return _share_out(db, f, owner, _folder_counts(db, [f.id]).get(f.id, 0))


# ================================================================ 搜索词
def _term_out(db: Session, t: SearchTerm) -> dict:
    return {"id": t.id, "term": t.shown or t.term, "key": t.term, "searches": t.searches, "empty_count": t.empty_count,
            "last_results": t.last_results, "last_at": t.last_at,
            "blocked": {"by": _who(db, t.blocked_by), "at": t.blocked_at, "reason": t.block_reason} if t.blocked else None,
            "covered": {"by": _who(db, t.covered_by), "at": t.covered_at, "note": t.covered_note} if t.covered_at else None}


@router.get("/search-terms/hot")
def hot_terms(db: Session = Depends(get_db)):
    """首页「大家在搜」的候选词：status=shown 展示中 / filtered 被过滤（reason：blocked / risk / length / few_people / rank）。"""
    return {"items": terms.hot_candidates(db, limit=50), "window_days": terms.HOT_DAYS, "min_people": terms.HOT_MIN_PEOPLE,
            "shown_max": terms.HOT_SHOWN}


@router.get("/search-terms/empty")
def empty_terms(status: str = Query("open", pattern="^(open|covered|all)$"), sort: str = Query("count", pattern="^(count|recent)$"),
                days: int = Query(30, ge=1, le=180), page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                db: Session = Depends(get_db)):
    """无结果搜索：站内搜索返回 0 条的词（v3.3.44 起服务端统计）。"""
    stmt = select(SearchTerm).where(SearchTerm.empty_count > 0, SearchTerm.last_at >= utcnow() - timedelta(days=days))
    if status == "open":
        stmt = stmt.where(SearchTerm.covered_at.is_(None))
    elif status == "covered":
        stmt = stmt.where(SearchTerm.covered_at.is_not(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = (SearchTerm.empty_count.desc(), SearchTerm.last_at.desc()) if sort == "count" else (SearchTerm.last_at.desc(),)
    rows = db.scalars(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_term_out(db, t) for t in rows]}


class CoverIn(BaseModel):
    note: str = Field("", max_length=200)


@router.post("/search-terms/{term_id}/cover")
def cover_term(term_id: int, body: CoverIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = db.get(SearchTerm, term_id)
    if t is None:
        _err(404, "not_found", "搜索词不存在")
    t.covered_at, t.covered_by, t.covered_note = utcnow(), me.id, body.note.strip()
    db.commit()
    activity.record("search_cover", f"无结果搜索标记已补收录：{t.shown or t.term}", user=me, target_type="search_term", target_id=t.id,
                    reason=t.covered_note)
    return _term_out(db, t)


@router.delete("/search-terms/{term_id}/cover")
def uncover_term(term_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = db.get(SearchTerm, term_id)
    if t is None:
        _err(404, "not_found", "搜索词不存在")
    t.covered_at, t.covered_by, t.covered_note = None, None, ""
    db.commit()
    return _term_out(db, t)


@router.get("/search-blocklist")
def blocklist(db: Session = Depends(get_db)):
    rows = db.scalars(select(SearchTerm).where(SearchTerm.blocked.is_(True)).order_by(SearchTerm.blocked_at.desc())).all()
    return {"items": [_term_out(db, t) for t in rows]}


class BlockIn(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    reason: str = Field("", max_length=200)


@router.post("/search-blocklist")
def block_term(body: BlockIn, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = terms.get_or_create(db, body.term)
    if t is None:
        _err(400, "bad_term", "请填写要屏蔽的词")
    if t.blocked:
        _err(400, "duplicate", "这个词已经屏蔽了")
    t.blocked, t.blocked_by, t.blocked_at, t.block_reason = True, me.id, utcnow(), body.reason.strip()
    db.commit()
    terms.invalidate_hot()
    activity.record("search_block", f"「大家在搜」屏蔽：{t.shown or t.term}", user=me, target_type="search_term", target_id=t.id,
                    reason=t.block_reason)
    return _term_out(db, t)


@router.delete("/search-blocklist/{term_id}")
def unblock_term(term_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = db.get(SearchTerm, term_id)
    if t is None or not t.blocked:
        _err(404, "not_found", "屏蔽词不存在")
    t.blocked, t.blocked_by, t.blocked_at, t.block_reason = False, None, None, ""
    db.commit()
    terms.invalidate_hot()
    activity.record("search_unblock", f"「大家在搜」取消屏蔽：{t.shown or t.term}", user=me, target_type="search_term", target_id=t.id)
    return {"ok": True}
