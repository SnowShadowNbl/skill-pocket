"""本地开发用的 FunASR 2pass 模拟服务（协议与 funasr-runtime-sdk-online 一致，不做真识别）。

    python scripts/mock_asr.py            # 监听 ws://127.0.0.1:10095
    .env 里设置 FUNASR_WS_URL=ws://127.0.0.1:10095

每收到约 0.6 秒音频回一段 2pass-online 增量文字；收到 is_speaking=false 后回 2pass-offline 整句（带标点）。
"""

import asyncio
import json

import websockets

PHRASE = "这个技能用起来挺顺手的，安装两分钟就跑通了，中文识别也很准，推荐给团队。"
BYTES_PER_STEP = 16000 * 2 * 6 // 10  # 0.6 秒 16k16bit 音频


async def handle(ws):
    received, pos, sentence = 0, 0, ""
    async for msg in ws:
        if isinstance(msg, bytes):
            received += len(msg)
            while received >= BYTES_PER_STEP and pos < len(PHRASE):
                received -= BYTES_PER_STEP
                piece = PHRASE[pos:pos + 3].replace("，", "").replace("。", "")
                pos += 3
                sentence += piece
                await ws.send(json.dumps({"mode": "2pass-online", "text": piece, "wav_name": "h5", "is_final": False}, ensure_ascii=False))
            continue
        cfg = json.loads(msg)
        if cfg.get("is_speaking") is False:
            await asyncio.sleep(0.4)  # 模拟离线模型修正耗时
            await ws.send(json.dumps({"mode": "2pass-offline", "text": PHRASE[:pos] if pos else "", "wav_name": "h5", "is_final": True}, ensure_ascii=False))
            await ws.close()
            return


async def main():
    async with websockets.serve(handle, "127.0.0.1", 10095, max_size=2**22):
        print("mock FunASR listening on ws://127.0.0.1:10095")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
