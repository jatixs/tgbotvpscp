"""Read-only operation history presentation; command payloads are never rendered."""
import json
from datetime import datetime, timezone
from html.parser import HTMLParser

from ..i18n import get_text
from ..utils import format_traffic, format_uptime


LABELS = {
    "ru": {
        "title": "Центр операций", "intro": "Команды серверам, их состояние и полученные ответы.",
        "back": "К серверам", "server": "Сервер", "all_servers": "Все серверы",
        "status": "Статус", "all_statuses": "Все статусы", "refresh": "Обновить",
        "status_help": "Что означают статусы операций",
        "live_connecting": "Подключение автообновления…", "live": "Обновляется автоматически",
        "live_reconnecting": "Связь прервана. Переподключение…", "live_expired": "Сессия истекла. Обновите страницу.",
        "older": "Более ранние", "latest": "Последние", "empty": "Операций пока нет",
        "empty_hint": "Здесь появятся команды, отправленные серверам после обновления. Попробуйте изменить фильтры.",
        "per_page": "Записей на страницу", "page": "Страница", "page_of": "из",
        "showing_records": "Показано", "prev": "Назад", "next": "Вперёд", "total_records": "Всего записей",
        "result": "Ответ сервера", "actor": "Инициатор (Telegram ID)", "updated": "Обновлено",
        "deleted": "Удалённый сервер", "time": "Время UTC", "operation": "Операция",
        "notice": "«Завершено» означает, что сервер вернул результат. Для перезагрузки это подтверждение приёма команды, а не проверка запуска сервера. Старые ноды не подтверждают выполнение. Прерванные операции автоматически не повторяются.",
        "queued": "В очереди", "dispatched": "Ожидает подтверждения", "running": "Выполняется",
        "finished": "Завершено", "failed": "Ошибка", "unknown": "Результат неизвестен",
        "legacy_sent": "Отправлено без подтверждения",
        "uptime": "Время работы", "traffic": "Статистика трафика", "top": "Процессы",
        "selftest": "Диагностика", "speedtest": "Проверка скорости", "update": "Обновление системы",
        "reboot": "Перезагрузка", "services_list": "Список сервисов", "service_action": "Управление сервисом",
        "start": "Запустить", "stop": "Остановить", "restart": "Перезапустить",
    },
    "en": {
        "title": "Operations center", "intro": "Server commands, their status and received responses.",
        "back": "Back to servers", "server": "Server", "all_servers": "All servers",
        "status": "Status", "all_statuses": "All statuses", "refresh": "Refresh",
        "status_help": "Understanding operation statuses",
        "live_connecting": "Connecting live updates…", "live": "Updating automatically",
        "live_reconnecting": "Connection lost. Reconnecting…", "live_expired": "Session expired. Refresh the page.",
        "older": "Older", "latest": "Latest", "empty": "No operations yet",
        "empty_hint": "Commands sent to servers after this upgrade will appear here. Try changing the filters.",
        "per_page": "Records per page", "page": "Page", "page_of": "of",
        "showing_records": "Showing", "prev": "Previous", "next": "Next", "total_records": "Total records",
        "result": "Server response", "actor": "Requested by (Telegram ID)", "updated": "Updated",
        "deleted": "Deleted server", "time": "Time UTC", "operation": "Operation",
        "notice": "“Completed” means the server returned a result. For a reboot, this acknowledges the request, not a successful restart. Older nodes cannot confirm execution. Interrupted operations are never retried automatically.",
        "queued": "Queued", "dispatched": "Awaiting acknowledgement", "running": "Running",
        "finished": "Completed", "failed": "Failed", "unknown": "Outcome unknown",
        "legacy_sent": "Sent without acknowledgement",
        "uptime": "Uptime", "traffic": "Traffic statistics", "top": "Processes",
        "selftest": "Diagnostics", "speedtest": "Speed test", "update": "System update",
        "reboot": "Reboot", "services_list": "List services", "service_action": "Manage service",
        "start": "Start", "stop": "Stop", "restart": "Restart",
    },
}


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def result_text(raw, lang):
    if not raw:
        return ""
    result = json.loads(raw)
    if isinstance(result, dict) and result.get("type") == "i18n":
        params = {}
        for key, value in result.get("params", {}).items():
            if isinstance(value, dict) and "key" in value:
                value = get_text(value["key"], lang, **value.get("params", {}))
            elif isinstance(value, dict) and value.get("format") in {"traffic", "uptime"}:
                formatter = format_traffic if value["format"] == "traffic" else format_uptime
                value = formatter(value.get("value", 0), lang)
            params[key] = value
        parser = _PlainText()
        parser.feed(get_text(result.get("key", ""), lang, **params))
        return "".join(parser.parts)
    if isinstance(result, dict) and result.get("type") == "services_list":
        return "\n".join(f"{s.get('name', '')}: {s.get('status', '')}" for s in result.get("services", []) if isinstance(s, dict))
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def present(row, names, lang):
    labels = LABELS.get(lang, LABELS["en"])
    command = labels.get(row.command, row.command)
    if row.command == "service_action":
        try:
            payload = json.loads(row.payload)
            action = payload.get("action", "")
            command = f"{labels.get(action, command)}: {payload.get('service', '')}"
        except (ValueError, TypeError, AttributeError):
            pass
    try:
        result = result_text(row.result, lang)
    except (ValueError, TypeError, KeyError, AttributeError):
        result = row.result or ""
    return {
        "id": row.id, "node_name": names.get(row.node_id, f"{labels['deleted']} #{row.node_id}"),
        "node_id": row.node_id, "command": command,
        "status": row.status, "status_label": labels.get(row.status, row.status),
        "requested_by": row.requested_by, "result": result,
        "created_at": timestamp(row.created_at), "updated_at": timestamp(row.updated_at),
    }
