"""GitHub 仓库入库：预览 → 选择 → 建条目 → 后台提炼（描述/安装/分类/封面）。"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from posixpath import basename

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, utcnow
from ..models import AppMeta, Category, Discovery, Item, Repo
from ..seed import FALLBACK_CODE
from .cover import COVER_THEME, GROUP_COLORS, THEME, generate_cover
from .extract import SourceDoc, extract, translate_texts
from .tracking import ItemTracker, create_task, start_task
from .github import BudgetExhausted, GitHub, GitHubError, NotFound, find_images, find_skill_dirs, parse_frontmatter, parse_repo_url, strip_frontmatter

log = logging.getLogger(__name__)

# 人工可编辑、受 locked_fields 保护的字段
EDITABLE_FIELDS = ("name", "summary", "description", "install_steps", "category_id", "kind", "cover_path", "homepage_url", "rank_blurb")

_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
MIN_COVER_BYTES = 8 * 1024  # 太小的多半是图标


def _parse_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def upsert_repo(db: Session, data: dict) -> Repo:
    repo = db.scalar(select(Repo).where(Repo.github_id == data["id"]))
    if repo is None:
        repo = Repo(github_id=data["id"])
        db.add(repo)
    repo.full_name = data["full_name"]
    repo.html_url = data["html_url"]
    repo.gh_description = data.get("description") or ""
    repo.topics = data.get("topics") or []
    repo.language = data.get("language") or ""
    repo.license = (data.get("license") or {}).get("spdx_id") or ""
    repo.stars = data.get("stargazers_count", 0)
    repo.forks = data.get("forks_count", 0)
    repo.default_branch = data.get("default_branch") or "main"
    repo.pushed_at = _parse_dt(data.get("pushed_at"))
    repo.archived = bool(data.get("archived"))
    repo.last_synced_at = utcnow()
    db.flush()
    return repo


def _blocklisted(db: Session, full_name: str) -> bool:
    from . import blocklist

    return blocklist.match(db, full_name) is not None


def preview(db: Session, url: str) -> dict:
    """解析地址，列出可入库的条目（monorepo 拆成多个 Skill）。"""
    ref = parse_repo_url(url)
    with GitHub() as gh:
        data = gh.repo(ref)
        full_name, branch = data["full_name"], data.get("default_branch") or "main"
        skill_dirs = find_skill_dirs(gh.tree_paths(full_name, branch))
        if ref.sub_path is not None:
            prefix = ref.sub_path.rstrip("/")
            skill_dirs = [d for d in skill_dirs if d == prefix or d.startswith(prefix + "/")]

        candidates = []
        if skill_dirs:
            def load(d: str) -> dict:
                path = f"{d}/SKILL.md" if d else "SKILL.md"
                try:
                    fm = parse_frontmatter(gh.file_text(full_name, branch, path))
                except GitHubError:
                    fm = {}
                return {"sub_path": d, "kind": "skill", "name": fm.get("name") or basename(d) or data["name"],
                        "description": fm.get("description", "")}

            with ThreadPoolExecutor(max_workers=8) as pool:
                candidates = list(pool.map(load, skill_dirs))
        else:
            candidates = [{"sub_path": "", "kind": "repo", "name": data["name"],
                           "description": data.get("description") or ""}]

    # 预览列表里的英文简介译成中文（一次批量调用；未配置 AI 时原样）
    zh = translate_texts([c["description"] for c in candidates] + [data.get("description") or ""])
    for c, d in zip(candidates, zh):
        c["description"] = d
    repo_desc_zh = zh[-1]

    repo = db.scalar(select(Repo).where(Repo.github_id == data["id"]))
    existing = {}
    if repo:
        existing = {i.sub_path: i.id for i in repo.items}
    for c in candidates:
        c["existing_item_id"] = existing.get(c["sub_path"])

    return {
        "repo": {
            "full_name": full_name, "html_url": data["html_url"], "description": repo_desc_zh,
            "stars": data.get("stargazers_count", 0), "language": data.get("language") or "",
            "topics": data.get("topics") or [], "default_branch": branch,
            "blocked": bool(repo and repo.repo_status == "rejected") or _blocklisted(db, full_name),
        },
        "mode": "skills" if skill_dirs else "repo",
        "candidates": candidates,
    }


def import_items(db: Session, url: str, picks: list[dict], source: str = "manual", user_id: int | None = None,
                 review: bool = False) -> list[int]:
    """review=True：普通用户提交，条目先进入「审核中」，提炼完成后由 AI 审核（services/review.py）。"""
    """picks: [{"sub_path", "kind", "name"}]。返回新建条目 id，已存在的跳过。"""
    ref = parse_repo_url(url)
    from . import blocklist

    if blocklist.match(db, ref.full_name):
        raise GitHubError("这个仓库已被列入黑名单，不能收录")
    with GitHub() as gh:
        data = gh.repo(ref)
    if blocklist.match(db, data["full_name"]):  # 改过名 / 转过户
        raise GitHubError("这个仓库已被列入黑名单，不能收录")
    repo = upsert_repo(db, data)
    repo.repo_status = "active"  # 手动导入视为解除拉黑
    db.add(Discovery(repo_id=repo.id, channel=source, channel_ref=url))

    placeholder = db.scalar(select(Category).where(Category.code == FALLBACK_CODE))
    existing = {i.sub_path for i in repo.items}
    ids = []
    for p in picks:
        sub = p.get("sub_path", "")
        if sub in existing:
            continue
        item = Item(
            repo_id=repo.id, sub_path=sub, name=p.get("name") or basename(sub) or repo.full_name.split("/")[1],
            category_id=placeholder.id, summary=p.get("description", "")[:500], source=source,
            status="awaiting" if review else "published", review_state="ai" if review else "",
            ai_status="pending", stars_at_collect=repo.stars,
            locked_fields=[], install_steps=[], created_by=user_id if source == "manual" else None,
        )
        db.add(item)
        db.flush()
        ids.append(item.id)
    db.commit()
    return ids


def _enabled_leaf_categories(db: Session) -> list[Category]:
    leafs = db.scalars(
        select(Category).where(Category.parent_id.is_not(None), Category.enabled.is_(True)).order_by(Category.sort)
    ).all()
    return sorted((c for c in leafs if c.parent.enabled), key=lambda c: (c.parent.sort, c.sort))


def category_choices(db: Session) -> list[tuple[str, str, str]]:
    """给 AI 的领域分类列表：(code, 「大类 › 子类」, 说明)。"""
    return [(c.code, f"{c.parent.name} › {c.name}", c.remark) for c in _enabled_leaf_categories(db)]


GALLERY_MAX = 5  # 每个条目最多保存几张文档截图做图片集


def save_image(item_id: int, content: bytes, ctype: str) -> str | None:
    """保存一张图片到 media/covers，返回相对路径；格式不支持返回 None。"""
    if ctype not in _EXT:
        return None
    covers = settings.media_dir / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    name = f"{item_id}-{hashlib.sha1(content).hexdigest()[:10]}.{_EXT[ctype]}"
    (covers / name).write_bytes(content)
    return f"covers/{name}"


def save_gallery(gh: GitHub, item_id: int, urls: list[str], limit: int = GALLERY_MAX) -> tuple[list[str], int]:
    """依次下载文档里的图片（跳过太小的图标、不支持的格式和重复图），返回 (保存路径列表, 尝试过的图片数)。"""
    saved, seen, tried = [], set(), 0
    for url in urls[: limit * 3]:
        if len(saved) >= limit:
            break
        tried += 1
        got = gh.download(url)
        if not got:
            continue
        content, ctype = got
        digest = hashlib.sha1(content).hexdigest()
        if len(content) < MIN_COVER_BYTES or ctype not in _EXT or digest in seen:
            continue
        seen.add(digest)
        path = save_image(item_id, content, ctype)
        if path:
            saved.append(path)
    return saved, tried


def _save_cover(gh: GitHub, item_id: int, urls: list[str]) -> tuple[str | None, int]:
    """只要一张封面时用：返回 (保存路径, 尝试过的图片数)。"""
    saved, tried = save_gallery(gh, item_id, urls, limit=1)
    return (saved[0] if saved else None), tried


COVER_LABEL = {"readme": "README 截图", "ai": "AI 示意图", "placeholder": "占位图", "upload": "上传图片"}


class _StageError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage, self.message = stage, message


def process_item(item_id: int, force: bool = False, task_id: int | None = None, trigger: str = "reextract") -> tuple[bool, str]:
    """拉文档 → 提炼 → 写回（跳过 locked_fields）→ 取封面。每个环节写入库日志。返回 (是否成功, 一句话结果)。"""
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None:
            return False, "条目不存在（可能已被删除）"
        tr = ItemTracker(item, trigger, task_id)
        if item.repo is None:
            tr.error("条目没有关联 GitHub 仓库，无法自动提炼", "repo")
            return False, "没有关联仓库"
        item.ai_status = "running"
        item.ai_error = ""
        db.commit()

        repo = item.repo
        locked = set(item.locked_fields or [])
        try:
            with GitHub() as gh:
                tr.stage("doc")
                try:
                    kind, fm, text, raw, doc_path = fetch_doc(gh, repo, item.sub_path)
                except BudgetExhausted:
                    raise
                except NotFound as e:
                    raise _StageError("doc", f"读取文档失败：{e}" + gone_check(item.id, "refresh")) from e
                except GitHubError as e:
                    raise _StageError("doc", f"读取文档失败：{e}") from e

                tr.stage("ai")
                leafs = _enabled_leaf_categories(db)
                doc = SourceDoc(
                    kind=kind, name=fm.get("name") or item.name, full_name=repo.full_name,
                    clone_url=repo.html_url + ".git", sub_path=item.sub_path,
                    gh_description=repo.gh_description, topics=repo.topics or [], text=text, frontmatter=fm,
                )
                result = extract(doc, category_choices(db))
                if result.error:
                    tr.warn(f"AI 提炼失败，已用规则兜底（内容为英文原文）：{result.error}", "ai")
                elif not result.by_ai:
                    tr.warn("未配置 AI 接口，用规则提炼（内容为英文原文）", "ai")

                if "summary" not in locked:
                    item.summary = result.summary
                if "description" not in locked:
                    item.description = result.description
                if "install_steps" not in locked:
                    item.install_steps = result.install_steps
                if "category_id" not in locked:
                    item.category_id = next(c.id for c in leafs if c.code == result.category_code)
                    item.ai_confidence = result.confidence
                if "kind" not in locked and result.kind:
                    item.kind, item.kind_confidence = result.kind, result.kind_confidence
                if result.search_tags:
                    item.search_tags = result.search_tags
                item.ai_model = settings.ai_text_model if result.by_ai and not result.error else ""
                if "name" not in locked and fm.get("name"):
                    item.name = fm["name"]
                    tr.name = item.name

                if "cover_path" not in locked and (force or not item.cover_path):
                    tr.stage("cover_readme")
                    urls = find_images(raw, repo.full_name, repo.default_branch, doc_path)
                    gallery, tried = save_gallery(gh, item.id, urls)
                    cover = gallery[0] if gallery else None
                    item.images = gallery
                    item.cover_path, item.cover_source = (cover, "readme") if cover else ("", "placeholder")
                    if not cover and tried:
                        tr.warn(f"文档里的 {tried} 张图片都无法使用（下载失败、太小或格式不支持），改用 AI 绘制", "cover_readme")

            # 没有可用截图时让 AI 画一张示意图（放在 GitHub 会话外，不占 GitHub 额度）
            if "cover_path" not in locked and not item.cover_path:
                tr.stage("cover_ai")
                if not ai_cover(db, item):
                    tr.warn("AI 绘制封面失败，暂用占位图（可在详情页重绘）" if settings.ai_enabled else "未配置 AI 接口，使用占位图", "cover_ai")

            tr.stage("save")
            item.ai_status = "failed" if result.error else ("done" if result.by_ai else "rule")
            item.ai_error = result.error
            db.commit()
            cat = db.get(Category, item.category_id)
            summary = f"入库成功 · 分类：{cat.name} · 封面：{COVER_LABEL.get(item.cover_source, item.cover_source)}"
            if tr.warnings:
                summary += f" · {len(tr.warnings)} 个警告"
            tr.success(summary)
            _after_extract(item.id, task_id)
            return True, summary
        except BudgetExhausted:
            # 额度用完：放回队列，明天的采集窗口继续
            db.rollback()
            item.ai_status = "pending"
            db.commit()
            tr.warn("GitHub 额度用完，留到下次采集继续", tr.current)
            raise
        except _StageError as e:
            db.rollback()
            item.ai_status, item.ai_error = "failed", e.message
            db.commit()
            tr.error(e.message, e.stage)
            _after_extract(item.id, task_id)
            return False, e.message
        except Exception as e:  # 后台任务不能把异常吞掉不留痕
            log.exception("process_item %s failed", item_id)
            db.rollback()
            msg = f"{e.__class__.__name__}: {e}"
            item.ai_status, item.ai_error = "failed", msg
            db.commit()
            tr.error(f"处理异常：{msg}", tr.current or "save")
            return False, msg


def _after_extract(item_id: int, task_id: int | None) -> None:
    """提炼结束后：待审核的条目立即 AI 审核；再更新语义搜索向量。都不影响提炼结果。"""
    from . import review, search
    try:
        review.ai_review(item_id, task_id)
    except Exception:
        log.exception("ai review %s failed", item_id)
    try:
        search.embed_items([item_id])
    except Exception:
        log.exception("embed %s failed", item_id)


def ai_cover(db: Session, item: Item) -> bool:
    cat = db.get(Category, item.category_id)
    group = cat.parent or cat
    fg, bg = GROUP_COLORS.get(group.code, THEME)
    path = generate_cover(item.id, item.name, item.summary, f"{group.name} / {cat.name}", fg, bg)
    if path:
        old = item.cover_path
        item.cover_path, item.cover_source = path, "ai"
        # AI 示意图放在图片集第一张（替换掉旧的封面）
        item.images = [path] + [p for p in (item.images or []) if p not in (path, old)]
        return True
    return False


def cover_for(item_id: int, task_id: int | None = None) -> tuple[bool, str]:
    """补封面任务里的单个条目。"""
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None:
            return False, "条目不存在"
        if item.cover_path:
            return True, "已有封面，跳过"
        tr = ItemTracker(item, "cover", task_id)
        tr.stage("cover_ai")
        if ai_cover(db, item):
            db.commit()
            tr._log("success", "AI 封面已生成", "cover_ai", duration=True)
            return True, "AI 封面已生成"
        tr.error("AI 绘制封面失败（接口异常或返回的 SVG 不合法）", "cover_ai")
        return False, "AI 绘制封面失败"


def redraw_cover_for(item_id: int, task_id: int | None = None) -> tuple[bool, str]:
    """换主题后重画 AI 封面：只处理当前封面是 AI 画的条目；画失败保留旧图。"""
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None:
            return False, "条目不存在"
        if item.cover_source != "ai":
            return True, "封面不是 AI 画的，跳过"
        tr = ItemTracker(item, "cover", task_id)
        tr.stage("cover_ai")
        if ai_cover(db, item):
            db.commit()
            tr._log("success", "AI 封面已按新主题重画", "cover_ai", duration=True)
            return True, "已重画"
        tr.error("AI 重画封面失败，保留旧封面", "cover_ai")
        return False, "重画失败，保留旧封面"


def _cover_is_current(cover_path: str) -> bool:
    """当前主题画的封面带 SMIL 动画；旧主题的没有。用来在重启后接着重画没画完的。"""
    try:
        return "<animate" in (settings.media_dir / cover_path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False


def start_cover_redraw(reason: str = "主题更新", only_stale: bool = False) -> int | None:
    """把 AI 封面按当前提示词重画（系统任务，不扣用户额度）。only_stale 时跳过已经是新主题的。"""
    with SessionLocal() as db:
        rows = db.execute(select(Item.id, Item.name, Item.cover_path)
                          .where(Item.cover_source == "ai", Item.status.in_(("published", "pending_review", "offline")))
                          .order_by(Item.id)).all()
    rows = [(i, n) for i, n, path in rows if not (only_stale and _cover_is_current(path or ""))]
    if not rows:
        return None
    task_id = create_task("cover", f"{reason} · 重画 {len(rows)} 张 AI 封面", rows)
    start_task(task_id, [i for i, _ in rows], lambda i, t: redraw_cover_for(i, t), 4)
    return task_id


def redraw_covers_if_theme_changed() -> int | None:
    """启动时调用：封面主题换了就标记并开始重画；主题没换但上次重画被重启打断，就只接着画还没换的。"""
    with SessionLocal() as db:
        row = db.get(AppMeta, "cover_theme")
        changed = not (row and row.value == COVER_THEME)
        if changed:
            if row is None:
                row = AppMeta(key="cover_theme")
                db.add(row)
            row.value = COVER_THEME
            db.commit()
    if changed:
        return start_cover_redraw("封面换成新主题", only_stale=True)
    return start_cover_redraw("接着重画封面", only_stale=True)


def gallery_for(item_id: int, task_id: int | None = None) -> tuple[bool, str]:
    """批量补图片集里的单个条目：从 GitHub 文档里抓最多 GALLERY_MAX 张截图并入图片集（人工改过图片的跳过）。"""
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None or item.repo is None:
            return False, "条目不存在或不是 GitHub 条目"
        if "cover_path" in (item.locked_fields or []):
            return True, "图片集人工改过，跳过"
        current = list(item.images or ([item.cover_path] if item.cover_path else []))
        if len(current) >= GALLERY_MAX:
            return True, "图片已经够多，跳过"
        repo, sub = item.repo, item.sub_path or ""
        try:
            with GitHub() as gh:
                _, _, _, raw, doc_path = fetch_doc(gh, repo, sub)  # Skill 读 SKILL.md，仓库读 README
                urls = find_images(raw, repo.full_name, repo.default_branch, doc_path)
                got, tried = save_gallery(gh, item.id, urls)
        except BudgetExhausted:
            return False, "GitHub 额度用完，稍后再试"
        except NotFound as e:
            return False, (f"读取文档失败：{e}" + gone_check(item_id, "gallery"))[:200]
        except GitHubError as e:
            return False, f"读取文档失败：{e}"[:200]
        added = [p for p in got if p not in current]
        if not added:
            return True, f"文档里没有新的可用图片（检查了 {tried} 张）" if tried else "文档里没有图片"
        if item.cover_source in ("ai", "placeholder"):
            images = added + current  # 真实截图排在 AI 示意图前面
            item.cover_source = "readme"
        else:
            images = current + added
        item.images = images[:GALLERY_MAX + 1]
        item.cover_path = item.images[0]
        db.commit()
        return True, f"新增 {len(added)} 张，共 {len(item.images)} 张"


def start_process_task(kind: str, title: str, item_ids: list[int], workers: int = 1, force: bool = False,
                       user_id: int | None = None) -> int | None:
    """把一批条目作为一个任务在后台提炼，返回任务 id。"""
    if not item_ids:
        return None
    with SessionLocal() as db:
        names = dict(db.execute(select(Item.id, Item.name).where(Item.id.in_(item_ids))).all())
    from . import billing

    task_id = create_task(kind, title, [(i, names.get(i, str(i))) for i in item_ids], user_id=user_id)
    # 用户发起的提炼计入这个账号的 AI 额度（管理员和系统任务不传 user_id）
    fn = billing.wrap(user_id, lambda i, t: process_item(i, force=force, task_id=t, trigger=kind))
    start_task(task_id, item_ids, fn, workers)
    return task_id


def gone_check(item_id: int, trigger: str) -> str:
    """读文档 404 时复查原地址：真的失效就立即下线（盖「原文已下线」、变灰不可点），返回附加说明。"""
    from . import liveness

    try:
        st = liveness.recheck([item_id], trigger)
    except Exception as e:  # 复查失败不影响原任务，留给每日巡检
        log.warning("recheck %s failed: %s", item_id, e)
        return ""
    return "；复查确认原地址已失效，已下线" if st["offline"] else ""


def fetch_doc(gh: GitHub, repo: Repo, sub_path: str) -> tuple[str, dict, str, str, str]:
    """读取条目的说明文档：Skill 读 SKILL.md，仓库读 README。返回 (kind, frontmatter, 正文, 原文, 文件路径)。"""
    if sub_path or _is_skill(gh, repo, sub_path):
        raw, path = _skill_md(gh, repo, sub_path)
        return "skill", parse_frontmatter(raw), strip_frontmatter(raw), raw, path
    raw, sha, path = gh.readme(repo.full_name)
    repo.readme_sha = sha
    return "repo", {}, raw, raw, path


def _skill_md(gh: GitHub, repo: Repo, sub_path: str) -> tuple[str, str]:
    """读取 SKILL.md；文件名大小写不统一（skill.md / Skill.md），GitHub 路径区分大小写，逐个试。"""
    err = None
    for fname in ("SKILL.md", "skill.md", "Skill.md"):
        path = f"{sub_path}/{fname}" if sub_path else fname
        try:
            return gh.file_text(repo.full_name, repo.default_branch, path), path
        except BudgetExhausted:
            raise
        except GitHubError as e:
            err = e
    raise err


def _is_skill(gh: GitHub, repo: Repo, sub_path: str) -> bool:
    try:
        gh.file_text(repo.full_name, repo.default_branch, "SKILL.md")
        return True
    except GitHubError:
        return False


# ---------------------------------------------------------------- 查重与按勾选导入（截图 / 长文 / 搜索共用）

def existing_item_for(db: Session, full_name: str, sub_path: str | None) -> int | None:
    """同仓库同目录已收录，或整仓库已作为一个条目收录，都算重复。"""
    repo = db.scalar(select(Repo).where(Repo.full_name.ilike(full_name)))
    if repo is None:
        return None
    items = db.execute(select(Item.id, Item.sub_path).where(
        Item.repo_id == repo.id, Item.status.in_(("published", "hidden", "pending_review", "awaiting", "offline")))).all()
    for iid, sub in items:
        if sub == (sub_path or "") or sub == "":
            return iid
    return None


def import_picks(db: Session, picks: list[dict], trigger: str, user_id: int | None = None,
                 review: bool = False) -> tuple[list[int], list[str], list[str]]:
    """picks: [{full_name, name, sub_path(None=按名称自动判断)}]。返回 (新建条目 id, 跳过的名称, 错误)。"""
    from .vision import norm

    created, skipped, errors = [], [], []
    for p in picks:
        full_name, name, sub_path = p["full_name"], p.get("name") or "", p.get("sub_path")
        if existing_item_for(db, full_name, sub_path) is not None:
            skipped.append(name or full_name)
            continue
        if sub_path is not None:
            # 已定位到具体 Skill 目录（来自 skills.sh），直接导入这一个
            chosen = [{"sub_path": sub_path, "kind": "skill" if sub_path else "repo",
                       "name": sub_path.rsplit("/", 1)[-1] if sub_path else (name or full_name.split("/")[1])}]
        else:
            try:
                pv = preview(db, full_name)
            except GitHubError as e:
                errors.append(f"{full_name}：{e}")
                continue
            cands = pv["candidates"]
            key = norm(name)
            hit = [c for c in cands if key and (norm(c["name"]) == key or norm(c["sub_path"].rsplit("/", 1)[-1]) == key)]
            if hit:
                chosen = hit[:1]
            elif pv["mode"] == "skills" and len(cands) > 1:
                chosen = [{"sub_path": "", "kind": "repo", "name": pv["repo"]["full_name"].split("/")[1]}]
            else:
                chosen = cands
            chosen = [c for c in chosen if not c.get("existing_item_id")]
        try:
            ids = import_items(db, full_name, chosen, source="manual", user_id=user_id, review=review)
        except GitHubError as e:
            errors.append(f"{full_name}：{e}")
            continue
        if p.get("kind"):
            for i in ids:
                db.get(Item, i).kind = p["kind"]
            db.commit()
        created += ids
    from .tracking import log
    for m in errors:
        log(trigger=trigger, stage="repo", level="error", message=f"导入失败：{m}", user_id=user_id)
    for n in skipped:
        log(trigger=trigger, stage="repo", level="info", message="已在库中，跳过", item_name=n, user_id=user_id)
    return created, skipped, errors
