"""AI-5：语音转文字。浏览器 ⇄ 本服务 ⇄ FunASR（2pass 流式）WebSocket 中转。

浏览器不直接连 FunASR：FunASR 不对公网暴露，也方便以后加鉴权 / 限流。
协议（FunASR runtime websocket）：
  1. 先发 JSON 配置 {"mode": "2pass", "chunk_size": [5, 10, 5], "wav_name": "h5", "is_speaking": true, ...}
  2. 再持续发 16kHz 16bit 单声道 PCM 二进制帧
  3. 说完发 {"is_speaking": false}
服务端返回 {"mode": "2pass-online" | "2pass-offline", "text": "...", "is_final": bool}
"""

import asyncio
import json
import logging

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings

router = APIRouter(tags=["asr"])
log = logging.getLogger(__name__)

MAX_SECONDS = 120  # 单次语音最长 2 分钟，防止忘记松手一直占着识别服务
MAX_BYTES = 16000 * 2 * MAX_SECONDS


@router.websocket("/api/asr/ws")
async def asr_ws(ws: WebSocket):
    await ws.accept()
    if not settings.funasr_ws_url:
        await ws.send_json({"error": "语音识别服务未配置（FUNASR_WS_URL）"})
        await ws.close(code=1011)
        return
    try:
        upstream = await websockets.connect(settings.funasr_ws_url, open_timeout=5, max_size=2**22,
                                            subprotocols=["binary"], ping_interval=None)
    except Exception as e:
        log.warning("connect funasr failed: %s", e)
        await ws.send_json({"error": "语音识别服务暂时不可用"})
        await ws.close(code=1011)
        return

    sent = 0

    async def client_to_upstream():
        nonlocal sent
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                sent += len(msg["bytes"])
                if sent > MAX_BYTES:
                    await upstream.send(json.dumps({"is_speaking": False}))
                    return
                await upstream.send(msg["bytes"])
            elif msg.get("text") is not None:
                await upstream.send(msg["text"])

    async def upstream_to_client():
        async for data in upstream:
            if isinstance(data, bytes):
                continue
            await ws.send_text(data)

    tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
    try:
        # 任一方向结束：浏览器断开 / 上游关闭。浏览器说完后还要等上游把最终结果发完，所以先等上游方向
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if tasks[0] in done and not tasks[1].done():
            try:
                await asyncio.wait_for(tasks[1], timeout=6)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await upstream.close()
        try:
            await ws.close()
        except Exception:
            pass
