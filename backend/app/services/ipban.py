"""IP 封禁：管理员可以禁止某个 IP 或网段访问全站。

封禁列表缓存在内存里（每分钟或改动后刷新），每个请求只做一次网段匹配，不查库。
"""

import ipaddress
import logging
import threading
import time

from sqlalchemy import select

from ..db import SessionLocal, utcnow
from ..models import IpBan

log = logging.getLogger(__name__)
REFRESH = 60

_nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
_loaded_at = 0.0
_lock = threading.Lock()


def parse(text: str) -> str:
    """「1.2.3.4」「1.2.3.0/24」「2408:8000::/32」→ 规范化的网段字符串；不合法抛 ValueError。"""
    net = ipaddress.ip_network(text.strip(), strict=False)
    if net.num_addresses > 2 ** 24 and net.version == 4 or net.version == 6 and net.prefixlen < 32:
        raise ValueError("网段太大，最多封到 IPv4 /8、IPv6 /32")
    return str(net)


def refresh() -> None:
    global _nets, _loaded_at
    now = utcnow()
    try:
        with SessionLocal() as db:
            rows = db.scalars(select(IpBan.cidr).where((IpBan.expires_at.is_(None)) | (IpBan.expires_at > now))).all()
        nets = []
        for c in rows:
            try:
                nets.append(ipaddress.ip_network(c, strict=False))
            except ValueError:
                continue
        with _lock:
            _nets, _loaded_at = nets, time.time()
    except Exception:  # 数据库还没迁移等情况：不拦截任何请求
        log.exception("load ip bans failed")
        _loaded_at = time.time()


def is_banned(ip: str) -> bool:
    if time.time() - _loaded_at > REFRESH:
        refresh()
    if not _nets:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr.version == n.version and addr in n for n in _nets)


def covers(cidr: str, ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
