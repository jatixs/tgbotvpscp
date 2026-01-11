# file: core/realtime/bus.py
import asyncio
import logging
import json
from typing import Set, Dict, Any

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()

    async def subscribe(self) -> asyncio.Queue:
        """Создает новую очередь для подписчика."""
        queue = asyncio.Queue()
        self._subscribers.add(queue)
        # logger.debug(f"Client subscribed. Total: {len(self._subscribers)}")
        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """Удаляет очередь подписчика."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
            # logger.debug(f"Client unsubscribed. Total: {len(self._subscribers)}")

    async def publish(self, event_type: str, data: Dict[str, Any]):
        """Публикует событие всем активным подписчикам."""
        if not self._subscribers:
            return

        message = {
            "event": event_type,
            "data": data
        }
        
        try:
            payload = json.dumps(message)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize event {event_type}: {e}")
            return

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

bus = EventBus()