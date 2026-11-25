#!/usr/bin/env python3
"""Finalize HTTPS migration from the VPS host, including Docker deployments."""
from __future__ import annotations

import asyncio
import os
import shutil
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


async def _await_exit(
    proc: asyncio.subprocess.Process,
    label: str,
    timeout: int,
    *,
    check: bool = True,
) -> int:
    try:
        returncode = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise RuntimeError(f"Command timed out: {label}") from exc
    if check and returncode:
        raise RuntimeError(f"Command failed ({returncode}): {label}")
    return returncode


async def compose_command() -> list[str]:
    search_path = "/usr/local/bin:/usr/bin:/bin:/snap/bin" if os.name == "posix" else None
    if shutil.which("docker", path=search_path):
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await _await_exit(proc, "docker compose version", 10, check=False) == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose", path=search_path):
        proc = await asyncio.create_subprocess_exec(
            "docker-compose",
            "version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await _await_exit(proc, "docker-compose version", 10, check=False) == 0:
            return ["docker-compose"]
    raise RuntimeError("Docker Compose is not installed")


async def _run_deploy_action(
    action: str,
    deploy_mode: str,
    compose: list[str] | None,
    profile: str,
    container: str,
) -> None:
    if deploy_mode != "docker":
        if action == "restart":
            proc = await asyncio.create_subprocess_exec("systemctl", "restart", "tg-bot", cwd=INSTALL_DIR)
            await _await_exit(proc, "systemctl restart tg-bot", 180)
        else:
            proc = await asyncio.create_subprocess_exec("/usr/local/bin/tgcp-bot", "tls", "check", cwd=INSTALL_DIR)
            await _await_exit(proc, "/usr/local/bin/tgcp-bot tls check", 180)
        return

    use_v2 = compose == ["docker", "compose"]
    if action == "restart":
        if use_v2:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "--profile", profile, "restart", container,
                cwd=INSTALL_DIR,
            )
            label = f"docker compose --profile {profile} restart {container}"
        else:
            proc = await asyncio.create_subprocess_exec(
                "docker-compose", "--profile", profile, "restart", container,
                cwd=INSTALL_DIR,
            )
            label = f"docker-compose --profile {profile} restart {container}"
    else:
        if use_v2:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "--profile", profile, "exec", "-T", container, "python", "manage.py", "tls", "check",
                cwd=INSTALL_DIR,
            )
            label = f"docker compose --profile {profile} exec -T {container} python manage.py tls check"
        else:
            proc = await asyncio.create_subprocess_exec(
                "docker-compose", "--profile", profile, "exec", "-T", container, "python", "manage.py", "tls", "check",
                cwd=INSTALL_DIR,
            )
            label = f"docker-compose --profile {profile} exec -T {container} python manage.py tls check"
    await _await_exit(proc, label, 180)


async def _main_async() -> int:
    try:
        _lines, config = read_env()
        deploy_mode = config.get("DEPLOY_MODE", "systemd")
        profile = config.get("COMPOSE_PROFILES") or config.get("INSTALL_MODE", "secure")
        if deploy_mode == "docker" and profile not in {"secure", "root"}:
            raise RuntimeError(f"Unsupported Docker Compose profile: {profile!r}")
        compose = await compose_command() if deploy_mode == "docker" else None
        container = f"tg-bot-{profile}"

        if len(sys.argv) > 1 and sys.argv[1] == "clear-initial-password":
            init_pwd_var = "TG_WEB_INITIAL_" + "PASSWORD"
            update_env(ENV_FILE, {init_pwd_var: ""})
            await _run_deploy_action("restart", deploy_mode, compose, profile, container)
            print("Initial plaintext password removed; service restarted.")
            return 0

        if not config.get("WEB_PUBLIC_URL", "").startswith("https://"):
            raise RuntimeError("WEB_PUBLIC_URL must be configured with HTTPS")
        await _run_deploy_action("tls-check", deploy_mode, compose, profile, container)

        updates = {"LEGACY_NODE_BRIDGE": "false"}
        if deploy_mode != "docker" and config.get("WEB_TLS_MODE") == "managed":
            updates["WEB_SERVER_HOST"] = "127.0.0.1"
        update_env(ENV_FILE, updates)

        await _run_deploy_action("restart", deploy_mode, compose, profile, container)
        print("HTTPS migration finalized; legacy bridge disabled.")
        return 0
    except Exception as exc:
        print(f"HTTPS migration was not finalized: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
