"""v3.3.55 后台批次 4b：管理员角色与权限。

角色：admin 超级管理员 / subadmin 管理员（老角色，保留原来的全部管理权限，只是不能管理管理员）/
moderator 内容审核 / support 客服 / viewer 只读。
权限按后台模块（与 frontend/src/admin/modules.js 的 key 一致）：'w' 读写、'r' 只读、缺省表示不可见。
接口层由 auth.require_admin 按「请求路径 → 模块」检查：GET 需要 r，其余需要 w。
"""

import re

MODULES = ("overview", "visitors", "reviews", "feedback", "comments", "search-terms", "activity", "content", "shares", "pins",
           "takedowns", "blocklist", "crawl-review", "ingest-tasks", "jobs", "logs", "liveness", "users", "accounts", "quota",
           "resources", "categories", "reason-templates", "staff", "maintenance", "operations")

ROLE_LABELS = {"admin": "超级管理员", "subadmin": "管理员", "moderator": "内容审核", "support": "客服", "viewer": "只读"}
ASSIGNABLE = ("subadmin", "moderator", "support", "viewer")  # 超级管理员只有 admin 一个，不能任命

_ALL = {m: "w" for m in MODULES}
MATRIX: dict[str, dict[str, str]] = {
    "admin": dict(_ALL),
    "subadmin": {**_ALL, "staff": "r", "reason-templates": "r"},
    "moderator": {"overview": "r", "reviews": "w", "comments": "w", "content": "w", "crawl-review": "w", "pins": "w", "shares": "w",
                  "search-terms": "w", "takedowns": "w", "blocklist": "w", "ingest-tasks": "w", "categories": "w", "feedback": "r",
                  "users": "r", "reason-templates": "r"},
    "support": {"overview": "r", "feedback": "w", "users": "r", "comments": "r", "content": "r", "reason-templates": "r"},
    "viewer": {m: "r" for m in MODULES if m not in ("staff", "reason-templates")},
}
CAPABILITIES = {
    "admin": ["export_email", "export", "send_message", "view_as_user", "manage_staff"],
    "subadmin": ["export", "send_message", "view_as_user"],
    "moderator": [],
    "support": ["send_message", "view_as_user"],
    "viewer": [],
}

ALWAYS = "*"  # 所有管理员都能访问（概览角标、全局搜索、个人视图、话术模板读取等）

# (正则, 模块)：按顺序匹配，先写更具体的
ROUTES: list[tuple[re.Pattern, str]] = [(re.compile(p), m) for p, m in [
    (r"^/api/admin/(summary|feed|feed/seen|search|views(/\d+)?|me/.*|verify/.*)$", ALWAYS),
    (r"^/api/admin/(reason-templates|reply-templates)(/\d+)?$", "reason-templates"),
    (r"^/api/admin/accounts/", "accounts"),
    (r"^/api/admin/client-versions", "accounts"),
    (r"^/api/admin/cover-queue", "content"),
    (r"^/api/admin/activity", "activity"),
    (r"^/api/admin/analytics/", "visitors"),
    (r"^/api/admin/insights/", "visitors"),
    (r"^/api/admin/ip-bans", "users"),
    (r"^/api/admin/blocklist", "blocklist"),
    (r"^/api/admin/(categories|category-audit)", "categories"),
    (r"^/api/categories", "categories"),
    (r"^/api/admin/comments", "comments"),
    (r"^/api/admin/(feedback|reply-templates)", "feedback"),
    (r"^/api/admin/ingest-tasks", "ingest-tasks"),
    (r"^/api/admin/items/\d+/review$", "reviews"),
    (r"^/api/admin/items/\d+/pin$", "pins"),
    (r"^/api/admin/pins", "pins"),
    (r"^/api/admin/(items|gallery-coverage|search/backfill)", "content"),
    (r"^/api/items", "content"),
    (r"^/api/admin/liveness", "liveness"),
    (r"^/api/admin/(quota|ai/)", "quota"),
    (r"^/api/admin/resources", "resources"),
    (r"^/api/admin/(health|alerts|backup|miniapp-config|storage|emails|notifications|push-runs|api-health|client-errors|releases|risk|code-limits|schedules)", "resources"),
    (r"^/api/admin/(maintenance|consistency)", "maintenance"),
    (r"^/api/admin/(announcements|home-config|subscriptions)", "operations"),
    (r"^/api/admin/tags", "users"),
    (r"^/api/admin/reviews", "reviews"),
    (r"^/api/admin/(search-blocklist|search-terms)", "search-terms"),
    (r"^/api/admin/shares", "shares"),
    (r"^/api/admin/staff-roles$", ALWAYS),
    (r"^/api/admin/staff", "staff"),
    (r"^/api/admin/takedowns", "takedowns"),
    (r"^/api/admin/users/\d+/(messages|view-sessions|view/[a-z]+)$", ALWAYS),  # 能力（send_message / view_as_user）在接口里检查
    (r"^/api/admin/messages/stats$", "overview"),
    (r"^/api/admin/users/\d+/quota", "quota"),
    (r"^/api/admin/users", "users"),
    (r"^/api/review", "crawl-review"),
    (r"^/api/(jobs|reclassify|rankings/blurbs)", "jobs"),
    (r"^/api/logs", "logs"),
]]


def module_for(path: str) -> str | None:
    for rx, m in ROUTES:
        if rx.search(path):
            return m
    return None


def permissions(role: str) -> dict[str, str]:
    return dict(MATRIX.get(role, {}))


def capabilities(role: str) -> list[str]:
    return list(CAPABILITIES.get(role, []))


def check(role: str, path: str, method: str) -> tuple[bool, str, str]:
    """返回 (是否允许, 模块, 需要的级别)。没有映射的后台接口：读允许所有管理员，写只允许超级管理员和老「管理员」。"""
    need = "r" if method in ("GET", "HEAD", "OPTIONS") else "w"
    m = module_for(path)
    if m == ALWAYS:
        return True, m, need
    if m is None:
        return (need == "r" or role in ("admin", "subadmin")), "", need
    have = MATRIX.get(role, {}).get(m)
    if path.startswith("/api/admin/users/export"):
        return "export" in CAPABILITIES.get(role, []), m, "w"
    return (have == "w" or (have == "r" and need == "r")), m, need


MODULE_LABELS = {"overview": "概览", "visitors": "访客与行为", "reviews": "审核", "feedback": "用户反馈", "comments": "评论审核",
                 "search-terms": "搜索词", "activity": "操作日志", "content": "内容管理", "shares": "分享页", "pins": "推荐位",
                 "takedowns": "下架申请", "blocklist": "黑名单", "crawl-review": "采集待确认", "ingest-tasks": "收录任务",
                 "jobs": "采集任务", "logs": "入库日志", "liveness": "失效巡检", "users": "用户管理", "accounts": "账号关系",
                 "quota": "AI 额度", "resources": "资源监控", "categories": "分类字典", "reason-templates": "话术模板",
                 "staff": "管理员", "maintenance": "维护工具", "operations": "运营工具"}
