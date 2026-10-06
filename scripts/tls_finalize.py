#!/usr/bin/env python3
"""Finalize HTTPS migration from the VPS host, including Docker deployments."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALL_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = INSTALL_DIR / ".env"


def read_env(path: Path = ENV_FILE) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def update_env(path: Path, values: dict[str, str]) -> None:
    lines, _current = read_env(path)
    remaining = dict(values)
    updated: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped else ""
        if key in values:
            if key not in seen:
                updated.append(f'{key}="{values[key]}"')
                seen.add(key)
                remaining.pop(key, None)
        else:
            updated.append(line)
    for key, value in remaining.items():
        updated.append(f'{key}="{value}"')

    fd, temporary = tempfile.mkstemp(prefix=".env.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write("\n".join(updated) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def compose_command() -> list[str]:
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run([docker, "compose", "version"], capture_output=True, timeout=10)
        if result.returncode == 0:
            return [docker, "compose"]
    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        result = subprocess.run([docker_compose, "version"], capture_output=True, timeout=10)
        if result.returncode == 0:
            return [docker_compose]
    raise RuntimeError("Docker Compose is not installed")


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=INSTALL_DIR, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")


def main() -> int:
    try:
        _lines, config = read_env()
        deploy_mode = config.get("DEPLOY_MODE", "systemd")
        profile = config.get("COMPOSE_PROFILES") or config.get("INSTALL_MODE", "secure")
        compose = compose_command() if deploy_mode == "docker" else None
        container = f"tg-bot-{profile}"

        if len(sys.argv) > 1 and sys.argv[1] == "clear-initial-password":
            update_env(ENV_FILE, {"TG_WEB_INITIAL_PASSWORD": ""})
            if deploy_mode == "docker":
                run([*compose, "--profile", profile, "restart", container])
            else:
                run(["systemctl", "restart", "tg-bot"])
            print("Initial plaintext password removed; service restarted.")
            return 0

        if not config.get("WEB_PUBLIC_URL", "").startswith("https://"):
            raise RuntimeError("WEB_PUBLIC_URL must be configured with HTTPS")
        if deploy_mode == "docker":
            run([*compose, "--profile", profile, "exec", "-T", container, "python", "manage.py", "tls", "check"])
        else:
            run(["/usr/local/bin/tgcp-bot", "tls", "check"])

        updates = {"LEGACY_NODE_BRIDGE": "false"}
        if deploy_mode != "docker" and config.get("WEB_TLS_MODE") == "managed":
            updates["WEB_SERVER_HOST"] = "127.0.0.1"
        update_env(ENV_FILE, updates)

        if deploy_mode == "docker":
            run([*compose, "--profile", profile, "restart", container])
        else:
            run(["systemctl", "restart", "tg-bot"])
        print("HTTPS migration finalized; legacy bridge disabled.")
        return 0
    except Exception as exc:
        print(f"HTTPS migration was not finalized: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
