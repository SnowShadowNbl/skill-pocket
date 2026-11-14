"""v3.3.61 后台批次 5b：维护工具与数据一致性检查。

维护工具：每个工具一张卡片，可先 dry_run 预览影响范围，执行要填原因；记录写操作日志（target_type=maintenance，target_label=工具 key）。
一致性检查：只检查数据库里「存下来的派生值 / 关系」，扫描结果缓存在 app_meta（key=consistency:<检查项>），页面先读缓存，不现场全表扫。
"""

import json
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import client_ip, require_admin
from ..db import SessionLocal, get_db, utcnow
from ..models import (ActivityLog, AppMeta, AuthSession, Category, Comment, FavDimension, Favorite, FavFolder,
                      FavoriteFolderLink, Item, Repo, User)
from ..services import activity, blocklist, ratings, users

router = APIRouter(prefix="/api/admin", tags=["admin-maintenance"], dependencies=[Depends(require_admin)])


def _err(http_status: int, code: str, message: str, **extra):
    raise HTTPException(http_status, jsonable_encoder({"code": code, "message": message, **extra}))


def _reason(r: str) -> str:
    r = (r or "").strip()
    if len(r) < 2:
        _err(400, "reason_required", "请填写原因")
    return r


# ================================================================ 维护工具
def _rated_items(db: Session) -> list[int]:
    return list(db.scalars(select(Comment.item_id).where(Comment.rating.is_not(None)).distinct()))


def _clear_memory_caches() -> dict:
    from ..services import item_quality, resources, search_terms
    from . import jobs

    search_terms.invalidate_hot()
    item_quality._spike_cache = (0.0, set())
    jobs._trend_cache = (0.0, [])
    resources._cache.clear()
    from ..services import cache

    cache.purge_expired()
    return {"cleared": ["大家在搜", "疑似刷星", "分类趋势", "资源监控", "已过期的缓存记录"]}


TOOLS = {
    "recalc_ratings": {"name": "重算评分", "dangerous": False,
                       "preview": lambda db: f"将重算 {len(_rated_items(db)) + db.scalar(select(func.count()).select_from(Item).where(Item.rating_count > 0))} 个条目的评分（含已没有评分的）"},
    "recalc_rankings": {"name": "重算最新榜单", "dangerous": True, "preview": lambda db: "将按当前分类和排除名单重算最近一期日榜和周榜"},
    "embed_backfill": {"name": "补齐语义搜索向量", "dangerous": False,
                       "preview": lambda db: "为还没有搜索标签或向量的条目补齐（会调用 AI，后台任务）"},
    "media_backfill": {"name": "补齐缩略图和动图", "dangerous": False,
                       "preview": lambda db: f"将检查 {db.scalar(select(func.count(func.distinct(Item.cover_path))).where(Item.cover_path != ''))} 张封面，缺的缩略图和动图排进后台生成"},
    "clear_cache": {"name": "清理缓存", "dangerous": False,
                    "preview": lambda db: "清空「大家在搜」、疑似刷星、分类趋势、资源监控的内存缓存，并删除已过期的缓存记录"},
}


def _run_tool(key: str, db: Session) -> tuple[str, str | None]:
    """返回 (结果摘要, 后台任务 id 或 None)。"""
    if key == "recalc_ratings":
        ids = set(_rated_items(db)) | set(db.scalars(select(Item.id).where(Item.rating_count > 0)))
        for i in ids:
            ratings.recompute(db, i)
        return f"已重算 {len(ids)} 个条目的评分", None
    if key == "recalc_rankings":
        from ..services.reclassify import recompute_latest_rankings

        threading.Thread(target=recompute_latest_rankings, daemon=True).start()
        return "已开始重算最近一期榜单（后台进行，约几秒）", None
    if key == "embed_backfill":
        from ..services import search

        if not search.enabled():
            _err(400, "not_available", "语义搜索没有配置，不能补齐向量")
        tid = search.start_backfill()
        return ("已开始补齐" if tid else "没有需要补齐的条目"), (f"task:{tid}" if tid else None)
    if key == "media_backfill":
        from ..services import anim, thumbs

        def run():
            thumbs.backfill()
            anim.backfill()

        threading.Thread(target=run, daemon=True, name="media-backfill-admin").start()
        return "已开始在后台补齐缩略图和动图（已有的会跳过）", None
    if key == "clear_cache":
        return "已清理：" + "、".join(_clear_memory_caches()["cleared"]), None
    _err(404, "not_found", "没有这个工具")


def _last_runs(db: Session) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in db.scalars(select(ActivityLog).where(ActivityLog.action == "maintenance").order_by(ActivityLog.id.desc()).limit(200)):
        k = r.target_label
        if k in TOOLS and k not in out:
            u = db.get(User, r.user_id) if r.user_id else None
            out[k] = {"at": r.created_at, "by": {"id": u.id, "label": users.label(u)} if u else None, "ok": (r.result or "ok") == "ok",
                      "summary": r.message or r.summary, "reason": r.reason}
    return out


@router.get("/maintenance")
def list_tools(db: Session = Depends(get_db)):
    last = _last_runs(db)
    return {"tools": [{"key": k, "name": t["name"], "dangerous": t["dangerous"], "dry_run": True, "last_run": last.get(k)}
                      for k, t in TOOLS.items()]}


class RunIn(BaseModel):
    reason: str = Field("", max_length=300)
    dry_run: bool = False


@router.post("/maintenance/{key}/run")
def run_tool(key: str, body: RunIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    t = TOOLS.get(key)
    if t is None:
        _err(404, "not_found", "没有这个工具")
    if body.dry_run:
        return {"ok": True, "dry_run": True, "summary": t["preview"](db), "task_id": None}
    reason = _reason(body.reason)
    start = time.time()
    try:
        summary, task_id = _run_tool(key, db)
        ok = True
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        summary, task_id, ok = f"执行失败：{e}", None, False
    ms = int((time.time() - start) * 1000)
    activity.record("maintenance", f"维护工具「{t['name']}」", user=me, target_type="maintenance", ip=client_ip(request), reason=reason,
                    result="ok" if ok else "failed", message=summary[:300], target_label=key, detail={"ms": ms, "task_id": task_id})
    return {"ok": ok, "dry_run": False, "summary": summary, "task_id": task_id, "duration_ms": ms}


# ================================================================ 数据一致性检查
def _check_ratings(db: Session) -> list[dict]:
    rows = db.execute(select(Comment.item_id, Comment.user_id, Comment.rating).where(
        Comment.status == "visible", Comment.rating.is_not(None), Comment.user_id.is_not(None)).order_by(Comment.created_at.desc(), Comment.id.desc())).all()
    latest: dict[int, dict[int, int]] = {}
    for iid, uid, r in rows:
        latest.setdefault(iid, {}).setdefault(uid, r)
    out = []
    ids = set(latest) | set(db.scalars(select(Item.id).where(Item.rating_count > 0)))
    for it in db.scalars(select(Item).where(Item.id.in_(ids or {-1}))):
        vals = list((latest.get(it.id) or {}).values())
        avg = round(sum(vals) / len(vals), 2) if vals else None
        cur = round(it.rating_avg, 2) if it.rating_avg is not None else None
        if (it.rating_count or 0) != len(vals) or cur != avg:
            out.append({"id": it.id, "label": it.name, "stored": {"avg": cur, "count": it.rating_count or 0}, "actual": {"avg": avg, "count": len(vals)}})
    return out


def _fix_ratings(db: Session, ids: list[int]) -> dict[int, str]:
    for i in ids:
        ratings.recompute(db, i)
    return {i: "已重算" for i in ids}


def _check_category(db: Session) -> list[dict]:
    cats = {c.id: c for c in db.scalars(select(Category))}
    out = []
    for it in db.scalars(select(Item).where(Item.status == "published")):
        c = cats.get(it.category_id)
        bad = c is None or not c.enabled or (c.parent_id and not cats[c.parent_id].enabled)
        if bad:
            tgt = cats.get(c.merged_into_id) if c is not None and c.merged_into_id else None
            out.append({"id": it.id, "label": it.name, "stored": {"category": c.name if c else f"#{it.category_id}（不存在）"},
                        "actual": {"category": tgt.name if tgt else "需要人工选分类"}})
    return out


def _fix_category(db: Session, ids: list[int]) -> dict[int, str]:
    cats = {c.id: c for c in db.scalars(select(Category))}
    res = {}
    for it in db.scalars(select(Item).where(Item.id.in_(ids))):
        c = cats.get(it.category_id)
        if c is not None and c.merged_into_id and c.merged_into_id in cats:
            it.category_id = c.merged_into_id
            res[it.id] = f"已改到「{cats[c.merged_into_id].name}」"
        else:
            res[it.id] = "skip:没有合并目标，请在内容管理里手动改分类"
    db.commit()
    return res


def _check_fav_links(db: Session) -> list[dict]:
    rows = db.execute(select(FavoriteFolderLink.favorite_id, FavoriteFolderLink.folder_id, Favorite.owner_id, FavDimension.owner_id, FavFolder.name)
                      .join(Favorite, Favorite.id == FavoriteFolderLink.favorite_id).join(FavFolder, FavFolder.id == FavoriteFolderLink.folder_id)
                      .join(FavDimension, FavDimension.id == FavFolder.dimension_id).where(Favorite.owner_id != FavDimension.owner_id)).all()
    return [{"id": fid * 100000 + fold, "label": f"收藏 #{fid} → 收藏夹「{name}」", "stored": {"favorite_owner": fo, "folder_owner": do},
             "actual": {"note": "收藏和收藏夹不属于同一个人，应删除这条关联"}} for fid, fold, fo, do, name in rows]


def _fix_fav_links(db: Session, ids: list[int]) -> dict[int, str]:
    res = {}
    for k in ids:
        fid, fold = divmod(k, 100000)
        link = db.get(FavoriteFolderLink, (fid, fold))
        if link is not None:
            db.delete(link)
            res[k] = "已删除关联"
        else:
            res[k] = "noop:关联已不存在"
    db.commit()
    return res


def _check_blocked(db: Session) -> list[dict]:
    snap = blocklist.snapshot(db)
    if not snap[0] and not snap[1]:
        return []
    rows = db.execute(select(Item.id, Item.name, Repo.full_name).join(Repo, Repo.id == Item.repo_id).where(Item.status == "published")).all()
    return [{"id": i, "label": n, "stored": {"status": "已上线", "repo": fn}, "actual": {"note": "仓库或作者在黑名单里"}}
            for i, n, fn in rows if blocklist.blocked_in(snap, fn)]


def _fix_blocked(db: Session, ids: list[int]) -> dict[int, str]:
    res = {}
    for it in db.scalars(select(Item).where(Item.id.in_(ids))):
        if it.status == "published":
            it.status = "hidden"
            res[it.id] = "已隐藏"
        else:
            res[it.id] = "noop:已经不是上线状态"
    db.commit()
    return res


def _check_sessions(db: Session) -> list[dict]:
    rows = db.execute(select(User.id, User.nickname, User.status, func.count(AuthSession.id)).join(AuthSession, AuthSession.user_id == User.id)
                      .where(User.status.in_(("disabled", "deleted", "merged")), AuthSession.revoked_at.is_(None),
                             AuthSession.expires_at > utcnow()).group_by(User.id, User.nickname, User.status)).all()
    return [{"id": uid, "label": nick or f"用户 #{uid}", "stored": {"active_sessions": n, "status": st}, "actual": {"active_sessions": 0}}
            for uid, nick, st, n in rows]


def _fix_sessions(db: Session, ids: list[int]) -> dict[int, str]:
    now = utcnow()
    res = {}
    for uid in ids:
        n = 0
        for s in db.scalars(select(AuthSession).where(AuthSession.user_id == uid, AuthSession.revoked_at.is_(None))):
            s.revoked_at = now
            n += 1
        res[uid] = f"已退出 {n} 个登录" if n else "noop:没有有效登录"
    db.commit()
    return res


CHECKS = {
    "item_ratings": ("条目评分（均分 / 人数）", _check_ratings, _fix_ratings),
    "item_category": ("上线条目挂在停用或已合并的分类", _check_category, _fix_category),
    "fav_folder_owner": ("收藏夹关联不属于同一个人", _check_fav_links, _fix_fav_links),
    "published_blocked": ("黑名单里的仓库仍在上线", _check_blocked, _fix_blocked),
    "inactive_sessions": ("停用 / 注销 / 已合并账号仍有有效登录", _check_sessions, _fix_sessions),
}
LIMIT = 200


def _meta_key(k: str) -> str:
    return f"consistency:{k}"


def _load(db: Session, k: str) -> dict | None:
    m = db.get(AppMeta, _meta_key(k))
    try:
        return json.loads(m.value) if m and m.value else None
    except ValueError:
        return None


def _scan(db: Session, k: str) -> dict:
    rows = CHECKS[k][1](db)
    data = {"checked_at": utcnow().isoformat(), "mismatches": len(rows), "items": rows[:LIMIT]}
    db.merge(AppMeta(key=_meta_key(k), value=json.dumps(jsonable_encoder(data), ensure_ascii=False)))
    db.commit()
    return data


def _status(d: dict | None) -> str:
    if d is None:
        return "unknown"
    return "ok" if d["mismatches"] == 0 else "warn"


@router.get("/consistency")
def list_checks(db: Session = Depends(get_db)):
    out = []
    for k, (name, _, _) in CHECKS.items():
        d = _load(db, k)
        out.append({"key": k, "name": name, "checked_at": d["checked_at"] if d else None, "mismatches": d["mismatches"] if d else None,
                    "status": _status(d)})
    return {"checks": out}


def _check_key(k: str):
    if k not in CHECKS:
        _err(404, "not_found", "没有这个检查项")


class ScanIn(BaseModel):
    reason: str = Field("", max_length=300)


@router.post("/consistency/{key}/scan")
def scan(key: str, request: Request, body: ScanIn | None = None, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    _check_key(key)
    d = _scan(db, key)
    return {"task_id": None, "key": key, "checked_at": d["checked_at"], "mismatches": d["mismatches"], "status": _status(d)}


@router.get("/consistency/{key}")
def detail(key: str, db: Session = Depends(get_db)):
    _check_key(key)
    d = _load(db, key)
    return {"key": key, "name": CHECKS[key][0], "checked_at": d["checked_at"] if d else None, "mismatches": d["mismatches"] if d else None,
            "status": _status(d), "limit": LIMIT, "items": d["items"] if d else []}


class FixIn(BaseModel):
    reason: str = Field("", max_length=300)
    ids: list[int] | None = None
    all: bool = False
    dry_run: bool = False


@router.post("/consistency/{key}/fix")
def fix(key: str, body: FixIn, request: Request, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    _check_key(key)
    fresh = CHECKS[key][1](db)  # 修复前重新确认，避免按旧扫描结果误改
    current = {r["id"]: r for r in fresh}
    if body.all:
        ids = list(current)
    elif body.ids:
        ids = list(dict.fromkeys(body.ids))
    else:
        _err(400, "empty_scope", "请先选择要修复的项")
    if body.dry_run:
        return {"dry_run": True, "count": sum(1 for i in ids if i in current), "already_ok": sum(1 for i in ids if i not in current)}
    reason = _reason(body.reason)
    todo = [i for i in ids if i in current]
    done = CHECKS[key][2](db, todo) if todo else {}
    results = []
    for i in ids:
        if i not in current:
            results.append({"id": i, "label": f"#{i}", "ok": True, "code": "noop", "message": "已经一致，不需要修复"})
            continue
        msg = done.get(i, "")
        code, _, text = msg.partition(":") if msg.startswith(("skip:", "noop:")) else ("ok", "", msg)
        results.append({"id": i, "label": current[i]["label"], "ok": code != "skip", "code": code, "message": text})
    activity.record("consistency_fix", f"修复数据一致性「{CHECKS[key][0]}」：{len(todo)} 项", user=me, target_type="maintenance",
                    ip=client_ip(request), reason=reason, target_label=key, detail={"ids": ids[:200]})
    _scan(db, key)
    ok = sum(1 for r in results if r["ok"])
    return {"results": results, "ok_count": ok, "fail_count": len(results) - ok}
