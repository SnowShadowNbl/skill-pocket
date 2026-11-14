"""发信：腾讯云邮件推送 SES（API 3.0，TC3-HMAC-SHA256 签名）。

每封邮件都写入 email_logs。没有配置 SES 时走 console 通道：只把验证码打到服务端日志里，供本地开发使用。
"""

import hashlib
import hmac
import json
import logging
import time

import httpx

from ..config import settings
from ..db import SessionLocal
from ..models import EmailLog

log = logging.getLogger(__name__)

HOST = "ses.tencentcloudapi.com"
VERSION = "2020-10-02"

PURPOSE_LABEL = {"login": "登录", "reset": "找回密码", "change": "修改密码", "delete": "注销账号"}


class MailError(Exception):
    pass


def _sign(action: str, payload: str, ts: int) -> str:
    date = time.strftime("%Y-%m-%d", time.gmtime(ts))
    canonical = (
        f"POST\n/\n\ncontent-type:application/json; charset=utf-8\nhost:{HOST}\nx-tc-action:{action.lower()}\n\n"
        f"content-type;host;x-tc-action\n{hashlib.sha256(payload.encode()).hexdigest()}"
    )
    scope = f"{date}/ses/tc3_request"
    to_sign = f"TC3-HMAC-SHA256\n{ts}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"

    def h(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    key = h(h(h(("TC3" + settings.ses_secret_key).encode(), date), "ses"), "tc3_request")
    sig = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"TC3-HMAC-SHA256 Credential={settings.ses_secret_id}/{scope}, SignedHeaders=content-type;host;x-tc-action, Signature={sig}"


def call(action: str, params: dict) -> dict:
    payload = json.dumps(params, ensure_ascii=False)
    ts = int(time.time())
    headers = {
        "Authorization": _sign(action, payload, ts), "Content-Type": "application/json; charset=utf-8", "Host": HOST,
        "X-TC-Action": action, "X-TC-Timestamp": str(ts), "X-TC-Version": VERSION, "X-TC-Region": settings.ses_region,
    }
    try:
        r = httpx.post(f"https://{HOST}", content=payload.encode(), headers=headers, timeout=15)
        data = r.json()["Response"]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise MailError(f"连接邮件服务失败：{e.__class__.__name__}") from e
    if "Error" in data:
        raise MailError(f"{data['Error'].get('Code')}: {data['Error'].get('Message')}")
    return data


def _record(email: str, purpose: str, provider: str, ok: bool, error: str = "") -> None:
    with SessionLocal() as db:
        db.add(EmailLog(email=email, purpose=purpose, provider=provider, ok=ok, error=error[:2000]))
        db.commit()


def send_code(email: str, code: str, purpose: str) -> None:
    """发送验证码邮件。失败抛 MailError（已记录发信日志）。"""
    if not settings.ses_enabled:
        log.warning("SES 未配置，验证码只记在日志里：%s %s → %s", purpose, email, code)
        _record(email, purpose, "console", True)
        return
    subject = f"Skill Pocket {PURPOSE_LABEL.get(purpose, '')}验证码：{code}"
    try:
        call("SendEmail", {
            "FromEmailAddress": settings.ses_from,
            "Destination": [email],
            "Subject": subject,
            "Template": {"TemplateID": settings.ses_template_id, "TemplateData": json.dumps({"code": code})},
            "TriggerType": 1,  # 触发类邮件（验证码），优先发送
        })
    except MailError as e:
        _record(email, purpose, "ses", False, str(e))
        raise
    _record(email, purpose, "ses", True)


_template_ok: dict = {"ok": None, "t": 0.0}


def email_login_ready() -> bool:
    """验证码邮件能不能发：已配置 SES 且模板审核通过（结果缓存 10 分钟）。本地开发模式总是可用。"""
    if settings.auth_dev_codes:
        return True
    if not settings.ses_enabled:
        return False
    now = time.time()
    if _template_ok["ok"] is not None and now - _template_ok["t"] < 600:
        return _template_ok["ok"]
    try:
        status = call("GetEmailTemplate", {"TemplateID": settings.ses_template_id}).get("TemplateStatus")
        ok = status == 0  # 0 审核通过 / 1 待审核 / 2 审核拒绝
    except MailError as e:
        log.warning("查询 SES 模板状态失败：%s", e)
        ok = bool(_template_ok["ok"])
    _template_ok.update(ok=ok, t=now)
    return ok
