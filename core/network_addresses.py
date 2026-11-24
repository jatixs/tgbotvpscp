"""Validated host addresses for dual-stack monitoring, without network lookups."""
import ipaddress
import logging
import socket


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
