"""对比（v2.3）：用户勾选 2~6 个条目（本站收录的条目，或外站的 GitHub 仓库），AI 先分组再多维度对比、给出推荐。

- 本站条目：直接用库里的介绍、安装步骤、星标、近 30 天星标增长、更新时间、许可证。
- 外站仓库：如果其实已经收录，按本站条目处理；否则现取 GitHub 仓库信息和 README 前一段（不入库）。
- 同一组条目 7 天内重复对比直接复用结果；分析在后台线程里做，前端轮询。
"""

import hashlib
import logging
import re
import threading
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..db import SessionLocal, utcnow
from ..models import CompareRun, Item, StarSnapshot
from ..schemas import _cover_url
from .thumbs import thumb_url
from ..seed import KINDS
from . import billing, judge
from .github import GitHub, GitHubError, RepoRef
from .ingest import existing_item_for

log = logging.getLogger(__name__)
MIN_ITEMS, MAX_ITEMS = 2, 6
REUSE = timedelta(days=7)
README_CHARS = 3500
CODES = "ABCDEF"


class CompareError(Exception):
    pass


def normalize(entries: list[dict]) -> list[dict]:
    """校验并去重：{"item_id": 1} 或 {"full_name": "owner/repo", "sub_path": ""}。"""
    out, seen = [], set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        if isinstance(e.get("item_id"), int):
            k, v = f"i:{e['item_id']}", {"item_id": e["item_id"]}
        elif isinstance(e.get("full_name"), str) and re.fullmatch(r"[\w.-]+/[\w.-]+", e["full_name"]):
            sub = str(e.get("sub_path") or "").strip("/")[:200]
            k, v = f"r:{e['full_name'].lower()}/{sub}", {"full_name": e["full_name"], "sub_path": sub}
        else:
            continue
        if k not in seen:
            seen.add(k)
            out.append(v)
    if not MIN_ITEMS <= len(out) <= MAX_ITEMS:
        raise CompareError(f"请选择 {MIN_ITEMS}~{MAX_ITEMS} 个条目进行对比")
    return out


def _entry_key(e: dict) -> str:
    return f"i:{e['item_id']}" if "item_id" in e else f"r:{e['full_name'].lower()}/{e.get('sub_path', '')}"


def fingerprint(entries: list[dict]) -> str:
    return hashlib.sha256("|".join(sorted(_entry_key(e) for e in entries)).encode()).hexdigest()[:40]


def _growth(db, repo_id: int | None, stars: int | None) -> int | None:
    if not repo_id or stars is None:
        return None
    since = (utcnow() - timedelta(days=30)).date()
    old = db.scalar(select(StarSnapshot.stars).where(StarSnapshot.repo_id == repo_id, StarSnapshot.snap_date <= since)
                    .order_by(StarSnapshot.snap_date.desc()).limit(1))
    return stars - old if old is not None else None


def _item_subject(db, it: Item) -> dict:
    r = it.repo
    return {
        "source": "site", "item_id": it.id, "name": it.name, "repo": r.full_name if r else "", "sub_path": it.sub_path or "",
        "html_url": r.html_url if r else it.homepage_url, "kind": KINDS.get(it.kind, ("",))[0], "category": it.category.name if it.category else "",
        "summary": it.summary, "description": (it.description or "")[:1500], "install": (it.install_steps or [])[:6],
        "stars": r.stars if r else None, "growth_30d": _growth(db, r.id if r else None, r.stars if r else None),
        "pushed_at": r.pushed_at.date().isoformat() if r and r.pushed_at else "", "archived": bool(r and r.archived),
        "license": r.license if r else "", "cover_url": _cover_url(it), "cover_thumb_url": thumb_url(it.cover_path), "offline": it.status == "offline",
    }


def subjects_for(entries: list[dict]) -> list[dict]:
    """展示用的基本信息（不调 GitHub）：本站条目来自库；外站仓库先用名称占位，分析时再补全。"""
    out = []
    with SessionLocal() as db:
        for e in entries:
            if "item_id" in e:
                it = db.scalar(select(Item).options(joinedload(Item.repo), joinedload(Item.category))
                               .where(Item.id == e["item_id"], Item.status.in_(("published", "offline"))))
                if it is None:
                    raise CompareError("有条目不存在或未公开，请从对比栏移除后再试")
                out.append(_item_subject(db, it))
            else:
                ex = existing_item_for(db, e["full_name"], e.get("sub_path") or None)
                it = db.scalar(select(Item).options(joinedload(Item.repo), joinedload(Item.category)).where(Item.id == ex)) if ex else None
                if it is not None and it.status in ("published", "offline"):
                    out.append(_item_subject(db, it))
                else:
                    name = (e.get("sub_path") or "").split("/")[-1] or e["full_name"].split("/")[1]
                    out.append({"source": "github", "item_id": None, "name": name, "repo": e["full_name"], "sub_path": e.get("sub_path", ""),
                                "html_url": f"https://github.com/{e['full_name']}" + (f"/tree/HEAD/{e['sub_path']}" if e.get("sub_path") else ""),
                                "kind": "", "category": "", "summary": "", "stars": None, "cover_url": "", "cover_thumb_url": None})
    for code, s in zip(CODES, out):
        s["code"] = code
    return out


def _fill_github(gh: GitHub, s: dict) -> None:
    owner, name = s["repo"].split("/", 1)
    d = gh.repo(RepoRef(owner, name))
    s.update(stars=d.get("stargazers_count"), pushed_at=(d.get("pushed_at") or "")[:10], archived=bool(d.get("archived")),
             license=((d.get("license") or {}).get("spdx_id") or ""), summary=d.get("description") or "",
             language=d.get("language") or "", topics=(d.get("topics") or [])[:10])
    try:
        text, _, _ = gh.readme(s["repo"], s.get("sub_path") or "")
        text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", "", text)
        s["readme"] = re.sub(r"\n{3,}", "\n\n", text).strip()[:README_CHARS]
    except GitHubError:
        s["readme"] = ""


def start(entries: list[dict], user_id: int | None) -> int:
    """返回对比任务 id；7 天内同一组条目已经对比过的直接复用。"""
    entries = normalize(entries)
    key = fingerprint(entries)
    with SessionLocal() as db:
        old = db.scalar(select(CompareRun).where(CompareRun.key == key, CompareRun.status.in_(("done", "running")),
                                                 CompareRun.created_at >= utcnow() - REUSE).order_by(CompareRun.id.desc()))
        if old is not None:
            return old.id
    subjects = subjects_for(entries)
    with SessionLocal() as db:
        run = CompareRun(key=key, entries=entries, subjects=subjects, status="running", stage="正在读取资料…", user_id=user_id)
        db.add(run)
        db.commit()
        run_id = run.id
    threading.Thread(target=_run, args=(run_id,), daemon=True, name=f"compare-{run_id}").start()
    return run_id


def _set(run_id: int, **patch) -> None:
    with SessionLocal() as db:
        run = db.get(CompareRun, run_id)
        for k, v in patch.items():
            setattr(run, k, v)
        db.commit()


def _run(run_id: int) -> None:
    with SessionLocal() as db:
        uid = db.get(CompareRun, run_id).user_id
    with billing.charged_to(uid):
        _run_inner(run_id)


def _run_inner(run_id: int) -> None:
    from .extract import model_label

    try:
        with SessionLocal() as db:
            subjects = [dict(s) for s in db.get(CompareRun, run_id).subjects]
        ext = [s for s in subjects if s["source"] == "github"]
        if ext:
            _set(run_id, stage=f"正在读取 {len(ext)} 个 GitHub 仓库的介绍…")
            with GitHub() as gh:
                for s in ext:
                    try:
                        _fill_github(gh, s)
                    except GitHubError as e:
                        s["summary"] = s["summary"] or f"（读取仓库失败：{e}）"
            _set(run_id, subjects=[{k: v for k, v in s.items() if k not in ("readme", "topics", "language")} for s in subjects])
        _set(run_id, stage="AI 正在分组并多维度对比…")
        brief = [{k: v for k, v in s.items() if k not in ("cover_url", "cover_thumb_url", "item_id", "html_url", "offline") and v not in ("", None, [])}
                 for s in subjects]
        for b in brief:
            b["source"] = "本站收录" if b["source"] == "site" else "GitHub（未收录）"
        result = judge.compare_items(brief)
        _set(run_id, status="done", stage="", result=result, model=model_label(), finished_at=utcnow())
    except judge.JudgeUnavailable as e:
        _set(run_id, status="failed", stage="", error=f"AI 暂时不可用：{e}"[:300], finished_at=utcnow())
    except Exception as e:  # noqa: BLE001 — 后台任务，任何异常都要落到状态里
        log.exception("compare %s failed", run_id)
        _set(run_id, status="failed", stage="", error=f"对比失败：{e.__class__.__name__}"[:300], finished_at=utcnow())


def subject_thumb(s: dict) -> str | None:
    """v3.3.12 老的对比记录里没存缩略图地址：从封面地址推出来。"""
    url = s.get("cover_url") or ""
    return s.get("cover_thumb_url") or (thumb_url(url[len("/media/"):]) if url.startswith("/media/") else None)


def run_out(run: CompareRun) -> dict:
    subjects = [{**s, "cover_thumb_url": subject_thumb(s)} for s in run.subjects or []]
    return {"id": run.id, "status": run.status, "stage": run.stage, "subjects": subjects, "result": run.result or {},
            "error": run.error, "model": run.model, "created_at": run.created_at, "finished_at": run.finished_at}
