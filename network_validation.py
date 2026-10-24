import ipaddress
import re
import socket


def parse_public_ip(value: str):
    try:
        address = ipaddress.ip_address(value.strip())
    except (AttributeError, ValueError):
        return None
    return address if address.is_global else None


def is_valid_network_host(host):
    """Accept only an IP address or DNS hostname before using remote list data in CLI args."""
    if not isinstance(host, str) or not host or len(host) > 253 or host.startswith("-"):
        return False

    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        normalized_host = host[:-1] if host.endswith(".") else host
        labels = normalized_host.split(".")
        return bool(labels) and all(
            len(label) <= 63
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
            for label in labels
        )


def resolve_public_host(host):
    if not is_valid_network_host(host):
        return None

    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError:
            return None
        addresses = set()
        for result in results:
            try:
                addresses.add(ipaddress.ip_address(result[4][0]))
            except ValueError:
                return None

    if not addresses or any(not address.is_global for address in addresses):
        return None
    return str(sorted(addresses, key=lambda address: (address.version, int(address)))[0])


def is_valid_iperf_server(server):
    if not isinstance(server, dict) or not is_valid_network_host(server.get("IP/HOST")):
        return False
    port = server.get("PORT")
    if isinstance(port, bool):
        return False
    if not isinstance(port, int) and (
        not isinstance(port, str) or not port.isdecimal()
    ):
        return False
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        return False
    return 1 <= port_number <= 65535
