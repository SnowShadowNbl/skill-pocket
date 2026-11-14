import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from datetime import datetime, time, timezone

from sqlalchemy import BigInteger, case, cast, func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from fastapi import Request

from ..auth import can as auth_can, client_ip, current_user, current_user_optional, is_admin, require_admin
from ..config import settings
from ..db import get_db, utcnow
from ..models import Category, Comment, FavFolder, User, Favorite, FavoriteFolderLink, Item, Ranking, RankingEntry, Repo, StarSnapshot
from ..schemas import CommentIn, ImportIn, ItemCreate, ItemUpdate, PreviewIn, comment_out, item_card, item_detail
from ..services import activity, crawler, ingest, moderation, pins, quota, ratings, review, search, search_terms, thumbs, tracking
from ..seed import KINDS
from ..services.github import GitHubError
from .favorites import fav_ids, folder_ids_of

router = APIRouter(prefix="/api", tags=["items"])


def _get_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id, options=[joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent)])
    if item is None:
        raise HTTPException(404, "条目不存在")
    return item


@router.get("/items")
def list_items(
    q: str = "",
    category: str = Query("", description="子类或大类 code"),
    source: str = Query("", pattern="^(|auto|manual)$"),
    sort: str = Query("stars", pattern="^(today|stars|collected|favorited|foryou)$"),
    kind: str = Query("", description="使用类型；none 表示未判定"),
    fav: str = Query("", description="只看收藏：1 / true"),
    fav_folder: str = Query("", description="收藏分类 id；配合 fav_dim 传 none 表示该维度下未整理"),
    fav_dim: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
    me: User | None = Depends(current_user_optional),
):
    # 主页只列已上线的；搜索和收藏里也能看到已下线的（卡片盖「原文已下线」水印）
    visible = ("published", "offline") if q or fav or fav_folder else ("published",)
    stmt = (select(Item).outerjoin(Repo, Item.repo_id == Repo.id)
            .options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent), joinedload(Item.creator))
            .where(Item.status.in_(visible)))

    owner = me.id if me else None
    only_fav = fav.lower() in ("1", "true", "yes") or bool(fav_folder)
    if only_fav and me is None:
        raise HTTPException(401, "请先登录", headers={"X-Login-Required": "1"})
    if sort == "favorited" and me is None:
        sort = "collected"
    prefs = _preferences(db, me.id) if sort == "foryou" and me else {}
    if sort == "foryou" and not prefs:
        sort = "today"  # 没登录或还没有收藏 / 浏览记录：退回「今日」
    if only_fav or sort == "favorited":
        stmt = stmt.join(Favorite, (Favorite.item_id == Item.id) & (Favorite.owner_id == owner), isouter=not only_fav)
    for word in q.split():
        like = f"%{word}%"
        fields = [Item.name, Item.summary, Item.description, Repo.full_name] + ([Favorite.note] if only_fav else [])
        stmt = stmt.where(or_(*(f.ilike(like) for f in fields)))
    if category:
        cat = db.scalar(select(Category).where(Category.code == category))
        if cat is not None and cat.merged_into_id:  # v3.3.50 被合并的分类：旧链接改看合并到的分类
            cat = db.get(Category, cat.merged_into_id) or cat
        if cat is None:
            raise HTTPException(400, f"未知分类 {category}")
        ids = [cat.id] + [c.id for c in cat.children]
        stmt = stmt.where(Item.category_id.in_(ids))
    if source:
        stmt = stmt.where(Item.source == source)
    if kind:
        if kind != "none" and kind not in KINDS:
            raise HTTPException(400, f"未知使用类型 {kind}")
        stmt = stmt.where(Item.kind == ("" if kind == "none" else kind))
    if fav_folder == "none" and fav_dim is not None:
        folders = select(FavFolder.id).where(FavFolder.dimension_id == fav_dim)
        organized = select(FavoriteFolderLink.favorite_id).where(FavoriteFolderLink.folder_id.in_(folders))
        stmt = stmt.where(Favorite.id.not_in(organized))
    elif fav_folder.isdigit():
        stmt = stmt.where(Favorite.id.in_(select(FavoriteFolderLink.favorite_id).where(FavoriteFolderLink.folder_id == int(fav_folder))))

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    if q.strip() and page == 1 and not (category or kind or only_fav or source) and not search.enabled():
        search_terms.record(q, total)  # v3.3.44 语义搜索不可用时，按名称匹配的结果数统计
    if sort == "today":
        stmt = _order_today(db, stmt)
    elif sort == "stars":
        stmt = stmt.order_by(func.coalesce(Repo.stars, -1).desc(), Item.collected_at.desc())
    elif sort == "favorited":
        stmt = stmt.order_by(Favorite.created_at.desc().nulls_last(), Item.collected_at.desc())
    elif sort == "foryou":
        mine = select(Favorite.item_id).where(Favorite.owner_id == owner)
        weight = case(*[(Item.category_id == cid, w) for cid, (w, _) in prefs.items()], else_=0)
        stmt = stmt.order_by(case((Item.id.in_(mine), 1), else_=0), weight.desc(), func.coalesce(Repo.stars, -1).desc(), Item.id.desc())
    else:
        stmt = stmt.order_by(Item.collected_at.desc())
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).unique().all()
    favs = fav_ids(db, owner)
    out = [item_card(i, favs) for i in rows]
    if only_fav and owner:
        # v3.3「最近在用」：近 14 天在这个条目下写过使用日志
        from datetime import timedelta
        recent = set(db.scalars(select(Comment.item_id).where(Comment.user_id == owner, Comment.created_at >= utcnow() - timedelta(days=14),
                                                              Comment.item_id.in_([i.id for i in rows] or [-1]))))
        for card in out:
            if card["id"] in recent:
                card["in_use"] = True
    if sort == "foryou":
        # 给推荐的条目一句「为什么推荐」（卡片上显示）
        for card, it in zip(out, rows):
            why = prefs.get(it.category_id)
            if why and it.id not in favs:
                card["match"] = {"reason": why[1]}
    return {"total": total, "page": page, "size": size, "items": out}


def _preferences(db: Session, user_id: int) -> dict[int, tuple[float, str]]:
    """v3.3 为你推荐：按收藏（权重 3）和最近 30 天浏览（权重 1）统计子类偏好；同一大类下的其他子类给一半权重。
    返回 {子类 id: (权重, 推荐理由)}，只取最靠前的 12 个子类。"""
    from datetime import timedelta

    from ..models import Event

    score: dict[int, float] = {}
    for (cid,) in db.execute(select(Item.category_id).join(Favorite, Favorite.item_id == Item.id).where(Favorite.owner_id == user_id)):
        score[cid] = score.get(cid, 0) + 3
    since = utcnow() - timedelta(days=30)
    viewed = [p.get("item_id") for p in db.scalars(select(Event.props).where(Event.user_id == user_id, Event.name == "item_view",
                                                                              Event.created_at >= since).limit(500)) if p]
    ids = [i for i in viewed if isinstance(i, int)]
    if ids:
        cats = dict(db.execute(select(Item.id, Item.category_id).where(Item.id.in_(ids))).all())
        for i in ids:
            if i in cats:
                score[cats[i]] = score.get(cats[i], 0) + 1
    if not score:
        return {}
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.parent_id.is_not(None)))}
    group_score: dict[int, float] = {}
    for cid, sc in score.items():
        if cid in cats:
            group_score[cats[cid].parent_id] = group_score.get(cats[cid].parent_id, 0) + sc
    out: dict[int, tuple[float, str]] = {}
    for cid, c in cats.items():
        w = score.get(cid, 0) + 0.5 * (group_score.get(c.parent_id, 0) - score.get(cid, 0))
        if w > 0:
            reason = f"你常看「{c.name}」" if score.get(cid) else f"和你关注的「{c.parent.name if c.parent else c.name}」相关"
            out[cid] = (w, reason)
    return dict(sorted(out.items(), key=lambda kv: -kv[1][0])[:12])


def _order_today(db: Session, stmt):
    """首页默认排序「今日」：管理员置顶的最前（按权重）→ 今天新收录的（按星标，v3.3.10 提到涨星前面）
    → 最近一天星标涨得多的（每个仓库只算一个条目）→ 其余按日期打散。
    v3.3.10 之前新收录排在涨星后面：新条目还没有前一天的快照、涨星算 0，每天几十个涨星条目会把当天新收录的压到后几页。
    打散用「(id + 日期) × 大质数 取模」：同一天内顺序固定（翻页不乱），换一天就不一样。"""
    d1 = db.scalar(select(func.max(StarSnapshot.snap_date)))
    d0 = db.scalar(select(func.max(StarSnapshot.snap_date)).where(StarSnapshot.snap_date < d1)) if d1 else None
    today = datetime.now().date()
    seed = today.toordinal() % 100000
    shuffle = (cast(Item.id + seed, BigInteger) * 2654435761) % 4294967291  # Postgres 上 int 会溢出，转 bigint
    is_fresh = Item.collected_at >= datetime.combine(today, time.min).astimezone(timezone.utc)
    fresh = case((is_fresh, 1), else_=0)
    fresh_stars = case((is_fresh, func.coalesce(Repo.stars, 0)), else_=-1)  # 今天新收录的按星标排
    if d0 is None:
        return stmt.order_by(pins.effective_weight().desc(), fresh.desc(), fresh_stars.desc(), shuffle)
    s1, s0 = aliased(StarSnapshot), aliased(StarSnapshot)
    delta = (select(s1.repo_id.label("repo_id"), (s1.stars - s0.stars).label("d"))
             .join(s0, (s0.repo_id == s1.repo_id) & (s0.snap_date == d0)).where(s1.snap_date == d1).subquery())
    # 一个仓库拆成很多 Skill 时，只让其中一个（当天打散后排第一的）吃到「今日涨星」的加权，其余回到打散顺序里，
    # 不然首页前排会被同一个仓库的子条目占满
    first_of_repo = func.row_number().over(partition_by=Item.repo_id, order_by=shuffle)
    gain = case(((delta.c.d > 0) & (first_of_repo == 1), delta.c.d), else_=0)
    return stmt.outerjoin(delta, delta.c.repo_id == Item.repo_id).order_by(pins.effective_weight().desc(), fresh.desc(), fresh_stars.desc(), gain.desc(), shuffle)


# ---- 语义搜索 ----

@router.get("/search")
def semantic_search(
    q: str = Query(..., min_length=1, max_length=200),
    kind: str = "",
    category: str = "",
    fav: str = "",
    limit: int = Query(48, le=100),
    stage: str = Query("fast", pattern="^(fast|ai)$"),
    db: Session = Depends(get_db),
    me: User | None = Depends(current_user_optional),
):
    """两段式语义搜索。stage=fast：向量检索立即返回（约 0.4 秒），ai_pending=true 表示 AI 精排还没做；
    前端随后用 stage=ai 再取一次，拿到「AI 理解为」和推荐理由后原地重排。Embedding 不可用时返回 mode=keyword。"""
    if not search.enabled():
        return {"mode": "keyword", "reason": "语义搜索暂不可用"}
    only_fav = fav.lower() in ("1", "true", "yes")
    if only_fav and me is None:
        raise HTTPException(401, "请先登录", headers={"X-Login-Required": "1"})
    stmt = select(Item.id, Item.name, Repo.full_name).outerjoin(Repo, Repo.id == Item.repo_id).where(Item.status.in_(("published", "offline")))
    if kind:
        stmt = stmt.where(Item.kind == ("" if kind == "none" else kind))
    if category:
        cat = db.scalar(select(Category).where(Category.code == category))
        if cat is not None and cat.merged_into_id:  # v3.3.50 被合并的分类：旧链接改看合并到的分类
            cat = db.get(Category, cat.merged_into_id) or cat
        if cat is not None:
            stmt = stmt.where(Item.category_id.in_([cat.id] + [c.id for c in cat.children]))
    if only_fav:
        stmt = stmt.where(Item.id.in_(select(Favorite.item_id).where(Favorite.owner_id == me.id)))
    rows = db.execute(stmt).all()
    allowed = {i for i, _, _ in rows}
    key = q.strip().lower()
    exact = [i for i, name, fn in rows if name.lower() == key or (fn and (fn.lower() == key or fn.split("/")[1].lower() == key))]
    q = q.strip()
    try:
        cand = search.vector_search(q, allowed, exact)
    except search.SearchUnavailable as e:
        return {"mode": "keyword", "reason": str(e)}
    r = search.refine(q, cand, exact, cached_only=stage == "fast")
    ai_pending = r is None and settings.ai_enabled and bool(cand)
    if r is None:
        r = {"understanding": "", "ranked": cand}
    ranked = r["ranked"][:limit]
    if stage == "fast" and not (kind or category or only_fav):
        search_terms.record(q, len(ranked))  # v3.3.44 无结果搜索统计（带筛选的不算）
    items = {i.id: i for i in db.scalars(select(Item).options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent),
                                                               joinedload(Item.creator)).where(Item.id.in_([x["id"] for x in ranked]))).unique()}
    favs = fav_ids(db, me.id if me else None)
    from ..services.extract import model_label
    return {"mode": "semantic", "understanding": r["understanding"], "ai_pending": ai_pending, "ai_model": model_label(), "total": len(ranked),
            "items": [{**item_card(items[x["id"]], favs), "match": {"score": x["score"], "reason": x["reason"]}}
                      for x in ranked if x["id"] in items]}


def _can_view(item: Item, me: User | None) -> bool:
    if item.status in ("published", "offline"):
        return True
    if is_admin(me):
        return True
    # 审核中 / 未通过：只有提交者自己能看
    return me is not None and item.status in ("awaiting", "declined") and item.created_by == me.id


@router.get("/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db), me: User | None = Depends(current_user_optional)):
    item = _get_item(db, item_id)
    if not _can_view(item, me):
        raise HTTPException(404, "条目不存在")
    if item.status == "offline" and not is_admin(me):
        # 已下线：不展示详情，只告诉前端下线了
        fav = db.scalar(select(Favorite.id).where(Favorite.owner_id == me.id, Favorite.item_id == item_id)) if me else None
        return {"id": item.id, "name": item.name, "offline": True, "offline_reason": item.offline_reason,
                "offline_at": item.offline_at, "favorited": fav is not None}
    count = db.scalar(select(func.count()).where(Comment.item_id == item_id, Comment.status.in_(("visible", "pending"))))
    rows = db.execute(
        select(Ranking, RankingEntry, Category.name)
        .join(RankingEntry, RankingEntry.ranking_id == Ranking.id)
        .join(Category, Category.id == Ranking.category_id)
        .where(RankingEntry.item_id == item_id)
        .order_by(Ranking.period_date.desc())
    ).all()
    rankings = [{"period": r.period, "period_date": r.period_date, "category_name": cname, "rank": e.rank,
                 "stars_delta": e.stars_delta, "stars_end": e.stars_end} for r, e, cname in rows]
    fav = db.scalar(select(Favorite).where(Favorite.owner_id == me.id, Favorite.item_id == item_id)) if me else None
    favorite = {"note": fav.note, "created_at": fav.created_at, "folder_ids": folder_ids_of(db, fav.id)} if fav else None
    return item_detail(item, count, rankings, {item_id} if fav else set(), favorite)


# ---- GitHub 导入 ----

@router.post("/import/preview")
def import_preview(body: PreviewIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    try:
        return ingest.preview(db, body.url)
    except GitHubError as e:
        raise HTTPException(400, str(e))


@router.post("/import")
def import_run(body: ImportIn, request: Request, db: Session = Depends(get_db), me: User = Depends(current_user)):
    if not body.picks:
        raise HTTPException(400, "请至少选择一个条目")
    quota.check_ai(db, me)
    quota.check_new_items(db, me, len(body.picks))
    try:
        ids = ingest.import_items(db, body.url, [p.model_dump() for p in body.picks], source="manual", user_id=me.id,
                                  review=review.needs_review(me))
    except GitHubError as e:
        tracking.log(trigger="github", stage="repo", level="error", message=f"导入失败：{e}", repo=body.url, user_id=me.id)
        raise HTTPException(400, str(e))
    task_id = ingest.start_process_task("github", f"GitHub 导入 · {body.url.split('github.com/')[-1][:80]}", ids, workers=2,
                                        user_id=me.id)
    if ids:
        activity.record("item_submit", f"GitHub 链接新增 {len(ids)} 个条目：{body.url[:120]}", user=me, target_type="task",
                        target_id=task_id, detail={"item_ids": ids, "via": "github"}, ip=client_ip(request))
    return {"created": ids, "task_id": task_id}


@router.post("/items")
def create_item(body: ItemCreate, request: Request, db: Session = Depends(get_db), me: User = Depends(current_user)):
    quota.check_ai(db, me)
    quota.check_new_items(db, me, 1)
    needs = review.needs_review(me)
    cat = db.get(Category, body.category_id)
    if cat is None or cat.parent_id is None:
        raise HTTPException(400, "请选择一个子分类")
    data = body.model_dump()
    if data["kind"] and data["kind"] not in KINDS:
        raise HTTPException(400, "未知使用类型")
    item = Item(**data, source="manual", status="awaiting" if needs else "published", review_state="ai" if needs else "",
                ai_status="done", created_by=me.id,
                locked_fields=[k for k in ingest.EDITABLE_FIELDS if data.get(k)])
    db.add(item)
    db.commit()
    tracking.log(trigger="manual_form", stage="save", level="success", message=f"手动填写入库 · 分类：{cat.name}",
                 item_id=item.id, item_name=item.name, repo=item.homepage_url, user_id=me.id)
    activity.record("item_submit", f"手动填写新增「{item.name}」", user=me, target_type="item", target_id=item.id,
                    detail={"via": "manual_form"}, ip=client_ip(request))
    if needs:
        review.ai_review_async(item.id)
    else:
        threading.Thread(target=search.embed_items, args=([item.id],), daemon=True).start()
    return {"id": item.id, "status": item.status}


# ---- 管理 ----

@router.put("/items/{item_id}", dependencies=[Depends(require_admin)])
def update_item(item_id: int, body: ItemUpdate, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    item = _get_item(db, item_id)
    changes = body.model_dump(exclude_unset=True)
    if "category_id" in changes:
        cat = db.get(Category, changes["category_id"])
        if cat is None or cat.parent_id is None:
            raise HTTPException(400, "请选择一个子分类")
    if changes.get("status") not in (None, "published", "hidden"):
        raise HTTPException(400, "status 只能是 published / hidden")
    if "kind" in changes and changes["kind"] not in KINDS:
        raise HTTPException(400, "未知使用类型")

    locked = set(item.locked_fields or [])
    before, after = {}, {}

    def _v(k, v):  # v3.3.46 修改记录：分类记名称，长文本截断
        if k == "category_id":
            c = db.get(Category, v) if v else None
            return c.name if c else v
        if isinstance(v, str) and len(v) > 300:
            return v[:300] + "…"
        return v

    for k, v in changes.items():
        old = getattr(item, k)
        if old != v:
            key = "category" if k == "category_id" else k
            before[key], after[key] = _v(k, old), _v(k, v)
            setattr(item, k, v)
            if k in ingest.EDITABLE_FIELDS:
                locked.add(k)
    item.locked_fields = sorted(locked)
    db.commit()
    if after:
        activity.record("item_edit", f"编辑「{item.name}」：{'、'.join(activity.FIELD_LABELS.get(k, k) for k in after)}", user=me,
                        target_type="item", target_id=item.id, before=jsonable_encoder(before), after=jsonable_encoder(after),
                        target_label=item.name)
    threading.Thread(target=search.embed_items, args=([item.id],), daemon=True).start()
    return {"ok": True, "locked_fields": item.locked_fields}


@router.post("/items/{item_id}/unlock", dependencies=[Depends(require_admin)])
def unlock_fields(item_id: int, fields: list[str] = Body(..., embed=True), db: Session = Depends(get_db)):
    """解除字段锁定，下次提炼时由 AI 覆盖。"""
    item = _get_item(db, item_id)
    item.locked_fields = [f for f in item.locked_fields or [] if f not in fields]
    db.commit()
    return {"locked_fields": item.locked_fields}


@router.post("/items/{item_id}/reextract", dependencies=[Depends(require_admin)])
def reextract(item_id: int, db: Session = Depends(get_db)):
    item = _get_item(db, item_id)
    if item.repo is None:
        raise HTTPException(400, "非 GitHub 条目无法重新提炼")
    item.ai_status = "pending"
    db.commit()
    task_id = ingest.start_process_task("reextract", f"重新提炼 · {item.name}", [item_id], force=True)
    return {"ok": True, "task_id": task_id}


@router.post("/items/reextract-pending", dependencies=[Depends(require_admin)])
def reextract_pending(db: Session = Depends(get_db)):
    """把规则提炼 / 失败的条目全部交给 AI 重做（配置 AI 之后用来批量中文化）。"""
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口（.env 里的 AI_BASE_URL / AI_API_KEY / AI_TEXT_MODEL）")
    # 采集任务没在跑时，排队中的（pending）也一起处理
    states = ("rule", "failed") if crawler.is_running() else ("rule", "failed", "pending")
    items = db.scalars(select(Item).where(Item.repo_id.is_not(None), Item.status == "published", Item.ai_status.in_(states))).all()
    for item in items:
        item.ai_status = "pending"
    db.commit()
    # 4 路并发：瓶颈在 AI 接口和 GitHub 的往返延迟，不在本机
    task_id = ingest.start_process_task("translate", f"批量中文化 · {len(items)} 个条目", [i.id for i in items], workers=4)
    return {"queued": len(items), "task_id": task_id}


@router.post("/items/{item_id}/cover", dependencies=[Depends(require_admin)])
def regenerate_cover(item_id: int, db: Session = Depends(get_db)):
    """让 AI 重新画一张封面（会覆盖 README 截图，并锁定封面字段）。"""
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口")
    item = _get_item(db, item_id)
    if not ingest.ai_cover(db, item):
        tracking.log(trigger="cover", stage="cover_ai", level="error", message="手动重绘封面失败",
                     item_id=item.id, item_name=item.name, source=item.source)
        raise HTTPException(502, "AI 生成封面失败，请稍后重试")
    item.locked_fields = sorted(set(item.locked_fields or []) | {"cover_path"})
    db.commit()
    tracking.log(trigger="cover", stage="cover_ai", level="success", message="手动重绘封面成功",
                 item_id=item.id, item_name=item.name, source=item.source)
    return {"cover_url": f"/media/{item.cover_path}", "cover_thumb_url": thumbs.thumb_url(item.cover_path)}


@router.post("/items/covers-missing", dependencies=[Depends(require_admin)])
def covers_missing(db: Session = Depends(get_db)):
    """给所有还在用占位图的条目批量生成 AI 封面。"""
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口")
    rows = db.execute(select(Item.id, Item.name).where(Item.status == "published", Item.cover_path == "")).all()
    if not rows:
        return {"queued": 0, "task_id": None}
    task_id = tracking.create_task("cover", f"补全 AI 封面 · {len(rows)} 个条目", [(i, n) for i, n in rows])
    tracking.start_task(task_id, [i for i, _ in rows], lambda i, t: ingest.cover_for(i, t), workers=4)
    return {"queued": len(rows), "task_id": task_id}


@router.post("/items/covers-redraw", dependencies=[Depends(require_admin)])
def covers_redraw():
    """按当前提示词把所有 AI 封面重画一遍（画失败的保留旧图）。"""
    if not settings.ai_enabled:
        raise HTTPException(400, "还没有配置 AI 接口")
    task_id = ingest.start_cover_redraw("手动重画")
    return {"task_id": task_id}


@router.delete("/items/{item_id}", dependencies=[Depends(require_admin)])
def delete_item(item_id: int, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    """删除条目及其评论。若仓库下已无条目，则拉黑该仓库，自动采集不再收录。"""
    item = _get_item(db, item_id)
    activity.record("item_delete", f"删除「{item.name}」", user=me, target_type="item", target_id=item.id)
    search.forget(item.id)
    repo = item.repo
    db.delete(item)
    db.flush()
    if repo is not None and not db.scalar(select(func.count()).where(Item.repo_id == repo.id)):
        repo.repo_status = "rejected"
    db.commit()
    return {"ok": True}


# ---- 收藏 ----

@router.post("/items/{item_id}/favorite")
def set_favorite(item_id: int, on: bool = Body(True, embed=True), db: Session = Depends(get_db),
                 me: User = Depends(current_user)):
    """收藏 / 取消收藏（需要登录，每人一份）。收藏后先进「未整理」，归类由 /api/favorites 下的接口处理。"""
    if db.get(Item, item_id) is None:
        raise HTTPException(404, "条目不存在")
    owner = me.id
    fav = db.scalar(select(Favorite).where(Favorite.owner_id == owner, Favorite.item_id == item_id))
    if on and fav is None:
        db.add(Favorite(owner_id=owner, item_id=item_id, note=""))
    elif not on and fav is not None:
        db.delete(fav)
    db.commit()
    count = db.scalar(select(func.count()).select_from(Favorite).join(Item, Item.id == Favorite.item_id)
                      .where(Favorite.owner_id == owner, Item.status == "published"))
    return {"favorited": on, "favorites": count}


# ---- v3.3 详情页推荐 ----

@router.get("/items/{item_id}/related")
def related(item_id: int, db: Session = Depends(get_db), me: User | None = Depends(current_user_optional)):
    """同类推荐（同一子类按星标）+ 收藏了这条的人还收藏了（按共同收藏人数，轻量协同过滤）。"""
    item = _get_item(db, item_id)
    if not _can_view(item, me):
        raise HTTPException(404, "条目不存在")
    opts = (joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
    fans = select(Favorite.owner_id).where(Favorite.item_id == item_id)
    also_rows = db.execute(
        select(Favorite.item_id, func.count(func.distinct(Favorite.owner_id)).label("n"))
        .join(Item, Item.id == Favorite.item_id)
        .where(Favorite.owner_id.in_(fans), Favorite.item_id != item_id, Item.status == "published")
        .group_by(Favorite.item_id).order_by(func.count(func.distinct(Favorite.owner_id)).desc(), Favorite.item_id.desc()).limit(6)
    ).all()
    also_ids = [i for i, _ in also_rows]
    also_map = {it.id: it for it in db.scalars(select(Item).options(*opts).where(Item.id.in_(also_ids))).unique()} if also_ids else {}
    similar = db.scalars(
        select(Item).options(*opts).outerjoin(Repo, Repo.id == Item.repo_id)
        .where(Item.category_id == item.category_id, Item.id != item_id, Item.status == "published",
               Item.id.not_in(also_ids or [-1]))
        .order_by(func.coalesce(Repo.stars, 0).desc(), Item.id.desc()).limit(6)
    ).unique().all()
    favs = fav_ids(db, me.id if me else None)
    return {
        "similar": [item_card(it, favs) for it in similar],
        "also": [{**item_card(also_map[i], favs), "co_count": n} for i, n in also_rows if i in also_map],
    }


# ---- 评论 ----

@router.get("/items/{item_id}/comments")
def list_comments(item_id: int, db: Session = Depends(get_db), me: User | None = Depends(current_user_optional)):
    stmt = select(Comment).options(joinedload(Comment.user)).where(Comment.item_id == item_id)
    # v3.3：待审核的评论只给作者本人和管理员看
    # v3.3.44 驳回 / 删除的评论（软删）谁都不再显示，只在后台可见
    if me and is_admin(me):
        stmt = stmt.where(Comment.status.in_(("visible", "pending")))
    else:
        stmt = stmt.where(or_(Comment.status == "visible", (Comment.status == "pending") & (Comment.user_id == (me.id if me else -1))))
    return [comment_out(c, me) for c in db.scalars(stmt.order_by(Comment.created_at.desc()))]


@router.post("/items/{item_id}/comments")
def add_comment(item_id: int, body: CommentIn, request: Request, db: Session = Depends(get_db), me: User = Depends(current_user)):
    item = _get_item(db, item_id)
    if not _can_view(item, me) or item.status == "offline":
        raise HTTPException(404, "条目不存在或已下线")
    content = body.content.strip()
    # v3.3 内容审核：AI 判断，违规直接拦下（不保存），拿不准的待管理员审核
    status, reason = moderation.check(content, item.name)
    if status == "blocked":
        activity.record("comment_blocked", f"拦下「{item.name}」的评论：{content[:60]}（{reason}）", user=me, target_type="item",
                        target_id=item_id, ip=client_ip(request))
        raise HTTPException(422, f"评论没有通过内容审核：{reason}")
    c = Comment(item_id=item_id, user_id=me.id, content=content, status=status, review_reason=reason, rating=body.rating,
                input_type=body.input_type if body.input_type in ("text", "voice") else "text")
    db.add(c)
    db.commit()
    db.refresh(c)
    if c.rating:
        ratings.recompute(db, item_id)
    tag = "（待审核）" if status == "pending" else ""
    activity.record("comment", f"评论「{item.name}」{tag}：{c.content[:60]}", user=me,
                    target_type="item", target_id=item_id, ip=client_ip(request))
    return comment_out(c, me)


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    """评论只能删自己的；管理员可以删任何评论。"""
    c = db.get(Comment, comment_id)
    if c is None:
        raise HTTPException(404, "评论不存在")
    if c.user_id != me.id and not auth_can(me, "comments"):
        raise HTTPException(403, "只能删除自己的评论")
    if c.status == "deleted":
        return {"ok": True}
    own = c.user_id == me.id
    old = c.status
    # v3.3.44 软删：保留内容和处置记录，后台可以查看和恢复
    item_id, rated = c.item_id, c.rating
    c.status, c.handled_by, c.handled_at, c.handle_reason = "deleted", me.id, utcnow(), "作者删除" if own else "管理员在前台删除"
    db.commit()
    activity.record("comment_delete", f"删除评论 #{c.id}：{c.content[:60]}", user=me, target_type="comment", target_id=c.id,
                    reason=c.handle_reason, before={"status": old}, after={"status": "deleted"})
    if rated:
        ratings.recompute(db, item_id)
    return {"ok": True}
