# 🌐 Инструкция по созданию веб-модуля

Данное руководство описывает, как создать **веб-модуль** — страницу или API-эндпоинт в WebUI — и связать его с Telegram-ботом.

Веб-слой находится в `core/web/` и построен на **aiohttp** + **Jinja2**. Каждый компонент отвечает за свою область:

| Файл | Назначение |
|------|-----------|
| `core/web/app.py` | Инициализация, маршруты, lifecycle |
| `core/web/views.py` | HTML-страницы (Jinja2) |
| `core/web/auth.py` | Аутентификация |
| `core/web/api_system.py` | Системные API |
| `core/web/api_nodes.py` | API нод |
| `core/web/streaming.py` | SSE-потоки (в том числе история графиков) |
| `core/web/middlewares.py` | WAF, CSRF, Rate Limiting |

---

## 📋 Обзор архитектуры

```
Браузер (Frontend)
    ↓ HTTP / SSE
core/web/middlewares.py (WAF → Rate Limit → CSRF)
    ↓
core/web/app.py (маршрутизация)
    ├── views.py       → Jinja2 HTML
    ├── api_system.py  → JSON API
    ├── api_nodes.py   → JSON API
    ├── streaming.py   → SSE потоки (включая историю графиков)
    └── auth.py        → Аутентификация
    ↓
core/shared_state.py (in-memory данные)
core/nodes_db.py (SQLite)
core/metrics_history.py (SQLite, история метрик)
core/messaging.py (Telegram уведомления)
```

---

## 🚀 Вариант 1: Добавление API-эндпоинта

Если вам нужен JSON API на базе `aiohttp`, добавьте хендлер в `core/web/api_system.py`.

### Шаг 1: Создание хендлера

**Файл:** `/opt/tg-bot/core/web/api_system.py`

```python
# Добавьте в конец файла перед определением маршрутов
@routes.post("/api/my-feature")
async def api_my_feature(request):
    """Пример авторизованного JSON endpoint."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    param = str(data.get("param", ""))[:100]
    return web.json_response({"status": "ok", "user_id": user["id"], "data": param})
```

### Шаг 2: Регистрация маршрута

**Файл:** `/opt/tg-bot/core/web/api_system.py`

В `api_system.py` уже объявлен `routes = web.RouteTableDef()`. Декоратор `@routes.post(...)` из примера выше регистрирует маршрут; отдельный список `system_routes` создавать не нужно.

### Шаг 3: Вызов из JavaScript

**Файл:** `/opt/tg-bot/core/static/js/dashboard.js` (или создайте свой `.js`)

```javascript
function getCsrfToken() {
    const item = document.cookie.split("; ").find(value => value.startsWith("csrf_token="));
    return item ? decodeURIComponent(item.slice("csrf_token=".length)) : "";
}

async function callMyFeature() {
    const response = await fetch("/api/my-feature", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": getCsrfToken()
        },
        body: JSON.stringify({ param: "hello" })
    });
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
}
```
> ⚠️ **Важно:** изменяющие `/api/` запросы проходят CSRF middleware. Передавайте значение cookie `csrf_token` в заголовке `X-CSRF-Token`; не отключайте middleware для нового endpoint.

---

## 🚀 Вариант 2: Добавление HTML-страницы

Если вам нужна полноценная страница с UI.

### Шаг 1: Создание HTML-шаблона

**Файл:** `/opt/tg-bot/core/templates/my_feature.html`

```html
<!DOCTYPE html>
<html lang="{{ lang }}" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>{{ page_title }} — {{ app_name }}</title>
    <link rel="stylesheet" href="/static/css/main.css">
    <link rel="stylesheet" href="/static/css/style.css">
    <script src="/static/js/theme_init.js"></script>
</head>
<body class="bg-gray-100 dark:bg-[#0b1120] min-h-screen transition-colors">

    <!-- Навигация (копируйте из dashboard.html) -->
    <nav class="...">
        <!-- ... -->
    </nav>

    <!-- Ваш контент -->
    <main class="max-w-7xl mx-auto px-4 pt-20 pb-8">
        <div class="bg-white/60 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/10 rounded-2xl p-6 shadow-lg dark:shadow-none">
            <h1 class="text-xl font-bold text-gray-900 dark:text-white mb-4">
                {{ I18N.my_feature_title }}
            </h1>
            <div id="content">
                <!-- Динамический контент -->
            </div>
        </div>
    </main>
    <script type="application/json" id="page-data">{{ i18n_data | tojson }}</script>

    <script>
        const I18N = JSON.parse(document.getElementById("page-data").textContent);
    </script>
    <script src="/static/js/common.js"></script>
    <script src="/static/js/my_feature.js"></script>
</body>
</html>
```

### Шаг 2: Добавление view

**Файл:** `/opt/tg-bot/core/web/views.py`

```python
async def my_feature_page(request):
    """Страница вашей фичи."""
    user = get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")

    lang = get_user_lang(user["id"])

    # Собираем строки для i18n на фронтенде
    i18n_keys = ["my_feature_title", "my_feature_desc"]
    i18n_data = {k: get_text(k, lang) for k in i18n_keys}

    context = {
        "lang": lang,
        "page_title": get_text("my_feature_title", lang),
        "app_name": "VPS Manager",
        "i18n_data": i18n_data,
        "I18N": i18n_data,
    }

    return aiohttp_jinja2.render_template("my_feature.html", request, context)
```

### Шаг 3: Регистрация маршрута

**Файл:** `/opt/tg-bot/core/web/views.py`
В `views.py` используйте существующую таблицу `routes`:

```python
@routes.get("/my-feature")
async def my_feature_page(request):
    ...
```

### Шаг 4: Создание JavaScript

**Файл:** `/opt/tg-bot/core/static/js/my_feature.js`

```javascript
document.addEventListener('DOMContentLoaded', () => {
    loadData();
});

async function loadData() {
    try {
        const resp = await fetch('/api/my-feature');
        const data = await resp.json();
        renderContent(data);
    } catch (err) {
        console.error('Load error:', err);
    }
}

function renderContent(data) {
    const container = document.getElementById('content');
    const paragraph = document.createElement("p");
    paragraph.className = "text-gray-700 dark:text-gray-300";
    paragraph.textContent = String(data.data ?? "");
    container.replaceChildren(paragraph);
}
```

---

## 🔗 Вариант 3: Связь WebUI с Telegram-ботом

Для двусторонней связи между WebUI и ботом используйте `shared_state` и `messaging`.

### Отправка уведомления из WebUI в Telegram

```python
# В вашем API-хендлере (core/web/api_system.py)
from core.messaging import send_alert
from core.rbac import is_admin
from core.web.auth import get_current_user

@routes.post("/api/my-action")
async def api_my_action(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)
    if not is_admin(user):
        return web.json_response({"error": "Forbidden"}, status=403)

    data = await request.json()
    result = do_something(data)
    bot = request.app.get("bot")
    if bot:
        await send_alert(bot, "Action performed from WebUI", alert_type="system")
    return web.json_response({"status": "ok", "result": result})
```

### Отправка данных из бота в WebUI (через SSE)

```python
# В вашем модуле (modules/my_feature.py)
from core.shared_state import WEB_NOTIFICATIONS
import time

async def my_feature_handler(message):
    # ... ваша логика ...

    # Отправляем событие в WebUI через SSE
    WEB_NOTIFICATIONS.append({
        "type": "my_feature",
        "title": "Событие из бота",
        "message": "Действие выполнено через Telegram",
        "timestamp": time.time()
    })
```

### Чтение общего состояния

```python
# В WebUI API (core/web/api_system.py)
from core.shared_state import ALERTS_CONFIG, ALLOWED_USERS

async def api_get_status(request):
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    return web.json_response({
        "alerts_enabled": ALERTS_CONFIG.get("global_enabled", True),
        "users_count": len(ALLOWED_USERS),
    })
```

```python
# В модуле бота (modules/my_feature.py)
from core.shared_state import WEB_NOTIFICATIONS

# Бот может читать уведомления WebUI и наоборот
```

---

## 🔒 Безопасность

### Обязательные правила
1. Проверяйте пользователя через `get_current_user(request)`; не читайте несуществующий `request["session"]`.
2. Для операций администратора используйте `core.rbac.is_admin(user)`; проверку делайте в каждом API/callback handler.
3. Изменяющие `/api/` requests должны пройти CSRF middleware с заголовком `X-CSRF-Token`.
4. Валидируйте тип, диапазон и размер входных данных; авторизация не заменяет валидацию.
5. Не отправляйте node tokens, passwords или иные секреты в browser payloads. Клиентское шифрование не является проверкой прав доступа.

---

## 📝 Добавление переводов для WebUI

**Файл:** `/opt/tg-bot/core/i18n.py`

Все строки для веб-интерфейса имеют префикс `web_`:

```python
STRINGS = {
    "web_my_feature_title": {
        "ru": "Моя функция",
        "en": "My Feature"
    },
    "web_my_feature_desc": {
        "ru": "Описание функции",
        "en": "Feature description"
    },
}
```

---

## 🔄 Перезапуск

После всех изменений:

**Systemd:**
```bash
sudo systemctl restart tg-bot
```

**Docker:**
```bash
docker compose restart
```

✅ **Готово!** Ваш веб-модуль интегрирован с ботом и WebUI.
