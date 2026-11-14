"""每日自动采集流水线（P2）。

顺序：星标快照 → 日榜 / 周榜 → 发现新仓库并判定收录 → 新条目 AI 提炼。
快照放最前面，保证每天在差不多同一时刻拍，增量才可比；提炼最耗额度，放最后。
任一阶段额度用完（等不到重置）就停在那里，没做完的工作第二天的窗口继续。
"""

import logging
import re
import threading
import time
import traceback
from collections import OrderedDict
from datetime import date, datetime, timedelta
from posixpath import basename
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import Category, Discovery, Item, JobRun, Repo, StarSnapshot
from ..seed import FALLBACK_CODE
from . import ingest
from .extract import prejudge
from . import blurbs, judge
from .github import BudgetExhausted, GitHub, GitHubError, RepoRef, crawl_budget, find_skill_dirs, rate_state
from . import tracking
from .rankings import compute_rankings

log = logging.getLogger(__name__)

# ---- 收录判定 ----
# v1.3 起由 AI 判断（judge.screen_repos / judge_collection）；以下规则只在 AI 不可用时兜底
SKILL_TOPICS = {"claude-skills", "claude-skill", "agent-skills", "agent-skill", "claude-code-skills", "anthropic-skills", "skills"}
MODEL_TOPICS = {
    "asr", "tts", "speech-recognition", "speech-to-text", "text-to-speech", "speech-synthesis", "voice-cloning",
    "llm", "large-language-model", "multimodal", "vlm", "vision-language-model", "text-to-image", "text-to-video",
    "image-generation", "video-generation", "diffusion", "stable-diffusion", "ocr", "embedding", "embeddings",
}
TOOL_TOPICS = {"mcp", "mcp-server", "model-context-protocol", "ai-agent", "ai-agents", "agent-framework", "rag", "llm-inference"}
# 名称 / 简介疑似相关，但 topic 不在白名单 → 进待确认队列
HINT = re.compile(r"\b(skill|skills|agent|agents|llm|gpt|claude|mcp|asr|tts|speech|diffusion|rag|copilot)\b|大模型|智能体|语音", re.I)

_lock = threading.Lock()


def tz() -> ZoneInfo:
    return ZoneInfo(settings.crawl_tz)


def local_today() -> date:
    return datetime.now(tz()).date()


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def window_deadline(now: datetime | None = None) -> datetime:
    """当前这一轮的截止时刻：今天的 CRAWL_END；已过则顺延到明天。"""
    now = now or datetime.now(tz())
    h, m = _hm(settings.crawl_end)
    end = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return end if end > now else end + timedelta(days=1)


def in_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(tz())
    sh, sm = _hm(settings.crawl_start)
    eh, em = _hm(settings.crawl_end)
    cur, start, end = now.hour * 60 + now.minute, sh * 60 + sm, eh * 60 + em
    return start <= cur < end if start < end else (cur >= start or cur < end)


def is_running() -> bool:
    return _lock.locked()


# ---------------------------------------------------------------- 阶段 1：快照

def snapshot(db: Session, gh: GitHub, stats: dict) -> None:
    """给所有“已发布条目所属”的仓库拍当天的星标快照。有 Token 走 GraphQL 批量，否则逐个 REST。"""
    day = local_today()
    repos = db.scalars(
        select(Repo).where(Repo.repo_status == "active", Repo.id.in_(
            select(Item.repo_id).where(Item.status == "published", Item.repo_id.is_not(None))))
    ).all()
    done = set(db.scalars(select(StarSnapshot.repo_id).where(StarSnapshot.snap_date == day)).all())
    todo = [r for r in repos if r.id not in done]

    counts: dict[str, int | None] = {}
    if settings.github_token and todo:
        counts = gh.star_counts([r.full_name for r in todo])

    for r in todo:
        stars = counts.get(r.full_name)
        if stars is None:
            # 没 Token，或 GraphQL 查不到（仓库改名 / 转移）：按 id 走 REST，同时更新名称
            try:
                data = gh.repo_by_id(r.github_id)
            except BudgetExhausted:
                raise
            except GitHubError as e:
                stats.setdefault("snapshot_errors", []).append(f"{r.full_name}: {e}"[:200])
                tracking.log(trigger="crawl", stage="snapshot", level="error", message=f"星标快照失败：{e}", repo=r.full_name)
                continue
            ingest.upsert_repo(db, data)
            stars = data.get("stargazers_count", 0)
        r.stars = stars
        r.last_synced_at = utcnow()
        db.merge(StarSnapshot(repo_id=r.id, snap_date=day, stars=stars))
        stats["snapshots"] = stats.get("snapshots", 0) + 1
        db.commit()
    stats["snapshot_total"] = len(repos)


# ---------------------------------------------------------------- 阶段 2：榜单

def rankings(db: Session, stats: dict) -> None:
    day = local_today()
    stats["daily_boards"] = compute_rankings(db, day, "daily")
    # v3.1：周榜 = 近 7 天星标增量，和日榜一样每天更新（原来只在周一出，数据不满一周时线上没有周榜）
    stats["weekly_boards"] = compute_rankings(db, day, "weekly")
    stats["monthly_boards"] = compute_rankings(db, day, "monthly")  # v3.3 月榜 = 近 30 天


# ---------------------------------------------------------------- 阶段 3：发现 + 判定

def _collect_candidates(gh: GitHub, stats: dict) -> "OrderedDict[str, dict]":
    cands: OrderedDict[str, dict] = OrderedDict()

    def add(full_name: str, channel: str, ref: str, data: dict | None = None, delta: int | None = None):
        key = full_name.lower()
        if key not in cands:
            cands[key] = {"full_name": full_name, "data": data, "channel": channel, "ref": ref, "delta": delta}

    for q in settings.crawl_queries:
        try:
            for it in gh.search_repos(q, per_page=30):
                add(it["full_name"], "search", q, data=it)
        except BudgetExhausted:
            raise
        except GitHubError as e:
            stats.setdefault("discover_errors", []).append(f"search {q}: {e}"[:200])
        time.sleep(2.5)  # Search API 单独限流（未认证 10 次 / 分钟）

    if settings.trending_enabled:
        for since in ("daily", "weekly"):
            try:
                for rank, (fn, delta) in enumerate(gh.trending(since), start=1):
                    add(fn, f"trending_{since}", f"第 {rank} 名", delta=delta)
            except GitHubError as e:
                stats.setdefault("discover_errors", []).append(f"trending {since}: {e}"[:200])

    for awesome in settings.awesome_repos:
        try:
            text, _, _ = gh.readme(awesome)
        except BudgetExhausted:
            raise
        except GitHubError as e:
            stats.setdefault("discover_errors", []).append(f"awesome {awesome}: {e}"[:200])
            continue
        for owner, name in re.findall(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?[/)#\s\"']", text):
            if owner.lower() not in ("topics", "orgs", "sponsors", "features", "marketplace"):
                add(f"{owner}/{name}", "awesome", awesome)

    stats["candidates"] = len(cands)
    return cands


def _classify(gh: GitHub, data: dict) -> tuple[str, list[str], str]:
    """返回 (kind, skill_dirs, note)。kind: skill / model / tool / review / ignore"""
    topics = {t.lower() for t in data.get("topics") or []}
    text = f"{data.get('name', '')} {data.get('description') or ''}"
    looks_skill = bool(topics & SKILL_TOPICS) or re.search(r"skill", text, re.I)

    skill_dirs: list[str] = []
    if looks_skill:
        try:
            skill_dirs = find_skill_dirs(gh.tree_paths(data["full_name"], data.get("default_branch") or "main"))
        except BudgetExhausted:
            raise
        except GitHubError:
            pass
    if skill_dirs or topics & SKILL_TOPICS:
        return "skill", skill_dirs, ""
    if topics & MODEL_TOPICS:
        return "model", [], ""
    if topics & TOOL_TOPICS:
        return "tool", [], ""
    m = HINT.search(text) or next((t for t in topics if HINT.search(t)), None)
    if m:
        relevant, reason = prejudge(data.get("name", ""), data.get("description") or "", list(topics))
        if relevant is False:
            return "ignore", [], reason
        hit = m.group(0) if hasattr(m, "group") else m
        return "review", [], reason or f"名称 / 简介含“{hit}”，topic 不在白名单"
    return "ignore", [], ""


SCREEN_BATCH = 10
# AI 给出的把握低于这个值时交给人工确认
SCREEN_MIN_CONFIDENCE = 0.6
# 多于这么多个 Skill 才请 AI 判断是拆开收录还是整体收录；超过上限一律整体收录
SPLIT_ASK_MIN = 4
SPLIT_HARD_MAX = 60
SRC_LABEL = {"search": "GitHub 搜索", "trending_daily": "Trending 日榜", "trending_weekly": "Trending 周榜", "awesome": "awesome 清单"}
KIND_LABEL = {"skill": "Skill", "model": "模型", "tool": "工具 / 智能体"}


def _skill_dirs(gh: GitHub, data: dict) -> list[str]:
    try:
        return find_skill_dirs(gh.tree_paths(data["full_name"], data.get("default_branch") or "main"))
    except BudgetExhausted:
        raise
    except GitHubError:
        return []


def _judge_batch(gh: GitHub, batch: list[dict]) -> list[tuple[str, list[str], str, str]]:
    """一批候选交给 AI 判断，返回每个的 (动作, Skill 目录, 说明, 使用类型)。动作：accept / review / ignore。
    AI 不可用时整批退回规则判断。"""
    try:
        verdicts = judge.screen_repos([{"full_name": d["full_name"], "description": d.get("description"),
                                        "topics": d.get("topics"), "language": d.get("language"),
                                        "stars": d.get("stargazers_count")} for d in batch])
    except judge.JudgeUnavailable:
        out = []
        for d in batch:
            kind, dirs, note = _classify(gh, d)
            action = {"review": "review", "ignore": "ignore"}.get(kind, "accept")
            item_kind = {"skill": "agent_skill", "model": "model"}.get(kind, "")
            out.append((action, dirs, note or (f"规则判定为{KIND_LABEL[kind]}" if kind in KIND_LABEL else ""), item_kind))
        return out

    out = []
    for d, v in zip(batch, verdicts):
        reason = v["reason"] or "AI 未说明理由"
        if v["relevant"] is None or v["confidence"] < SCREEN_MIN_CONFIDENCE:
            out.append(("review", [], f"AI 拿不准（把握 {v['confidence']:.0%}）：{reason}", v["kind"]))
        elif not v["relevant"]:
            out.append(("ignore", [], f"AI 判定不相关：{reason}", v["kind"]))
        else:
            dirs = _skill_dirs(gh, d) if v["kind"] in ("agent_skill", "") or "skill" in d["full_name"].lower() else []
            out.append(("accept", dirs, f"AI 判定收录：{reason}", v["kind"] or ("agent_skill" if dirs else "")))
    return out


def _split_mode(d: dict, dirs: list[str]) -> tuple[bool, str]:
    """一个仓库多个 Skill 时，是逐个收录还是整体收录一个条目。返回 (是否拆开, 说明)。"""
    if len(dirs) <= 1:
        return True, ""
    if len(dirs) > SPLIT_HARD_MAX:
        return False, f"{len(dirs)} 个 Skill，整体收录"
    if len(dirs) < SPLIT_ASK_MIN:
        return True, ""
    try:
        mode, reason = judge.judge_collection(d["full_name"], d.get("description") or "", dirs)
        return mode == "split", f"AI：{reason}"
    except judge.JudgeUnavailable:
        split = len(dirs) <= settings.skill_split_max
        return split, "" if split else f"超过 {settings.skill_split_max} 个 Skill，按合集整体收录（规则兜底）"


def discover(db: Session, gh: GitHub, stats: dict) -> None:
    cands = _collect_candidates(gh, stats)
    known = {fn.lower(): (rid, status) for rid, fn, status in db.execute(select(Repo.id, Repo.full_name, Repo.repo_status)).all()}
    placeholder = db.scalar(select(Category).where(Category.code == FALLBACK_CODE))

    # 1) 取新候选的仓库信息（已收录的上了 Trending 只记一笔发现记录）
    fresh: list[tuple[dict, dict]] = []
    from . import blocklist

    blocked = blocklist.snapshot(db)
    for key, c in cands.items():
        if blocklist.blocked_in(blocked, key):  # v3.3.48 黑名单
            stats["skipped_blocked"] = stats.get("skipped_blocked", 0) + 1
            continue
        if key in known:
            rid, status = known[key]
            if status == "active" and c["channel"].startswith("trending"):
                db.add(Discovery(repo_id=rid, channel=c["channel"], channel_ref=c["ref"], trending_delta=c["delta"]))
            continue
        if len(fresh) >= settings.max_new_repos_per_run:
            stats["skipped_over_limit"] = stats.get("skipped_over_limit", 0) + 1
            continue
        data = c["data"]
        try:
            if data is None:
                owner, name = c["full_name"].split("/", 1)
                data = gh.repo(RepoRef(owner, name))
        except BudgetExhausted:
            db.commit()
            raise
        except GitHubError as e:
            stats.setdefault("discover_errors", []).append(f"{c['full_name']}: {e}"[:200])
            tracking.log(trigger="crawl", stage="discover", level="error", message=f"读取候选仓库失败：{e}", repo=c["full_name"])
            continue
        # 仓库改过名 / 转过户时，旧名字会被 GitHub 重定向到已收录的仓库：按返回的真实名字再查一次
        real = data["full_name"].lower()
        if blocklist.blocked_in(blocked, real):
            stats["skipped_blocked"] = stats.get("skipped_blocked", 0) + 1
            continue
        if real in known:
            rid, status = known[real]
            if status == "active" and rid and c["channel"].startswith("trending"):
                db.add(Discovery(repo_id=rid, channel=c["channel"], channel_ref=c["ref"], trending_delta=c["delta"]))
            continue
        known[real] = (None, "pending")
        fresh.append((c, data))
    db.commit()
    stats["new_repos_checked"] = len(fresh)

    # 2) 分批交给 AI 判断（fork / 已归档的直接跳过，不花 token）
    for i in range(0, len(fresh), SCREEN_BATCH):
        part = fresh[i:i + SCREEN_BATCH]
        live = [d for _, d in part if not (d.get("fork") or d.get("archived"))]
        try:
            judged = iter(_judge_batch(gh, live)) if live else iter(())
        except BudgetExhausted:
            db.commit()
            raise
        for c, data in part:
            if data.get("fork") or data.get("archived"):
                action, dirs, note, item_kind = "ignore", [], "fork / 已归档", ""
            else:
                action, dirs, note, item_kind = next(judged)
            # 每个候选单独保存：一个出错只跳过它，不让整轮采集失败
            try:
                with db.begin_nested():
                    _save_candidate(db, c, data, action, dirs, note, item_kind, placeholder, stats)
            except IntegrityError as e:
                stats.setdefault("discover_errors", []).append(f"{data['full_name']}: 保存失败（{e.orig.__class__.__name__}）"[:200])
                tracking.log(trigger="crawl", stage="discover", level="error", message="保存候选失败，已跳过：数据冲突",
                             repo=data["full_name"])
        db.commit()


def _save_candidate(db: Session, c: dict, data: dict, action: str, dirs: list[str], note: str, item_kind: str,
                    placeholder: Category, stats: dict) -> None:
    repo = ingest.upsert_repo(db, data)
    src = SRC_LABEL.get(c["channel"], c["channel"])
    db.add(Discovery(repo_id=repo.id, channel=c["channel"], channel_ref=c["ref"], trending_delta=c["delta"]))
    if db.scalar(select(func.count()).select_from(Item).where(Item.repo_id == repo.id)):
        # 同一个仓库已经有条目（例如按 GitHub 数字 id 认出来的改名仓库）：只记发现，不重复收录
        tracking.log(trigger="crawl", stage="discover", level="info", message=f"来源：{src} · 已收录过，跳过", repo=repo.full_name)
        return

    if action == "ignore":
        repo.repo_status = "ignored"
        stats["ignored"] = stats.get("ignored", 0) + 1
        tracking.log(trigger="crawl", stage="discover", level="info", message=f"来源：{src} · 不收录：{note}",
                     item_name=data["name"], repo=repo.full_name)
        return
    if action == "review":
        db.add(Item(repo_id=repo.id, sub_path="", name=data["name"], category_id=placeholder.id, kind=item_kind,
                    summary=(data.get("description") or "")[:500], source="auto", status="pending_review",
                    ai_status="pending", review_note=note, stars_at_collect=repo.stars,
                    locked_fields=[], install_steps=[]))
        stats["pending_review"] = stats.get("pending_review", 0) + 1
        tracking.log(trigger="crawl", stage="discover", level="info", message=f"来源：{src} · 进入待确认：{note}",
                     item_name=data["name"], repo=repo.full_name)
        return

    split, split_note = _split_mode(data, dirs)
    if not split:
        stats["collections"] = stats.get("collections", 0) + 1
        dirs = []
    for sub in (dirs or [""]):
        db.add(Item(repo_id=repo.id, sub_path=sub, name=basename(sub) or data["name"], category_id=placeholder.id,
                    kind=item_kind, summary=(data.get("description") or "")[:500] if not sub else "", source="auto",
                    status="published", ai_status="pending", stars_at_collect=repo.stars,
                    locked_fields=[], install_steps=[]))
        stats["new_items"] = stats.get("new_items", 0) + 1
    tracking.log(trigger="crawl", stage="discover", level="info",
                 message=f"来源：{src} · {note} · 新增 {len(dirs or [''])} 个条目" + (f"（{split_note}）" if split_note else ""),
                 item_name=data["name"], repo=repo.full_name)
    # 新仓库当天也拍一次快照，明天就能算增量
    db.merge(StarSnapshot(repo_id=repo.id, snap_date=local_today(), stars=repo.stars))


# ---------------------------------------------------------------- 阶段 4：提炼

def extract_pending(db: Session, stats: dict) -> None:
    rows = db.execute(
        select(Item.id, Item.name).where(Item.status == "published", Item.ai_status == "pending", Item.repo_id.is_not(None)).order_by(Item.id)
    ).all()
    stats["extract_total"] = len(rows)
    if not rows:
        return
    task_id = tracking.create_task("crawl", f"自动采集 · 提炼 {len(rows)} 个新条目", [(i, n) for i, n in rows])
    stats["task_id"] = task_id
    done = [0]

    def one(item_id: int, tid: int):
        ok, msg = ingest.process_item(item_id, task_id=tid, trigger="crawl")  # 额度用完会抛 BudgetExhausted
        done[0] += 1
        stats["extracted"] = done[0]
        if done[0] % 5 == 0:
            _flush(stats)
        return ok, msg

    # 采集线程里串行跑，额度用完时剩余条目标记为“留到下次”
    tracking.run_task(task_id, [i for i, _ in rows], one, workers=1, stop_on=(BudgetExhausted,))


_current_job: int | None = None


def _flush(stats: dict) -> None:
    """长阶段中途把进度写回任务记录，方便页面显示。"""
    if _current_job is None:
        return
    with SessionLocal() as s:
        job = s.get(JobRun, _current_job)
        if job:
            job.stats = dict(stats)
            s.commit()


def mark_interrupted() -> None:
    """启动时把上次进程退出时还在跑的任务标记为中断。"""
    with SessionLocal() as db:
        for job in db.scalars(select(JobRun).where(JobRun.status == "running")):
            job.status, job.error, job.finished_at = "failed", "服务重启，任务中断（未完成的工作下次继续）", utcnow()
        for item in db.scalars(select(Item).where(Item.ai_status == "running")):
            item.ai_status = "pending"
        db.commit()
    tracking.mark_interrupted()


# ---------------------------------------------------------------- 总控

STAGES = [
    ("snapshot", "星标快照", lambda db, gh, st: snapshot(db, gh, st)),
    ("rankings", "生成榜单", lambda db, gh, st: rankings(db, st)),
    ("blurbs", "榜单中文详解", lambda db, gh, st: blurbs.refresh(db, gh, st)),
    ("discover", "发现新仓库", lambda db, gh, st: discover(db, gh, st)),
    ("extract", "AI 提炼", lambda db, gh, st: extract_pending(db, st)),
]


def run_crawl(trigger: str = "schedule", deadline: datetime | None = None) -> int | None:
    """执行一轮完整采集，返回 JobRun id；已有任务在跑时返回 None。"""
    if not _lock.acquire(blocking=False):
        return None
    deadline = deadline or window_deadline()
    with SessionLocal() as db:
        job = JobRun(job_name="daily_crawl", status="running",
                     stats={"trigger": trigger, "deadline": deadline.isoformat(), "stage": "snapshot"})
        db.add(job)
        db.commit()
        global _current_job
        _current_job = job.id
        stats: dict = dict(job.stats)
        status, error = "ok", ""
        try:
            with crawl_budget(deadline), GitHub() as gh:
                for key, label, fn in STAGES:
                    stats["stage"] = key
                    job.stats = dict(stats)
                    db.commit()
                    t0 = time.monotonic()
                    try:
                        fn(db, gh, stats)
                    except BudgetExhausted as e:
                        db.rollback()
                        status, error = "partial", str(e)
                        stats.setdefault("stage_seconds", {})[key] = round(time.monotonic() - t0, 1)
                        break
                    except GitHubError as e:
                        # 网络等问题：记下来，后面的阶段照常跑（榜单 / 提炼不依赖本阶段全部成功）
                        db.rollback()
                        stats.setdefault("stage_errors", {})[key] = str(e)[:300]
                        if status == "ok":
                            status = "warning"
                    stats.setdefault("stage_seconds", {})[key] = round(time.monotonic() - t0, 1)
        except Exception as e:
            db.rollback()
            log.exception("crawl failed")
            status, error = "failed", f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[-1500:]}"
        finally:
            stats["stage"] = "done"
            stats["rate"] = {k: v for k, v in rate_state.items()}
            job = db.get(JobRun, job.id)
            job.stats, job.status, job.error, job.finished_at = stats, status, error[:4000], utcnow()
            db.commit()
            _current_job = None
            _lock.release()
        return job.id


def start_in_background(trigger: str) -> bool:
    if is_running():
        return False
    # 窗口内跑到窗口结束；窗口外手动触发只给 1 小时，额度不够就留给夜里
    now = datetime.now(tz())
    deadline = window_deadline(now) if in_window(now) else now + timedelta(hours=1)
    threading.Thread(target=run_crawl, args=(trigger, deadline), daemon=True, name="crawl").start()
    return True


def pending_counts(db: Session) -> dict:
    return {
        "pending_review": db.scalar(select(func.count()).where(Item.status == "pending_review")),
        "pending_extract": db.scalar(select(func.count()).where(Item.status == "published", Item.ai_status == "pending")),
    }
