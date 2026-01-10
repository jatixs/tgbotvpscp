import os
import sys
import json
import shutil
import logging
import asyncio
import time
from tortoise import Tortoise
from core.config import (
    CONFIG_DIR, USERS_FILE, ALERTS_CONFIG_FILE, USER_SETTINGS_FILE,
    KEYBOARD_CONFIG_FILE, NODES_FILE, SECURITY_KEY_FILE, CIPHER_SUITE,
    load_encrypted_json, save_encrypted_json
)
from core.models import Node


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s')

TIMESTAMP = int(time.time())
BACKUP_DIR = os.path.join(
    os.path.dirname(CONFIG_DIR),
    f"config_backup_{TIMESTAMP}")
TEMP_DIR = os.path.join(
    os.path.dirname(CONFIG_DIR),
    f"config_temp_migration_{TIMESTAMP}")


async def migrate_nodes_from_json(source_json_path, target_db_path):
    """Мигрирует данные из nodes.json в зашифрованную nodes.db."""
    logging.info(f"⏳ Processing nodes: JSON -> Encrypted DB...")

    db_url = f"sqlite://{target_db_path}"
    await Tortoise.init(db_url=db_url, modules={"models": ["core.models"]})
    await Tortoise.generate_schemas()

    try:
        with open(source_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        count = 0
        if data:
            for token, node_data in data.items():
                import hashlib
                t_hash = hashlib.sha256(token.encode()).hexdigest()

                await Node.create(
                    token_hash=t_hash,
                    token_safe=token,
                    name=node_data.get("name", "Unknown"),
                    ip=node_data.get("ip", "Unknown"),
                    created_at=node_data.get("created_at", time.time()),
                    last_seen=node_data.get("last_seen", 0),
                    stats=node_data.get("stats", {}),
                    history=node_data.get("history", []),
                    tasks=node_data.get("tasks", []),
                    extra_state={}
                )
                count += 1

        logging.info(f"✅ Nodes migrated: {count}")
    finally:
        await Tortoise.close_connections()


def reencrypt_json_file(filename):
    """Читает JSON (простой или зашифрованный) и сохраняет зашифрованным."""
    src = os.path.join(BACKUP_DIR, filename)
    dst = os.path.join(TEMP_DIR, filename)

    if os.path.exists(src):
        try:
            data = load_encrypted_json(src)
            if data:
                save_encrypted_json(dst, data)
                logging.info(f"✅ Re-encrypted: {filename}")
            else:
                logging.warning(f"⚠️ Skipped (empty/invalid): {filename}")
        except Exception as e:
            logging.error(f"❌ Error processing {filename}: {e}")
            raise e


def main():
    print(f"🚀 Starting Secure Configuration Migration...")

    if not os.path.exists(CONFIG_DIR):
        logging.info("ℹ️ Config directory not found. Skipping.")
        return

    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    logging.info(f"📦 Creating backup: {BACKUP_DIR}")
    shutil.copytree(CONFIG_DIR, BACKUP_DIR)

    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

    try:

        if os.path.exists(SECURITY_KEY_FILE):
            shutil.copy2(
                SECURITY_KEY_FILE,
                os.path.join(
                    TEMP_DIR,
                    "security.key"))
        elif os.path.exists(os.path.join(CONFIG_DIR, "security.key")):
            shutil.copy2(
                os.path.join(
                    CONFIG_DIR, "security.key"), os.path.join(
                    TEMP_DIR, "security.key"))

        reencrypt_json_file("users.json")
        reencrypt_json_file("alerts_config.json")
        reencrypt_json_file("user_settings.json")
        reencrypt_json_file("keyboard_config.json")

        for f in ["system_config.json", "web_auth.txt"]:
            src = os.path.join(BACKUP_DIR, f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(TEMP_DIR, f))

        nodes_json_src = os.path.join(BACKUP_DIR, "nodes.json")
        nodes_db_dst = os.path.join(TEMP_DIR, "nodes.db")

        if os.path.exists(nodes_json_src):
            asyncio.run(migrate_nodes_from_json(nodes_json_src, nodes_db_dst))
        elif os.path.exists(os.path.join(BACKUP_DIR, "nodes.db")):
            logging.info("ℹ️ nodes.json missing, copying existing nodes.db.")
            shutil.copy2(os.path.join(BACKUP_DIR, "nodes.db"), nodes_db_dst)

        logging.info("🔄 Applying new configuration...")
        shutil.rmtree(CONFIG_DIR)
        shutil.copytree(TEMP_DIR, CONFIG_DIR)
        shutil.rmtree(TEMP_DIR)

        logging.info("✨ Migration completed successfully!")

    except Exception as e:
        logging.error(f"🔥 CRITICAL FAILURE: {e}")
        logging.info("🔙 Restoring configuration from backup...")
        if os.path.exists(CONFIG_DIR):
            shutil.rmtree(CONFIG_DIR)
        shutil.copytree(BACKUP_DIR, CONFIG_DIR)
        sys.exit(1)


if __name__ == "__main__":
    main()
