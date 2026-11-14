from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import Category, Item
from ..schemas import CategoryIn, CategoryUpdate

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _out(c: Category, counts: dict[int, int]) -> dict:
    return {"id": c.id, "parent_id": c.parent_id, "code": c.code, "name": c.name, "icon": c.icon,
            "sort": c.sort, "enabled": c.enabled, "remark": c.remark, "item_count": counts.get(c.id, 0)}


@router.get("")
def tree(include_disabled: bool = False, db: Session = Depends(get_db)):
    """两级树。大类的 item_count 为其子类之和。只统计已发布条目。"""
    counts = dict(db.execute(
        select(Item.category_id, func.count()).where(Item.status == "published").group_by(Item.category_id)
    ).all())
    groups = db.scalars(select(Category).where(Category.parent_id.is_(None)).order_by(Category.sort)).all()
    out = []
    for g in groups:
        if not (g.enabled or include_disabled):
            continue
        children = [_out(c, counts) for c in g.children if c.enabled or include_disabled]
        node = _out(g, counts)
        node["item_count"] = sum(c["item_count"] for c in children)
        node["children"] = children
        out.append(node)
    return out


@router.post("", dependencies=[Depends(require_admin)])
def create(body: CategoryIn, db: Session = Depends(get_db)):
    if db.scalar(select(Category).where(Category.code == body.code)):
        raise HTTPException(409, f"分类编码 {body.code} 已存在")
    if body.parent_id is not None:
        parent = db.get(Category, body.parent_id)
        if parent is None or parent.parent_id is not None:
            raise HTTPException(400, "父级必须是一个大类")
    c = Category(**body.model_dump())
    db.add(c)
    db.commit()
    return _out(c, {})


@router.put("/{cid}", dependencies=[Depends(require_admin)])
def update(cid: int, body: CategoryUpdate, db: Session = Depends(get_db)):
    c = db.get(Category, cid)
    if c is None:
        raise HTTPException(404, "分类不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return _out(c, {})
