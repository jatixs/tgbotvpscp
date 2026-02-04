#!/usr/bin/env python3
import asyncio
import argparse
import sys
import os
import subprocess
import logging
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
                    # setdefault чтобы не перезаписать системные переменные, если они уже есть
                    os.environ.setdefault(key, val.strip('"').strip("'"))
    except Exception as e:
        print(f"⚠️ Ошибка чтения .env: {e}")
logging.basicConfig(format="%(message)s", level=logging.INFO)

from tortoise import Tortoise
from core import config, auth, models, utils
from core.nodes_db import init_db


async def init_services():
    """Init DB"""
    await init_db()


async def close_services():
    """Close connections"""
    await Tortoise.close_connections()


async def cmd_adduser(args):
    print(f"🔧 Добавление администратора...")
    auth.load_users()
    # Предполагаем, что add_user работает с текущим хранилищем (JSON или БД)
    if auth.add_user(args.id, "admins", args.name):
        if hasattr(auth, "save_users"):
            auth.save_users()
        print(f"✅ Администратор {args.name} (ID: {args.id}) добавлен.")
    else:
        print(f"⚠️ Пользователь {args.id} уже существует.")


async def cmd_webpass(args):
    new_pass = args.password
    if not new_pass:
        new_pass = utils.generate_random_string(12)

    utils.update_env_variable("TG_WEB_INITIAL_PASSWORD", new_pass)
    print(f"✅ Пароль Web-панели изменен.")
    print(f"🔑 Новый пароль сохранен в файле .env")
    print("ℹ️  Перезапустите бота для применения: tgcp-bot restart")
    

async def cmd_stats(args):
    await init_services()
    try:
        node_count = await models.Node.all().count()
        # Active nodes are those with last_seen within NODE_OFFLINE_TIMEOUT
        now = time.time()
        threshold = now - config.NODE_OFFLINE_TIMEOUT
        active = await models.Node.filter(last_seen__gte=threshold).count()
        print(f"📊 Статистика:")
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
                if os.path.isfile(full_path):
                    try:
                        os.unlink(full_path)
                        count += 1
                    except Exception:
                        pass
    print(f"✅ Удалено файлов: {count}")


async def cmd_restart(args):
    print("♻️  Перезапуск службы бота...")
    is_docker = os.environ.get("DEPLOY_MODE") == "docker"

    try:
        if is_docker:
            # Для Docker используем subprocess вместо os.system
            result = subprocess.run(
                ["docker", "compose", "restart"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                print(f"⚠️ Ошибка перезапуска: {result.stderr}")
        else:
            # Используем subprocess.run вместо os.system для systemctl
            result = subprocess.run(
                ["sudo", "systemctl", "restart", "tg-bot"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                print(f"⚠️ Ошибка перезапуска: {result.stderr}")
        print("✅ Команда отправлена.")
    except subprocess.TimeoutExpired:
        print("❌ Превышен timeout перезапуска.")
    except Exception as e:
        print(f"❌ Ошибка при перезапуске: {e}")


async def cmd_status(args):
    """Check bot status"""
    print("📊 Проверка статуса бота...")
    is_docker = os.environ.get("DEPLOY_MODE") == "docker"
    
    try:
        if is_docker:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                print("🐳 Docker режим:")
                # Parse and display container status
                if result.stdout:
                    try:
                        import json
                        # docker compose ps --format json returns one JSON object per line
                        containers = []
                        for line in result.stdout.strip().split('\n'):
                            if line:
                                containers.append(json.loads(line))
                        
                        if containers:
                            for container in containers:
                                name = container.get('Name', 'Unknown')
                                state = container.get('State', 'unknown')
                                status = container.get('Status', '')
                                print(f"  • {name}: {state} ({status})")
                        else:
                            print("  Контейнеры не найдены")
                    except:
                        # Fallback to raw output if JSON parsing fails
                        print(result.stdout)
                else:
                    print("  Контейнеры не найдены")
            else:
                print(f"⚠️ Ошибка: {result.stderr}")
        else:
            result = subprocess.run(
                ["systemctl", "status", "tg-bot", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10
            )
            print("🔧 Systemd режим:")
            print(result.stdout if result.stdout else result.stderr)
    except subprocess.TimeoutExpired:
        print("❌ Превышен timeout проверки статуса.")
    except Exception as e:
        print(f"❌ Ошибка проверки статуса: {e}")


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
║                 --password <пароль> (опционально)          ║
║                                                            ║
║    stats     ➜  Показать статистику БД                    ║
║                                                            ║
║    cleanlogs ➜  Очистить файлы логов                      ║
║                                                            ║
║    restart   ➜  Перезапустить бота                        ║
║                                                            ║
║    status    ➜  Показать статус бота                      ║
║                                                            ║
╠════════════════════════════════════════════════════════════╣
║  💡 Примеры:                                               ║
║    tgcp-bot stats                                          ║
║    tgcp-bot adduser --id 123456789 --name Admin            ║
║    tgcp-bot webpass --password MyNewPass123                ║
╚════════════════════════════════════════════════════════════╝
"""
    print(banner)


def main():
    parser = argparse.ArgumentParser(
        prog="tgcp-bot",
        description="CLI утилита управления Telegram VPS Bot",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="Показать справку")

    subparsers = parser.add_subparsers(dest="command", title="Доступные команды")

    # Команда: adduser
    p_add = subparsers.add_parser("adduser", help="Добавить администратора")
    p_add.add_argument("--id", type=int, required=True, help="Telegram ID")
    p_add.add_argument("--name", type=str, default="Admin", help="Имя пользователя")

    # Команда: webpass
    p_pass = subparsers.add_parser("webpass", help="Сбросить пароль Web-панели")
    p_pass.add_argument("--password", type=str, help="Новый пароль (опционально)")

    # Команда: stats
    subparsers.add_parser("stats", help="Показать статистику БД")

    # Команда: cleanlogs
    subparsers.add_parser("cleanlogs", help="Очистить файлы логов")

    # Команда: restart
    subparsers.add_parser("restart", help="Перезапустить бота")

    # Команда: status
    subparsers.add_parser("status", help="Показать статус бота")

    args = parser.parse_args()

    if not args.command or args.help:
        print_banner()
        return

    try:
        if args.command == "adduser":
            asyncio.run(cmd_adduser(args))
        elif args.command == "webpass":
            asyncio.run(cmd_webpass(args))
        elif args.command == "stats":
            asyncio.run(cmd_stats(args))
        elif args.command == "cleanlogs":
            asyncio.run(cmd_cleanlogs(args))
        elif args.command == "restart":
            asyncio.run(cmd_restart(args))
        elif args.command == "status":
            asyncio.run(cmd_status(args))
    except KeyboardInterrupt:
        print("\n⛔ Отменено.")
    except Exception as e:
        print(f"❌ Произошла ошибка: {e}")


if __name__ == "__main__":
    main()
