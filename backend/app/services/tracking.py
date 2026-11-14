"""批次任务进度 + 入库日志。

- log()：写一条入库日志（哪个条目、哪个环节、成功 / 警告 / 失败、原因）
- ItemTracker：处理单个条目时切换“当前环节”，页面上的进度条据此显示“第 3/9 个 · AI 提炼中”
- create_task() / run_task() / start_task()：把一批条目作为一个任务跑，统计成功 / 失败

所有写入都用独立的短会话，不和业务事务混在一起：业务失败回滚时日志照样留下。
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from sqlalchemy import select

from ..db import SessionLocal, utcnow
from ..models import IngestLog, Item, Task, TaskItem

log_ = logging.getLogger(__name__)

STAGES = {
    "queue": "排队",
    "discover": "发现与收录判定",
    "snapshot": "星标快照",
    "repo": "读取仓库信息",
    "doc": "读取 README / SKILL.md",
    "ai": "AI 提炼与分类",
    "cover_readme": "提取 README 截图",
    "cover_ai": "AI 绘制封面",
    "save": "保存入库",
    "classify": "AI 重新分类",
    "review": "AI 审核",
    "liveness": "失效巡检",
    "embed": "生成语义向量",
    "blurb": "榜单中文详解",
    "search": "搜索 GitHub",
    "read": "AI 通读长文",
}
TRIGGERS = {
    "github": "GitHub 导入",
    "screenshot": "截图识别",
    "manual_form": "手动填写",
    "crawl": "自动采集",
    "reextract": "重新提炼",
    "translate": "批量中文化",
    "cover": "补全封面",
    "gallery": "补图片集",
    "review": "待确认收录",
    "search": "搜索添加",
    "text": "长文识别",
    "reclassify": "重新分类",
    "blurb": "榜单详解",
    "liveness": "失效巡检",
    "tags": "补充搜索标签",
    "audit": "AI 分类抽检",
}
AUTO_TRIGGERS = {"crawl", "reclassify", "blurb", "liveness", "tags"}

_lock = threading.Lock()  # SQLite 下串行化这些小写入，避免并发提炼时互相等锁


def log(*, trigger: str, stage: str, level: str, message: str, item_id: int | None = None, item_name: str = "",
        repo: str = "", task_id: int | None = None, duration_ms: int | None = None, source: str | None = None,
        user_id: int | None = None) -> None:
    try:
        with _lock, SessionLocal() as db:
            db.add(IngestLog(
                task_id=task_id, item_id=item_id, item_name=item_name[:200], repo=repo[:200],
                source=source or ("auto" if trigger in AUTO_TRIGGERS else "manual"), user_id=user_id,
                trigger=trigger, stage=stage, level=level, message=message[:4000], duration_ms=duration_ms,
            ))
            db.commit()
    except Exception:  # 日志写失败不能影响主流程
        log_.exception("write ingest log failed")


class ItemTracker:
    """处理单个条目时用：记录当前环节、写日志、计时。"""

    def __init__(self, item: Item, trigger: str, task_id: int | None = None):
        self.item_id = item.id
        self.name = item.name
        self.repo = item.repo.full_name + (f"/{item.sub_path}" if item.sub_path else "") if item.repo else ""
        self.source = item.source
        self.user_id = item.created_by
        self.trigger = trigger
        self.task_id = task_id
        self.t0 = time.monotonic()
        self.current = ""
        self.warnings: list[str] = []

    def stage(self, key: str) -> None:
        self.current = key
        if self.task_id is None:
            return
        try:
            with _lock, SessionLocal() as db:
                ti = db.scalar(select(TaskItem).where(TaskItem.task_id == self.task_id, TaskItem.item_id == self.item_id))
                if ti:
                    ti.stage = key
                    db.commit()
        except Exception:
            log_.exception("update task stage failed")

    def _log(self, level: str, message: str, stage: str | None = None, duration: bool = False) -> None:
        log(trigger=self.trigger, stage=stage or self.current or "save", level=level, message=message,
            item_id=self.item_id, item_name=self.name, repo=self.repo, task_id=self.task_id,
            source="auto" if self.trigger in AUTO_TRIGGERS else self.source, user_id=self.user_id,
            duration_ms=int((time.monotonic() - self.t0) * 1000) if duration else None)

    def warn(self, message: str, stage: str | None = None) -> None:
        self.warnings.append(message)
        self._log("warn", message, stage)

    def error(self, message: str, stage: str | None = None) -> None:
        self._log("error", message, stage, duration=True)

    def success(self, message: str) -> None:
        self._log("success", message, "save", duration=True)


# ---------------------------------------------------------------- 批次任务

def create_task(kind: str, title: str, items: list[tuple[int, str]], source: str | None = None,
                user_id: int | None = None) -> int:
    with _lock, SessionLocal() as db:
        task = Task(kind=kind, title=title[:200], source=source or ("auto" if kind in AUTO_TRIGGERS else "manual"), user_id=user_id,
                    total=len(items), status="running" if items else "ok", finished_at=None if items else utcnow())
        db.add(task)
        db.flush()
        for seq, (item_id, name) in enumerate(items, start=1):
            db.add(TaskItem(task_id=task.id, item_id=item_id, seq=seq, name=name[:200], stage="queue"))
        db.commit()
        return task.id


def _finish_item(task_id: int, item_id: int, ok: bool, message: str = "", deferred: bool = False) -> None:
    with _lock, SessionLocal() as db:
        ti = db.scalar(select(TaskItem).where(TaskItem.task_id == task_id, TaskItem.item_id == item_id))
        task = db.get(Task, task_id)
        if ti:
            ti.status = "deferred" if deferred else ("ok" if ok else "failed")
            ti.message = message[:500]
            ti.finished_at = utcnow()
        if task and not deferred:
            task.done += 1
            task.failed += 0 if ok else 1
        db.commit()


def _start_item(task_id: int, item_id: int) -> None:
    with _lock, SessionLocal() as db:
        ti = db.scalar(select(TaskItem).where(TaskItem.task_id == task_id, TaskItem.item_id == item_id))
        if ti:
            ti.status, ti.started_at = "running", utcnow()
            db.commit()


def finish_task(task_id: int, status: str | None = None) -> None:
    with _lock, SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        if status is None:
            status = "ok" if task.failed == 0 and task.done >= task.total else ("failed" if task.done and task.failed == task.done else "partial")
        task.status, task.finished_at = status, utcnow()
        db.commit()


def run_task(task_id: int, item_ids: list[int], fn: Callable[[int, int], tuple[bool, str]], workers: int = 1,
             stop_on: tuple[type[BaseException], ...] = ()) -> None:
    """依次（或并发）处理任务里的条目。fn(item_id, task_id) 返回 (是否成功, 一句话结果)。
    stop_on 里的异常（如 GitHub 额度用完）会终止整个任务：剩余条目标记为“留到下次”，异常继续往外抛。"""
    stopped: list[BaseException] = []

    def one(item_id: int) -> None:
        if stopped:
            _finish_item(task_id, item_id, False, "额度用完，留到下次采集", deferred=True)
            return
        _start_item(task_id, item_id)
        try:
            ok, msg = fn(item_id, task_id)
        except stop_on as e:
            stopped.append(e)
            _finish_item(task_id, item_id, False, str(e), deferred=True)
            return
        except Exception as e:
            log_.exception("task %s item %s failed", task_id, item_id)
            ok, msg = False, f"{e.__class__.__name__}: {e}"
        _finish_item(task_id, item_id, ok, msg)

    try:
        if workers <= 1:
            for i in item_ids:
                one(i)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(one, item_ids))
    finally:
        finish_task(task_id, "partial" if stopped else None)
    if stopped:
        raise stopped[0]


def start_task(task_id: int, item_ids: list[int], fn: Callable[[int, int], tuple[bool, str]], workers: int = 1) -> None:
    threading.Thread(target=run_task, args=(task_id, item_ids, fn, workers), daemon=True, name=f"task-{task_id}").start()


def mark_interrupted() -> None:
    """启动时：上次进程退出时还在跑的任务标记为中断。"""
    with SessionLocal() as db:
        for task in db.scalars(select(Task).where(Task.status == "running")):
            task.status, task.finished_at = "partial", utcnow()
            for ti in db.scalars(select(TaskItem).where(TaskItem.task_id == task.id, TaskItem.status.in_(("pending", "running")))):
                ti.status, ti.message = "deferred", "服务重启，任务中断"
        db.commit()
