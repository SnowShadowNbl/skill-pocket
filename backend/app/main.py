import html
import logging
import re
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from .changelog import seed_changelog
from .config import settings
from .db import SessionLocal, upgrade_db
from .models import Item, User
from .routers import account, accounts_admin, ai_admin, admin, admin_batch1, analytics, asr, auth, categories, category_admin, changelog, comms_admin, content_admin, favorites, feedback, feedback_admin, finder, ingest_monitor, insights, items, maintenance, operations, media_admin, observability, ops_admin, compare, jobs, manage, moderation, notifications, risk_admin, search_assist, staff, takedown, tasks, track, uploads, user_care, voice, wechat
from .seed import seed_categories
from .services import activity, anim, cache, crawler, geo, ingest, ipban, reclassify, scheduler, search, thumbs, visits
from .services import rankings as rankings_svc

logging.basicConfig(level=logging.INFO)


def ensure_admin(db) -> None:
    """唯一的超级管理员 admin（新库没有经过迁移时在这里建；密码沿用 ADMIN_PASSWORD_HASH）。"""
    admin = db.scalar(select(User).where(User.username == "admin"))
    if admin is None:
        db.add(User(username="admin", nickname="管理员", role="admin", status="active",
                    password_hash=settings.admin_password_hash or ""))
        db.commit()
    elif not admin.password_hash and settings.admin_password_hash:
        admin.password_hash = settings.admin_password_hash
        db.commit()


def _media_backfill() -> None:
    try:
        anim.backfill()  # v3.3.14 缩略图和动图都排进同一个后台队列
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("media backfill failed", exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    upgrade_db()
    with SessionLocal() as db:
        switched = seed_categories(db)
        seed_changelog(db)
        has_items = bool(db.scalar(select(func.count()).select_from(Item)))
        ensure_admin(db)
        # 周榜改为每天更新的「近 7 天」：已有日榜的日期补算周榜（补过的跳过）
        rankings_svc.backfill_weekly(db)
    crawler.mark_interrupted()
    cache.purge_expired()
    activity.purge_old()
    visits.purge_old()
    geo.ensure_data()
    # v3.3.12 已有封面补生成小程序用的缩略图（后台线程，已有的跳过）
    # v3.3.13 再给 SVG 封面预生成详情页动图（同一个后台线程，跑在缩略图之后）
    threading.Thread(target=_media_backfill, name="media-backfill", daemon=True).start()
    if search.enabled():
        # 语义搜索：给还没有搜索标签 / 向量的条目补齐（后台任务，已有的跳过）
        search.start_backfill()
    if switched and has_items and settings.ai_enabled:
        # 领域分类换了版本：后台让 AI 给存量条目重新分类（不重写介绍）
        reclassify.start()
    if settings.ai_enabled and settings.cover_redraw_on_start:
        # 封面主题换了（提示词里的配色 / 动效）：后台把旧的 AI 封面全部重画一次，只跑一次
        ingest.redraw_covers_if_theme_changed()
    scheduler.start()
    yield
    scheduler.stop()
    from .services import apistats

    apistats.flush()  # v3.3.66 退出前把内存里的接口统计写进库


app = FastAPI(title="Skill Pocket", lifespan=lifespan)


@app.middleware("http")
async def block_banned_ips(request, call_next):
    """被封禁的 IP 访问任何页面和接口都返回 403。"""
    from .auth import client_ip

    if ipban.is_banned(client_ip(request)):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "你的 IP 已被禁止访问本站"}, status_code=403)
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>禁止访问</title>"
                            "<p style='font:16px system-ui;margin:20vh auto;max-width:28em;text-align:center;color:#334155'>"
                            "你的 IP 已被禁止访问 Skill Pocket。如有疑问，请联系站长。</p>", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def api_stats(request, call_next):
    """v3.3.66 接口健康：按小时汇总请求数、4xx / 5xx 和耗时（路由模板，不存逐条）。"""
    import time as _t

    from .services import apistats

    start = _t.perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        try:
            apistats.record(request.method, path, status, int((_t.perf_counter() - start) * 1000))
        except Exception:  # noqa: BLE001
            pass


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(account.router)
app.include_router(categories.router)
app.include_router(items.router)
app.include_router(search_assist.router)
app.include_router(voice.router)  # v3.3.103 语音文字整理
app.include_router(favorites.shared_router)
app.include_router(notifications.router)
app.include_router(wechat.router)
app.include_router(jobs.router)
app.include_router(uploads.router)
app.include_router(tasks.router)
app.include_router(asr.router)
app.include_router(changelog.router)
app.include_router(favorites.router)
app.include_router(finder.router)
app.include_router(feedback.router)
app.include_router(feedback_admin.router)  # 要在 admin 之前（同路径的旧反馈接口已移除）
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(staff.router)
app.include_router(compare.router)
app.include_router(content_admin.router)  # 要在 manage 之前：/items/quality-stats 不能被 /items/{item_id} 抢走
app.include_router(manage.router)
app.include_router(accounts_admin.router)
app.include_router(admin_batch1.router)
app.include_router(moderation.router)
app.include_router(takedown.router)
app.include_router(takedown.admin)
app.include_router(category_admin.router)
app.include_router(ingest_monitor.router)
app.include_router(user_care.router)
app.include_router(ai_admin.router)
app.include_router(maintenance.router)
app.include_router(media_admin.router)
app.include_router(ops_admin.router)
app.include_router(comms_admin.router)
app.include_router(observability.public)
app.include_router(observability.router)
app.include_router(risk_admin.router)
app.include_router(insights.router)
app.include_router(operations.public)
app.include_router(operations.router)
app.include_router(track.router)

settings.media_dir.mkdir(parents=True, exist_ok=True)


@app.get("/media/thumb/{rel:path}", include_in_schema=False)
def cover_thumb(rel: str):
    """v3.3.12 封面缩略图（小程序用）：没有就现场生成。"""
    path = thumbs.ensure(rel)
    if path is None:
        raise HTTPException(404, "没有这张缩略图")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=2592000, immutable"})


@app.get("/media/anim/{rel:path}", include_in_schema=False)
def cover_anim(rel: str):
    """v3.3.13 SVG 封面的动图 WebP（小程序详情页用）。
    v3.3.14 还没生成好时立刻返回 404（不缓存）并插到后台队列队首，请求从不等待渲染；小程序先显示静态缩略图。"""
    state, path = anim.lookup(rel)
    if path is None:
        msg = "动图正在生成，请稍后再试" if state == "pending" else "没有这张动图"
        headers = {"Cache-Control": "no-store"} if state == "pending" else {"Cache-Control": "public, max-age=86400"}
        raise HTTPException(404, msg, headers=headers)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=2592000, immutable"})


app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

# 生产环境：前端打包后由后端一并托管（SPA 回退到 index.html）
if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    _OG_PATH = re.compile(r"^items/(\d+)/?$")

    def _with_og(item_id: int) -> HTMLResponse | None:
        """分享链接：给 /items/{id} 的页面加上标题、简介、封面（Open Graph），聊天软件里显示为卡片。"""
        with SessionLocal() as db:
            it = db.get(Item, item_id)
            if it is None or it.status not in ("published", "offline"):
                return None
            title = f"{it.name} · Skill Pocket" if it.status == "published" else f"{it.name}（原文已下线）· Skill Pocket"
            desc = it.summary or "你的 Skill 口袋：每天自动采集更新 GitHub 星标增速榜"
            image = f"/media/{it.cover_path}" if it.cover_path and not it.cover_path.endswith(".svg") else ""
        page = (settings.frontend_dist / "index.html").read_text(encoding="utf-8")
        e = html.escape
        meta = (f'<meta property="og:type" content="article"><meta property="og:site_name" content="Skill Pocket">'
                f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">'
                f'<meta name="description" content="{e(desc)}">'
                + (f'<meta property="og:image" content="{e(image)}">' if image else ""))
        page = re.sub(r"<title>.*?</title>", f"<title>{e(title)}</title>", page, count=1, flags=re.S)
        return HTMLResponse(page.replace("</head>", meta + "</head>", 1))

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        m = _OG_PATH.match(path)
        if m:
            resp = _with_og(int(m.group(1)))
            if resp is not None:
                return resp
        if path.startswith("api/"):
            raise HTTPException(404)
        f = settings.frontend_dist / path
        if path and f.is_file():
            return FileResponse(f)
        if path == "admin" or path.startswith("admin/"):
            # P4 管理端：独立的单页应用
            return FileResponse(settings.frontend_dist / "admin.html")
        return FileResponse(settings.frontend_dist / "index.html")
