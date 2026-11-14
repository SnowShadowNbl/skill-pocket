"""v3.3 站内消息：订阅分类的上新汇总、收藏的仓库发布新版本。每天采集结束后跑一次（scheduler 里 08:30）。"""

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..models import Category, CategorySubscription, Favorite, Item, Notification, Repo
from .github import GitHub, GitHubError

log = logging.getLogger(__name__)


def push(db: Session, user_id: int, kind: str, title: str, body: str = "", link: str = "") -> None:
    db.add(Notification(user_id=user_id, kind=kind, title=title[:200], body=body[:500], link=link[:300]))


def digest_new_items(db: Session) -> int:
    """订阅了某个分类的人：上次通知之后该分类（大类含子类）新上线的条目，汇总成一条消息。返回发出的条数。"""
    sent = 0
    now = utcnow()
    for sub in db.scalars(select(CategorySubscription)):
        cat = db.get(Category, sub.category_id)
        if cat is None:
            continue
        ids = [cat.id] + [c.id for c in cat.children]
        since = sub.last_notified_at or sub.created_at
        rows = db.scalars(select(Item).where(Item.category_id.in_(ids), Item.status == "published", Item.collected_at > since)
                          .order_by(Item.collected_at.desc())).all()
        sub.last_notified_at = now
        if not rows:
            continue
        names = "、".join(r.name for r in rows[:3]) + (f" 等 {len(rows)} 个" if len(rows) > 3 else "")
        push(db, sub.user_id, "new_items", f"你订阅的「{cat.name}」上新了 {len(rows)} 个", names, f"/?category={cat.code}&sort=collected")
        sent += 1
    db.commit()
    return sent


def check_releases(db: Session, gh: GitHub | None = None, limit: int = 300) -> int:
    """被收藏过的仓库：取最新 Release，标签变了就通知收藏了它的人（第一次只记下，不通知）。返回发出的条数。"""
    repo_ids = db.scalars(
        select(Repo.id).join(Item, Item.repo_id == Repo.id).join(Favorite, Favorite.item_id == Item.id)
        .where(Item.status == "published").group_by(Repo.id).order_by(func.count(Favorite.id).desc()).limit(limit)
    ).all()
    own = gh is None
    gh = gh or GitHub()
    sent = 0
    try:
        for rid in repo_ids:
            repo = db.get(Repo, rid)
            try:
                rel = gh.latest_release(repo.full_name)
            except GitHubError:
                continue
            tag = (rel or {}).get("tag_name") or ""
            if not tag or tag == repo.latest_release:
                continue
            first = not repo.latest_release
            repo.latest_release = tag[:100]
            if first:
                continue
            fans = db.execute(select(Favorite.owner_id, Item.id, Item.name).join(Item, Item.id == Favorite.item_id)
                              .where(Item.repo_id == rid, Item.status == "published")).all()
            seen: set[int] = set()
            for uid, item_id, name in fans:
                if uid in seen:
                    continue
                seen.add(uid)
                push(db, uid, "release", f"你收藏的「{name}」发布了新版本 {tag}", (rel.get("name") or "")[:200], f"/items/{item_id}")
                sent += 1
            db.commit()
    finally:
        if own:
            gh.close()
    db.commit()
    return sent


def _record_run(db: Session, ok: bool, digests, releases, error: str = "", started=None) -> None:
    """v3.3.64 记下每日推送的执行结果（运行监控「推送」服务状态用）。"""
    import json

    from ..models import AppMeta

    rec = {"started_at": started.isoformat() if started else None, "at": utcnow().isoformat(), "ok": ok, "digests": digests,
           "releases": releases, "error": error[:300]}
    db.merge(AppMeta(key="push_last_run", value=json.dumps(rec)))
    m = db.get(AppMeta, "push_runs")  # v3.3.65 执行记录（保留最近 60 次）
    try:
        runs = json.loads(m.value) if m and m.value else []
    except ValueError:
        runs = []
    db.merge(AppMeta(key="push_runs", value=json.dumps((runs + [rec])[-60:])))
    db.commit()


def run_daily() -> None:
    started = utcnow()
    with SessionLocal() as db:
        try:
            n1 = digest_new_items(db)
            n2 = check_releases(db)
            # 只保留 60 天内的消息
            db.query(Notification).filter(Notification.created_at < utcnow() - timedelta(days=60)).delete()
            db.commit()
            log.info("notifications: %s digests, %s releases", n1, n2)
            _record_run(db, True, n1, n2, started=started)
        except Exception as e:  # noqa: BLE001 — 通知失败不影响别的任务
            log.exception("daily notifications failed")
            db.rollback()
            _record_run(db, False, None, None, str(e), started=started)
