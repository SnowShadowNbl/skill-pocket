"""进程内定时任务：每天 CRAWL_START 触发一轮采集；08:30 站内消息（上新汇总、版本提醒）。

v3.3.68 后台「定时任务」：可以手动执行一次、暂停、恢复。暂停状态存在 app_meta（schedules_paused），重启后仍然生效。
数据库备份由宿主机 cron 执行（deploy/maintenance.sh，每天 08:30），不在这里，只在后台只读展示。
"""

import json
import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from . import crawler

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None

JOBS = {
    "daily_crawl": {"name": "每日采集", "describe": lambda: f"每天 {settings.crawl_start}"},
    "daily_notify": {"name": "每日上新与版本提醒", "describe": lambda: "每天 08:30"},
}


def _paused() -> dict:
    from ..db import SessionLocal
    from ..models import AppMeta

    with SessionLocal() as db:
        m = db.get(AppMeta, "schedules_paused")
        try:
            return json.loads(m.value) if m and m.value else {}
        except ValueError:
            return {}


def _save_paused(v: dict) -> None:
    from ..db import SessionLocal
    from ..models import AppMeta

    with SessionLocal() as db:
        db.merge(AppMeta(key="schedules_paused", value=json.dumps(v)))
        db.commit()


def start() -> None:
    global _scheduler
    if not settings.crawl_enabled or _scheduler:
        return
    h, m = crawler._hm(settings.crawl_start)
    _scheduler = BackgroundScheduler(timezone=settings.crawl_tz)
    _scheduler.add_job(
        lambda: crawler.run_crawl("schedule"), CronTrigger(hour=h, minute=m, timezone=settings.crawl_tz),
        id="daily_crawl", max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    # v3.3 站内消息：订阅分类上新汇总、收藏仓库的新版本（采集一般在 08:00 前结束）
    from . import notify

    _scheduler.add_job(notify.run_daily, CronTrigger(hour=8, minute=30, timezone=settings.crawl_tz),
                       id="daily_notify", max_instances=1, coalesce=True, misfire_grace_time=3600)
    _scheduler.start()
    for key in _paused():
        if _scheduler.get_job(key):
            _scheduler.pause_job(key)
    log.info("crawl scheduled daily at %s (%s)", settings.crawl_start, settings.crawl_tz)


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_time():
    job = _scheduler.get_job("daily_crawl") if _scheduler else None
    return job.next_run_time if job else None


def info() -> list[dict]:
    paused = _paused()
    out = []
    for key, j in JOBS.items():
        job = _scheduler.get_job(key) if _scheduler else None
        out.append({"key": key, "name": j["name"], "cron": j["describe"](), "enabled": job is not None,
                    "next_run_at": job.next_run_time if job else None, "paused": key in paused, "paused_at": (paused.get(key) or {}).get("at"),
                    "paused_by": (paused.get(key) or {}).get("by"), "running": crawler.is_running() if key == "daily_crawl" else None})
    return out


def pause(key: str, by: int) -> None:
    from ..db import utcnow

    p = _paused()
    p[key] = {"at": utcnow().isoformat(), "by": by}
    _save_paused(p)
    if _scheduler and _scheduler.get_job(key):
        _scheduler.pause_job(key)


def resume(key: str) -> None:
    p = _paused()
    p.pop(key, None)
    _save_paused(p)
    if _scheduler and _scheduler.get_job(key):
        _scheduler.resume_job(key)


def run_now(key: str) -> str:
    if key == "daily_crawl":
        if crawler.is_running():
            return "already_running"
        threading.Thread(target=lambda: crawler.run_crawl("manual"), daemon=True, name="crawl-manual").start()
        return "started"
    if key == "daily_notify":
        from . import notify

        threading.Thread(target=notify.run_daily, daemon=True, name="notify-manual").start()
        return "started"
    raise KeyError(key)
