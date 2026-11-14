"""v3.3.13 AI SVG 封面的动图版本（小程序详情页用）：把 SVG 里的 SMIL 动画按时间逐帧算出来，渲染成循环播放的动图 WebP。

小程序 <image> 不会播放 SVG 动画，这里自己求值 <animate> / <animateTransform>（values / from-to、keyTimes、
calcMode linear / discrete / spline、begin 偏移、additive），每帧把属性写回元素后交给 resvg 渲染。
地址固定为 /media/anim/<封面路径>.webp；只有带动画的 .svg 封面才有。
v3.3.14 起由后台单线程队列生成：封面一变就排队、启动时回填、请求到了还没生成就插到队首；请求本身从不等待渲染。
"""

import io
import logging
import os
import re
import threading
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

from PIL import Image

from ..config import settings

log = logging.getLogger(__name__)

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

WIDTH = 640
MAX_PERIOD = 8.0
MAX_BYTES = 300 * 1024
# 依次尝试：(帧率, 质量, 宽度)，体积超过 300KB 就往下退
PLANS = ((15, 72, 640), (12, 62, 640), (10, 52, 560), (8, 45, 480))
WARMUP = 120.0  # 从「已经播放了一会儿」的稳定状态开始取帧，begin 延迟的动画也都在动
_lock = threading.Lock()
_NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?", re.I)


def anim_url(cover_path: str | None) -> str | None:
    return f"/media/anim/{cover_path}.webp" if cover_path and cover_path.endswith(".svg") else None


# ---------------------------------------------------------------- SMIL 求值

def _clock(v: str | None) -> float:
    """'1.5s' / '300ms' / '0:00:02' → 秒；事件触发之类认不出的当作 0。"""
    if not v:
        return 0.0
    v = v.strip().split(";")[0].strip()
    try:
        if v.endswith("ms"):
            return float(v[:-2]) / 1000
        if v.endswith("s"):
            return float(v[:-1])
        if v.endswith("min"):
            return float(v[:-3]) * 60
        if ":" in v:
            parts = [float(p) for p in v.split(":")]
            return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
        return float(v)
    except ValueError:
        return 0.0


def _bezier(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(30):
        t = (lo + hi) / 2
        bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3
        lo, hi = (t, hi) if bx < x else (lo, t)
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3


def _lerp_str(a: str, b: str, f: float) -> str:
    """按 a 的格式把其中每个数字插值到 b 对应的数字（'0 0' → '10 5'、'12px' 之类都行）。"""
    na, nb = _NUM.findall(a), _NUM.findall(b)
    if len(na) != len(nb) or not na:
        return a if f < 0.5 else b
    it = iter(float(x) + (float(y) - float(x)) * f for x, y in zip(na, nb))
    return _NUM.sub(lambda _m: f"{next(it):.4g}", a)


class _Anim:
    def __init__(self, el: ET.Element, parent: ET.Element):
        g = el.get
        self.parent = parent
        self.is_transform = el.tag.endswith("animateTransform")
        self.attr = g("attributeName", "")
        self.ttype = g("type", "translate")
        self.dur = _clock(g("dur")) or 0.0
        self.begin = _clock(g("begin"))
        rc = g("repeatCount", "")
        self.repeat = float("inf") if rc == "indefinite" or g("repeatDur") == "indefinite" else (float(rc) if rc else 1.0)
        self.freeze = g("fill") == "freeze"
        self.additive = g("additive") == "sum"
        if g("values"):
            self.values = [v.strip() for v in g("values").split(";") if v.strip()]
        else:
            self.values = [v for v in (g("from"), g("to")) if v is not None]
        self.calc = g("calcMode", "linear")
        kt = g("keyTimes")
        self.times = [float(x) for x in kt.split(";")] if kt else None
        ks = g("keySplines")
        self.splines = [[float(n) for n in _NUM.findall(s)] for s in ks.split(";")] if ks else None
        if self.times and len(self.times) != len(self.values):
            self.times = None

    def valid(self) -> bool:
        return self.dur > 0 and len(self.values) >= 1 and bool(self.attr)

    def value_at(self, t: float) -> str | None:
        lt = t - self.begin
        if lt < 0:
            return None
        if lt >= self.dur * self.repeat:
            return self.values[-1] if self.freeze else None
        p = (lt % self.dur) / self.dur
        vals = self.values
        if len(vals) == 1:
            return vals[0]
        if self.calc == "discrete":
            times = self.times or [i / len(vals) for i in range(len(vals))]
            idx = max(i for i, k in enumerate(times) if k <= p + 1e-9)
            return vals[idx]
        times = self.times or [i / (len(vals) - 1) for i in range(len(vals))]
        for i in range(len(vals) - 1):
            if p <= times[i + 1] or i == len(vals) - 2:
                span = times[i + 1] - times[i]
                f = 0.0 if span <= 0 else min(1.0, max(0.0, (p - times[i]) / span))
                if self.calc == "spline" and self.splines and i < len(self.splines) and len(self.splines[i]) == 4:
                    f = _bezier(f, *self.splines[i])
                return _lerp_str(vals[i], vals[i + 1], f)
        return vals[-1]


class Scene:
    """解析一次 SVG，之后按时间点产出静态 SVG 文本。"""

    def __init__(self, svg_text: str):
        self.root = ET.fromstring(svg_text)
        parents = {c: p for p in self.root.iter() for c in p}
        self.anims: list[_Anim] = []
        for el in list(self.root.iter()):
            tag = el.tag.split("}")[-1]
            if tag in ("animate", "animateTransform", "set", "animateMotion"):
                parent = parents.get(el)
                if parent is None:
                    continue
                parent.remove(el)
                if tag in ("animate", "animateTransform"):
                    a = _Anim(el, parent)
                    if a.valid():
                        self.anims.append(a)
        self.base = {id(a.parent): dict(a.parent.attrib) for a in self.anims}

    def period(self) -> float:
        """选一个循环周期：在 3–8 秒里找让所有无限循环动画尽量「刚好转完整圈」的长度。"""
        durs = sorted({round(a.dur, 3) for a in self.anims if a.repeat == float("inf")})
        if not durs:
            return min(MAX_PERIOD, max((a.begin + a.dur * min(a.repeat, 3) for a in self.anims), default=4.0))
        best, best_err = MAX_PERIOD, None
        for i in range(30, int(MAX_PERIOD * 10) + 1, 1):
            T = i / 10
            # 循环接缝处每个动画「跳」了多少秒：T 不是 d 的整数倍时，跳 min(余数, d-余数)
            err = sum(min((T / d) % 1, 1 - (T / d) % 1) * d for d in durs if d > 0)
            err += 0.001 * T  # 同样合适时取短的
            if best_err is None or err < best_err - 1e-9:
                best, best_err = T, err
        return best

    def frame(self, t: float) -> str:
        for a in self.anims:  # 先复原
            a.parent.attrib.clear()
            a.parent.attrib.update(self.base[id(a.parent)])
        transforms: dict[int, list[str]] = {}
        for a in self.anims:
            v = a.value_at(t)
            if v is None:
                continue
            if a.is_transform:
                tr = f"{a.ttype}({v.replace(',', ' ')})"
                key = id(a.parent)
                if a.additive and key in transforms:
                    transforms[key].append(tr)
                elif a.additive:
                    base = self.base[key].get("transform")
                    transforms[key] = ([base] if base else []) + [tr]
                else:
                    transforms[key] = [tr]
                a.parent.set("transform", " ".join(transforms[key]))
            else:
                a.parent.set(a.attr, v)
                style = a.parent.get("style")
                if style and a.attr in style:  # 样式里同名属性优先级更高，去掉以免盖住动画值
                    a.parent.set("style", ";".join(s for s in style.split(";") if s.split(":")[0].strip() != a.attr))
        return ET.tostring(self.root, encoding="unicode")


# ---------------------------------------------------------------- 渲染

def render(svg_text: str) -> bytes | None:
    """返回动图 WebP；没有动画返回 None。"""
    import resvg_py

    scene = Scene(svg_text)
    if not scene.anims:
        return None
    T = scene.period()
    out = b""
    for fps, quality, width in PLANS:
        n = max(2, round(T * fps))
        frames = []
        for i in range(n):
            png = bytes(resvg_py.svg_to_bytes(svg_string=scene.frame(WARMUP + T * i / n), width=width))
            im = Image.open(io.BytesIO(png)).convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            frames.append(bg)
        buf = io.BytesIO()
        frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=round(1000 * T / n), loop=0,
                       quality=quality, method=4, minimize_size=True)
        out = buf.getvalue()
        if len(out) <= MAX_BYTES:
            break
    return out


def _source(rel: str) -> Path | None:
    if not rel.endswith(".svg.webp") or not rel.startswith("covers/"):
        return None
    root = settings.media_dir.resolve()
    src = (root / rel[:-5]).resolve()
    if root not in src.parents or not src.is_file():
        return None
    return src


def ensure(rel: str) -> Path | None:
    """返回动图文件（需要时生成）；不是 SVG、没有动画或渲染失败返回 None。"""
    src = _source(rel)
    if src is None:
        return None
    dst = settings.media_dir / "anim" / rel
    miss = dst.with_suffix(dst.suffix + ".none")  # 记下「没有动画 / 渲染失败」，不用每次重算
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    if miss.is_file() and miss.stat().st_mtime >= src.stat().st_mtime:
        return None
    with _lock:  # 一次只渲染一张，免得把 CPU 占满
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = render(src.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.warning("anim render failed: %s", rel, exc_info=True)
            data = None
        if not data:
            miss.touch()
            return None
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dst)
    return dst


def lookup(rel: str) -> tuple[str, Path | None]:
    """v3.3.14 只查不渲染：('ok', 文件) / ('none', None) 没有动画 / ('pending', None) 已排进后台队列 / ('bad', None)。
    请求线程绝不在这里等渲染，免得大量请求排队占满线程、拖慢整个网站。"""
    src = _source(rel)
    if src is None:
        return "bad", None
    dst = settings.media_dir / "anim" / rel
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return "ok", dst
    miss = dst.with_suffix(dst.suffix + ".none")
    if miss.is_file() and miss.stat().st_mtime >= src.stat().st_mtime:
        return "none", None
    enqueue(rel[: -len(".webp")], front=True)
    return "pending", None


# ---------------------------------------------------------------- v3.3.14 后台生成队列（缩略图 + 动图）

_queue: deque[str] = deque()
_queued: set[str] = set()
_cv = threading.Condition()
_worker: threading.Thread | None = None


def enqueue(cover_path: str, front: bool = False) -> None:
    """把一张封面排进后台生成（缩略图，SVG 再加动图）。用户正在看的插到队首，回填的排队尾。"""
    global _worker
    if not cover_path or not cover_path.startswith("covers/"):
        return
    with _cv:
        if cover_path in _queued:
            if front and cover_path in _queue:
                _queue.remove(cover_path)
                _queue.appendleft(cover_path)
            return
        _queued.add(cover_path)
        if front:
            _queue.appendleft(cover_path)
        else:
            _queue.append(cover_path)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="cover-media", daemon=True)
            _worker.start()
        _cv.notify()


def _run() -> None:
    import time

    from . import thumbs

    while True:
        with _cv:
            while not _queue:
                _cv.wait()
            p = _queue.popleft()
        try:
            thumbs.ensure(f"{p}.jpg")
            if p.endswith(".svg"):
                ensure(f"{p}.webp")
        except Exception:  # noqa: BLE001
            log.warning("cover media failed: %s", p, exc_info=True)
        finally:
            with _cv:
                _queued.discard(p)
        time.sleep(0.3)  # 歇一下，不和采集、请求抢 CPU


def pending() -> int:
    with _cv:
        return len(_queue)


def backfill() -> dict:
    """已发布条目的封面全部排进后台生成（新的在前；已生成的工作线程会直接跳过）。"""
    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import Item

    with SessionLocal() as db:
        paths = list(dict.fromkeys(db.scalars(select(Item.cover_path).where(Item.status == "published", Item.cover_path != "")
                                              .order_by(Item.id.desc()))))
    for p in paths:
        enqueue(p)
    return {"queued": len(paths)}


# ---------------------------------------------------------------- v3.3.14 封面一变（AI 画好 / 上传 / 后台换图）就排队预生成

def _watch_cover() -> None:
    from sqlalchemy import event

    from ..models import Item

    @event.listens_for(Item.cover_path, "set")
    def _on_cover(_target, value, old, _initiator):  # noqa: ANN001
        if value and value != old:
            enqueue(value)


_watch_cover()
