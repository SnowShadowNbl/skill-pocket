"""微信小程序：wx.login 的 code 换 openid（code2session）。session_key 只在这里用，不下发、不入库。"""

import httpx

from ..config import settings

CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WechatError(Exception):
    pass


def ready() -> bool:
    return bool(settings.wx_appid and settings.wx_secret)


def code2session(code: str) -> dict:
    """返回 {"openid": ..., "unionid": ...|None}。"""
    if not ready():
        raise WechatError("服务端未配置小程序 AppID / Secret")
    try:
        r = httpx.get(CODE2SESSION_URL, timeout=8, params={
            "appid": settings.wx_appid, "secret": settings.wx_secret, "js_code": code, "grant_type": "authorization_code"})
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise WechatError("连接微信服务器失败，请稍后再试") from e
    if data.get("errcode") or not data.get("openid"):
        raise WechatError(f"微信登录失败（{data.get('errcode')}），请重试")
    return {"openid": data["openid"], "unionid": data.get("unionid")}


# ---------------------------------------------------------------- v3.3.9 小程序码（网页扫码登录 / 绑定）

import base64
import threading
import time

_token_lock = threading.Lock()
_access: tuple[str, float] = ("", 0.0)


def access_token() -> str:
    """服务端调用凭证，有效期约 2 小时，提前 5 分钟刷新。"""
    global _access
    if not ready():
        raise WechatError("服务端未配置小程序 AppID / Secret")
    with _token_lock:
        if _access[0] and time.time() < _access[1]:
            return _access[0]
        try:
            data = httpx.get("https://api.weixin.qq.com/cgi-bin/token", timeout=8, params={
                "grant_type": "client_credential", "appid": settings.wx_appid, "secret": settings.wx_secret}).json()
        except (httpx.HTTPError, ValueError) as e:
            raise WechatError("连接微信服务器失败，请稍后再试") from e
        if not data.get("access_token"):
            raise WechatError(f"获取微信调用凭证失败（{data.get('errcode')}）")
        _access = (data["access_token"], time.time() + int(data.get("expires_in", 7200)) - 300)
        return _access[0]


def qr_image(scene: str, page: str = "pages/scan/index") -> str:
    """wxacode.getUnlimited：生成带 scene 的小程序码，返回 data URL。"""
    global _access
    body = {"scene": scene, "page": page, "check_path": False, "env_version": settings.wx_qr_env or "release", "width": 430}
    for attempt in range(2):
        try:
            r = httpx.post("https://api.weixin.qq.com/wxa/getwxacodeunlimit", params={"access_token": access_token()},
                           json=body, timeout=10)
        except httpx.HTTPError as e:
            raise WechatError("连接微信服务器失败，请稍后再试") from e
        if r.headers.get("content-type", "").startswith("image/"):
            mime = r.headers["content-type"].split(";")[0]
            return f"data:{mime};base64," + base64.b64encode(r.content).decode()
        try:
            err = r.json()
        except ValueError:
            err = {}
        if err.get("errcode") in (40001, 42001) and attempt == 0:  # 凭证失效：刷新后重试一次
            _access = ("", 0.0)
            continue
        raise WechatError(f"生成小程序码失败（{err.get('errcode')}）")
    raise WechatError("生成小程序码失败")
