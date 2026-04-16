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
| `core/web/streaming.py` | SSE-потоки |
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
    ├── streaming.py   → SSE потоки
    └── auth.py        → Аутентификация
    ↓
core/shared_state.py (in-memory данные)
core/nodes_db.py (SQLite)
core/messaging.py (Telegram уведомления)
```

---

## 🚀 Вариант 1: Добавление API-эндпоинта

Если вам нужен JSON API на базе `aiohttp`, добавьте хендлер в `core/web/api_system.py`.

### Шаг 1: Создание хендлера

**Файл:** `/opt/tg-bot/core/web/api_system.py`

```python
# Добавьте в конец файла перед определением маршрутов
async def api_my_feature(request):
    """Ваш кастомный API-эндпоинт."""
    # 1. Проверка авторизации (сессия)
    session = request.get("session")
    if not session:
        return web.json_response({"error": "Unauthorized"}, status=401)

    # 2. Получение данных из запроса
    if request.method == "POST":
        data = await request.json()
        param = data.get("param", "")
    else:
        param = request.query.get("param", "")

    # 3. Ваша логика
    result = {"status": "ok", "data": f"Processed: {param}"}

    # 4. Возвращаем JSON
    return web.json_response(result)
```

### Шаг 2: Регистрация маршрута

**Файл:** `/opt/tg-bot/core/web/api_system.py`

Найдите список маршрутов `system_routes` (обычно в конце файла) и добавьте:

```python
system_routes = [
    # ... существующие маршруты ...
    web.get("/api/my-feature", api_my_feature),
    web.post("/api/my-feature", api_my_feature),
]
```

### Шаг 3: Вызов из JavaScript

**Файл:** `/opt/tg-bot/core/static/js/dashboard.js` (или создайте свой `.js`)

```javascript
async function callMyFeature() {
    try {
        const resp = await fetch('/api/my-feature', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': CSRF_TOKEN  // обязательно для POST
            },
            body: JSON.stringify({ param: 'hello' })
        });
        const data = await resp.json();
        console.log(data);
    } catch (err) {
        console.error('API error:', err);
    }
}
```

> ⚠️ **Важно:** Все POST запросы должны включать CSRF-токен в заголовке `X-CSRF-Token`. Он доступен из переменной `CSRF_TOKEN`, которая передается в шаблон.

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

    <script>
        const CSRF_TOKEN = '{{ csrf_token }}';
        const WEB_KEY = '{{ web_key }}';
        const I18N = {{ i18n_json | safe }};
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
    session = request.get("session")
    if not session:
        raise web.HTTPFound("/login")

    user_role = session.get("role", "users")
    lang = session.get("lang", "ru")

    # Собираем строки для i18n на фронтенде
    i18n_keys = ["my_feature_title", "my_feature_desc"]
    i18n_data = {k: get_text(k, lang) for k in i18n_keys}

    context = {
        "lang": lang,
        "page_title": get_text("my_feature_title", lang),
        "app_name": "VPS Manager",
        "csrf_token": session.get("csrf_token", ""),
        "web_key": WEB_KEY,
        "i18n_json": json.dumps(i18n_data, ensure_ascii=False),
        "I18N": i18n_data,
    }

    return aiohttp_jinja2.render_template("my_feature.html", request, context)
```

### Шаг 3: Регистрация маршрута

**Файл:** `/opt/tg-bot/core/web/views.py`

Добавьте в список `view_routes`:

```python
view_routes = [
    # ... существующие маршруты ...
    web.get("/my-feature", my_feature_page),
]
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
    container.innerHTML = `<p class="text-gray-700 dark:text-gray-300">${data.data}</p>`;
}
```

---

## 🔗 Вариант 3: Связь WebUI с Telegram-ботом

Для двусторонней связи между WebUI и ботом используйте `shared_state` и `messaging`.

### Отправка уведомления из WebUI в Telegram

```python
# В вашем API-хендлере (core/web/api_system.py)
from core.messaging import send_alert

async def api_my_action(request):
    session = request.get("session")
    if not session:
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()

    # Выполняем действие
    result = do_something(data)

    # Отправляем уведомление в Telegram всем админам
    bot = request.app.get("bot")
    if bot:
        await send_alert(
            bot,
            "🔔 Действие выполнено из WebUI",
            alert_type="system"
        )

    return web.json_response({"status": "ok"})
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

1. **CSRF-токен** — все POST/PUT/DELETE запросы должны включать `X-CSRF-Token`
2. **Проверка сессии** — всегда проверяйте `request.get("session")`
3. **Проверка роли** — для опасных операций проверяйте `session.get("role")`
4. **Валидация входных данных** — никогда не доверяйте пользовательскому вводу
5. **Шифрование** — используйте `encrypt_for_web()` для передачи чувствительных данных

### Пример проверки прав

```python
async def api_admin_action(request):
    session = request.get("session")
    if not session:
        return web.json_response({"error": "Unauthorized"}, status=401)

    # Только для админов
    if session.get("role") not in ("owner", "admins"):
        return web.json_response({"error": "Forbidden"}, status=403)

    # ... логика ...
```

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
