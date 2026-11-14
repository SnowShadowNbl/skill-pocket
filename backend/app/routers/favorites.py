"""收藏分类。

两层结构：维度 → 分类。系统维度（领域大类、使用类型）按条目属性自动归组、只读；
自定义维度由用户增删改，首次使用时自动建一个「我的分类」。一个收藏在同一维度下可以放进多个分类。
删除分类 / 维度只删除归类关系，不会取消收藏。

收藏与分类都按登录用户隔离（owner_id = 用户 id），所有接口都需要登录。
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db, utcnow
from ..models import Category, User, FavDimension, FavFolder, Favorite, FavoriteFolderLink, Item
from ..seed import KINDS
from ..services import judge

router = APIRouter(prefix="/api/favorites", tags=["favorites"])

MAX_DIMENSIONS = 10
MAX_FOLDERS = 100
DEFAULT_DIMENSION = "我的分类"


def owner_id(user: User = Depends(current_user)) -> int:
    return user.id


# ---------------------------------------------------------------- 公共查询（items 路由也用）

def fav_ids(db: Session, owner: int | None) -> set[int]:
    if owner is None:
        return set()
    return set(db.scalars(select(Favorite.item_id).where(Favorite.owner_id == owner)).all())


def ensure_default_dimension(db: Session, owner: int) -> None:
    if not db.scalar(select(func.count()).select_from(FavDimension).where(FavDimension.owner_id == owner)):
        db.add(FavDimension(owner_id=owner, name=DEFAULT_DIMENSION, sort=0))
        db.commit()


def _dimension(db: Session, owner: int, dim_id: int) -> FavDimension:
    d = db.get(FavDimension, dim_id)
    if d is None or d.owner_id != owner:
        raise HTTPException(404, "维度不存在")
    return d


def _folder(db: Session, owner: int, folder_id: int) -> FavFolder:
    f = db.get(FavFolder, folder_id)
    if f is None or f.dimension.owner_id != owner:
        raise HTTPException(404, "分类不存在")
    return f


def _favorite(db: Session, owner: int, item_id: int) -> Favorite:
    fav = db.scalar(select(Favorite).where(Favorite.owner_id == owner, Favorite.item_id == item_id))
    if fav is None:
        raise HTTPException(404, "还没有收藏这个条目")
    return fav


def _name(v: str) -> str:
    v = v.strip()
    if not v:
        raise HTTPException(400, "名称不能为空")
    if len(v) > 20:
        raise HTTPException(400, "名称最多 20 个字")
    return v


def folder_ids_of(db: Session, fav_id: int) -> list[int]:
    return list(db.scalars(select(FavoriteFolderLink.folder_id).where(FavoriteFolderLink.favorite_id == fav_id)).all())


# ---------------------------------------------------------------- 结构

@router.get("/structure")
def structure(db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """左侧栏：系统维度 + 自定义维度，各分类的收藏数，以及每个自定义维度下的「未整理」数。"""
    ensure_default_dimension(db, owner)
    favs = db.execute(
        select(Favorite.id, Item.kind, Category.parent_id)
        .join(Item, Item.id == Favorite.item_id).join(Category, Category.id == Item.category_id)
        .where(Favorite.owner_id == owner, Item.status.in_(("published", "offline")))
    ).all()
    total = len(favs)
    live = {fid for fid, _, _ in favs}

    groups = {c.id: c for c in db.scalars(select(Category).where(Category.parent_id.is_(None)))}
    by_group: dict[int, int] = {}
    by_kind: dict[str, int] = {}
    for _, kind, gid in favs:
        by_group[gid] = by_group.get(gid, 0) + 1
        by_kind[kind or ""] = by_kind.get(kind or "", 0) + 1
    system = [
        {"key": "group", "name": "领域大类", "system": True, "folders": [
            {"key": groups[g].code, "name": groups[g].name, "emoji": groups[g].icon, "count": n}
            for g, n in sorted(by_group.items(), key=lambda x: groups[x[0]].sort) if g in groups]},
        {"key": "kind", "name": "使用类型", "system": True, "folders": [
            {"key": k, "name": label, "emoji": icon, "count": by_kind[k]} for k, (label, icon, _) in KINDS.items() if by_kind.get(k)]
            + ([{"key": "none", "name": "未判定", "emoji": "❔", "count": by_kind[""]}] if by_kind.get("") else [])},
    ]

    links = db.execute(select(FavoriteFolderLink.favorite_id, FavoriteFolderLink.folder_id)).all()
    per_folder: dict[int, int] = {}
    sorted_in: dict[int, set[int]] = {}  # folder → favorites
    for fav_id, folder_id in links:
        if fav_id in live:
            per_folder[folder_id] = per_folder.get(folder_id, 0) + 1
            sorted_in.setdefault(folder_id, set()).add(fav_id)
    dims = db.scalars(select(FavDimension).where(FavDimension.owner_id == owner).order_by(FavDimension.sort, FavDimension.id)).all()
    custom = []
    for d in dims:
        organized = set().union(*(sorted_in.get(f.id, set()) for f in d.folders)) if d.folders else set()
        custom.append({"id": d.id, "name": d.name, "system": False, "unsorted": total - len(organized), "folders": [
            {"id": f.id, "name": f.name, "emoji": f.emoji, "count": per_folder.get(f.id, 0), "last_used_at": f.last_used_at,
             "share_token": None if f.share_closed_at else f.share_token, "share_closed": bool(f.share_closed_at)}
            for f in d.folders]})
    return {"total": total, "system": system, "dimensions": custom}


# ---------------------------------------------------------------- 维度

class DimensionIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@router.post("/dimensions")
def add_dimension(body: DimensionIn, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    n = db.scalar(select(func.count()).select_from(FavDimension).where(FavDimension.owner_id == owner))
    if n >= MAX_DIMENSIONS:
        raise HTTPException(400, f"最多 {MAX_DIMENSIONS} 个维度")
    name = _name(body.name)
    if db.scalar(select(FavDimension).where(FavDimension.owner_id == owner, FavDimension.name == name)):
        raise HTTPException(409, "已有同名维度")
    d = FavDimension(owner_id=owner, name=name, sort=n)
    db.add(d)
    db.commit()
    return {"id": d.id, "name": d.name}


@router.patch("/dimensions/{dim_id}")
def rename_dimension(dim_id: int, body: DimensionIn, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    d = _dimension(db, owner, dim_id)
    d.name = _name(body.name)
    db.commit()
    return {"id": d.id, "name": d.name}


@router.delete("/dimensions/{dim_id}")
def delete_dimension(dim_id: int, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    d = _dimension(db, owner, dim_id)
    if db.scalar(select(func.count()).select_from(FavDimension).where(FavDimension.owner_id == owner)) <= 1:
        raise HTTPException(400, "至少保留一个自定义维度")
    db.delete(d)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 分类

class FolderIn(BaseModel):
    dimension_id: int
    name: str = Field(min_length=1, max_length=40)
    emoji: str = Field("", max_length=16)
    item_ids: list[int] = []  # 撤销删除时把原来的条目放回去


class FolderPatch(BaseModel):
    name: str | None = Field(None, max_length=40)
    emoji: str | None = Field(None, max_length=16)


@router.post("/folders")
def add_folder(body: FolderIn, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    d = _dimension(db, owner, body.dimension_id)
    if len(d.folders) >= MAX_FOLDERS:
        raise HTTPException(400, f"每个维度最多 {MAX_FOLDERS} 个分类")
    name = _name(body.name)
    if any(f.name == name for f in d.folders):
        raise HTTPException(409, "这个维度下已有同名分类")
    f = FavFolder(dimension_id=d.id, name=name, emoji=body.emoji.strip(), sort=len(d.folders))
    db.add(f)
    db.flush()
    if body.item_ids:
        for fav in db.scalars(select(Favorite).where(Favorite.owner_id == owner, Favorite.item_id.in_(body.item_ids))):
            db.add(FavoriteFolderLink(favorite_id=fav.id, folder_id=f.id))
    db.commit()
    return {"id": f.id, "name": f.name, "emoji": f.emoji, "dimension_id": d.id}


@router.patch("/folders/{folder_id}")
def update_folder(folder_id: int, body: FolderPatch, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    f = _folder(db, owner, folder_id)
    if body.name is not None:
        name = _name(body.name)
        if name != f.name and any(x.name == name for x in f.dimension.folders):
            raise HTTPException(409, "这个维度下已有同名分类")
        f.name = name
    if body.emoji is not None:
        f.emoji = body.emoji.strip()
    db.commit()
    return {"id": f.id, "name": f.name, "emoji": f.emoji}


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """返回原分类信息和其中的条目，前端「撤销」时原样建回。"""
    f = _folder(db, owner, folder_id)
    item_ids = list(db.scalars(select(Favorite.item_id).join(FavoriteFolderLink, FavoriteFolderLink.favorite_id == Favorite.id)
                               .where(FavoriteFolderLink.folder_id == f.id)).all())
    snapshot = {"dimension_id": f.dimension_id, "name": f.name, "emoji": f.emoji, "item_ids": item_ids}
    db.delete(f)
    db.commit()
    return snapshot


@router.post("/folders/reorder")
def reorder_folders(ids: list[int] = Body(..., embed=True), db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    for n, fid in enumerate(ids):
        _folder(db, owner, fid).sort = n
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 归类

class MoveIn(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=500)
    add: list[int] = []
    remove: list[int] = []


@router.post("/move")
def move(body: MoveIn, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """批量把收藏放进 / 移出分类。"""
    add = [_folder(db, owner, f) for f in body.add]
    remove = [_folder(db, owner, f).id for f in body.remove]
    favs = db.scalars(select(Favorite).where(Favorite.owner_id == owner, Favorite.item_id.in_(body.item_ids))).all()
    fav_ids_ = [f.id for f in favs]
    if remove and fav_ids_:
        db.execute(delete(FavoriteFolderLink).where(FavoriteFolderLink.favorite_id.in_(fav_ids_),
                                                    FavoriteFolderLink.folder_id.in_(remove)))
    have = set(db.execute(select(FavoriteFolderLink.favorite_id, FavoriteFolderLink.folder_id)
                          .where(FavoriteFolderLink.favorite_id.in_(fav_ids_))).all()) if fav_ids_ else set()
    now = utcnow()
    for f in add:
        f.last_used_at = now
        for fid in fav_ids_:
            if (fid, f.id) not in have:
                db.add(FavoriteFolderLink(favorite_id=fid, folder_id=f.id))
    db.commit()
    return {"ok": True, "count": len(fav_ids_)}


class ItemFoldersIn(BaseModel):
    dimension_id: int
    folder_ids: list[int]


@router.put("/{item_id}/folders")
def set_item_folders(item_id: int, body: ItemFoldersIn, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """设置一个收藏在某个维度下所属的分类（收藏后的小浮层用）。"""
    fav = _favorite(db, owner, item_id)
    d = _dimension(db, owner, body.dimension_id)
    in_dim = {f.id for f in d.folders}
    want = set(body.folder_ids)
    if not want <= in_dim:
        raise HTTPException(400, "分类不属于这个维度")
    db.execute(delete(FavoriteFolderLink).where(FavoriteFolderLink.favorite_id == fav.id,
                                                FavoriteFolderLink.folder_id.in_(in_dim - want)))
    have = set(folder_ids_of(db, fav.id))
    now = utcnow()
    for f in d.folders:
        if f.id in want:
            f.last_used_at = now
            if f.id not in have:
                db.add(FavoriteFolderLink(favorite_id=fav.id, folder_id=f.id))
    db.commit()
    return {"folder_ids": folder_ids_of(db, fav.id)}


class NoteIn(BaseModel):
    note: str = Field("", max_length=500)


@router.put("/{item_id}/note")
def set_note(item_id: int, body: NoteIn, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    fav = _favorite(db, owner, item_id)
    fav.note = body.note.strip()
    db.commit()
    return {"note": fav.note}


# ---------------------------------------------------------------- AI 帮我整理

@router.post("/organize/suggest")
def organize_suggest(dimension_id: int = Body(..., embed=True), db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """给该维度下「未整理」的收藏建议分类，只返回建议，由用户确认后再调用 /move。"""
    d = _dimension(db, owner, dimension_id)
    organized = set(db.scalars(select(FavoriteFolderLink.favorite_id)
                               .where(FavoriteFolderLink.folder_id.in_([f.id for f in d.folders]))).all()) if d.folders else set()
    rows = db.execute(
        select(Favorite.id, Item).join(Item, Item.id == Favorite.item_id)
        .where(Favorite.owner_id == owner, Item.status.in_(("published", "offline"))).order_by(Favorite.created_at.desc())
    ).all()
    todo = [it for fid, it in rows if fid not in organized][:40]
    if not todo:
        return {"suggestions": []}
    items = [{"id": it.id, "name": it.name, "summary": it.summary[:120], "category": it.category.name,
              "kind": KINDS.get(it.kind, ("",))[0]} for it in todo]
    folders = [{"id": f.id, "name": f.name} for f in d.folders]
    try:
        got = judge.suggest_folders(d.name, folders, items)
    except judge.JudgeUnavailable as e:
        raise HTTPException(503, f"AI 暂不可用：{e}")
    names = {it.id: it.name for it in todo}
    return {"suggestions": [{**s, "item_name": names[s["item_id"]]} for s in got]}


# ---------------------------------------------------------------- v3.3 分享与导出

@router.post("/folders/{folder_id}/share")
def share_folder(folder_id: int, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """公开分享一个收藏分类：生成只读链接 /s/<token>（已分享的返回原链接）。"""
    import secrets

    f = _folder(db, owner, folder_id)
    if f.share_closed_at:
        raise HTTPException(403, {"code": "share_closed_by_admin",
                                  "message": "这个分类的分享已被管理员关闭" + (f"：{f.share_closed_reason}" if f.share_closed_reason else "")})
    if not f.share_token:
        f.share_token = secrets.token_urlsafe(9)
        f.share_views = f.share_views or 0
        db.commit()
    return {"token": f.share_token, "path": f"/s/{f.share_token}"}


@router.delete("/folders/{folder_id}/share")
def unshare_folder(folder_id: int, db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    f = _folder(db, owner, folder_id)
    f.share_token = None
    db.commit()
    return {"ok": True}


@router.get("/export")
def export(request: Request, format: str = "md", db: Session = Depends(get_db), owner: int = Depends(owner_id)):
    """导出全部收藏（Markdown 清单或 JSON），含备注、分类和链接。"""
    import json as _json

    site = f"{request.url.scheme}://{request.headers.get('x-forwarded-host') or request.url.netloc}"
    from urllib.parse import quote

    from fastapi.responses import Response
    from sqlalchemy.orm import joinedload

    pairs = db.execute(select(Favorite, Item).join(Item, Item.id == Favorite.item_id)
                       .options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
                       .where(Favorite.owner_id == owner).order_by(Favorite.created_at.desc())).unique().all()
    favs = [f for f, _ in pairs]
    item_of = {f.id: it for f, it in pairs}
    names = {f.id: f.name for f in db.scalars(select(FavFolder).join(FavDimension).where(FavDimension.owner_id == owner))}
    links: dict[int, list[str]] = {}
    for fid, folder_id in db.execute(select(FavoriteFolderLink.favorite_id, FavoriteFolderLink.folder_id)
                                     .where(FavoriteFolderLink.favorite_id.in_([f.id for f in favs] or [-1]))):
        if folder_id in names:
            links.setdefault(fid, []).append(names[folder_id])
    rows = []
    for f in favs:
        it = item_of[f.id]
        cat = it.category
        rows.append({
            "name": it.name, "summary": it.summary or "", "note": f.note or "",
            "category": f"{cat.parent.name} / {cat.name}" if cat and cat.parent else (cat.name if cat else ""),
            "kind": KINDS.get(it.kind, ("",))[0] if it.kind else "", "folders": links.get(f.id, []),
            "github": it.repo.html_url if it.repo else "", "homepage": it.homepage_url or "",
            "page": f"{site}/items/{it.id}", "favorited_at": f.created_at.isoformat() if f.created_at else "",
        })
    day = utcnow().strftime("%Y%m%d")
    if format == "json":
        body, mime, ext = _json.dumps({"count": len(rows), "items": rows}, ensure_ascii=False, indent=2), "application/json", "json"
    else:
        lines = [f"# 我的 Skill 口袋 · {len(rows)} 个收藏", "", f"> 导出自 Skill Pocket（{site}），{utcnow().strftime('%Y-%m-%d')}", ""]
        for r in rows:
            link = r["github"] or r["homepage"] or r["page"]
            lines.append(f"- **[{r['name']}]({link})**" + (f" — {r['summary']}" if r["summary"] else ""))
            meta = " · ".join(x for x in [r["category"], r["kind"], "、".join(r["folders"])] if x)
            if meta:
                lines.append(f"  - {meta}")
            if r["note"]:
                lines.append(f"  - 备注：{r['note']}")
        body, mime, ext = "\n".join(lines) + "\n", "text/markdown; charset=utf-8", "md"
    fname = f"skill-pocket-收藏-{day}.{ext}"
    return Response(body, media_type=mime, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


shared_router = APIRouter(prefix="/api/shared", tags=["favorites"])


@shared_router.get("/{token}")
def shared_folder(token: str, db: Session = Depends(get_db)):
    """公开的收藏分类（只读，不需要登录）：分类名、分享人、里面已上线的条目。"""
    from sqlalchemy.orm import joinedload

    from ..models import Repo
    from ..schemas import item_card, public_user

    f = db.scalar(select(FavFolder).where(FavFolder.share_token == token)) if token else None
    if f is None or f.share_closed_at:
        raise HTTPException(404, "分享已关闭或不存在")
    from sqlalchemy import update
    db.execute(update(FavFolder).where(FavFolder.id == f.id).values(share_views=func.coalesce(FavFolder.share_views, 0) + 1))
    db.commit()
    owner = db.get(User, f.dimension.owner_id)
    items = db.scalars(
        select(Item).join(Favorite, Favorite.item_id == Item.id).join(FavoriteFolderLink, FavoriteFolderLink.favorite_id == Favorite.id)
        .outerjoin(Repo, Repo.id == Item.repo_id)
        .options(joinedload(Item.repo), joinedload(Item.category).joinedload(Category.parent))
        .where(FavoriteFolderLink.folder_id == f.id, Item.status == "published").order_by(Favorite.created_at.desc())
    ).unique().all()
    return {"folder": {"name": f.name, "emoji": f.emoji}, "owner": public_user(owner) if owner else None,
            "items": [item_card(it) for it in items]}
