"""新增 Skill 的两种查找方式，都在后台线程里跑，进度和结果写在 FinderJob.result 里供前端轮询。

搜索添加（kind=search）：
  需求 → AI 理解并生成 3~5 组英文搜索词 → GitHub 搜索（+ skills.sh）→ 合并去重 → AI 按相关度打分排序

长文识别（kind=text）：
  原文 / 链接 → 提取文中的 GitHub 链接 → AI 分段通读抽取提到的项目 → 合并去重 → 逐条对应仓库（必要时 AI 挑选）

两者的结果都是候选列表，用户勾选后走 ingest.import_picks 入库。
"""

import html
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx

from ..config import settings
from ..db import SessionLocal
from ..models import FinderJob
from . import billing, cache, judge, vision
from .github import GitHub, GitHubError, RepoRef, parse_repo_url
from .ingest import existing_item_for

log = logging.getLogger(__name__)

_write_lock = threading.Lock()
SEARCH_TTL = timedelta(hours=24)
PLAN_TTL = timedelta(days=7)
PER_QUERY = 10
MIN_SCORE = 50
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 300


# ---------------------------------------------------------------- 结果读写

def _update(job_id: int, **patch) -> dict:
    """合并写入 result；candidates 整体替换。"""
    with _write_lock, SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        data = dict(job.result or {})
        status = patch.pop("status", None)
        data.update(patch)
        job.result = data
        if status:
            job.status = status
        db.commit()
        return data


def _set_candidate(job_id: int, index: int, patch: dict) -> None:
    with _write_lock, SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        data = dict(job.result)
        cands = list(data.get("candidates") or [])
        cands[index] = {**cands[index], **patch}
        data["candidates"] = cands
        if all(c.get("state") != "resolving" for c in cands) and job.status == "running" and data.get("stage") == "resolve":
            job.status, data["stage"], data["message"] = "done", "done", f"找到 {len(cands)} 个"
        job.result = data
        db.commit()


def mark_importing(job_id: int, indexes: list[int]) -> list[int]:
    """v3.3.7 把勾选的行标成「加入中」（加锁逐行改，不覆盖正在后台加入的其他批次）。
    已经在加入中 / 已收录的行跳过，返回真正要加入的序号。"""
    with _write_lock, SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        data = dict(job.result or {})
        cands = list(data.get("candidates") or [])
        ok = []
        for i in indexes:
            if 0 <= i < len(cands) and cands[i].get("state") == "matched":
                cands[i] = {**cands[i], "state": "importing", "import_error": ""}
                ok.append(i)
        data["candidates"] = cands
        data["importing"] = any(c.get("state") == "importing" for c in cands)
        job.result = data
        db.commit()
        return ok


def _finish_importing(job_id: int, patch: dict) -> None:
    """一批加完：只有所有行都不在「加入中」了，任务的 importing 才清掉（可能还有别的批次在跑）。"""
    with _write_lock, SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        data = dict(job.result or {})
        data.update(patch)
        data["importing"] = any(c.get("state") == "importing" for c in data.get("candidates") or [])
        job.result = data
        job.status = "imported"
        db.commit()


def run_import(job_id: int, picks: list[dict], user_id: int | None, review: bool) -> None:
    """后台逐个加入勾选的结果（v3.0.3）：核对仓库、建条目可能要一两分钟，不再让接口干等（网关 60 秒会超时）。
    每加好一个就把那一行改成「已收录」并带上条目 id，前端轮询任务就能原地更新；全部加完再建 AI 提炼任务。"""
    from . import activity, ingest

    created_all: list[int] = []
    trigger = "search"
    try:
        with billing.charged_to(user_id):
            with SessionLocal() as db:
                job = db.get(FinderJob, job_id)
                trigger = "search" if job.kind == "search" else "text"
                for p in picks:
                    idx = p.pop("index", None)
                    try:
                        created, skipped, errors = ingest.import_picks(db, [p], trigger, user_id=user_id, review=review)
                    except Exception as e:  # 单个失败不影响其他
                        log.exception("import pick failed: %s", p.get("full_name"))
                        created, skipped, errors = [], [], [f"{p.get('full_name')}：{e}"]
                    created_all += created
                    if idx is None:
                        continue
                    if created:
                        _set_candidate(job_id, idx, {"state": "existing", "existing_item_id": created[0], "import_error": ""})
                    elif skipped:
                        ex = ingest.existing_item_for(db, p["full_name"], p.get("sub_path"))
                        _set_candidate(job_id, idx, {"state": "existing", "existing_item_id": ex, "import_error": ""})
                    else:
                        _set_candidate(job_id, idx, {"state": "matched", "import_error": "；".join(errors) or "加入失败"})
    finally:
        label = "搜索添加" if trigger == "search" else "长文识别"
        task_id = ingest.start_process_task(trigger, f"{label} · {len(created_all)} 个条目", created_all, workers=2, user_id=user_id)
        _finish_importing(job_id, {"last_import": {"created": created_all, "task_id": task_id}})
        if created_all:
            from ..models import User
            with SessionLocal() as db:
                who = db.get(User, user_id) if user_id else None
                activity.record("item_submit", f"{label}新增 {len(created_all)} 个条目", user=who, target_type="task",
                                target_id=task_id, detail={"item_ids": created_all, "via": trigger, "job_id": job_id})


def create_job(kind: str, query: str, source_url: str = "", user_id: int | None = None) -> int:
    with SessionLocal() as db:
        job = FinderJob(kind=kind, query=query, source_url=source_url, status="running", user_id=user_id,
                        result={"stage": "start", "message": "准备中…", "candidates": []})
        db.add(job)
        db.commit()
        return job.id


def _fail(job_id: int, message: str) -> None:
    _update(job_id, status="failed", stage="failed", message=message, error=message)


def _existing(full_name: str, sub_path: str | None) -> int | None:
    with SessionLocal() as db:
        return existing_item_for(db, full_name, sub_path)


def _brief(d: dict) -> dict:
    return {"full_name": d["full_name"], "html_url": d["html_url"], "description": d.get("description") or "",
            "stars": d.get("stargazers_count", 0), "language": d.get("language") or "", "topics": d.get("topics") or [],
            "pushed_at": d.get("pushed_at"), "default_branch": d.get("default_branch") or "main"}


# ---------------------------------------------------------------- 搜索添加

def _cached_search(gh: GitHub, q: str) -> list[dict]:
    key = cache.make_key("ghsearch", q)
    hit = cache.get(key)
    if hit is not None:
        return hit
    found = [_brief(d) for d in gh.search_repos(q, per_page=PER_QUERY, sort=None)]
    cache.put(key, found, SEARCH_TTL)
    return found


def _plan(q: str, avoid: list[str]) -> dict:
    """AI 生成搜索方案；首次（不换说法）的方案缓存 7 天。AI 不可用时只能直接搜原文。"""
    key = cache.make_key("plan", q)
    if not avoid:
        hit = cache.get(key)
        if hit:
            return hit
    try:
        plan = judge.plan_search(q, avoid)
    except judge.JudgeUnavailable:
        if re.search(r"[一-鿿]", q):
            raise
        plan = {"intent": "named", "kind": "", "understanding": "", "queries": [q], "skill_queries": [q], "fallback": True}
    if not avoid:
        cache.put(key, plan, PLAN_TTL)
    return plan


def _job_owner(job_id: int) -> int | None:
    with SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        return job.user_id if job else None


def run_search(job_id: int, more: bool = False) -> None:
    try:
        with billing.charged_to(_job_owner(job_id)):
            _run_search(job_id, more)
    except Exception as e:
        log.exception("search job %s failed", job_id)
        _fail(job_id, f"搜索失败：{e}")


def _run_search(job_id: int, more: bool) -> None:
    with SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        q, prev = job.query, dict(job.result or {})
    avoid = [x for p in prev.get("plans") or [] for x in p["queries"]] if more else []
    old = {c["full_name"].lower(): c for c in prev.get("candidates") or []} if more else {}

    # 直接给了 GitHub 地址 / owner/repo：不用搜，直接核实
    direct = None
    if re.fullmatch(r"\s*(https?://)?(www\.)?github\.com/\S+\s*|\s*[\w.-]+/[\w.-]+\s*", q):
        try:
            direct = parse_repo_url(q)
        except GitHubError:
            direct = None

    _update(job_id, stage="plan", message="AI 正在理解你的需求…")
    if direct:
        plan = {"intent": "named", "kind": "", "understanding": f"直接查找 {direct.full_name}", "queries": [], "skill_queries": []}
    else:
        try:
            plan = _plan(q, avoid)
        except judge.JudgeUnavailable as e:
            return _fail(job_id, f"中文需求需要 AI 理解后才能搜索，但 AI 暂不可用：{e}")
    # v3.0 首页 GitHub 搜索框不再区分「搜索添加 / 长文识别」：AI 判断输入其实是一串项目名或一段介绍时，转去逐个识别
    if plan.get("intent") == "list" and not more and not direct:
        with SessionLocal() as db:
            db.get(FinderJob, job_id).kind = "text"
            db.commit()
        _update(job_id, rerouted="text", plan=plan, message="AI 判断这是多个项目，改为逐个识别…")
        return _run_text(job_id)
    plans = (prev.get("plans") or []) + [plan] if more else [plan]
    _update(job_id, plan=plan, plans=plans)

    found: dict[str, dict] = {}
    with GitHub() as gh:
        if direct:
            try:
                d = _brief(gh.repo(RepoRef(direct.owner, direct.repo)))
                found[d["full_name"].lower()] = {**d, "sub_path": direct.sub_path, "via": "github", "hits": 1}
            except GitHubError as e:
                return _fail(job_id, f"找不到这个仓库：{e}")
        for n, sq in enumerate(plan["queries"], start=1):
            _update(job_id, stage="search", message=f"正在搜索第 {n}/{len(plan['queries'])} 组：{sq}")
            try:
                for d in _cached_search(gh, sq):
                    k = d["full_name"].lower()
                    if k in found:
                        found[k]["hits"] += 1
                    elif k not in old:
                        found[k] = {**d, "sub_path": None, "via": "search", "hits": 1}
            except GitHubError as e:
                _update(job_id, warning=f"「{sq}」搜索失败：{e}")
        for sq in plan.get("skill_queries") or []:
            _update(job_id, stage="search", message=f"正在 skills.sh 查找 Skill：{sq}")
            for hit in vision.skills_sh_search(sq, limit=5):
                k = hit["source"].lower()
                if k in old:
                    continue
                if k in found:
                    found[k].setdefault("skill_id", hit["skill_id"])
                    found[k]["installs"] = hit["installs"]
                    continue
                try:
                    owner, name = hit["source"].split("/", 1)
                    d = _brief(gh.repo(RepoRef(owner, name)))
                except (GitHubError, ValueError):
                    continue
                found[k] = {**d, "sub_path": None, "via": "skills.sh", "hits": 1, "skill_id": hit["skill_id"],
                            "installs": hit["installs"]}

        cands = list(found.values())[:40]
        if not cands:
            return _update(job_id, status="done", stage="done", message="没有搜到相关仓库，换个说法试试",
                           candidates=list(old.values()))

        # 先把 GitHub 原始结果（按命中次数、星标排）给前端显示，AI 排序在后面补上，不让用户干等
        prelim = sorted(cands, key=lambda c: (-c["hits"], -(c["stars"] or 0)))
        for c in prelim:
            ex = _existing(c["full_name"], c["sub_path"])
            c.update(name=c.get("skill_id") or c["full_name"].split("/")[1], score=None, reason="", kind=plan.get("kind") or "",
                     state="existing" if ex else "matched", existing_item_id=ex,
                     match={k: c.get(k) for k in ("full_name", "html_url", "description", "description_zh", "stars", "language")})
        _update(job_id, stage="rank", message=f"搜到 {len(cands)} 个，AI 正在按相关度排序…",
                candidates=list(old.values()) + prelim, preliminary=True)
        try:
            scores = judge.rerank(q if not plan.get("understanding") else f"{q}（{plan['understanding']}）", cands)
        except judge.JudgeUnavailable:
            scores = {}
        for c in cands:
            s = scores.get(c["full_name"].lower())
            c.update(score=s["score"] if s else None, reason=s["reason"] if s else "", kind=(s or {}).get("kind") or plan.get("kind") or "",
                     description_zh=(s or {}).get("desc_zh") or "")  # v3.3.86 中文简介，小程序简洁模式 GitHub 列用
        if scores:
            cands = [c for c in cands if (c["score"] or 0) >= MIN_SCORE]
            cands.sort(key=lambda c: (-(c["score"] or 0), -c["hits"], -(c["stars"] or 0)))
        else:
            cands.sort(key=lambda c: (-c["hits"], -(c["stars"] or 0)))

        rv = vision.Resolver(gh)
        for c in cands:
            if c.get("skill_id") and c["sub_path"] is None:
                c["sub_path"] = rv.skill_dir(c["full_name"], c["default_branch"], c["skill_id"])
            c["name"] = c["skill_id"] if c.get("skill_id") and c["sub_path"] else c["full_name"].split("/")[1]
            ex = _existing(c["full_name"], c["sub_path"])
            c.update(state="existing" if ex else "matched", existing_item_id=ex,
                     match={k: c.get(k) for k in ("full_name", "html_url", "description", "description_zh", "stars", "language")})

    merged = list(old.values()) + cands
    msg = f"找到 {len(cands)} 个相关结果" if cands else "这次没找到更相关的结果"
    _update(job_id, status="done", stage="done", message=msg, candidates=merged, preliminary=False)


# ---------------------------------------------------------------- 长文识别

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def html_to_text(page: str) -> str:
    """网页转纯文本：保留链接地址（文中的 GitHub 链接是最准的线索），去掉脚本、样式和标签。"""
    m = re.search(r'<div[^>]+id="js_content"[^>]*>(.*)', page, re.S)  # 微信公众号正文
    if m:
        page = m.group(1)
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", page, flags=re.S | re.I)
    page = re.sub(r"<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", page, flags=re.I)
    page = re.sub(r"<[^>]+>", " ", page)
    page = html.unescape(page)
    page = re.sub(r"[ \t\r\f\v]+", " ", page)
    return re.sub(r"\n\s*\n+", "\n\n", page).strip()


def fetch_article(url: str) -> str:
    if not re.match(r"^https?://", url):
        url = "https://" + url
    try:
        r = httpx.get(url, headers=_UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ValueError(f"抓取文章失败：{e.__class__.__name__}，请把正文复制粘贴进来") from e
    ctype = r.headers.get("content-type", "")
    text = html_to_text(r.text) if "html" in ctype or "<html" in r.text[:500].lower() else r.text
    if len(text) < 200:
        raise ValueError("没抓到正文（可能需要登录或有反爬限制），请把正文复制粘贴进来")
    return text[: settings.text_max_chars]


# 只认 ASCII 字符：中文正文里链接后面常紧跟全角标点或汉字
_GH_LINK = re.compile(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(?:tree|blob)/[\w.%-]+/([\w./%-]+))?(?![\w-]|\.\w)", re.A)
_NOT_OWNER = {"topics", "orgs", "sponsors", "features", "marketplace", "settings", "login", "about", "collections", "trending", "apps"}


def github_links(text: str) -> list[dict]:
    out, seen = [], set()
    for owner, repo, path in _GH_LINK.findall(text):
        if owner.lower() in _NOT_OWNER:
            continue
        sub = path.rstrip(".").removesuffix("/SKILL.md").removesuffix("SKILL.md").strip("/") if path else ""
        key = f"{owner}/{repo}/{sub}".lower()
        if key not in seen:
            seen.add(key)
            out.append({"repo": f"{owner}/{repo}", "sub_path": sub or None})
    return out


def chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_CHARS:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        # 尽量在段落处断开
        cut = text.rfind("\n", start + CHUNK_CHARS // 2, end)
        end = cut if cut > 0 and end < len(text) else end
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return parts


def run_text(job_id: int) -> None:
    try:
        with billing.charged_to(_job_owner(job_id)):
            _run_text(job_id)
    except Exception as e:
        log.exception("text job %s failed", job_id)
        _fail(job_id, f"识别失败：{e}")


def _run_text(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(FinderJob, job_id)
        text, url = job.query, job.source_url
    if not text and url:
        _update(job_id, stage="fetch", message="正在抓取文章…")
        try:
            text = fetch_article(url)
        except ValueError as e:
            return _fail(job_id, str(e))
        with SessionLocal() as db:
            db.get(FinderJob, job_id).query = text
            db.commit()

    links = github_links(text)
    parts = chunks(text)
    _update(job_id, stage="read", message=f"AI 正在通读全文（共 {len(parts)} 段）…", chars=len(text), links=len(links))
    done = [0]

    def read(part: str) -> list[dict]:
        try:
            got = judge.extract_mentions(part)
        finally:
            done[0] += 1
            _update(job_id, message=f"AI 正在通读全文（{done[0]}/{len(parts)} 段）…")
        return got

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            mentions = [m for got in pool.map(billing.wrap(billing.owner(), read), parts) for m in got]
    except judge.JudgeUnavailable as e:
        if not links:
            return _fail(job_id, f"长文识别需要 AI，但 AI 暂不可用：{e}")
        mentions = []

    # 合并：同一仓库或同名的只保留一条；文中有链接但 AI 没提到的也补上
    merged: dict[str, dict] = {}
    for m in mentions:
        k = (m["repo"] or "").lower() or vision.norm(m["name"])
        if k in merged:
            if not merged[k]["context"] and m["context"]:
                merged[k]["context"] = m["context"]
            continue
        merged[k] = {**m, "sub_path": None}
    by_name = {vision.norm(v["name"]): v for v in merged.values()}
    for ln in links:
        k = ln["repo"].lower()
        name = (ln["sub_path"] or ln["repo"]).rsplit("/", 1)[-1]
        if k in merged:
            merged[k]["sub_path"] = merged[k]["sub_path"] or ln["sub_path"]
            merged[k]["from_link"] = True
            continue
        hit = by_name.get(vision.norm(name)) or by_name.get(vision.norm(ln["repo"].split("/")[1]))
        if hit and (not hit["repo"] or hit["repo"].lower() == k):
            hit["repo"], hit["sub_path"], hit["from_link"] = ln["repo"], ln["sub_path"], True
            continue
        merged[k] = {"name": name, "repo": ln["repo"], "kind": "", "open_source": True, "homepage": None,
                     "context": "", "description": "", "sub_path": ln["sub_path"], "from_link": True}

    cands = []
    for m in merged.values():
        closed = m["open_source"] is False and not m["repo"]
        cands.append({**m, "state": "closed" if closed else "resolving", "match": None, "existing_item_id": None,
                      "via": None, "uncertain": False, "suggestions": []})
    if not cands:
        return _update(job_id, status="done", stage="done", message="文中没有找到 Skill、模型或项目", candidates=[])
    _update(job_id, stage="resolve", message=f"识别出 {len(cands)} 个，正在对应 GitHub 仓库…", candidates=cands)
    if all(c["state"] != "resolving" for c in cands):
        return _update(job_id, status="done", stage="done", message=f"识别出 {len(cands)} 个")

    with GitHub() as gh:
        rv = vision.Resolver(gh)

        def one(pair):
            i, c = pair
            if c["state"] != "resolving":
                return
            try:
                patch = _resolve_mention(gh, rv, c)
            except Exception as e:
                patch = {"state": "unmatched", "error": str(e)[:200]}
            _set_candidate(job_id, i, patch)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(billing.wrap(billing.owner(), one), list(enumerate(cands))))


def _resolve_mention(gh: GitHub, rv: "vision.Resolver", c: dict) -> dict:
    if c["repo"]:
        owner, name = c["repo"].split("/", 1)
        try:
            d = gh.repo(RepoRef(owner, name))
            match = vision._repo_brief(d)
            sub = c["sub_path"] or ""
            ex = _existing(match["full_name"], sub)
            # 原文里的链接最可信；AI 凭记忆给出的 owner/repo 已核实存在，但仍标明来源
            return {"match": match, "sub_path": c["sub_path"], "via": "link" if c.get("from_link") else "ai",
                    "state": "existing" if ex else "matched", "existing_item_id": ex}
        except GitHubError:
            pass  # 文中写错或模型记错，按名称再找
    r = rv.resolve({"name": c["name"], "repo": None, "kind": "skill" if c["kind"] == "agent_skill" else c["kind"] or "other",
                    "context": c["context"], "description": c["description"]})
    patch = {k: r.get(k) for k in ("match", "sub_path", "via", "installs", "suggestions", "uncertain", "pick_reason")}
    if r["match"]:
        ex = _existing(r["match"]["full_name"], r["sub_path"])
        patch.update(state="existing" if ex else "matched", existing_item_id=ex)
    else:
        patch["state"] = "closed" if c["open_source"] is False else "unmatched"
    return patch
