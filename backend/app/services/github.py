import base64
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from posixpath import dirname, join, normpath
from urllib.parse import urlparse

import httpx

from ..config import settings

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


class GitHubError(Exception):
    pass


class NotFound(GitHubError):
    """404：仓库或文件不存在（或为私有仓库）。调用方可据此触发失效检查。"""


class BudgetExhausted(GitHubError):
    """额度用完且等不到重置（超出采集窗口），本轮采集停在这里，第二天继续。"""


# 最近一次看到的额度，供任务日志展示：{"core": {...}, "search": {...}, "graphql": {...}}
rate_state: dict[str, dict] = {}

# 采集线程里设置截止时间：额度用完就睡到重置；交互式请求（导入）没有截止时间，直接报错
_gate = threading.local()


@contextmanager
def crawl_budget(deadline: datetime):
    _gate.deadline = deadline
    try:
        yield
    finally:
        _gate.deadline = None


def _record_rate(r: httpx.Response) -> None:
    res = r.headers.get("x-ratelimit-resource")
    if res and r.headers.get("x-ratelimit-remaining") is not None:
        rate_state[res] = {
            "limit": int(r.headers.get("x-ratelimit-limit", 0)),
            "remaining": int(r.headers["x-ratelimit-remaining"]),
            "reset": int(r.headers.get("x-ratelimit-reset", 0)),
        }


def _wait_for_reset(r: httpx.Response) -> None:
    deadline = getattr(_gate, "deadline", None)
    if deadline is None:
        raise GitHubError("GitHub API 已达速率上限，请在 .env 配置 GITHUB_TOKEN 或稍后再试")
    if r.headers.get("retry-after"):  # 二级限流
        wake = time.time() + int(r.headers["retry-after"]) + 1
    else:
        wake = int(r.headers.get("x-ratelimit-reset", time.time() + 60)) + 3
    if wake > deadline.timestamp():
        raise BudgetExhausted(f"GitHub 额度用完，重置时间超出采集窗口（{deadline:%H:%M}），剩余工作明天继续")
    time.sleep(max(1.0, wake - time.time()))


@dataclass
class RepoRef:
    owner: str
    repo: str
    sub_path: str | None = None  # URL 指向子目录时有值

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_repo_url(text: str) -> RepoRef:
    """支持 owner/repo、https://github.com/owner/repo(.git)、/tree/<branch>/<path>、/blob/<branch>/<path>/SKILL.md"""
    text = text.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", text):
        owner, repo = text.split("/")
        return RepoRef(owner, repo.removesuffix(".git"))

    if not text.startswith("http"):
        text = "https://" + text
    u = urlparse(text)
    if u.netloc.lower() not in ("github.com", "www.github.com"):
        raise GitHubError("只支持 github.com 的仓库地址")
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2:
        raise GitHubError("地址里缺少 owner/repo")
    ref = RepoRef(parts[0], parts[1].removesuffix(".git"))
    if len(parts) > 4 and parts[2] in ("tree", "blob"):
        path = "/".join(parts[4:])
        if parts[2] == "blob":
            path = dirname(path)
        ref.sub_path = path.strip("/")
    return ref


def _client() -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return httpx.Client(headers=headers, timeout=20, follow_redirects=True)


def _is_rate_limited(r: httpx.Response) -> bool:
    if r.status_code not in (403, 429):
        return False
    return r.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in r.text.lower()


def _request(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response:
    net_fails = 0
    for _ in range(8):
        try:
            r = client.request(method, url, **kw)
        except httpx.TransportError as e:
            # 国内访问 GitHub 偶发连接失败 / 超时：退避重试 3 次
            net_fails += 1
            if net_fails > 3:
                raise GitHubError(f"连接 GitHub 失败：{e.__class__.__name__}，请检查网络或代理") from e
            time.sleep((2, 5, 10)[net_fails - 1])
            continue
        except httpx.HTTPError as e:
            raise GitHubError(f"连接 GitHub 失败：{e.__class__.__name__}") from e
        _record_rate(r)
        if _is_rate_limited(r):
            _wait_for_reset(r)
            continue
        if r.status_code == 404:
            raise NotFound("仓库或文件不存在（或为私有仓库）")
        if r.status_code >= 400:
            raise GitHubError(f"GitHub 返回 {r.status_code}：{r.text[:200]}")
        return r
    raise GitHubError("GitHub 持续限流，已放弃")


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    return _request(client, "GET", url, **kw)


# 搜索接口单独限流（带 Token 每分钟 30 次），全站所有搜索共用一个滑动窗口，超出就排队等
_search_lock = threading.Lock()
_search_times: deque[float] = deque()


def search_slot(max_wait: float = 70.0) -> None:
    deadline = time.monotonic() + max_wait
    while True:
        with _search_lock:
            now = time.monotonic()
            while _search_times and now - _search_times[0] > 60:
                _search_times.popleft()
            if len(_search_times) < settings.search_per_minute:
                _search_times.append(now)
                return
            wait = 60 - (now - _search_times[0]) + 0.2
        if time.monotonic() + wait > deadline:
            raise GitHubError("GitHub 搜索太频繁，请稍等一分钟再试")
        time.sleep(wait)


class GitHub:
    def __init__(self):
        self.client = _client()

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def repo(self, ref: RepoRef) -> dict:
        return _get(self.client, f"{API}/repos/{ref.full_name}").json()

    def latest_release(self, full_name: str) -> dict | None:
        """v3.3 最新 Release；没有 Release 时返回 None。"""
        try:
            return _get(self.client, f"{API}/repos/{full_name}/releases/latest").json()
        except NotFound:
            return None

    def repo_by_id(self, github_id: int) -> dict:
        """按数字 id 取仓库，改名 / 转移后依然有效。"""
        return _get(self.client, f"{API}/repositories/{github_id}").json()

    def owner_repos(self, owner: str) -> list[dict]:
        """某个用户 / 组织的公开仓库（最近更新的 100 个）。"""
        return _get(self.client, f"{API}/users/{owner}/repos", params={"per_page": 100, "sort": "updated"}).json()

    def search_repos(self, q: str, per_page: int = 30, sort: str | None = "stars") -> list[dict]:
        """sort=None 时按 GitHub 的相关度（best match）排序。"""
        search_slot()
        params = {"q": q, "per_page": per_page}
        if sort:
            params.update(sort=sort, order="desc")
        data = _get(self.client, f"{API}/search/repositories", params=params).json()
        return data.get("items", [])

    def graphql(self, query: str) -> dict:
        if not settings.github_token:
            raise GitHubError("GraphQL 需要 GITHUB_TOKEN")
        data = _request(self.client, "POST", f"{API}/graphql", json={"query": query}).json()
        if data.get("errors") and not data.get("data"):
            raise GitHubError(f"GraphQL 错误：{data['errors'][0].get('message', '')[:200]}")
        return data.get("data") or {}

    def star_counts(self, full_names: list[str]) -> dict[str, int | None]:
        """GraphQL 一次查一批仓库的星标数；查不到（改名 / 删除）的返回 None。"""
        out: dict[str, int | None] = {}
        for start in range(0, len(full_names), 50):
            batch = full_names[start:start + 50]
            parts = []
            for i, fn in enumerate(batch):
                owner, name = fn.split("/", 1)
                parts.append(f'r{i}: repository(owner: "{_gq(owner)}", name: "{_gq(name)}") {{ stargazerCount }}')
            data = self.graphql("query {\n" + "\n".join(parts) + "\n}")
            for i, fn in enumerate(batch):
                node = data.get(f"r{i}")
                out[fn] = node["stargazerCount"] if node else None
        return out

    def trending(self, since: str = "daily") -> list[tuple[str, int | None]]:
        """解析 GitHub Trending 页面（官方无 API）：[(owner/repo, 窗口期新增星标)]，按页面排名顺序。"""
        try:
            r = self.client.get("https://github.com/trending", params={"since": since},
                                headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 SkillBase"})
        except httpx.HTTPError as e:
            raise GitHubError(f"读取 Trending 失败：{e.__class__.__name__}") from e
        if r.status_code != 200:
            raise GitHubError(f"读取 Trending 失败：{r.status_code}")
        out = []
        for chunk in r.text.split('<article class="Box-row"')[1:]:
            m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"/]+/[^"/]+)"', chunk)
            if not m:
                continue
            d = re.search(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)", chunk)
            out.append((m.group(1), int(d.group(1).replace(",", "")) if d else None))
        return out

    def tree_paths(self, full_name: str, branch: str) -> list[str]:
        data = _get(self.client, f"{API}/repos/{full_name}/git/trees/{branch}", params={"recursive": "1"}).json()
        return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]

    def readme(self, full_name: str, sub_path: str = "") -> tuple[str, str, str]:
        """返回 (内容, sha, 文件路径)。sub_path 非空时取该目录下的 README。"""
        url = f"{API}/repos/{full_name}/readme" + (f"/{sub_path}" if sub_path else "")
        data = _get(self.client, url).json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return content, data.get("sha", ""), data.get("path", "README.md")

    def file_text(self, full_name: str, branch: str, path: str) -> str:
        r = _get(self.client, f"{RAW}/{full_name}/{branch}/{path}")
        return r.text

    def download(self, url: str, max_bytes: int = 8 * 1024 * 1024) -> tuple[bytes, str] | None:
        try:
            with self.client.stream("GET", url, headers={"Accept": "image/*"}) as r:
                if r.status_code != 200:
                    return None
                ctype = r.headers.get("content-type", "").split(";")[0]
                if not ctype.startswith("image/") or "svg" in ctype:
                    return None
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        return None
                return bytes(buf), ctype
        except Exception:  # 坏链接（InvalidURL 等）只跳过这张图，不影响条目
            return None


def _gq(v: str) -> str:
    return v.replace("\\", "").replace('"', "")


def find_skill_dirs(paths: list[str]) -> list[str]:
    """仓库里所有 SKILL.md 所在目录（根目录为 ''）。"""
    dirs = {dirname(p) for p in paths if p.rsplit("/", 1)[-1].lower() == "skill.md"}
    return sorted(dirs)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            value = kv.group(2).strip()
            # YAML 块标量（| / > 及其变体）的内容在后续缩进行里
            out[key] = "" if re.fullmatch(r"[|>][+-]?", value) else value.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return {k: v for k, v in out.items() if v}


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^﻿?---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)


_BADGE_HINTS = ("shields.io", "badge", "badgen", "travis-ci", "codecov", "star-history", "starchart",
                "contrib.rocks", "/workflows/", "sponsor", "buymeacoffee", "ko-fi", "visitor", "hits.")


def find_images(markdown: str, full_name: str, branch: str, doc_path: str) -> list[str]:
    """按出现顺序取文档里的图片地址，过滤徽章/图标，相对路径转为 raw 地址。"""
    found = re.findall(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)", markdown)
    found += re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", markdown, re.I)
    # 保持文档中的先后顺序
    found.sort(key=lambda u: markdown.find(u))

    base_dir = dirname(doc_path)
    out = []
    for url in found:
        url = url.strip()
        if not url or any(ch.isspace() for ch in url):
            continue
        low = url.lower()
        if any(h in low for h in _BADGE_HINTS) or low.split("?")[0].endswith(".svg") or low.startswith("data:"):
            continue
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith("http"):
            path = url.lstrip("./") if url.startswith("/") else normpath(join(base_dir, url))
            url = f"{RAW}/{full_name}/{branch}/{path.lstrip('/')}"
        else:
            m = re.match(r"https://github\.com/([^/]+/[^/]+)/blob/(.+)", url)
            if m:
                url = f"{RAW}/{m.group(1)}/{m.group(2)}"
        if url not in out:
            out.append(url)
    return out
