"""账号合并：把只有微信的副账号并入有邮箱（或 admin 用户名）的主账号。

调用方负责事务：这里只 flush 不 commit，任何一步抛错由调用方 rollback，数据保持原样。
"""

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import (TakedownRequest, 
    ActivityLog, AiCall, AuthSession, CategorySubscription, Comment, CompareRun, Event, FavDimension, FavFolder, Favorite, FavoriteFolderLink,
    Feedback, FinderJob, IngestLog, IpBan, Item, ItemReview, Notification, QuotaDaily, QuotaLedger, Task, Upload, User, Visitor,
)

# 归属直接改成主账号的字段（v3.0.3 指向 users 的外键 18 处，减去下面单独处理的 auth_sessions、quota_daily；
# 另加没有外键的 events.user_id）。新增指向 users 的外键时必须在这里或 SPECIAL 里登记，测试会检查。
REASSIGN = [
    (Item, "created_by"), (Comment, "user_id"), (Upload, "user_id"), (AiCall, "user_id"), (Task, "user_id"),
    (IngestLog, "user_id"), (FinderJob, "user_id"), (QuotaLedger, "user_id"), (QuotaLedger, "operator_id"),
    (ItemReview, "submitter_id"), (ItemReview, "reviewer_id"), (ActivityLog, "user_id"), (Feedback, "user_id"),
    (Visitor, "user_id"), (CompareRun, "user_id"), (IpBan, "created_by"), (Event, "user_id"),
    (Notification, "user_id"),  # v3.3 站内消息
    (TakedownRequest, "user_id"),  # v3.3.48 下架申请
]
SPECIAL = {("auth_sessions", "user_id"), ("quota_daily", "user_id"), ("users", "merged_into"),
           ("category_subscriptions", "user_id"),  # v3.3 分类订阅：同一分类两边都订了只留一条
           ("wx_qr_logins", "web_user_id"), ("wx_qr_logins", "wx_user_id"),  # v3.3.9 扫码记录 10 分钟有效，不迁移
           ("admin_views", "user_id"),
           ("user_tags", "user_id")}  # v3.3.71 后台标签：被并入账号的标签不迁移（随账号保留）  # v3.3.42 管理员的筛选视图：被并入的一方是新微信账号，不会有视图


def counts(db: Session, user_id: int) -> dict:
    """合并确认页上展示的数量。"""
    return {
        "favorites": db.scalar(select(func.count()).select_from(Favorite).where(Favorite.owner_id == user_id)),
        "folders": db.scalar(select(func.count()).select_from(FavFolder).join(FavDimension)
                             .where(FavDimension.owner_id == user_id)),
        "comments": db.scalar(select(func.count()).select_from(Comment).where(Comment.user_id == user_id)),
        "compares": db.scalar(select(func.count()).select_from(CompareRun).where(CompareRun.user_id == user_id)),
    }


def _move_links(db: Session, src_col, src_id: int, dst_id: int) -> None:
    """把 favorite_folder_links 里 src_col == src_id 的行改到 dst_id（主键冲突的直接丢弃）。"""
    other = FavoriteFolderLink.folder_id if src_col is FavoriteFolderLink.favorite_id else FavoriteFolderLink.favorite_id
    rows = db.scalars(select(other).where(src_col == src_id)).all()
    have = set(db.scalars(select(other).where(src_col == dst_id)).all())
    db.execute(delete(FavoriteFolderLink).where(src_col == src_id))
    for o in rows:
        if o not in have:
            db.execute(insert(FavoriteFolderLink).values({src_col.key: dst_id, other.key: o}))
            have.add(o)


def _merge_dimensions(db: Session, primary: User, secondary: User) -> None:
    mine = {d.name: d for d in db.scalars(select(FavDimension).where(FavDimension.owner_id == primary.id))}
    next_sort = max([d.sort for d in mine.values()], default=-1) + 1
    for d in db.scalars(select(FavDimension).where(FavDimension.owner_id == secondary.id).order_by(FavDimension.sort)).all():
        target = mine.get(d.name)
        if target is None:
            d.owner_id, d.sort = primary.id, next_sort
            next_sort += 1
            continue
        names = {f.name: f for f in target.folders}
        fsort = max([f.sort for f in target.folders], default=-1) + 1
        for f in list(d.folders):
            same = names.get(f.name)
            if same is not None:
                _move_links(db, FavoriteFolderLink.folder_id, f.id, same.id)
                d.folders.remove(f)  # delete-orphan 删除，避免删维度时级联再删一次
            else:
                f.dimension, f.sort = target, fsort
                names[f.name] = f
                fsort += 1
        db.flush()
        db.delete(d)
    db.flush()


def _merge_favorites(db: Session, primary: User, secondary: User) -> None:
    mine = {f.item_id: f for f in db.scalars(select(Favorite).where(Favorite.owner_id == primary.id))}
    for f in db.scalars(select(Favorite).where(Favorite.owner_id == secondary.id)).all():
        keep = mine.get(f.item_id)
        if keep is None:
            f.owner_id = primary.id
            continue
        _move_links(db, FavoriteFolderLink.favorite_id, f.id, keep.id)
        a, b = (keep.note or "").strip(), (f.note or "").strip()
        if b and b != a:
            keep.note = f"{a}\n{b}" if a else b
        db.delete(f)
    db.flush()


def _merge_quota(db: Session, primary: User, secondary: User) -> None:
    mine = {q.day: q for q in db.scalars(select(QuotaDaily).where(QuotaDaily.user_id == primary.id))}
    for q in db.scalars(select(QuotaDaily).where(QuotaDaily.user_id == secondary.id)).all():
        t = mine.get(q.day)
        if t is None:
            q.user_id = primary.id
        else:
            t.calls += q.calls
            t.tokens += q.tokens
            t.used += q.used
            db.delete(q)
    # 余额：保留主账号的（副账号多是刚发的免费额度，相加等于白送一份）；主账号还没发放过时沿用副账号的
    if primary.quota_balance is None:
        primary.quota_balance = secondary.quota_balance
    db.flush()


def _merge_subscriptions(db: Session, primary: User, secondary: User) -> None:
    mine = set(db.scalars(select(CategorySubscription.category_id).where(CategorySubscription.user_id == primary.id)))
    for s in db.scalars(select(CategorySubscription).where(CategorySubscription.user_id == secondary.id)).all():
        if s.category_id in mine:
            db.delete(s)
        else:
            s.user_id = primary.id
            mine.add(s.category_id)
    db.flush()


def merge_users(db: Session, primary: User, secondary: User) -> str | None:
    _merge_subscriptions(db, primary, secondary)
    _merge_dimensions(db, primary, secondary)
    _merge_favorites(db, primary, secondary)
    _merge_quota(db, primary, secondary)
    for model, col in REASSIGN:
        c = getattr(model, col)
        db.execute(update(model).where(c == secondary.id).values({col: primary.id}).execution_options(synchronize_session=False))
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == secondary.id, AuthSession.revoked_at.is_(None))):
        s.revoked_at = utcnow()
    # 头像：副账号上传过微信头像就用它；只有随机预设头像时保留主账号的
    old_avatar = None
    if secondary.avatar.startswith("avatars/"):
        if primary.avatar != secondary.avatar:
            old_avatar = primary.avatar
        primary.avatar = secondary.avatar
    openid, unionid = secondary.wx_openid, secondary.wx_unionid
    secondary.wx_openid = secondary.wx_unionid = None
    secondary.status, secondary.merged_into, secondary.avatar = "merged", primary.id, ""
    db.flush()
    primary.wx_openid, primary.wx_unionid = openid, unionid or primary.wx_unionid
    db.flush()
    # 被替换掉的旧头像文件由调用方在提交成功后删除（回滚时文件还要用）
    return old_avatar if old_avatar and old_avatar.startswith("avatars/") else None


def drop_file(avatar: str | None) -> None:
    if avatar:
        (settings.media_dir / avatar).unlink(missing_ok=True)
