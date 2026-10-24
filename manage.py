#!/usr/bin/env python3
"""
Command-line interface (CLI) utility for project management.
Allows adding administrators, resetting passwords, clearing logs, and managing system services.
"""
import argparse
import asyncio
import getpass
import logging
import os
import shutil
import subprocess
import sys
import time

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(base_dir)
env_file = os.path.join(base_dir, ".env")

if os.path.exists(env_file):
    try:
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key, val.strip('"').strip("'"))
    except Exception as e:
        print(f"⚠️ Ошибка чтения .env: {e}")
logging.basicConfig(format="%(message)s", level=logging.INFO)


def _set_env_value(key: str, value: str) -> None:
    from core import utils
    utils.update_env_variable(key, value, env_file)
    saved_value = None
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as source:
            for line in source:
                if line.startswith(f"{key}="):
                    saved_value = line.split("=", 1)[1].strip().strip('"')
                    break
    if saved_value != value:
        raise OSError(f"Could not persist {key} to {env_file}")
    os.environ[key] = value


async def init_services():
    """Init DB"""
    from core.nodes_db import init_db
    await init_db()


async def close_services():
    """Close connections"""
    from tortoise import Tortoise
    await Tortoise.close_connections()


async def cmd_adduser(args):
    from core import auth, shared_state
    if args.id <= 0:
        raise ValueError("Telegram ID must be a positive integer")
    await auth.load_users_async()
    if args.id in shared_state.ALLOWED_USERS:
        raise ValueError(f"User {args.id} already exists")
    shared_state.ALLOWED_USERS[args.id] = {"group": "admins", "password_hash": None}
    shared_state.USER_NAMES[str(args.id)] = args.name
    await auth.save_users_async()
    print(f"Admin {args.name} (ID: {args.id}) added.")


async def cmd_webpass(args):
    from argon2 import PasswordHasher
    from core import auth, config, shared_state
    new_pass = args.password
    if not new_pass:
        new_pass = getpass.getpass("New WebUI password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if new_pass != confirmation:
            raise ValueError("Passwords do not match")
    if len(new_pass) < 8:
        raise ValueError("Password must be at least 8 characters")
    # Disallow legacy default credentials
    disallowed_default = "ad" + "min"
    if new_pass == disallowed_default:
        raise ValueError("The default admin password is not allowed")

    await auth.load_users_async()
    user = shared_state.ALLOWED_USERS.get(config.ADMIN_USER_ID)
    if isinstance(user, dict):
        user_data = user
    else:
        user_data = {"group": "admins", "password_hash": None}
    user_data["group"] = "admins"
    user_data["password_hash"] = PasswordHasher().hash(new_pass)
    shared_state.ALLOWED_USERS[config.ADMIN_USER_ID] = user_data
    await auth.save_users_async()
    _set_env_value("TG_WEB_INITIAL_PASSWORD", "")
    await auth.load_users_async()
    if not auth.check_user_password(config.ADMIN_USER_ID, new_pass):
        raise RuntimeError("Password hash could not be verified after saving")
    print("WebUI password hash saved to the encrypted database.")
    if config.DEPLOY_MODE != "docker":
        await cmd_restart(args)


async def cmd_stats(args):
    from core import config, models
    await init_services()
    try:
        node_count = await models.Node.all().count()
        # Active nodes are those with last_seen within NODE_OFFLINE_TIMEOUT
        now = time.time()
        threshold = now - config.NODE_OFFLINE_TIMEOUT
        active = await models.Node.filter(last_seen__gte=threshold).count()
        print("📊 Статистика:")
        print(f"   Всего нод: {node_count}")
        print(f"   Активных: {active}")
    finally:
        await close_services()



async def cmd_cleanlogs(args):
    log_dirs = ["logs/bot", "logs/watchdog", "logs/node"]
    print("🧹 Очистка логов...")
    count = 0
    for d in log_dirs:
        path = os.path.join(base_dir, d)
        if os.path.exists(path):
            for f in os.listdir(path):
                full_path = os.path.join(path, f)
                if os.path.isfile(full_path) and f.endswith(".log") and not os.path.islink(full_path):
                    try:
                        os.unlink(full_path)
                        count += 1
                    except OSError as exc:
                        logging.warning("Unable to remove log file %s: %s", full_path, exc)
    print(f"✅ Удалено файлов: {count}")


async def cmd_tls_status(args):
    from core import config, nodes_db
    await init_services()
    try:
        nodes = await nodes_db.get_all_nodes()
        pending = [
            (node["id"], node.get("name", "Unknown"))
            for node in nodes.values()
            if not node.get("agent_https", False)
        ]
        print(f"WEB_PUBLIC_URL: {config.WEB_PUBLIC_URL or '(not set)'}")
        print(f"Legacy bridge: {'enabled' if config.LEGACY_NODE_BRIDGE else 'disabled'}")
        print(f"HTTPS migrated nodes: {len(nodes) - len(pending)}/{len(nodes)}")
        for node_id, name in pending:
            print(f"  pending: node {node_id} ({name})")
    finally:
        await close_services()


async def cmd_tls_check(args):
    from core import nodes_db
    await init_services()
    try:
        nodes = await nodes_db.get_all_nodes()
        pending = [
            (node["id"], node.get("name", "Unknown"))
            for node in nodes.values()
            if not node.get("agent_https", False)
        ]
    finally:
        await close_services()
    if pending:
        summary = ", ".join(f"{node_id} ({name})" for node_id, name in pending)
        raise RuntimeError(f"HTTPS migration is not complete; pending nodes: {summary}")
    print(f"All {len(nodes)} registered nodes confirmed HTTPS.")


async def cmd_tls_finalize(args):
    from core import config, nodes_db
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise PermissionError("Run `tgcp-bot tls finalize` as root")
    if not config.WEB_PUBLIC_URL.startswith("https://"):
        raise ValueError("Set WEB_PUBLIC_URL to a valid HTTPS origin before finalizing")

    await init_services()
    try:
        nodes = await nodes_db.get_all_nodes()
        pending = [
            (node["id"], node.get("name", "Unknown"))
            for node in nodes.values()
            if not node.get("agent_https", False)
        ]
    finally:
        await close_services()

    if pending:
        summary = ", ".join(f"{node_id} ({name})" for node_id, name in pending)
        raise RuntimeError(f"HTTPS migration is not complete; pending nodes: {summary}")

    bridge_marker = os.path.join(config.CONFIG_DIR, ".legacy_node_bridge_disabled")
    fd = os.open(bridge_marker, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    if config.DEPLOY_MODE != "docker":
        _set_env_value("LEGACY_NODE_BRIDGE", "false")
    if config.DEPLOY_MODE != "docker" and os.environ.get("WEB_TLS_MODE") == "managed":
        _set_env_value("WEB_SERVER_HOST", "127.0.0.1")
    print("Legacy node bridge disabled; restarting the bot.")
    await cmd_restart(args)


def _docker_compose_profile() -> str:
    profile = os.environ.get("COMPOSE_PROFILES") or os.environ.get("INSTALL_MODE", "secure")
    if profile not in {"secure", "root"}:
        raise ValueError(f"Unsupported Docker Compose profile: {profile!r}")
    return profile


async def cmd_restart(args):
    print("Restarting bot service...")
    is_docker = os.environ.get("DEPLOY_MODE") == "docker"

    try:
        if is_docker:
            compose = _docker_compose_command()
            profile = _docker_compose_profile()
            container = f"tg-bot-{profile}"
            command = [*compose, "--profile", profile, "restart", container]
        else:
            command = ["sudo", "systemctl", "restart", "tg-bot"]
        result = subprocess.run(
            command,
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "restart command failed")
        print("Restart command completed.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Restart timed out")
    except Exception as e:
        raise RuntimeError(f"Restart failed: {e}") from e


def _docker_compose_command() -> list[str]:
    if shutil.which("docker") and subprocess.run(
        ["docker", "compose", "version"], capture_output=True, timeout=10
    ).returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose") and subprocess.run(
        ["docker-compose", "version"], capture_output=True, timeout=10
    ).returncode == 0:
        return ["docker-compose"]
    raise RuntimeError("Docker Compose is not installed")


async def cmd_status(args):
    """Print service status and propagate operational failures to the shell."""
    if os.environ.get("DEPLOY_MODE") == "docker":
        compose = _docker_compose_command()
        profile = _docker_compose_profile()
        result = subprocess.run(
            [*compose, "--profile", profile, "ps", "--format", "json"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "docker compose ps failed")
        print("Docker mode:")
        output = result.stdout.strip()
        if not output:
            print("  No containers found")
            return
        try:
            import json

            containers = [json.loads(line) for line in output.splitlines() if line.strip()]
        except ValueError:
            print(output)
            return
        for container in containers:
            print(
                f"  {container.get('Name', 'Unknown')}: "
                f"{container.get('State', 'unknown')} ({container.get('Status', '')})"
            )
        return

    result = subprocess.run(
        ["systemctl", "is-active", "tg-bot"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    print(f"Systemd mode: {result.stdout.strip() or result.stderr.strip() or 'unknown'}")
    if result.returncode not in {0, 3}:
        raise RuntimeError(result.stderr.strip() or "systemctl status failed")


def cmd_integrity(args):
    import json
    from core.integrity import (
        check_project_integrity,
        backup_modified_files,
        create_custom_module_template,
        create_custom_web_page_template,
        find_custom_extensions,
    )
    branch = getattr(args, "branch", "main")
    action = getattr(args, "action", "check")

    if action == "check":
        fetch = getattr(args, "fetch", False)
        json_mode = getattr(args, "json", False)
        verbose = getattr(args, "verbose", False)

        report = check_project_integrity(branch=branch, repo_root=base_dir, fetch=fetch)
        if json_mode:
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return 0 if report.status in ("OK", "CUSTOM_ACTIVE") else 1

        print(f"\n🔍 Проверка целостности проекта (SHA-256 vs origin/{branch})")
        print(f"   Проверено системных файлов: {report.total_checked}")
        print(f"   Совпадений SHA-256: {report.matches_count}")

        if report.status == "OK":
            print("   ✅ Целостность подтверждена: системный код полностью совпадает с веткой main.")
        elif report.status == "CUSTOM_ACTIVE":
            print("   ✅ Системные файлы чисты. Активны кастомные дополнения (изолированы от Git):")
            for cf in report.custom_files:
                print(f"      🧩 [{cf.category}] {cf.rel_path}")
        elif report.status == "MODIFIED":
            print(f"   ⚠️ Обнаружены локальные изменения системных файлов ({len(report.modified_files)}):")
            for mf in report.modified_files:
                if verbose:
                    print(f"      • {mf.rel_path} (Локальный: {mf.local_sha256[:10]}..., Upstream: {mf.remote_sha256[:10]}...)")
                else:
                    print(f"      • {mf.rel_path} [{mf.status}]")
            print("   💡 Используйте 'tgcp-bot integrity backup' для сохранения копии перед обновлением.")
        elif report.status == "ERROR":
            print(f"   ❌ Ошибка: {report.error_message}")
            return 1

        if report.custom_files and report.status == "MODIFIED":
            print(f"\n   🧩 Также обнаружены кастомные дополнения ({len(report.custom_files)}):")
            for cf in report.custom_files:
                print(f"      • [{cf.category}] {cf.rel_path}")

        return 0 if report.status in ("OK", "CUSTOM_ACTIVE") else 1

    elif action == "backup":
        success, backup_dir, backed_up = backup_modified_files(repo_root=base_dir, branch=branch)
        if backed_up:
            print(f"📦 Бэкап успешно создан ({len(backed_up)} файлов):")
            print(f"   Папка: {backup_dir}")
            for f in backed_up:
                print(f"   • {f}")
        else:
            print("ℹ️ Нет модифицированных системных файлов для бэкапа.")
        return 0

    elif action == "new-module":
        name = getattr(args, "name", "") or getattr(args, "flag_name", "")
        if not name:
            print("❌ Укажите имя модуля: tgcp-bot integrity new-module <имя>")
            return 1
        try:
            path = create_custom_module_template(name, repo_root=base_dir)
            print(f"✨ Создан шаблон кастомного модуля: {path}")
            print("   Он автоматически подключится при запуске бота и изолирован от Git!")
            return 0
        except Exception as e:
            print(f"❌ Ошибка создания модуля: {e}")
            return 1

    elif action == "new-page":
        name = getattr(args, "name", "") or getattr(args, "flag_name", "")
        if not name:
            print("❌ Укажите имя страницы: tgcp-bot integrity new-page <имя>")
            return 1
        try:
            r_path, t_path = create_custom_web_page_template(name, repo_root=base_dir)
            print("✨ Создан шаблон WebUI страницы:")
            print(f"   Маршрут: {r_path}")
            print(f"   Шаблон:  {t_path}")
            print(f"   URL:     /custom/{name}")
            return 0
        except Exception as e:
            print(f"❌ Ошибка создания страницы: {e}")
            return 1

    elif action == "list-custom":
        custom_files = find_custom_extensions(repo_root=base_dir)
        if not custom_files:
            print("ℹ️ Кастомных дополнений пока нет.")
            print("   Создать: tgcp-bot integrity new-module <имя> или new-page <имя>")
        else:
            print(f"🧩 Найдено кастомных файлов: {len(custom_files)}")
            for cf in custom_files:
                print(f"   • [{cf.category}] {cf.rel_path} (изменен: {cf.modified_time})")
        return 0


def print_banner():
    """Print pretty CLI banner with commands"""
    banner = """
╔════════════════════════════════════════════════════════════╗
║           🤖 TGCP-BOT - Telegram VPS Bot Manager           ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  📋 Доступные команды:                                     ║
║                                                            ║
║    adduser   ➜  Добавить администратора                   ║
║                 --id <ID>  --name <Имя>                    ║
║                                                            ║
║    webpass   ➜  Сбросить пароль Web-панели                ║
║                 Пароль запрашивается скрыто                ║
║                                                            ║
║    integrity ➜  Целостность SHA-256 и кастомизация        ║
║                 check | backup | new-module | new-page     ║
║                                                            ║
║    stats     ➜  Показать статистику БД                    ║
║                                                            ║
║    cleanlogs ➜  Очистить файлы логов                      ║
║                                                            ║
║    tls       ➜  Статус/завершение HTTPS миграции нод       ║
║                                                            ║
║    restart   ➜  Перезапустить бота                        ║
║                                                            ║
║    status    ➜  Показать статус бота                      ║
║                                                            ║
╠════════════════════════════════════════════════════════════╣
║  💡 Примеры:                                               ║
║    tgcp-bot integrity check                                ║
║    tgcp-bot integrity backup                               ║
║    tgcp-bot integrity new-module mymodule                  ║
║    tgcp-bot stats                                          ║
║    tgcp-bot webpass                                        ║
╚════════════════════════════════════════════════════════════╝
"""
    print(banner)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tgcp-bot",
        description="CLI утилита управления Telegram VPS Bot",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="Показать справку")

    subparsers = parser.add_subparsers(dest="command", title="Доступные команды")

    # Add new admin user command
    p_add = subparsers.add_parser("adduser", help="Добавить администратора")
    p_add.add_argument("--id", type=int, required=True, help="Telegram ID")
    p_add.add_argument("--name", type=str, default="Admin", help="Имя пользователя")

    # Reset web panel password command
    p_pass = subparsers.add_parser("webpass", help="Сбросить пароль Web-панели")
    p_pass.add_argument(
        "--password",
        type=str,
        help="Новый пароль (не рекомендуется: виден в shell history/process list)",
    )

    # Show database statistics command
    subparsers.add_parser("stats", help="Показать статистику БД")

    # Clean old log files command
    subparsers.add_parser("cleanlogs", help="Очистить файлы логов")

    # Restart bot service command
    subparsers.add_parser("restart", help="Перезапустить бота")

    # Show bot status command
    subparsers.add_parser("status", help="Показать статус бота")

    tls_parser = subparsers.add_parser("tls", help="Управление миграцией HTTPS нод")
    tls_commands = tls_parser.add_subparsers(dest="tls_command", required=True)
    tls_commands.add_parser("status", help="Статус HTTPS для зарегистрированных нод")
    tls_commands.add_parser("check", help="Проверить, что все ноды подтвердили HTTPS")
    tls_commands.add_parser("finalize", help="Закрыть legacy HTTP bridge после миграции всех нод")

    # Integrity & Custom extensions command
    p_integ = subparsers.add_parser("integrity", help="Целостность SHA-256 и управление кастомизацией")
    p_integ.add_argument(
        "action",
        nargs="?",
        default="check",
        choices=["check", "backup", "new-module", "new-page", "list-custom"],
        help="Действие: check (по умолчанию), backup, new-module, new-page, list-custom",
    )
    p_integ.add_argument("name", nargs="?", default="", help="Имя кастомного модуля или страницы")
    p_integ.add_argument("--branch", type=str, default="main", help="Целевая ветка Git (по умолчанию main)")
    p_integ.add_argument("--fetch", action="store_true", help="Сделать git fetch origin перед проверкой")
    p_integ.add_argument("--json", action="store_true", help="Вывод в формате JSON")
    p_integ.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод контрольных сумм")
    p_integ.add_argument("--name", dest="flag_name", type=str, default="", help="Имя (через флаг)")

    args = parser.parse_args(argv)

    if not args.command or args.help:
        print_banner()
        return

    try:
        if args.command == "adduser":
            asyncio.run(cmd_adduser(args))
        elif args.command == "webpass":
            asyncio.run(cmd_webpass(args))
        elif args.command == "integrity":
            return cmd_integrity(args)
        elif args.command == "stats":
            asyncio.run(cmd_stats(args))
        elif args.command == "cleanlogs":
            asyncio.run(cmd_cleanlogs(args))
        elif args.command == "restart":
            asyncio.run(cmd_restart(args))
        elif args.command == "status":
            asyncio.run(cmd_status(args))
        elif args.command == "tls" and args.tls_command == "status":
            asyncio.run(cmd_tls_status(args))
        elif args.command == "tls" and args.tls_command == "check":
            asyncio.run(cmd_tls_check(args))
        elif args.command == "tls" and args.tls_command == "finalize":
            asyncio.run(cmd_tls_finalize(args))
    except KeyboardInterrupt:
        print("\n⛔ Отменено.")
        return 130
    except Exception as e:
        print(f"❌ Произошла ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
