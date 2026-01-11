import os
import json
import logging
from core.config import CIPHER_SUITE, CONFIG_DIR

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Migration")

FILES_TO_MIGRATE = [
    "users.json",
    "alerts_config.json",
    "user_settings.json"
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

    # Проверяем, зашифрован ли файл уже (пытаемся прочитать как JSON)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # Если файл пустой, игнорируем
            if not content:
                return
            # Если начинается не с { или [, скорее всего это уже шифрованные байты (или мусор)
            if not content.startswith('{') and not content.startswith('['):
                logger.info(f"Файл {filename} уже зашифрован или имеет неверный формат. Пропуск.")
                return
            
            # Пробуем распарсить JSON
            data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.info(f"Файл {filename} не является открытым JSON. Вероятно, уже зашифрован.")
        return

    logger.info(f"🔄 Миграция {filename}...")

    # 1. Создаем бэкап
    try:
        import shutil
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

def main():
    logger.info("🚀 Запуск миграции конфигурации...")
    
    try:
        # Проходимся по всем файлам
        for filename in FILES_TO_MIGRATE:
            migrate_file(filename)
        
        logger.info("✅ Все миграции выполнены успешно.")
        
        # --- ОЧИСТКА ---
        # Удаляем бэкапы только если код дошел до этой строчки без критических ошибок
        cleanup_backups()
        
    except Exception as e:
        logger.critical(f"⛔ Критическая ошибка во время миграции: {e}")
        exit(1)

if __name__ == "__main__":
    main()