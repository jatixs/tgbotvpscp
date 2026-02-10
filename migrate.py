import os
import json
import logging
import sys
import shutil
from core import config  
from core.config import CIPHER_SUITE, CONFIG_DIR  # For encryption

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Migration")

FILES_TO_MIGRATE = [
    "users.json",
    "alerts_config.json",
    "user_settings.json",
    "services.json"
]

def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_encrypted(path: str, data: dict):
    json_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
    encrypted_data = CIPHER_SUITE.encrypt(json_bytes)
    with open(path, 'wb') as f:
        f.write(encrypted_data)

def cleanup_backups():
    """
    Удаляет файлы .bak в папке config, если они существуют.
    Вызывается только после успешной миграции.
    """
    logger.info("🧹 Очистка файлов бэкапов...")
    count = 0
    for filename in FILES_TO_MIGRATE:
        backup_path = os.path.join(CONFIG_DIR, f"{filename}.bak")
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
                logger.info(f"✅ Удален бэкап: {filename}.bak")
                count += 1
            except OSError as e:
                logger.error(f"❌ Ошибка удаления {filename}.bak: {e}")
    
    if count == 0:
        logger.info("Бэкапы не найдены или уже удалены.")
    else:
        logger.info(f"Очистка завершена. Удалено файлов: {count}")

def migrate_file(filename: str):
    file_path = os.path.join(CONFIG_DIR, filename)
    backup_path = os.path.join(CONFIG_DIR, f"{filename}.bak")

    if not os.path.exists(file_path):
        return  # Файла нет, пропускаем

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return
            if not content.startswith('{') and not content.startswith('['):
                return
            data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    logger.info(f"🔄 Миграция (шифрование) {filename}...")

    # 1. Создаем бэкап
    try:
        shutil.copy2(file_path, backup_path)
        logger.info(f"   Бэкап создан: {filename}.bak")
    except Exception as e:
        logger.error(f"❌ Ошибка создания бэкапа для {filename}: {e}")
        return

    # 2. Шифруем и перезаписываем
    try:
        save_encrypted(file_path, data)
        logger.info(f"   Файл {filename} успешно зашифрован.")
    except Exception as e:
        logger.error(f"❌ Ошибка шифрования {filename}: {e}")
        # Восстанавливаем из бэкапа при ошибке
        if os.path.exists(backup_path):
            shutil.move(backup_path, file_path)
            logger.warning("   Файл восстановлен из бэкапа.")
        return


def ensure_env_variables():
    """
    Проверяет .env файл на наличие всех необходимых переменных.
    Добавляет недостающие переменные с значениями по умолчанию.
    """
    env_file = os.path.join(config.BASE_DIR, ".env")
    
    if not os.path.exists(env_file):
        logger.warning(".env файл не найден, пропуск проверки переменных.")
        return
    
    logger.info("🔍 Проверка переменных окружения в .env...")
    
    # Список обязательных переменных с дефолтными значениями
    required_vars = {
        "WEB_SERVER_HOST": "0.0.0.0",  # nosec B104
        "WEB_SERVER_PORT": "8080",
        "INSTALL_MODE": "secure",
        "DEPLOY_MODE": "systemd",
        "ENABLE_WEB_UI": "true",
        "DEBUG": "false",
        "TG_BOT_NAME": "VPS Bot",
    }
    
    # Опциональные переменные (добавляются с пустым значением)
    optional_vars = [
        "SENTRY_DSN",
        "TG_ADMIN_USERNAME",
        "TG_BOT_CONTAINER_NAME",
        "COMPOSE_PROFILES",
        "WEB_DOMAIN",
    ]
    
    try:
        with open(env_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        existing_vars = set()
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                var_name = line.split('=')[0].strip()
                existing_vars.add(var_name)
        
        changes_made = False
        lines_to_add = []
        
        # Проверяем обязательные переменные
        for var_name, default_val in required_vars.items():
            if var_name not in existing_vars:
                lines_to_add.append(f'{var_name}="{default_val}"')
                logger.info(f"  + Добавлена переменная: {var_name}={default_val}")
                changes_made = True
        
        # Проверяем опциональные переменные
        for var_name in optional_vars:
            if var_name not in existing_vars:
                lines_to_add.append(f'{var_name}=""')
                changes_made = True
        
        if lines_to_add:
            with open(env_file, 'a', encoding='utf-8') as f:
                f.write('\n' + '\n'.join(lines_to_add) + '\n')
            logger.info(f"✅ Добавлено {len(lines_to_add)} переменных в .env")
        else:
            logger.info("✅ Все переменные окружения актуальны.")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке .env: {e}")


def migrate_metadata():
    """
    Проверяет и восстанавливает WEB_METADATA в system_config.json.
    Если структура нарушена или ключи отсутствуют - сбрасывает/дополняет до дефолтных.
    Поддерживает флаг --reset-meta для принудительного сброса.
    """
    logger.info("🔍 Checking WebUI Metadata consistency...")
    force_reset = "--reset-meta" in sys.argv
    current_meta = getattr(config, "WEB_METADATA", {})
    defaults = {
        "favicon": "/static/favicon.ico",
        "title": "",
        "description": "",
        "keywords": "",
        "locked": False
    }
    
    modified = False

    if force_reset:
        logger.warning("⚠️ FORCE RESET: Resetting WebUI Metadata to defaults by user request.")
        current_meta = defaults.copy()
        modified = True
        
    elif not isinstance(current_meta, dict):
        logger.warning("WEB_METADATA is corrupted (not a dict). Resetting to defaults.")
        current_meta = defaults.copy()
        modified = True
        
    else:
        for key, default_val in defaults.items():
            if key not in current_meta:
                logger.info(f"Missing key '{key}' in metadata. Adding default.")
                current_meta[key] = default_val
                modified = True
            else:
                val = current_meta[key]
                expected_type = type(default_val)
                if not isinstance(val, expected_type) and val is not None:
                    try:
                        if expected_type == bool:
                            current_meta[key] = str(val).lower() in ("true", "1", "yes", "on")
                        elif expected_type == str:
                            current_meta[key] = str(val)
                        elif expected_type == int:
                            current_meta[key] = int(val)
                        
                        modified = True
                        logger.warning(f"Fixed type for key '{key}': {val} -> {current_meta[key]}")
                    except Exception:
                        current_meta[key] = default_val
                        modified = True
                        logger.warning(f"Reset key '{key}' to default due to type error.")
    if modified:
        logger.info("Saving corrected Metadata to system configuration...")
        config.WEB_METADATA = current_meta
        config.save_system_config({"WEB_METADATA": current_meta})
        logger.info("Migration completed: Metadata updated.")
    else:
        logger.info("WebUI Metadata is valid. No changes needed.")

def main():
    logger.info("🚀 Запуск миграции конфигурации...")
    
    try:
        # Проверка и обновление переменных окружения
        ensure_env_variables()
        
        for filename in FILES_TO_MIGRATE:
            migrate_file(filename)
        migrate_metadata()
        logger.info("✅ Все миграции выполнены успешно.")
        cleanup_backups()
        
    except Exception as e:
        logger.critical(f"⛔ Критическая ошибка во время миграции: {e}")
        exit(1)

if __name__ == "__main__":
    main()