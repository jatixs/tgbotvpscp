# file: core/metrics/publisher.py
import asyncio
import psutil
import logging
import time
from datetime import datetime

from core.realtime.bus import bus
from core import nodes_db
from core.config import NODE_OFFLINE_TIMEOUT

logger = logging.getLogger(__name__)

async def system_metrics_publisher(app):
    """
    Фоновая задача для сбора метрик хоста и статусов нод.
    """
    logger.info("Starting SSE Metrics Publisher")
    try:
        while True:
            # 1. Метрики Хоста (где стоит бот)
            try:
                cpu_percent = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                boot_time = datetime.fromtimestamp(psutil.boot_time())
                uptime_seconds = (datetime.now() - boot_time).total_seconds()

                metrics_data = {
                    "cpu": cpu_percent,
                    "ram_percent": mem.percent,
                    "ram_used": round(mem.used / (1024**3), 2),
                    "ram_total": round(mem.total / (1024**3), 2),
                    "disk_percent": disk.percent,
                    "uptime": _format_uptime(uptime_seconds)
                }
                await bus.publish("host_metrics", metrics_data)
            except Exception as e:
                logger.error(f"Error collecting host metrics: {e}")

            # 2. Статусы Нод
            try:
                # Получаем все ноды через nodes_db (данные уже расшифрованы и обработаны)
                all_nodes = await nodes_db.get_all_nodes()
                nodes_list = []
                now = time.time()
                
                for token, node in all_nodes.items():
                    last_seen = node.get("last_seen", 0)
                    is_restarting = node.get("is_restarting", False)
                    
                    status = "offline"
                    if is_restarting:
                        status = "restarting"
                    elif now - last_seen < NODE_OFFLINE_TIMEOUT:
                        status = "online"
                    
                    nodes_list.append({
                        "id": token, # Используем токен как ID для сопоставления в JS
                        "name": node.get("name", "Unknown"),
                        "ip": node.get("ip", "Unknown"),
                        "status": status,
                        "cpu": node.get("stats", {}).get("cpu", 0),
                        "ram": node.get("stats", {}).get("ram", 0),
                        "disk": node.get("stats", {}).get("disk", 0)
                    })
                
                if nodes_list:
                    await bus.publish("nodes_status", {"nodes": nodes_list})

            except Exception as e:
                logger.error(f"Error fetching nodes for SSE: {e}")

            await asyncio.sleep(2)

    except asyncio.CancelledError:
        logger.info("SSE Metrics Publisher stopped")
    except Exception as e:
        logger.error(f"Critical error in metrics publisher: {e}")

def _format_uptime(seconds):
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        return f"{int(days)}d {int(hours)}h"
    return f"{int(hours)}h {int(minutes)}m"