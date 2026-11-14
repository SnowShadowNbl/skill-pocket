"""用户的停用与删除（用户自己注销、管理员删除共用同一套处理）。"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AuthSession, FavDimension, Favorite, User


def revoke_sessions(db: Session, user_id: int) -> None:
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))):
        s.revoked_at = utcnow()


def account_id(u: User) -> str:
    """v3.3.38 账号标识（不含昵称）：邮箱 / 用户名 / 微信用户 #id / 用户 #id。后台列表名字下面、弹窗副标题用它。"""
    return u.email or u.username or (f"微信用户 #{u.id}" if u.wx_openid else f"用户 #{u.id}")


def label(u: User | None) -> str:
    """v3.3.17 日志里称呼一个账号：昵称（账号标识），邮箱为空时不会出现 None。"""
    if u is None:
        return "未知用户"
    return f"{u.nickname or '用户'}（{account_id(u)}）"


def anonymize(db: Session, user: User) -> None:
    """删除账号：收藏与收藏分类删除；评论和提交的条目保留，显示为「已注销用户」；邮箱释放，可以重新注册。"""
    db.execute(delete(Favorite).where(Favorite.owner_id == user.id))
    db.execute(delete(FavDimension).where(FavDimension.owner_id == user.id))
    revoke_sessions(db, user.id)
    user.status, user.email, user.username, user.password_hash = "deleted", None, None, ""
    user.nickname, user.avatar = "已注销用户", ""
    user.wx_openid, user.wx_unionid = None, None
