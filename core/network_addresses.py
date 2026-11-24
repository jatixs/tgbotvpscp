"""Validated host addresses for dual-stack monitoring, and asynchronous reverse DNS."""
import asyncio
import ipaddress
import logging
import socket
import time

from network_validation import parse_public_ip


def normalize_address(value, version):
    try:
        address = ipaddress.ip_address(str(value or "").split("%", 1)[0])
    except ValueError:
        return ""
    if address.version != version or address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
        return ""
    return str(address)


def collect_ipv6_addresses():
    import psutil
    addresses = []
    try:
        for interface in psutil.net_if_addrs().values():
            for info in interface:
                if info.family != socket.AF_INET6:
                    continue
                value = normalize_address(info.address, 6)
                if value and ipaddress.ip_address(value).is_global:
                    addresses.append(value)
    except (OSError, RuntimeError) as error:
        logging.debug("Could not enumerate IPv6 addresses: %s", error)
    return list(dict.fromkeys(addresses))


def node_ip_addresses(node):
    stats = node.get("stats") or {}
    result = {}
    for version in (4, 6):
        candidates = (stats.get(f"ipv{version}"), stats.get("external_ip") if version == 4 else None, node.get("ip"))
        result[f"ipv{version}"] = next((ip for value in candidates if (ip := normalize_address(value, version))), "")
    return result


_PTR_CACHE: dict[str, tuple[float, str]] = {}


async def get_reverse_ptr(ip: str) -> str:
    """Resolve a public IP PTR with a bounded cache and timeout."""
    address = parse_public_ip(ip)
    if address is None or address.is_multicast:
        return ""
    key = str(address)
    cached = _PTR_CACHE.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        hostname, _, _ = await asyncio.wait_for(
            asyncio.to_thread(socket.gethostbyaddr, key), timeout=3.0
        )
        result = hostname.rstrip(".")
    except (ValueError, OSError, asyncio.TimeoutError) as exc:
        logging.debug("Reverse PTR lookup failed for %s: %s", key, exc)
        result = ""
    if len(_PTR_CACHE) >= 1024:
        _PTR_CACHE.pop(next(iter(_PTR_CACHE)))
    _PTR_CACHE[key] = (time.monotonic() + (900 if result else 60), result)
    return result


async def get_preferred_reverse_ptr(ipv4: str, ipv6: str) -> str:
    for value, version in ((ipv4, 4), (ipv6, 6)):
        address = parse_public_ip(value)
        if address is not None and address.version == version and not address.is_multicast:
            return await get_reverse_ptr(str(address))
    return ""
