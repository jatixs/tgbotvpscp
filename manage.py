#!/usr/bin/env python3
import asyncio
import argparse
import sys
import os
import logging

# Настройка путей и логгера
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO, format='%(message)s')

from tortoise import Tortoise
from core import config, auth, models, utils
from core.nodes_db import init_db

async def init():
    """Инициализация БД"""
    # Загружаем переменные окружения, если они еще не загружены
    config.load_env() 
    await init_db()

async def close():
    """Закрытие соединений"""
    await Tortoise.close_connections()

# --- Логика команд ---

async def create_superuser(args):
    """Создает администратора"""
    print(f"🔧 Добавление администратора...")
    if not args.id:
        print("❌ Ошибка: Не указан Telegram ID (--id)")
        return

    # Загружаем текущих пользователей
    auth.load_users()
    
    # Функция add_user в auth.py синхронная или асинхронная?
    # В v1.15.2 auth.load_users и auth.add_user - синхронные (работают с JSON/памятью)
    # или асинхронные (если переехали на БД). 
    # Предполагаем, что add_user уже умеет работать с текущим хранилищем.
    
    if auth.add_user(args.id, "admins", args.name):
        print(f"✅ Администратор {args.name} (ID: {args.id}) успешно добавлен!")
        auth.save_users() # На случай если add_user не сохраняет сразу
    else:
        print(f"⚠️ Пользователь {args.id} уже существует или ошибка добавления.")

async def reset_web_password(args):
    """Сброс пароля от веб-панели"""
    new_pass = args.password
    if not new_pass:
        new_pass = utils.generate_random_string(12)
    
    # Обновляем .env
    utils.update_env_variable("TG_WEB_INITIAL_PASSWORD", new_pass)
    print(f"✅ Пароль Web-панели изменен.")
    print(f"🔑 Новый пароль: {new_pass}")
    print("ℹ️  Чтобы изменения вступили в силу, перезапустите бота: tgcp-bot restart")

async def show_stats(args):
    """Показать статистику"""
    await init()
    try:
        node_count = await models.Node.all().count()
        active_nodes = await models.Node.filter(status="active").count()
        print(f"📊 Статистика базы данных:")
        print(f"   Всего нод: {node_count}")
        print(f"   Активных: {active_nodes}")
    except Exception as e:
        print(f"❌ Ошибка чтения БД: {e}")
    finally:
        await close()

async def clean_logs(args):
    """Очистка логов"""
    log_dirs = ["logs/bot", "logs/watchdog", "logs/node"]
    print("🧹 Очистка логов...")
    count = 0
    for d in log_dirs:
        path = os.path.join(config.BASE_DIR, d)
        if os.path.exists(path):
            for f in os.listdir(path):
                file_path = os.path.join(path, f)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                        count += 1
                except Exception as e:
                    print(f"   Ошибка удаления {f}: {e}")
    print(f"✅ Удалено файлов: {count}")

async def restart_service(args):
    """Перезапуск сервисов"""
    print("♻️ Перезапуск бота...")
    os.system("sudo systemctl restart tg-bot")
    print("✅ Команда отправлена.")

# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="TGCP-BOT CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Команды")

    # adduser
    p_adduser = subparsers.add_parser("adduser", help="Добавить админа")
    p_adduser.add_argument("--id", type=int, required=True, help="Telegram ID")
    p_adduser.add_argument("--name", type=str, default="Admin", help="Имя")

    # webpass
    p_webpass = subparsers.add_parser("webpass", help="Сброс пароля Web-панели")
    p_webpass.add_argument("--password", type=str, help="Новый пароль")

    # stats
    subparsers.add_parser("stats", help="Статистика БД")

    # cleanlogs
    subparsers.add_parser("cleanlogs", help="Очистить логи")

    # restart
    subparsers.add_parser("restart", help="Перезапустить службу бота")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "adduser":
            asyncio.run(create_superuser(args))
        elif args.command == "webpass":
            asyncio.run(reset_web_password(args))
        elif args.command == "stats":
            asyncio.run(show_stats(args))
        elif args.command == "cleanlogs":
            asyncio.run(clean_logs(args))
        elif args.command == "restart":
            asyncio.run(restart_service(args))
            
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")

if __name__ == "__main__":
    main()