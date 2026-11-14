"""IP → 中文地理位置（离线 ip2region 数据库，查询不经过任何第三方服务）。

数据文件 ip2region_v4.xdb / ip2region_v6.xdb 放在 data/geo/；不存在时启动后台下载（GitHub 原仓库）。
xdb 结构：256 字节头 + 256×256 的向量索引（按 IP 前两个字节分段，每项 8 字节：段起止指针）
       + 二分查找的段索引（起始 IP、结束 IP、地区数据长度 u16、地区数据指针 u32）。
"""

import ipaddress
import json
import logging
import struct
import threading
from functools import lru_cache

import httpx

from ..config import settings

log = logging.getLogger(__name__)

GEO_DIR = settings.media_dir.parent / "geo"
# 依次尝试：jsDelivr（国内较快，单文件上限 20MB，v6 超限会失败）→ GitHub 原地址
SOURCES = {
    v: [f"https://cdn.jsdelivr.net/gh/lionsoul2014/ip2region@master/data/ip2region_v{v}.xdb",
        f"https://raw.githubusercontent.com/lionsoul2014/ip2region/master/data/ip2region_v{v}.xdb"]
    for v in (4, 6)
}
HEADER, VECTOR_COLS, VECTOR_SIZE = 256, 256, 8

_lock = threading.Lock()
_downloading = False

# 境外地名的中文译名（AI 翻译后缓存在 data/geo/zh.json；翻译完成前先显示原文）
ZH_FILE = GEO_DIR / "zh.json"
_zh: dict[str, str] | None = None
_zh_pending: set[str] = set()
_zh_timer: threading.Timer | None = None


class _Xdb:
    def __init__(self, buf: bytes, ip_len: int):
        self.buf, self.ip_len = buf, ip_len
        self.seg = ip_len * 2 + 6
        # IPv4 的段索引里 IP 是小端 uint32（与旧版格式兼容）；IPv6 按大端字节序比较
        self.little = ip_len == 4

    def _ip_at(self, off: int) -> int:
        b = self.buf[off:off + self.ip_len]
        return int.from_bytes(b, "little" if self.little else "big")

    def search(self, ip_bytes: bytes) -> str:
        il0, il1 = ip_bytes[0], ip_bytes[1]
        vi = HEADER + (il0 * VECTOR_COLS + il1) * VECTOR_SIZE
        s_ptr, e_ptr = struct.unpack_from("<II", self.buf, vi)
        target = int.from_bytes(ip_bytes, "big")
        lo, hi = 0, (e_ptr - s_ptr) // self.seg
        while lo <= hi:
            mid = (lo + hi) // 2
            p = s_ptr + mid * self.seg
            sip, eip = self._ip_at(p), self._ip_at(p + self.ip_len)
            if target < sip:
                hi = mid - 1
            elif target > eip:
                lo = mid + 1
            else:
                dlen, dptr = struct.unpack_from("<HI", self.buf, p + self.ip_len * 2)
                return self.buf[dptr:dptr + dlen].decode("utf-8", "replace")
        return ""


_searchers: dict[int, _Xdb] = {}


def _load(version: int) -> _Xdb | None:
    if version in _searchers:
        return _searchers[version]
    path = GEO_DIR / f"ip2region_v{version}.xdb"
    if not path.exists():
        return None
    with _lock:
        if version not in _searchers:
            _searchers[version] = _Xdb(path.read_bytes(), 4 if version == 4 else 16)
    return _searchers[version]


def ensure_data() -> None:
    """数据文件不存在时后台下载（只下一次）。"""
    global _downloading
    missing = [v for v in SOURCES if not (GEO_DIR / f"ip2region_v{v}.xdb").exists()]
    if not missing or _downloading or not settings.geo_download:
        return
    _downloading = True

    def run():
        global _downloading
        GEO_DIR.mkdir(parents=True, exist_ok=True)
        for v in missing:
            tmp = GEO_DIR / f"ip2region_v{v}.xdb.part"
            for url in SOURCES[v]:
                try:
                    with httpx.stream("GET", url, timeout=httpx.Timeout(30, read=120), follow_redirects=True) as r:
                        r.raise_for_status()
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_bytes(1 << 20):
                                f.write(chunk)
                    if tmp.stat().st_size < 1_000_000:
                        raise ValueError("文件太小，可能下载失败")
                    tmp.replace(GEO_DIR / f"ip2region_v{v}.xdb")
                    log.info("ip2region v%s 下载完成（%s）", v, url)
                    break
                except Exception as e:
                    log.warning("ip2region v%s 从 %s 下载失败：%s", v, url, e)
                    tmp.unlink(missing_ok=True)
        _downloading = False

    threading.Thread(target=run, daemon=True, name="geo-download").start()


def _pretty(region: str) -> str:
    """「中国|0|广东省|深圳市|电信」或「中国|广东省|深圳市|电信|CN」→「中国 广东省 深圳市 电信」。"""
    parts = []
    for p in region.split("|"):
        p = p.strip()
        if not p or p == "0" or (p.isascii() and p.isalpha() and len(p) <= 3 and p.isupper()):
            continue
        if parts and p == parts[-1]:
            continue  # 直辖市：「北京市|北京市」只留一个
        parts.append(p)
    return " ".join(parts)


def _zh_map() -> dict[str, str]:
    global _zh
    if _zh is None:
        try:
            _zh = json.loads(ZH_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _zh = {}
    return _zh


def _translate_pending() -> None:
    global _zh_timer
    from . import judge

    with _lock:
        todo = sorted(_zh_pending)[:60]
        _zh_timer = None
    if not todo:
        return
    try:
        got = judge.translate_places(todo)
    except judge.JudgeUnavailable as e:
        log.info("境外地名翻译暂不可用：%s", e)
        got = {}
    with _lock:
        zh = _zh_map()
        zh.update(got)
        _zh_pending.difference_update(todo)
        try:
            GEO_DIR.mkdir(parents=True, exist_ok=True)
            ZH_FILE.write_text(json.dumps(zh, ensure_ascii=False, indent=0), encoding="utf-8")
        except OSError:
            log.warning("保存地名译名失败")
        more = bool(_zh_pending - set(got))
    _search.cache_clear()
    if more and got:
        _schedule_translate()


def _schedule_translate() -> None:
    """攒一小批再翻译（5 秒内出现的境外地名一次调用处理）。"""
    global _zh_timer
    if _zh_timer is None:
        _zh_timer = threading.Timer(5, _translate_pending)
        _zh_timer.daemon = True
        _zh_timer.start()


def _localize(region: str) -> str:
    if not region or not any(c.isascii() and c.isalpha() for c in region.split("|")[0]):
        return region
    key = "|".join(p for p in region.split("|") if p and p != "0" and not (p.isascii() and p.isalpha() and len(p) <= 3 and p.isupper()))
    zh = _zh_map().get(key)
    if zh:
        return zh
    with _lock:
        if key not in _zh_pending:
            _zh_pending.add(key)
            _schedule_translate()
    return region


@lru_cache(maxsize=20000)
def _search(version: int, packed: bytes) -> str:
    return _pretty(_localize(_searchers[version].search(packed)))


def lookup(ip: str) -> str:
    """返回中文归属地，查不到返回空字符串。"""
    if not ip:
        return ""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return ""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if addr.is_loopback:
        return "本机"
    if addr.is_private or addr.is_link_local:
        return "局域网"
    db = _load(addr.version)
    if db is None:
        ensure_data()
        return ""
    try:
        return _search(addr.version, addr.packed)
    except Exception:
        log.exception("ip2region lookup %s failed", ip)
        return ""
