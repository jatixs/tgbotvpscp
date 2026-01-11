# file: core/web/sse.py
import asyncio
import logging
from aiohttp import web
from core.realtime.bus import bus

logger = logging.getLogger(__name__)

async def sse_handler(request: web.Request) -> web.StreamResponse:
    """
    Обрабатывает SSE соединение.
    Предполагается, что авторизация уже пройдена в вызывающей функции.
    """
    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )

    try:
        await response.prepare(request)
        queue = await bus.subscribe()
        
        # Ping для установки связи
        await response.write(b"event: ping\ndata: connected\n\n")

        while True:
            try:
                # Ждем данные или таймаут для keep-alive
                payload = await asyncio.wait_for(queue.get(), timeout=10.0)
                msg = f"data: {payload}\n\n"
                await response.write(msg.encode('utf-8'))
            except asyncio.TimeoutError:
                # Keep-alive пинг, чтобы соединение не рвалось
                await response.write(b": keep-alive\n\n")

    except (asyncio.CancelledError, ConnectionResetError):
        # Клиент отключился
        pass
    except Exception as e:
        logger.error(f"SSE Handler Error: {e}")
    finally:
        if 'queue' in locals():
            await bus.unsubscribe(queue)
        await response.write_eof()

    return response