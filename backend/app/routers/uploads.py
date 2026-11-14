"""手动上传：截图识别入库（AI-4）。

流程：上传 → 视觉模型识别出条目列表（立即返回）→ 后台逐条对应 GitHub 仓库 / Skill 目录 → 前端轮询看进度 → 勾选入库。
每条的 state：resolving（对应中）/ matched（可加入）/ existing（已收录）/ unmatched（没找到）
"""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..models import Item, Repo, Upload, UploadItem
from .. import auth
from ..auth import current_user
from ..models import User
from ..services import activity, billing, ingest, quota, review, tracking, vision
from ..services.github import GitHub, GitHubError

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
log = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_write_lock = threading.Lock()


# ---------------------------------------------------------------- 查重

def _library_index(db: Session) -> dict[str, list[dict]]:
    """库内已发布条目按“归一化名称”建索引（含仓库名），用于同名查重。"""
    idx: dict[str, list[dict]] = {}
    rows = db.execute(
        select(Item.id, Item.name, Item.sub_path, Repo.full_name)
        .outerjoin(Repo, Repo.id == Item.repo_id)
        .where(Item.status.in_(("published", "hidden", "pending_review")))
    ).all()
    for iid, name, sub, full_name in rows:
        entry = {"id": iid, "name": name, "repo": full_name, "sub_path": sub}
        keys = {vision.norm(name)}
        if full_name and not sub:
            keys.add(vision.norm(full_name.split("/")[1]))
        for k in keys:
            idx.setdefault(k, []).append(entry)
    return idx


_existing_for = ingest.existing_item_for


# ---------------------------------------------------------------- 后台对应

def _save_item(upload_id: int, index: int, patch: dict) -> None:
    with _write_lock, SessionLocal() as db:
        rec = db.get(Upload, upload_id)
        data = dict(rec.ai_result)
        items = list(data["items"])
        items[index] = {**items[index], **patch}
        data["items"] = items
        if rec.status == "resolving" and all(it.get("state") != "resolving" for it in items):
            rec.status = "recognized"  # 只从「对应中」改过来，别把「加入中 / 已导入」改回去
        rec.ai_result = data
        db.commit()


def _resolve_all(upload_id: int, items: list[dict]) -> None:
    with GitHub() as gh:
        rv = vision.Resolver(gh)

        def one(pair):
            i, it = pair
            if it["state"] != "resolving":
                return
            try:
                r = rv.resolve(it)
            except Exception as e:  # 单条失败不影响其他
                _save_item(upload_id, i, {"state": "unmatched", "error": str(e)[:200]})
                return
            patch = {**r}
            if r["match"]:
                with SessionLocal() as db:
                    ex = _existing_for(db, r["match"]["full_name"], r["sub_path"])
                patch.update(state="existing" if ex else "matched", existing_item_id=ex)
            elif it.get("same_name"):
                # 外部都没找到，但库里有同名条目：按“已收录”提示（可在页面上改）
                h = it["same_name"][0]
                patch.update(state="existing", existing_item_id=h["id"], via="library", sub_path=h["sub_path"],
                             match={"full_name": h["repo"], "html_url": f"https://github.com/{h['repo']}",
                                    "description": "", "stars": None, "language": ""} if h["repo"] else None)
            else:
                patch["state"] = "unmatched"
            _save_item(upload_id, i, patch)

        with SessionLocal() as db:
            rec = db.get(Upload, upload_id)
            uid = rec.user_id if rec else None
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(billing.wrap(uid, one), list(enumerate(items))))


def _out(rec: Upload) -> dict:
    return {"id": rec.id, "status": rec.status, "image_url": f"/media/{rec.image_path}", **rec.ai_result}


# ---------------------------------------------------------------- 接口

@router.post("")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db), me: User = Depends(current_user)):
    quota.check_ai(db, me)
    if file.content_type not in ALLOWED:
        raise HTTPException(400, "只支持 PNG / JPG / WebP / GIF 图片")
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, "图片不能超过 10MB")
    try:
        img, mime = vision.prepare_image(raw)
    except Exception:
        raise HTTPException(400, "无法读取这张图片")

    folder = settings.media_dir / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.{'png' if mime == 'image/png' else 'jpg'}"
    (folder / fname).write_bytes(img)
    rec = Upload(image_path=f"uploads/{fname}", status="recognizing", user_id=me.id)
    db.add(rec)
    db.commit()
    activity.record("recognize", "上传截图识别", user=me, target_type="upload", target_id=rec.id)

    try:
        with billing.charged_to(me.id):
            result = vision.recognize(img, mime)
    except RuntimeError as e:
        rec.status, rec.ai_result = "failed", {"error": str(e)}
        db.commit()
        raise HTTPException(502, str(e))

    # 库内同名条目：只作为提示（可能是别人搬运的副本）；是否真重复以对应到的仓库 / Skill 目录为准
    idx = _library_index(db)
    for it in result["items"]:
        it.update(state="resolving", existing_item_id=None, match=None, sub_path=None, via=None, installs=None,
                  suggestions=[], same_name=(idx.get(vision.norm(it["name"])) or [])[:3])

    rec.status = "resolving" if any(it["state"] == "resolving" for it in result["items"]) else "recognized"
    rec.ai_result = result
    db.commit()
    threading.Thread(target=_resolve_all, args=(rec.id, result["items"]), daemon=True).start()
    return _out(rec)


@router.get("/search")
def search_repo(q: str, me: User = Depends(current_user)):
    """识别不到时手动输入名称：同时查 skills.sh 和 GitHub。"""
    q = q.strip()
    if not q:
        return []
    out = []
    hit = vision.skills_sh_lookup(q)
    if hit:
        out.append({"full_name": hit["source"], "html_url": f"https://github.com/{hit['source']}", "description": f"skills.sh：{hit['skill_id']}",
                    "stars": None, "language": "", "installs": hit["installs"], "skill_id": hit["skill_id"]})
    with GitHub() as gh:
        try:
            out += [vision._repo_brief(d) for d in gh.search_repos(f"{q} in:name", per_page=6)]
        except GitHubError as e:
            if not out:
                raise HTTPException(502, str(e))
    return out


@router.get("/{upload_id}")
def get_upload(upload_id: int, db: Session = Depends(get_db), me: User = Depends(current_user)):
    rec = db.get(Upload, upload_id)
    if rec is None or (rec.user_id != me.id and not auth.is_admin(me)):
        raise HTTPException(404, "上传记录不存在")
    return _out(rec)


class Pick(BaseModel):
    full_name: str
    name: str = ""
    sub_path: str | None = None  # 指定仓库内的 Skill 目录；None 表示按名称自动判断


class ImportIn(BaseModel):
    picks: list[Pick]


@router.post("/{upload_id}/import")
def import_from_upload(upload_id: int, body: ImportIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    rec = db.get(Upload, upload_id)
    if rec is None or (rec.user_id != me.id and not auth.is_admin(me)):
        raise HTTPException(404, "上传记录不存在")
    if not body.picks:
        raise HTTPException(400, "请至少选择一个条目")

    if rec.status == "importing":
        raise HTTPException(409, "上一批还在加入中，请稍候")

    quota.check_ai(db, me)
    quota.check_new_items(db, me, len(body.picks))
    # v3.3.25 加入改到后台线程：逐个核对仓库、建条目可能要好几分钟，原来同步执行会被网关 60 秒掐断，
    # 手机上显示失败，服务器却还在加（截图识别 47 号：10:25 点加入，10:37 才加完）。
    # 接口最多等 20 秒：加完了照旧返回结果（老版本客户端不受影响）；没加完返回 queued，前端轮询 GET /api/uploads/{id}，
    # status 从 importing 变成 imported 后读 import 字段。
    with _write_lock:
        db.refresh(rec)
        rec.status = "importing"
        rec.ai_result = {k: v for k, v in (rec.ai_result or {}).items() if k != "import"}
        db.commit()
    t = threading.Thread(target=_run_import, args=(rec.id, [p.model_dump() for p in body.picks], me.id, review.needs_review(me)),
                         daemon=True)
    t.start()
    t.join(IMPORT_WAIT)
    db.refresh(rec)
    if rec.status == "imported" and (rec.ai_result or {}).get("import"):
        return {**rec.ai_result["import"], "queued": False}
    return {"created": [], "skipped": [], "errors": [], "task_id": None, "queued": True, "status": "importing"}


IMPORT_WAIT = 20  # 秒


def _run_import(upload_id: int, picks: list[dict], user_id: int, needs_review: bool) -> None:
    created, skipped, errors, task_id = [], [], [], None
    try:
        with SessionLocal() as db:
            try:
                created, skipped, errors = ingest.import_picks(db, picks, "screenshot", user_id=user_id, review=needs_review)
            except Exception as e:  # noqa: BLE001 —— 整批意外失败：记下原因，让前端能停下来提示
                log.exception("upload %s import failed", upload_id)
                errors = [f"加入失败：{e}"]
            for i in created:
                db.add(UploadItem(upload_id=upload_id, item_id=i))
            db.commit()
            task_id = ingest.start_process_task("screenshot", f"截图导入 · {len(created)} 个条目", created, workers=2, user_id=user_id)
    finally:
        with _write_lock, SessionLocal() as db:  # 和后台对应共用一把锁，免得互相覆盖 ai_result
            rec = db.get(Upload, upload_id)
            if rec is not None:
                rec.status = "imported"
                rec.ai_result = {**(rec.ai_result or {}),
                                 "import": {"created": created, "skipped": skipped, "errors": errors, "task_id": task_id}}
                db.commit()
            who = db.get(User, user_id)
        if created:
            activity.record("item_submit", f"截图识别新增 {len(created)} 个条目", user=who, target_type="task", target_id=task_id,
                            detail={"item_ids": created, "via": "screenshot", "upload_id": upload_id})
