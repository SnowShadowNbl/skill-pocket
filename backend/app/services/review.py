"""用户提交条目的审核：审核通过后才公开。

流程：普通用户提交 → status=awaiting, review_state=ai → AI 提炼介绍 → 提炼完成后立即 AI 审核 → 按档位处理
  最大 max     ：AI 必须给出通过 / 驳回，直接生效，写上线日志
  中等 medium  ：AI 有把握（≥ 阈值）的直接生效；拿不准的 review_state=admin，交给管理员
  关闭 off     ：AI 只给意见，全部 review_state=admin
管理员新增、夜间自动采集的条目不走这里。
"""

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AppMeta, Item, ItemReview, User
from . import activity, judge, tracking

log = logging.getLogger(__name__)

MODES = {"max": "最大", "medium": "中等", "off": "关闭"}
DEFAULT_MODE, DEFAULT_THRESHOLD = "medium", 0.8


def get_settings(db: Session) -> dict:
    mode = db.get(AppMeta, "ai_review_mode")
    th = db.get(AppMeta, "ai_review_threshold")
    m = mode.value if mode and mode.value in MODES else DEFAULT_MODE
    try:
        t = float(th.value) if th else DEFAULT_THRESHOLD
    except ValueError:
        t = DEFAULT_THRESHOLD
    return {"mode": m, "mode_label": MODES[m], "threshold": t}


def set_settings(db: Session, mode: str, threshold: float) -> dict:
    db.merge(AppMeta(key="ai_review_mode", value=mode))
    db.merge(AppMeta(key="ai_review_threshold", value=str(threshold)))
    db.commit()
    return get_settings(db)


def needs_review(user: User | None) -> bool:
    return user is not None and user.role not in ("admin", "subadmin", "moderator")  # v3.3.55 有内容修改权限的管理员提交免审


def _similar(db: Session, item: Item) -> list[dict]:
    """库里同名或同仓库的已上线条目，给 AI 判断是否重复。"""
    from .vision import norm

    key = norm(item.name)
    rows = db.scalars(select(Item).where(Item.status.in_(("published", "hidden")), Item.id != item.id)).all()
    out = []
    for it in rows:
        same_repo = item.repo_id and it.repo_id == item.repo_id
        if same_repo or norm(it.name) == key:
            out.append({"id": it.id, "name": it.name, "repo": it.repo.full_name if it.repo else it.homepage_url,
                        "sub_path": it.sub_path, "summary": it.summary[:120]})
    return out[:8]


def _record(db: Session, item: Item, reviewer: str, decision: str, confidence: float | None, reason: str,
            mode: str = "", reviewer_id: int | None = None) -> None:
    db.add(ItemReview(item_id=item.id, item_name=item.name, submitter_id=item.created_by, reviewer=reviewer,
                      reviewer_id=reviewer_id, decision=decision, confidence=confidence, reason=reason[:500], mode=mode))


def _publish(item: Item) -> None:
    item.status, item.review_state = "published", ""


def _decline(item: Item, reason: str) -> None:
    item.status, item.review_state, item.review_note = "declined", "", reason


def ai_review(item_id: int, task_id: int | None = None) -> str:
    """AI 审核一个待审核条目，返回结论（approve / reject / admin）。"""
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        if item is None or item.status != "awaiting":
            return "skip"
        cfg = get_settings(db)
        tr = tracking.ItemTracker(item, "review", task_id)
        tr.stage("review")
        info = {
            "name": item.name, "repo": (item.repo.full_name + (f"/{item.sub_path}" if item.sub_path else "")) if item.repo else item.homepage_url,
            "kind": item.kind, "category": item.category.name if item.category else "", "summary": item.summary,
            "description": item.description[:1500], "stars": item.repo.stars if item.repo else None,
            "topics": (item.repo.topics or [])[:10] if item.repo else [],
            "extract_failed": item.ai_status in ("failed", "rule"),
        }
        try:
            r = judge.review_item(info, _similar(db, item), must_decide=cfg["mode"] == "max")
        except judge.JudgeUnavailable as e:
            item.review_state = "admin"
            _record(db, item, "ai", "unsure", None, f"AI 暂不可用，转交管理员：{e}", cfg["mode"])
            db.commit()
            tr.warn("AI 审核暂不可用，已转交管理员", "review")
            return "admin"

        reason = r["reason"] + (f"（与条目 #{r['duplicate_of']} 重复）" if r["duplicate_of"] else "")
        confident = r["confidence"] >= cfg["threshold"]
        if cfg["mode"] == "off" or r["decision"] == "unsure" or (cfg["mode"] == "medium" and not confident):
            item.review_state = "admin"
            _record(db, item, "ai", r["decision"] if cfg["mode"] == "off" else "unsure", r["confidence"],
                    f"AI 意见：{'建议通过' if r['decision'] == 'approve' else '建议驳回' if r['decision'] == 'reject' else '拿不准'}。{reason}",
                    cfg["mode"])
            db.commit()
            tr._log("info", f"已转交管理员审核（AI 把握 {r['confidence']:.0%}）：{reason}", "review")
            outcome = "admin"
        elif r["decision"] == "approve":
            _publish(item)
            _record(db, item, "ai", "approve", r["confidence"], reason, cfg["mode"])
            db.commit()
            tr._log("success", f"AI 审核通过，已上线：{reason}", "review")
            outcome = "approve"
        else:
            _decline(item, reason)
            _record(db, item, "ai", "reject", r["confidence"], reason, cfg["mode"])
            db.commit()
            tr._log("warn", f"AI 审核未通过：{reason}", "review")
            outcome = "reject"
        submitter = db.get(User, item.created_by) if item.created_by else None
        activity.record("review", f"AI 审核「{item.name}」：{ {'approve': '通过上线', 'reject': '驳回', 'admin': '转交管理员'}[outcome] }",
                        user=submitter, actor="system", target_type="item", target_id=item.id,
                        detail={"decision": outcome, "confidence": r["confidence"], "reason": reason})
        return outcome


def ai_review_async(item_id: int) -> None:
    threading.Thread(target=ai_review, args=(item_id,), daemon=True, name=f"review-{item_id}").start()


def admin_decide(db: Session, item: Item, admin: User, decision: str, reason: str) -> None:
    """管理员：approve / reject（待审核条目），revoke（把已上线的撤回下线），restore（重新上线）。"""
    if decision == "approve":
        _publish(item)
    elif decision == "reject":
        _decline(item, reason or "管理员驳回")
    elif decision == "revoke":
        _decline(item, reason or "管理员撤回")
    elif decision == "restore":
        item.status, item.review_state, item.offline_at, item.offline_reason = "published", "", None, ""
    _record(db, item, "admin", decision, None, reason, reviewer_id=admin.id)
    db.commit()
    label = {"approve": "通过上线", "reject": "驳回", "revoke": "撤回下线", "restore": "重新上线"}[decision]
    activity.record("review", f"管理员{label}「{item.name}」" + (f"：{reason}" if reason else ""), user=admin,
                    target_type="item", target_id=item.id, detail={"decision": decision, "reason": reason})
