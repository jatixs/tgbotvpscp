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
    ├── streaming.py   → SSE streams
    └── auth.py        → Authentication
    ↓
core/shared_state.py (in-memory data)
core/nodes_db.py (SQLite)
core/messaging.py (Telegram notifications)
```

---

## 🚀 Option 1: Adding an API Endpoint

If you need a JSON API built on `aiohttp`, add a handler to `core/web/api_system.py`.

### Step 1: Create Handler

**File:** `/opt/tg-bot/core/web/api_system.py`

```python
# Add at the end of the file before route definitions
async def api_my_feature(request):
    """Your custom API endpoint."""
    # 1. Check authorization (session)
    session = request.get("session")
    if not session:
        return web.json_response({"error": "Unauthorized"}, status=401)

    # 2. Get request data
    if request.method == "POST":
        data = await request.json()
        param = data.get("param", "")
    else:
        param = request.query.get("param", "")

    # 3. Your logic
    result = {"status": "ok", "data": f"Processed: {param}"}

    # 4. Return JSON
    return web.json_response(result)
```

### Step 2: Register Route

**File:** `/opt/tg-bot/core/web/api_system.py`

Find the `system_routes` list (usually at the end of the file) and add:

```python
system_routes = [
    # ... existing routes ...
    web.get("/api/my-feature", api_my_feature),
    web.post("/api/my-feature", api_my_feature),
]
```

### Step 3: Call from JavaScript

**File:** `/opt/tg-bot/core/static/js/dashboard.js` (or create your own `.js`)

```javascript
async function callMyFeature() {
    try {
        const resp = await fetch('/api/my-feature', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': CSRF_TOKEN  // required for POST
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

> ⚠️ **Important:** All POST requests must include a CSRF token in the `X-CSRF-Token` header. It is available from the `CSRF_TOKEN` variable passed to the template.

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

### Step 2: Add View

**File:** `/opt/tg-bot/core/web/views.py`

```python
async def my_feature_page(request):
    """Your feature page."""
    session = request.get("session")
    if not session:
        raise web.HTTPFound("/login")

    user_role = session.get("role", "users")
    lang = session.get("lang", "ru")

    # Collect i18n strings for frontend
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

### Step 3: Register Route

**File:** `/opt/tg-bot/core/web/views.py`

Add to `view_routes`:

```python
view_routes = [
    # ... existing routes ...
    web.get("/my-feature", my_feature_page),
]
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
    container.innerHTML = `<p class="text-gray-700 dark:text-gray-300">${data.data}</p>`;
}
```

---

## 🔗 Option 3: Connecting WebUI with Telegram Bot

For two-way communication between WebUI and the bot, use `shared_state` and `messaging`.

### Sending Notification from WebUI to Telegram

```python
# In your API handler (core/web/api_system.py)
from core.messaging import send_alert

async def api_my_action(request):
    session = request.get("session")
    if not session:
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()

    # Perform action
    result = do_something(data)

    # Send notification to Telegram (all admins)
    bot = request.app.get("bot")
    if bot:
        await send_alert(
            bot,
            "🔔 Action performed from WebUI",
            alert_type="system"
        )

    return web.json_response({"status": "ok"})
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

1. **CSRF Token** — all POST/PUT/DELETE requests must include `X-CSRF-Token`
2. **Session Check** — always check `request.get("session")`
3. **Role Check** — for dangerous operations check `session.get("role")`
4. **Input Validation** — never trust user input
5. **Encryption** — use `encrypt_for_web()` for sensitive data transmission

### Permission Check Example

```python
async def api_admin_action(request):
    session = request.get("session")
    if not session:
        return web.json_response({"error": "Unauthorized"}, status=401)

    # Admin only
    if session.get("role") not in ("owner", "admins"):
        return web.json_response({"error": "Forbidden"}, status=403)

    # ... logic ...
```

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
