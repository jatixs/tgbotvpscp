import json
import os
import logging
import secrets
import time
from .config import NODES_FILE
from .shared_state import NODES

MAX_HISTORY_POINTS = 60 

def load_nodes():
    try:
        if os.path.exists(NODES_FILE):
            with open(NODES_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                NODES.clear()
                NODES.update(data)
            for token in NODES:
                NODES[token]["history"] = []
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
        nodes_to_save = {}
        for k, v in NODES.items():
            node_copy = v.copy()
            if "history" in node_copy:
                del node_copy["history"]
            nodes_to_save[k] = node_copy
            
        with open(NODES_FILE, "w", encoding='utf-8') as f:
            json.dump(nodes_to_save, f, indent=4, ensure_ascii=False)
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
        "tasks": [],
        "history": []
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
        node = NODES[token]
        node["last_seen"] = time.time()
        node["ip"] = ip
        node["stats"] = stats
        
        if "history" not in node:
            node["history"] = []
            
        point = {
            "t": int(time.time()),
            "c": stats.get("cpu", 0),
            "r": stats.get("ram", 0),
            "rx": stats.get("net_rx", 0),
            "tx": stats.get("net_tx", 0)
        }
        
        node["history"].append(point)
        
        if len(node["history"]) > MAX_HISTORY_POINTS:
            node["history"] = node["history"][-MAX_HISTORY_POINTS:]