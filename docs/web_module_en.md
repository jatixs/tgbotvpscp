# 🌐 Guide to Creating a Web Module

This guide describes how to create a **web module** — a page or API endpoint in WebUI — and connect it to the Telegram bot.

The web layer is located in `core/web/` and built on **aiohttp** + **Jinja2**. Each component handles its own area:

| File | Purpose |
|------|---------|
| `core/web/app.py` | Initialization, routes, lifecycle |
| `core/web/views.py` | HTML pages (Jinja2) |
| `core/web/auth.py` | Authentication |
| `core/web/api_system.py` | System API |
| `core/web/api_nodes.py` | Node API |
| `core/web/api_metrics.py` | Chart metrics history |
| `core/web/streaming.py` | SSE streams |
| `core/web/middlewares.py` | WAF, CSRF, Rate Limiting |

---

## 📋 Architecture Overview

```
Browser (Frontend)
    ↓ HTTP / SSE
core/web/middlewares.py (WAF → Rate Limit → CSRF)
    ↓
core/web/app.py (routing)
    ├── views.py       → Jinja2 HTML
    ├── api_system.py  → JSON API
    ├── api_nodes.py   → JSON API
    ├── api_metrics.py → JSON API (chart history)
    ├── streaming.py   → SSE streams
    └── auth.py        → Authentication
    ↓
core/shared_state.py (in-memory data)
core/nodes_db.py (SQLite)
core/metrics_history.py (SQLite, metrics history)
core/messaging.py (Telegram notifications)
```

---

## 🚀 Option 1: Adding an API Endpoint

If you need a JSON API built on `aiohttp`, add a handler to `core/web/api_system.py`.

### Step 1: Create Handler

**File:** `/opt/tg-bot/core/web/api_system.py`

```python
# Add at the end of the file before route definitions
@routes.post("/api/my-feature")
async def api_my_feature(request):
    """Example authenticated JSON endpoint."""
    user = get_current_user(request)
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    param = str(data.get("param", ""))[:100]
    return web.json_response({"status": "ok", "user_id": user["id"], "data": param})
```

### Step 2: Register Route

**File:** `/opt/tg-bot/core/web/api_system.py`

`api_system.py` already declares `routes = web.RouteTableDef()`. The `@routes.post(...)` decorator in the example registers the endpoint; do not create a separate `system_routes` list.

### Step 3: Call from JavaScript

**File:** `/opt/tg-bot/core/static/js/dashboard.js` (or create your own `.js`)

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
> ⚠️ **Important:** Mutating `/api/` requests pass through the CSRF middleware. Send the `csrf_token` cookie value in the `X-CSRF-Token` header; do not disable middleware for a new endpoint.

---

## 🚀 Option 2: Adding an HTML Page

If you need a full page with UI.

### Step 1: Create HTML Template

**File:** `/opt/tg-bot/core/templates/my_feature.html`

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

    <!-- Navigation (copy from dashboard.html) -->
    <nav class="...">
        <!-- ... -->
    </nav>

    <!-- Your content -->
    <main class="max-w-7xl mx-auto px-4 pt-20 pb-8">
        <div class="bg-white/60 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/10 rounded-2xl p-6 shadow-lg dark:shadow-none">
            <h1 class="text-xl font-bold text-gray-900 dark:text-white mb-4">
                {{ I18N.my_feature_title }}
            </h1>
            <div id="content">
                <!-- Dynamic content -->
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

### Step 2: Add View

**File:** `/opt/tg-bot/core/web/views.py`

```python
async def my_feature_page(request):
    """Your feature page."""
    user = get_current_user(request)
    if not user:
        raise web.HTTPFound("/login")

    lang = get_user_lang(user["id"])

    # Collect i18n strings for frontend
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

### Step 3: Register Route

**File:** `/opt/tg-bot/core/web/views.py`
In `views.py`, use the existing route table:

```python
@routes.get("/my-feature")
async def my_feature_page(request):
    ...
```

### Step 4: Create JavaScript

**File:** `/opt/tg-bot/core/static/js/my_feature.js`

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

## 🔗 Option 3: Connecting WebUI with Telegram Bot

For two-way communication between WebUI and the bot, use `shared_state` and `messaging`.

### Sending Notification from WebUI to Telegram

```python
# In your API handler (core/web/api_system.py)
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

### Sending Data from Bot to WebUI (via SSE)

```python
# In your module (modules/my_feature.py)
from core.shared_state import WEB_NOTIFICATIONS
import time

async def my_feature_handler(message):
    # ... your logic ...

    # Send event to WebUI via SSE
    WEB_NOTIFICATIONS.append({
        "type": "my_feature",
        "title": "Event from bot",
        "message": "Action performed via Telegram",
        "timestamp": time.time()
    })
```

### Reading Shared State

```python
# In WebUI API (core/web/api_system.py)
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
# In bot module (modules/my_feature.py)
from core.shared_state import WEB_NOTIFICATIONS

# Bot can read WebUI notifications and vice versa
```

---

## 🔒 Security

### Mandatory Rules
1. Resolve the authenticated user with `get_current_user(request)`; do not read a nonexistent `request["session"]`.
2. Use `core.rbac.is_admin(user)` for administrator operations and enforce permissions in every API/callback handler.
3. Mutating `/api/` requests must pass the CSRF middleware with the `X-CSRF-Token` header.
4. Validate input types, ranges, and sizes; authentication does not replace validation.
5. Never send node tokens, passwords, or other secrets in browser payloads. Client-side encryption is not an authorization check.

---

## 📝 Adding Translations for WebUI

**File:** `/opt/tg-bot/core/i18n.py`

All web interface strings use the `web_` prefix:

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

## 🔄 Restart

After all changes:

**Systemd:**
```bash
sudo systemctl restart tg-bot
```

**Docker:**
```bash
docker compose restart
```

✅ **Done!** Your web module is integrated with the bot and WebUI.
