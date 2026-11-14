"""v3.3.48 黑名单：仓库（owner/name）或 GitHub 账号（owner）。采集、用户提交、管理员导入都会检查。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BlockEntry


def norm_repo(full_name: str) -> str:
    return (full_name or "").strip().strip("/").lower()


def match(db: Session, full_name: str) -> BlockEntry | None:
    """仓库本身或它的 owner 在黑名单里时返回对应记录。"""
    fn = norm_repo(full_name)
    if not fn:
        return None
    owner = fn.split("/", 1)[0]
    return db.scalar(select(BlockEntry).where(
        ((BlockEntry.kind == "repo") & (BlockEntry.value == fn)) | ((BlockEntry.kind == "owner") & (BlockEntry.value == owner))
    ).limit(1))


def snapshot(db: Session) -> tuple[set[str], set[str]]:
    """（仓库集合, owner 集合），批量判断用。"""
    repos, owners = set(), set()
    for kind, value in db.execute(select(BlockEntry.kind, BlockEntry.value)).all():
        (repos if kind == "repo" else owners).add(value)
    return repos, owners


def blocked_in(snap: tuple[set[str], set[str]], full_name: str) -> bool:
    fn = norm_repo(full_name)
    return fn in snap[0] or fn.split("/", 1)[0] in snap[1]
