import json
import os
import logging
import secrets
import time
from .config import NODES_FILE
from .shared_state import NODES

def load_nodes():
    try:
        if os.path.exists(NODES_FILE):
            with open(NODES_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                NODES.clear()
                NODES.update(data)
            logging.info(f"Loaded {len(NODES)} nodes from {NODES_FILE}.")
        else:
            NODES.clear()
            logging.info("nodes.json not found. Created empty nodes db.")
            save_nodes()
    except Exception as e:
        logging.error(f"Error loading nodes.json: {e}", exc_info=True)
        NODES.clear()

def save_nodes():
    try:
        os.makedirs(os.path.dirname(NODES_FILE), exist_ok=True)
        with open(NODES_FILE, "w", encoding='utf-8') as f:
            json.dump(NODES, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        logging.debug("Nodes db saved successfully.")
    except Exception as e:
        logging.error(f"Error saving nodes.json: {e}", exc_info=True)

def create_node(name: str) -> str:
    token = secrets.token_hex(16) 
    NODES[token] = {
        "name": name,
        "created_at": time.time(),
        "last_seen": 0,
        "ip": "Unknown",
        "stats": {},
        "tasks": []
    }
    save_nodes()
    logging.info(f"Created new node: {name} (Token: {token[:8]}...)")
    return token

def delete_node(token: str):
    if token in NODES:
        name = NODES[token].get("name", "Unknown")
        del NODES[token]
        save_nodes()
        logging.info(f"Node deleted: {name}")

def get_node_by_token(token: str):
    return NODES.get(token)

def update_node_heartbeat(token: str, ip: str, stats: dict):
    if token in NODES:
        NODES[token]["last_seen"] = time.time()
        NODES[token]["ip"] = ip
        NODES[token]["stats"] = stats