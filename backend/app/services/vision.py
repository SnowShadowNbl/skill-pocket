"""AI-4：识别截图里的 Skill / 模型 / 仓库，并对应到真实的 GitHub 仓库。"""

import base64
import difflib
import io
import json
import re
import threading
import time

from PIL import Image

from ..config import settings
from .extract import _chat_json
import httpx

from .github import GitHub, GitHubError, RepoRef, find_skill_dirs

MAX_SIDE = 1600  # 长边超过就等比缩小，省 token 也更快

VISION_PROMPT = """你会看到一张截图，可能来自文章、榜单、推文、GitHub 页面或聊天记录。
找出其中提到的所有 Agent Skill、AI 模型、MCP Server、AI 工具或 GitHub 仓库，只输出 JSON：
{
  "page": "一句话描述这张截图是什么（中文）",
  "items": [
    {
      "name": "条目名称（照截图原文）",
      "repo": "owner/repo。截图里能看到就照抄；截图没写但你有把握知道的也可以填（系统会去 GitHub 核实）；不确定填 null",
      "description": "截图里对它的描述，翻译成中文，没有就 null",
      "stars": 截图里显示的星标数（整数，没有就 null），
      "rank": 截图里显示的排名（整数，没有就 null），
      "kind": "skill / model / tool / agent / other"
    }
  ]
}
要求：只列截图里真实出现的条目，不要补充截图以外的内容；同一条目只列一次；最多 30 个。"""


def prepare_image(raw: bytes) -> tuple[bytes, str]:
    """统一转成 JPEG / PNG 并限制尺寸。返回 (字节, mime)。"""
    img = Image.open(io.BytesIO(raw))
    img.load()
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.convert("RGBA").save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png"
    img.convert("RGB").save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def recognize(image: bytes, mime: str) -> dict:
    if not settings.ai_enabled:
        raise RuntimeError("截图识别需要先配置 AI 接口")
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
    content = [
        {"type": "text", "text": "请识别这张截图。"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    data = _chat_json(VISION_PROMPT, content, "AI-4")
    items = []
    seen = set()
    for it in data.get("items") or []:
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            continue
        name = str(it["name"]).strip()[:200]
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        repo = it.get("repo")
        repo = repo.strip().strip("/") if isinstance(repo, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", repo.strip().strip("/")) else None
        items.append({
            "name": name,
            "repo": repo,
            "description": (str(it["description"]).strip()[:300] if it.get("description") else ""),
            "stars": it.get("stars") if isinstance(it.get("stars"), int) else None,
            "rank": it.get("rank") if isinstance(it.get("rank"), int) else None,
            "kind": it.get("kind") if it.get("kind") in ("skill", "model", "tool", "agent", "other") else "other",
        })
    return {"page": str(data.get("page") or "")[:200], "items": items[:30]}


def _repo_brief(d: dict) -> dict:
    return {"full_name": d["full_name"], "html_url": d["html_url"], "description": d.get("description") or "",
            "stars": d.get("stargazers_count", 0), "language": d.get("language") or ""}


def norm(name: str) -> str:
    """名称归一化：忽略大小写、空格、下划线、连字符，用于判断“同名”。"""
    return re.sub(r"[\s_\-./]+", "", name.lower())


_sh_lock = threading.Lock()
_SH_CACHE_FILE = settings.media_dir.parent / "skills_sh_cache.json"
_SH_TTL = 7 * 24 * 3600


def _load_sh_cache() -> dict[str, dict]:
    try:
        data = json.loads(_SH_CACHE_FILE.read_text(encoding="utf-8"))
        now = time.time()
        return {k: v for k, v in data.items() if now - v.get("t", 0) < _SH_TTL}
    except Exception:
        return {}


# 文件缓存（7 天）：同名 Skill 反复出现时不再请求 skills.sh，避免触发它的限流
_sh_cache: dict[str, dict] = _load_sh_cache()


def _save_sh_cache() -> None:
    try:
        _SH_CACHE_FILE.write_text(json.dumps(_sh_cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _skills_sh_query(q: str) -> list[dict] | None:
    """请求 skills.sh 搜索接口；它对并发请求会限流（返回非 JSON 页面），所以串行 + 失败退避重试。失败返回 None。"""
    with _sh_lock:
        for attempt in range(4):
            try:
                r = httpx.get("https://skills.sh/api/search", params={"q": q}, timeout=15,
                              headers={"User-Agent": "Mozilla/5.0 SkillPocket"})
                return r.json().get("skills") or []
            except Exception:
                time.sleep(2.0 * (attempt + 1))
            finally:
                time.sleep(0.6)
    return None


def skills_sh_search(q: str, limit: int = 8) -> list[dict]:
    """按关键词搜 skills.sh，返回安装量最高的若干个：[{source, skill_id, installs}]。结果缓存 7 天。"""
    key = "q:" + norm(q)
    if len(q.strip()) < 2:
        return []
    if key in _sh_cache:
        return _sh_cache[key]["hit"] or []
    skills = _skills_sh_query(q.strip())
    if skills is None:
        return []
    hits = sorted(skills, key=lambda x: x.get("installs") or 0, reverse=True)[:limit]
    out = [{"source": x["source"], "skill_id": x.get("skillId") or x.get("name"), "installs": x.get("installs")}
           for x in hits if x.get("source")]
    with _sh_lock:
        _sh_cache[key] = {"hit": out, "t": time.time()}
        _save_sh_cache()
    return out


def skills_sh_lookup(name: str) -> dict | None:
    """在 skills.sh 按名称查 Skill，返回同名里安装量最高的一个：{source, skill_id, installs}。
    skills.sh 对并发请求会限流（返回非 JSON 页面），所以串行 + 失败退避重试 + 缓存。"""
    q = name.strip()
    key = norm(q)
    if len(q) < 2:
        return None
    if key in _sh_cache:
        return _sh_cache[key]["hit"]
    skills = _skills_sh_query(q)
    if skills is None:
        return None  # 查询失败不缓存，下次还能再试
    same = [x for x in skills if norm(x.get("skillId") or "") == key or norm(x.get("name") or "") == key]
    best = max(same, key=lambda x: x.get("installs") or 0) if same else None
    hit = {"source": best["source"], "skill_id": best.get("skillId") or best.get("name"), "installs": best.get("installs")} if best else None
    with _sh_lock:
        _sh_cache[key] = {"hit": hit, "t": time.time()}
        _save_sh_cache()
    return hit


class Resolver:
    """把一条识别结果对应到 GitHub 仓库（以及仓库内的 Skill 目录）。同一次上传里复用仓库目录树。"""

    def __init__(self, gh: GitHub):
        self.gh = gh
        self._trees: dict[str, list[str]] = {}

    def skill_dir(self, full_name: str, branch: str, skill_id: str) -> str | None:
        if full_name not in self._trees:
            try:
                self._trees[full_name] = find_skill_dirs(self.gh.tree_paths(full_name, branch))
            except GitHubError:
                self._trees[full_name] = []
        dirs = self._trees[full_name]
        key = norm(skill_id)
        hit = [d for d in dirs if norm(d.rsplit("/", 1)[-1]) == key]
        return min(hit, key=len) if hit else (("" if "" in dirs else None) if len(dirs) <= 1 else None)

    def resolve(self, item: dict) -> dict:
        """返回 {match, sub_path, via, installs, suggestions}；via: skills.sh / github / fuzzy / search"""
        out = {"match": None, "sub_path": None, "via": None, "installs": None, "suggestions": [], "uncertain": False}

        # 1) Skill：先查 skills.sh 拿到真正的来源仓库，再定位到仓库里的 Skill 目录
        if item.get("kind") == "skill" or not item.get("repo"):
            hit = skills_sh_lookup(item["name"])
            if hit:
                owner, name = hit["source"].split("/", 1)
                try:
                    data = self.gh.repo(RepoRef(owner, name))
                    out.update(match=_repo_brief(data), via="skills.sh", installs=hit["installs"],
                               sub_path=self.skill_dir(data["full_name"], data.get("default_branch") or "main", hit["skill_id"]))
                    return out
                except GitHubError:
                    pass

        # 2) 截图里写了（或模型给出的）owner/repo：核实；名字差一两个字母时在该 owner 下纠正
        if item.get("repo"):
            owner, name = item["repo"].split("/", 1)
            try:
                out.update(match=_repo_brief(self.gh.repo(RepoRef(owner, name))), via="github")
                return out
            except GitHubError:
                pass
            try:
                repos = self.gh.owner_repos(owner)
            except GitHubError:
                repos = []
            names = {d["name"].lower(): d for d in repos}
            close = difflib.get_close_matches(name.lower(), list(names), n=1, cutoff=0.8)
            if close:
                out.update(match=_repo_brief(names[close[0]]), via="fuzzy")
                return out

        # 3) 按名称搜仓库：同名的当作匹配，其余作为候选
        try:
            found = self.gh.search_repos(f"{item['name']} in:name", per_page=5)
        except GitHubError:
            found = []
        out["suggestions"] = [_repo_brief(d) for d in found]
        exact = [d for d in found if norm(d["name"]) == norm(item["name"])]
        if exact:
            # Skill 只靠仓库名搜到的，常是别人的副本：标记为推测，让用户核对
            out.update(match=_repo_brief(exact[0]), via="search", uncertain=item.get("kind") == "skill")
        if out["suggestions"] and (not exact or len(exact) > 1 or item.get("kind") == "skill"):
            # 候选不唯一 / 拿不准：让 AI 结合上下文挑一个
            from .judge import JudgeUnavailable, pick_repo
            try:
                fn, conf, reason = pick_repo(item["name"], item.get("context") or item.get("description") or "", out["suggestions"])
            except JudgeUnavailable:
                return out
            if fn:
                out.update(match=next(s for s in out["suggestions"] if s["full_name"] == fn), via="ai",
                           uncertain=conf < 0.8, pick_reason=reason)
        return out


def resolve(gh: GitHub, item: dict) -> dict:
    return Resolver(gh).resolve(item)
