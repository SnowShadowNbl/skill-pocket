"""v3.3.37 识别请求来自哪一端、哪个版本（后台批次 0：渠道与客户端版本）。

- 客户端主动上报优先：请求头 X-Client（web / miniprogram）、X-Client-Version。
- 小程序兜底：微信小程序发出的请求，Referer 固定是 https://servicewechat.com/<AppID>/<版本>/page-frame.html，
  版本段为 devtools（开发者工具）、0（开发版 / 体验版）或正式版号。
- 网页按 User-Agent 区分电脑和手机。
历史数据没有这些字段，一律显示「未知」，不倒推。
"""

import re

from fastapi import Request

CHANNELS = {"web-pc": "PC 网页", "web-mobile": "手机网页", "miniprogram": "小程序", "": "未知"}
METHODS = {"email_code": "邮箱验证码", "password": "密码", "wechat": "小程序微信登录", "wx_qr": "网页微信扫码",
           "merge": "账号合并后换发", "": "未知"}

_WX_REFERER = re.compile(r"^https://servicewechat\.com/(wx[0-9a-f]+)/([^/]+)/", re.I)
_MOBILE = re.compile(r"Mobile|Android|iPhone|iPad|iPod|HarmonyOS", re.I)


def client_of(request: Request | None) -> tuple[str, str]:
    """→ (端, 版本)。端是 web-pc / web-mobile / miniprogram。"""
    if request is None:
        return "", ""
    h = request.headers
    claimed = (h.get("x-client") or "").strip().lower()
    version = (h.get("x-client-version") or "").strip()[:40]
    m = _WX_REFERER.match(h.get("referer") or "")
    if claimed in ("miniprogram", "mp", "mp-weixin") or m:
        if not version and m:
            v = m.group(2)
            version = "开发者工具" if v == "devtools" else "开发版 / 体验版" if v == "0" else v
        return "miniprogram", version
    ua = h.get("user-agent") or ""
    return ("web-mobile" if _MOBILE.search(ua) else "web-pc"), version
