"""每日失效巡检：检查已收录条目的 GitHub 原地址是否还在、仓库里是否还有内容。

由服务器系统定时任务在每天 03:30 调用（python -m app.cli check-liveness）。
- 失效（作废）：仓库不存在 / 被删除 / 被封禁（404、451），仓库为空，Skill 目录或 SKILL.md 已删除
- 已归档不算失效
- 网络错误不判定，留到下次
下线只做逻辑处理（status=offline），不删除数据；原地址恢复后下一次巡检自动重新上线。
"""

import logging
from collections import defaultdict

import httpx
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import Item, LivenessRun, Repo
from . import activity, search, tracking
from .github import API, GitHubError, _client, _request, find_skill_dirs

log = logging.getLogger(__name__)

GQL_BATCH = 40


def _gql_repos(client: httpx.Client, names: list[str]) -> dict[str, dict | None]:
    """一次查一批仓库：存在性、是否为空、是否归档、默认分支。查不到的值为 None。"""
    parts = []
    for i, fn in enumerate(names):
        owner, name = fn.split("/", 1)
        parts.append(f'r{i}: repository(owner: {_q(owner)}, name: {_q(name)}) {{ nameWithOwner isEmpty isArchived isDisabled '
                     f'defaultBranchRef {{ name }} }}')
    r = client.post(f"{API}/graphql", json={"query": "query {" + " ".join(parts) + "}"})
    if r.status_code != 200:
        raise GitHubError(f"GraphQL {r.status_code}")
    data = r.json().get("data") or {}
    return {fn: data.get(f"r{i}") for i, fn in enumerate(names)}


def _q(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _rest_repo(client: httpx.Client, full_name: str) -> dict | None:
    """REST 兜底（没有 Token 时）。不存在返回 None；网络错误抛 GitHubError。"""
    r = client.get(f"{API}/repos/{full_name}")
    if r.status_code in (404, 451):
        return None
    if r.status_code >= 400:
        raise GitHubError(f"GitHub 返回 {r.status_code}")
    d = r.json()
    return {"nameWithOwner": d["full_name"], "isEmpty": d.get("size", 0) == 0, "isArchived": d.get("archived"),
            "isDisabled": d.get("disabled"), "defaultBranchRef": {"name": d.get("default_branch")}}


def run(trigger: str = "schedule") -> int:
    """执行一次巡检，返回 LivenessRun id。"""
    with SessionLocal() as db:
        run_rec = LivenessRun(status="running")
        db.add(run_rec)
        db.commit()
        run_id = run_rec.id
        items = db.scalars(select(Item).where(Item.repo_id.is_not(None), Item.status.in_(("published", "offline", "hidden")))
                           .limit(settings.liveness_max_items)).all()
        stats, changes = _check(db, items, trigger)

        rec = db.get(LivenessRun, run_id)
        rec.status, rec.finished_at = "ok" if not stats["errors"] else "partial", utcnow()
        rec.checked, rec.went_offline, rec.restored, rec.errors = stats["checked"], stats["offline"], stats["restored"], stats["errors"]
        rec.detail = {"trigger": trigger, "changes": changes[:500]}
        db.commit()
    _after(changes)
    activity.record("liveness", f"失效巡检：检查 {stats['checked']} 个，新下线 {stats['offline']} 个，恢复 {stats['restored']} 个"
                    + (f"，{stats['errors']} 个查询失败" if stats["errors"] else ""), actor="system",
                    detail={"run_id": run_id, **stats})
    return run_id


def recheck(item_ids: list[int], trigger: str = "auto") -> dict:
    """单独复查几个条目（例如抓文档时 GitHub 返回 404）：确认原地址真的失效才下线，和每日巡检同一套判定。"""
    ids = sorted(set(i for i in item_ids if i))
    if not ids:
        return {"checked": 0, "offline": 0, "restored": 0, "errors": 0}
    with SessionLocal() as db:
        items = db.scalars(select(Item).where(Item.id.in_(ids), Item.repo_id.is_not(None),
                                              Item.status.in_(("published", "offline", "hidden")))).all()
        stats, changes = _check(db, items, trigger)
    _after(changes)
    if stats["offline"] or stats["restored"]:
        activity.record("liveness", f"复查原地址：新下线 {stats['offline']} 个，恢复 {stats['restored']} 个",
                        actor="system", detail={"trigger": trigger, "changes": changes[:50], **stats})
    return stats


def _after(changes: list[dict]):
    for c in changes:
        if c["change"] == "offline":
            search.forget(c["item_id"])


def _check(db, items: list[Item], trigger: str) -> tuple[dict, list[dict]]:
    """判定一批条目的原地址是否还有效，改状态并提交。返回 (统计, 变化列表)。"""
    by_repo: dict[int, list[Item]] = defaultdict(list)
    for it in items:
        by_repo[it.repo_id].append(it)
    repos = {r.id: r for r in db.scalars(select(Repo).where(Repo.id.in_(list(by_repo))))}

    stats = {"checked": 0, "offline": 0, "restored": 0, "errors": 0}
    changes: list[dict] = []
    now = utcnow()

    def mark(item: Item, dead_reason: str | None):
        item.checked_at = now
        if dead_reason and item.status != "offline":
            item.status, item.offline_at, item.offline_reason = "offline", now, dead_reason
            stats["offline"] += 1
            changes.append({"item_id": item.id, "name": item.name, "change": "offline", "reason": dead_reason})
            tracking.log(trigger="liveness", stage="liveness", level="warn", message=f"原地址失效，已下线：{dead_reason}",
                         item_id=item.id, item_name=item.name, repo=repos[item.repo_id].full_name)
        elif not dead_reason and item.status == "offline":
            item.status, item.offline_at, item.offline_reason = "published", None, ""
            stats["restored"] += 1
            changes.append({"item_id": item.id, "name": item.name, "change": "restored"})
            tracking.log(trigger="liveness", stage="liveness", level="success", message="原地址恢复，已重新上线",
                         item_id=item.id, item_name=item.name, repo=repos[item.repo_id].full_name)

    with _client() as client:
        names = {rid: r.full_name for rid, r in repos.items()}
        info: dict[int, dict | None] = {}
        failed: set[int] = set()
        ids = list(names)
        for k in range(0, len(ids), GQL_BATCH):
            chunk = ids[k:k + GQL_BATCH]
            try:
                if settings.github_token:
                    got = _gql_repos(client, [names[i] for i in chunk])
                    info.update({i: got[names[i]] for i in chunk})
                else:
                    for i in chunk:
                        info[i] = _rest_repo(client, names[i])
            except (GitHubError, httpx.HTTPError) as e:
                log.warning("liveness batch failed: %s", e)
                failed.update(chunk)

        for rid, its in by_repo.items():
            if rid in failed:
                stats["errors"] += len(its)
                continue
            d = info.get(rid)
            if d is None:
                # 按名称查不到时再按仓库 id 确认一次：仓库改名 / 转移后旧名称查不到，但并没有失效
                try:
                    r = client.get(f"{API}/repositories/{repos[rid].github_id}")
                except httpx.HTTPError:
                    stats["errors"] += len(its)
                    continue
                if r.status_code == 200:
                    j = r.json()
                    repos[rid].full_name, repos[rid].html_url = j["full_name"], j["html_url"]
                    d = {"nameWithOwner": j["full_name"], "isEmpty": j.get("size", 0) == 0, "isArchived": j.get("archived"),
                         "isDisabled": j.get("disabled"), "defaultBranchRef": {"name": j.get("default_branch")}}
                elif r.status_code not in (404, 451):
                    stats["errors"] += len(its)
                    continue
            stats["checked"] += len(its)
            if d is None:
                for it in its:
                    mark(it, "GitHub 仓库已不存在（被删除、改为私有或被封禁）")
                continue
            if d.get("isDisabled"):
                for it in its:
                    mark(it, "GitHub 仓库已被禁用")
                continue
            if d.get("isEmpty"):
                for it in its:
                    mark(it, "GitHub 仓库已清空")
                continue
            repo = repos[rid]
            repo.archived = bool(d.get("isArchived"))
            skill_items = [it for it in its if it.sub_path]
            for it in its:
                if not it.sub_path:
                    mark(it, None)
            if skill_items:
                # Skill 条目：确认目录和 SKILL.md 还在（同一仓库只取一次目录树）
                branch = (d.get("defaultBranchRef") or {}).get("name") or repo.default_branch
                try:
                    tree = _request(client, "GET", f"{API}/repos/{repo.full_name}/git/trees/{branch}", params={"recursive": "1"}).json()
                    dirs = set(find_skill_dirs([t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]))
                    if tree.get("truncated"):
                        dirs = None  # 目录树太大被截断时不判定
                except GitHubError as e:
                    log.warning("tree %s failed: %s", repo.full_name, e)
                    dirs = None
                for it in skill_items:
                    if dirs is None:
                        it.checked_at = now
                    else:
                        mark(it, None if it.sub_path in dirs else "原仓库中这个 Skill 的目录或 SKILL.md 已被删除")
        db.commit()
    return stats, changes
