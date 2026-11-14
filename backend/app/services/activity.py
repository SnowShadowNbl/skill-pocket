"""操作日志：用户与管理员的关键操作。管理员「实时动态」就是用户侧（user / guest）的操作日志。

写入用独立的短会话，业务回滚时日志照样留下；写失败不影响主流程。
"""

import logging
from datetime import timedelta

from sqlalchemy import delete

from ..db import SessionLocal, utcnow
from ..models import ActivityLog, User

log = logging.getLogger(__name__)
RETENTION_DAYS = 180

ACTIONS = {
    "register": "注册",
    "login": "登录",
    "login_fail": "登录失败",
    "password": "修改密码",
    "delete_account": "注销账号",
    "item_submit": "新增条目",
    "recognize": "识别任务",
    "comment": "发表评论",
    "comment_delete": "删除评论",
    "feedback": "提交反馈",
    "review": "审核条目",
    "item_edit": "编辑条目",
    "item_bulk": "批量处理条目",
    "tag": "用户标签",
    "user_tags": "修改用户标签",
    "announcement": "发送公告",
    "home_config": "首页运营位",
    "insights_export": "导出分析数据",
    "code_limited": "验证码请求被限制",
    "code_limit": "修改验证码阈值",
    "schedule": "定时任务控制",
    "alert_ack": "确认告警",
    "alert_resolve": "关闭告警",
    "retention": "修改数据保留天数",
    "storage_cleanup": "清理存储",
    "cover_regen": "重新生成缩略图 / 动图",
    "maintenance": "维护工具",
    "consistency_fix": "修复数据一致性",
    "user_message": "给用户发消息",
    "view_as_user": "以用户视角查看",
    "admin_verify": "高危操作身份验证",
    "feedback_assign": "指派反馈",
    "feedback_note": "反馈内部备注",
    "category_merge": "合并分类",
    "category_split": "拆分分类",
    "category_audit": "AI 分类抽检",
    "ingest_retry": "重试收录任务",
    "ingest_abort": "终止收录任务",
    "takedown_request": "申请下架",
    "takedown_approve": "同意下架",
    "takedown_reject": "驳回下架申请",
    "block_add": "加入黑名单",
    "block_remove": "移出黑名单",
    "comment_approve": "通过评论",
    "comment_reject": "驳回评论",
    "comment_restore": "恢复评论",
    "share_close": "关闭分享",
    "share_reopen": "解除分享关闭",
    "search_block": "屏蔽搜索词",
    "search_unblock": "取消屏蔽搜索词",
    "search_cover": "标记已补收录",
    "item_pin": "首页置顶",
    "item_delete": "删除条目",
    "item_offline": "条目下线",
    "item_online": "条目重新上线",
    "feedback_update": "处理反馈",
    "review_settings": "修改审核设置",
    "crawl": "触发采集",
    "category": "修改分类字典",
    "liveness": "失效巡检",
    "staff": "任免管理员",
    "compare": "对比",
    "user_status": "停用 / 启用用户",
    "user_export": "导出用户",
    "bind_conflict": "绑定冲突",
    "user_delete": "删除用户",
    "user_email": "修改用户邮箱",
    "user_remark": "备注用户",
    "quota_change": "调整 AI 额度",
    "quota_settings": "免费额度默认值",
    "ip_ban": "IP 封禁",
}


# v3.3.37 修改前后对比里字段的中文名
FIELD_LABELS = {
    "status": "状态", "role": "角色", "email": "邮箱", "nickname": "昵称", "remark": "备注", "quota_balance": "AI 额度",
    "wx_bound": "微信绑定", "pin_weight": "置顶权重", "category": "分类", "kind": "使用类型",
    "name": "名称", "summary": "简介", "description": "详细介绍", "install_steps": "安装说明", "homepage_url": "主页",
    "rank_blurb": "榜单详解", "rank_excluded": "排除出榜单", "rating": "评分", "pin_starts_at": "置顶开始", "pin_ends_at": "置顶结束", "enabled": "启用", "reply": "回复", "assignee": "负责人", "priority": "优先级", "note": "备注",
}


def record(action: str, summary: str, *, user: User | None = None, actor: str | None = None, target_type: str = "",
           target_id: int | None = None, detail: dict | None = None, ip: str = "", reason: str = "",
           before: dict | None = None, after: dict | None = None, result: str = "ok", message: str = "",
           target_label: str = "") -> None:
    """写操作日志。v3.3.37 管理操作留痕：reason 原因；before / after 只放变化的字段（平铺字典）；result ok / failed。"""
    try:
        with SessionLocal() as db:
            db.add(ActivityLog(
                user_id=user.id if user else None,
                actor=actor or ("admin" if user is not None and user.role in ("admin", "subadmin", "moderator", "support", "viewer") else "user" if user else "guest"),
                action=action, target_type=target_type, target_id=target_id, summary=summary[:300],
                detail=detail or {}, ip=ip[:64], reason=(reason or "")[:300], before=before, after=after,
                result=result if result in ("ok", "failed") else "ok", message=(message or "")[:300],
                target_label=(target_label or "")[:200],
            ))
            db.commit()
    except Exception:
        log.exception("write activity log failed")


def purge_old() -> int:
    with SessionLocal() as db:
        from .ops import retention

        days = retention(db)["activity_days"]  # v3.3.64 保留天数可在后台调整
        n = db.execute(delete(ActivityLog).where(ActivityLog.created_at < utcnow() - timedelta(days=days))).rowcount
        db.commit()
        return n
