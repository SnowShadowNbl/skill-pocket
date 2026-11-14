"""v3.3 评论内容审核：交给 AI 判断（judge.moderate_comment），AI 不可用时才用敏感词兜底。

AI 结果：pass → 公开；block → 直接拦下，不保存；review → 保存为待审核，只有作者和管理员看得到。
兜底规则只会把评论送去人工审核，不会直接拦下，避免误伤。
"""

import re

from . import judge

# 兜底用的少量高风险词（只在 AI 不可用时用）：命中就交给管理员
_RISK = re.compile(
    r"(加微|加v|加V|vx[:：]|wx[:：]|微信号|qq群|QQ群|加群|代写|代刷|刷单|返利|博彩|赌博|赌场|六合彩|色情|裸聊|约炮|毒品|冰毒|"
    r"枪支|发票代开|办证|贷款秒批|兼职日结|\d{11}|https?://(?!github\.com|gitee\.com|huggingface\.co)\S+)",
    re.I,
)


def check(content: str, item_name: str) -> tuple[str, str]:
    """返回 (status, reason)：status 为 visible / pending / blocked。"""
    try:
        r = judge.moderate_comment(content, item_name)
    except judge.JudgeUnavailable:
        if _RISK.search(content):
            return "pending", "AI 审核暂不可用，命中敏感词，等管理员确认"
        return "visible", ""
    if r["decision"] == "block":
        return "blocked", r["reason"] or "内容不符合社区规范"
    if r["decision"] == "review":
        return "pending", r["reason"] or "AI 拿不准，等管理员确认"
    return "visible", ""
