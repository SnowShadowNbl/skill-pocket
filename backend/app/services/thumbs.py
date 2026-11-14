"""v3.3.12 封面缩略图：给小程序用的位图（小程序 <image> 不支持带动画 / 渐变引用的 SVG，原图 PNG 也太大）。

缩略图地址固定为 /media/thumb/<封面路径>.jpg（宽 640、保持比例、JPEG 质量 80，透明处铺白底）。
文件不存在时第一次访问现场生成，之后直接返回；封面换了文件名也就换了，不会拿到旧图。
"""

import io
import logging
import os
import threading
from pathlib import Path

from PIL import Image

from ..config import settings

log = logging.getLogger(__name__)

WIDTH = 640
QUALITY = 80
_lock = threading.Lock()


def thumb_url(cover_path: str | None) -> str | None:
    return f"/media/thumb/{cover_path}.jpg" if cover_path else None


def _source(rel: str) -> Path | None:
    """缩略图相对路径（covers/xx.svg.jpg）→ 原封面文件；路径不合法或原图不存在时返回 None。"""
    if not rel.endswith(".jpg") or not rel.startswith("covers/"):
        return None
    root = settings.media_dir.resolve()
    src = (root / rel[:-4]).resolve()
    if root not in src.parents or not src.is_file():
        return None
    return src


def _render(src: Path) -> bytes:
    if src.suffix.lower() == ".svg":
        import resvg_py
        png = bytes(resvg_py.svg_to_bytes(svg_path=str(src), width=WIDTH))
        im = Image.open(io.BytesIO(png))
    else:
        im = Image.open(src)
        im.load()
        if im.width > WIDTH:
            im = im.resize((WIDTH, max(1, round(im.height * WIDTH / im.width))), Image.LANCZOS)
    im = im.convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.getchannel("A"))
    buf = io.BytesIO()
    bg.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


def ensure(rel: str) -> Path | None:
    """返回缩略图文件（需要时生成）；原图不存在或渲染失败返回 None。"""
    src = _source(rel)
    if src is None:
        return None
    dst = settings.media_dir / "thumb" / rel
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    with _lock:
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        try:
            data = _render(src)
        except Exception:  # noqa: BLE001 —— 坏图 / 渲染器异常：不出缩略图，小程序显示占位
            log.warning("thumb render failed: %s", rel, exc_info=True)
            return None
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dst)
    return dst


def backfill() -> dict:
    """给已有封面一次性生成缩略图（已有的跳过）。"""
    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import Item

    with SessionLocal() as db:
        paths = {p for p in db.scalars(select(Item.cover_path).where(Item.cover_path != "")) if p}
    ok = fail = 0
    for p in sorted(paths):
        if ensure(f"{p}.jpg"):
            ok += 1
        else:
            fail += 1
    return {"total": len(paths), "ok": ok, "failed": fail}
