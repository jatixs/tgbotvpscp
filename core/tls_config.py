"""Pure helpers for validating public TLS endpoints and building Certbot argv."""
from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import re
import sys
from urllib.parse import urlsplit


def normalize_identifier(value: str) -> tuple[str, str]:
    candidate = str(value or "").strip().rstrip(".")
    if not candidate or any(char.isspace() for char in candidate):
        raise ValueError("A public IPv4 address or DNS name is required")

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        address = None

    if address is not None:
        if not isinstance(address, ipaddress.IPv4Address) or not address.is_global:
            raise ValueError("Only globally routable IPv4 addresses are supported")
        return "ip", str(address)

    try:
        hostname = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Invalid DNS name") from exc

    if len(hostname) > 253 or not hostname:
        raise ValueError("Invalid DNS name length")
    labels = hostname.split(".")
    if any(
        not label
        or len(label) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("Invalid DNS name")
    if (
        len(labels) < 2
        or hostname in {"localhost", "local", "internal"}
        or hostname.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example"))
        or all(label.isdigit() for label in labels)
    ):
        raise ValueError("A public DNS name is required")
    return "domain", hostname


def public_https_url(identifier: str, port: int = 443) -> str:
    kind, host = normalize_identifier(identifier)
    if not 1 <= int(port) <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    port = int(port)
    if port == 80:
        raise ValueError("HTTPS cannot use port 80 because ACME HTTP-01 needs it")
    port_suffix = "" if port == 443 else f":{port}"
    return f"https://{host}{port_suffix}"


def parse_public_https_url(value: str) -> tuple[str, int, str, str]:
    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("Invalid HTTPS URL") from exc

    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected an HTTPS origin without path, query, or credentials")

    kind, host = normalize_identifier(parsed.hostname)
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if port == 80:
        raise ValueError("HTTPS cannot use port 80 because ACME HTTP-01 needs it")
    cert_name = host if kind == "domain" else f"tgbot-ip-{host.replace('.', '-')}"
    return kind, host, port, cert_name


def upgrade_legacy_http_url(http_url: str, port: int = 443) -> str:
    """Convert a valid legacy HTTP origin to HTTPS without changing its host."""
    try:
        parsed = urlsplit(str(http_url or "").strip())
        parsed.port
    except ValueError as exc:
        raise ValueError("Invalid legacy agent URL") from exc
    if (
        parsed.scheme.lower() != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected a legacy HTTP origin")
    kind, host = normalize_identifier(parsed.hostname)
    if parsed.path not in {"", "/"}:
        raise ValueError("Legacy agent URL must not contain a path")
    return public_https_url(host, port)


def build_certbot_args(
    identifier: str,
    email: str = "",
    *,
    certbot_binary: str = "certbot",
    webroot: str = "/var/www/tgbot-acme",
) -> list[str]:
    kind, host = normalize_identifier(identifier)
    cert_name = host if kind == "domain" else f"tgbot-ip-{host.replace('.', '-')}"
    arguments = [
        certbot_binary,
        "certonly",
        "--webroot",
        "--webroot-path",
        webroot,
        "--non-interactive",
        "--agree-tos",
        "--keep-until-expiring",
        "--cert-name",
        cert_name,
    ]
    if email:
        arguments.extend(["--email", email])
    else:
        arguments.append("--register-unsafely-without-email")

    if kind == "ip":
        arguments.extend(["--ip-address", host, "--required-profile", "shortlived"])
    else:
        arguments.extend(["--domain", host])
    return arguments


def find_nginx_certificates(config_dump: str, host: str) -> list[tuple[str, str]]:
    """Return (certificate, key) pairs from server blocks whose server_name matches host."""
    text = re.sub(r"(?m)#.*$", "", config_dump)
    tokens = re.findall(r"\"[^\"]*\"|'[^']*'|[{};]|[^\s{};\"']+", text)

    servers: list[list[list[str]]] = []
    stack: list[tuple[str, list[list[str]]]] = []
    words: list[str] = []
    for token in tokens:
        if token == "{":
            stack.append((words[0] if words else "", []))
            words = []
        elif token == "}":
            if stack:
                name, directives = stack.pop()
                if name == "server":
                    servers.append(directives)
            words = []
        elif token == ";":
            if stack and words:
                stack[-1][1].append(words)
            words = []
        else:
            words.append(token.strip("\"'"))

    host = host.lower()
    pairs: list[tuple[str, str]] = []
    for directives in servers:
        names = [arg.lower() for d in directives if d[0] == "server_name" for arg in d[1:]]
        matched = any(
            name == host or ("*" in name and fnmatch.fnmatchcase(host, name)) for name in names
        )
        if not matched:
            continue
        certs = [d[1] for d in directives if d[0] == "ssl_certificate" and len(d) > 1]
        keys = [d[1] for d in directives if d[0] == "ssl_certificate_key" and len(d) > 1]
        for cert, key in zip(certs, keys):
            if "$" in cert or "$" in key:
                continue
            pair = tuple(path if path.startswith("/") else f"/etc/nginx/{path}" for path in (cert, key))
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    parse_command = commands.add_parser("parse-url")
    parse_command.add_argument("url")
    build_command = commands.add_parser("build-url")
    build_command.add_argument("identifier")
    build_command.add_argument("port", nargs="?", type=int, default=443)
    upgrade_command = commands.add_parser("upgrade-url")
    upgrade_command.add_argument("url")
    upgrade_command.add_argument("port", nargs="?", type=int, default=443)
    certbot_command = commands.add_parser("certbot-args")
    certbot_command.add_argument("identifier")
    certbot_command.add_argument("email")
    certbot_command.add_argument("certbot_binary")
    certbot_command.add_argument("webroot")
    nginx_command = commands.add_parser("find-nginx-cert")
    nginx_command.add_argument("host")
    args = parser.parse_args(argv)

    try:
        if args.command == "parse-url":
            kind, host, port, cert_name = parse_public_https_url(args.url)
            output = [kind, host, str(port), cert_name]
            sys.stdout.write("\n".join(output) + "\n")
        elif args.command == "build-url":
            sys.stdout.write(public_https_url(args.identifier, args.port) + "\n")
        elif args.command == "upgrade-url":
            sys.stdout.write(upgrade_legacy_http_url(args.url, args.port) + "\n")
        elif args.command == "find-nginx-cert":
            for cert, key in find_nginx_certificates(sys.stdin.read(), args.host):
                sys.stdout.write(f"{cert}\t{key}\n")
        else:
            output = build_certbot_args(
                args.identifier,
                args.email,
                certbot_binary=args.certbot_binary,
                webroot=args.webroot,
            )
            sys.stdout.buffer.write(b"\0".join(item.encode("utf-8") for item in output) + b"\0")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())