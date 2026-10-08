# 📘 Архитектура проекта: VPS Manager Telegram Bot

## 🎯 Обзор системы

**VPS Manager Telegram Bot** — это профессиональная система управления инфраструктурой, построенная на современной асинхронной архитектуре. Проект реализует паттерн **Агент-Клиент**, где центральный бот управляет сетью удаленных серверов через унифицированный API.

### 🏗 Архитектурные принципы

1. **Модульность** — каждая функция изолирована в отдельном модуле
2. **Асинхронность** — полная поддержка asyncio для высокой производительности
3. **Безопасность** — многоуровневая защита (WAF, Rate Limiting, шифрование)
4. **Масштабируемость** — поддержка неограниченного числа удаленных нод
5. **Отказоустойчивость** — система Watchdog и автоматический перезапуск
6. **Разделение ответственности** — веб-слой вынесен в `core/web/`, бот-логика в `modules/`

## 🔒 HTTPS и подключение нод

`WEB_PUBLIC_URL` — канонический публичный HTTPS origin панели. При managed TLS установщик настраивает Nginx и Certbot; внешний reverse proxy должен сам выпускать и продлевать сертификат. Systemd WebUI по умолчанию слушает loopback, Docker публикует порт только на host loopback.

Для домена и глобального публичного IPv4 поддерживается HTTPS. IP-сертификат Let's Encrypt использует short-lived профиль и действует 160 часов. HTTP-01 требует доступный извне TCP-порт 80; managed renewal проверяется ежечасно. Private/local IP не подходят.

Новые агенты подключаются к HTTPS origin. `GET /api/agent/https` объявляет URL без токена; bootstrap передает секрет в `X-Node-Token`, heartbeat подписывается HMAC. Обновленный агент проверяет TLS и тот же hostname, затем сохраняет HTTPS URL. При переходе со старой systemd-установки ограниченный HTTP bridge временно обслуживает только discovery/bootstrap и подписанный heartbeat. После обновления всех агентов выполните `tgcp-bot tls status`, затем `tgcp-bot tls finalize`.

Браузерные страницы используют числовой ID ноды. Агентские токены не помещаются в URL или клиентские JSON-ответы.

---

## 📂 Структура проекта

### 🔹 Корневой уровень

```
/opt/tg-bot/
├── bot.py                    # Точка входа, инициализация приложения
├── watchdog.py              # Мониторинг здоровья, автоперезапуск
├── migrate.py               # Система миграции данных
├── manage.py                # CLI для управления ботом
├── .env                     # Конфигурация (секреты, токены)
├── requirements.txt         # Python зависимости
├── docker-compose.yml       # Docker конфигурация
├── Dockerfile               # Образ контейнера
└── deploy.sh               # Автоматизированный установщик
```

#### **bot.py** — Главный файл приложения
**Назначение:** Точка входа в систему, оркестратор всех компонентов

**Основные функции:**
- Инициализация Aiogram Bot и Dispatcher с MemoryStorage
- Подключение SQLite базы данных (Tortoise ORM)
- Запуск веб-сервера через `core/web/app.py` на порту 8080
- Регистрация **18 функциональных модулей** и middleware
- Обработка lifecycle events (startup/shutdown)
- Интеграция с Sentry для мониторинга ошибок
- Категоризированное меню: Мониторинг, Управление, Безопасность, Инструменты, Настройки
- Fallback-обработчик неизвестных команд (возвращает случайные интересные факты с API uselessfacts и переводит их через Google Translate)

**Регистрация модулей:**
```python
register_module(selftest)          # Доступно всем
register_module(users, admin_only=True)  # Только админам
register_module(reboot, root_only=True)  # Только root
```

**Технологии:** Aiogram 3.x, AsyncIO, Tortoise ORM

---

#### **watchdog.py** — Система мониторинга
**Назначение:** Обеспечение непрерывной работы бота

**Основные функции:**
- Проверка активности процесса бота (health check)
- Автоматический перезапуск при сбое
- Отправка уведомлений о статусе (start/stop/crash)
- Логирование событий системы
- Мониторинг потребления ресурсов

**Режимы работы:**
- Systemd service (классическая установка)
- Docker container (контейнеризация)

---

### 🔹 Директория `core/` — Ядро системы

```
core/
├── config.py               # Центральная конфигурация
├── auth.py                 # Система авторизации (Telegram)
├── i18n.py                 # Интернационализация
├── keyboards.py            # Генерация UI элементов
├── messaging.py            # Система уведомлений
├── middlewares.py          # Anti-spam, фильтры (Telegram)
├── utils.py                # Вспомогательные утилиты
├── nodes_db.py             # База данных нод (Tortoise ORM)
├── metrics_history.py      # История метрик для графиков (3 мин … 7 дней)
├── models.py               # ORM модели
├── orchestrator.py         # Memory Orchestrator (Lazy Loading / GC)
├── shared_state.py         # Глобальное состояние (in-memory)
├── tasks.py                # Фоновые задачи (мониторинг, очистка)
├── web/                    # 🌐 Веб-сервер (подробнее ниже)
│   ├── app.py              # Инициализация aiohttp, маршруты
│   ├── auth.py             # Аутентификация (Web)
│   ├── middlewares.py      # WAF, Rate Limiting, CSRF
│   ├── api_nodes.py        # API управления нодами
│   ├── api_system.py       # API системных настроек
│   ├── streaming.py        # Server-Sent Events (SSE)
│   └── views.py            # HTML-представления (Jinja2)
├── static/                 # CSS, JS, изображения
│   ├── css/
│   │   ├── login.css       # Стили авторизации
│   │   ├── main.css        # Общие стили Tailwind
│   │   └── style.css       # Компоненты и анимации
│   └── js/
│       ├── common.js       # Шифрование, модалки, toast
│       ├── chart_range.js  # Выбор периода графиков и опрос истории
│       ├── dashboard.js    # Логика дашборда и SSE
│       ├── login.js        # Авторизация
│       ├── nodes_monitor.js # Мониторинг нод
│       ├── settings.js     # Настройки и уведомления
│       ├── reset_password.js # Сброс пароля
│       └── theme_init.js   # Темы оформления
└── templates/              # HTML шаблоны (Jinja2)
    ├── dashboard.html      # Главная панель
    ├── login.html          # Страница входа
    ├── nodes_monitor.html  # Мониторинг нод
    ├── reset_password.html # Сброс пароля
    ├── settings.html       # Настройки
    └── terminal.html       # Веб-терминал SSH
    └── terminal.html       # Web SSH terminal
```

---

#### **config.py** — Конфигурационный центр
**Назначение:** Централизованное управление настройками

**Загружаемые параметры:**
- `TOKEN` — Токен Telegram бота
- `ALERT_BOT_TOKEN` — Токен Gateway-бота (опционально)
- `ADMIN_USER_ID` — ID главного администратора
- `WEB_SERVER_HOST/PORT` — Настройки веб-сервера
- `DEPLOY_MODE` — Режим установки (root/secure)
- `DEFAULT_LANGUAGE` — Язык по умолчанию
- `ENABLE_WEB_UI` — Включение веб-интерфейса
- Пути к директориям (логи, конфиг, бэкапы)

**Функции:**
- `load_encrypted_json()` — Чтение зашифрованных конфигов
- `save_encrypted_json()` — Сохранение с Fernet шифрованием
- `save_system_config()` — Запись системных настроек
- `save_keyboard_config()` — Конфигурация клавиатуры
- `setup_logging()` — Настройка логирования (Debug/Release)

---

#### **auth.py** — Система авторизации (Telegram)
**Назначение:** Управление доступом пользователей бота

**Иерархия ролей:**
1. **Root/Owner** (ADMIN_USER_ID) — полный доступ, включая опасные операции
2. **Admins** — управление нодами, пользователями, генерация ссылок
3. **Users** — только просмотр статистики

**Функции:**
- `is_root_admin()` — Проверка владельца
- `is_admin()` — Проверка административных прав
- `is_allowed()` — Валидация доступа к команде
- `load_users()` / `save_users()` — Работа с зашифрованным списком пользователей
- `refresh_user_names()` — Обновление имен через Telegram API

**Хранилище:** `/opt/tg-bot/config/users.json` (Fernet encryption)

---

#### **i18n.py** — Система интернационализации
**Назначение:** Многоязычная поддержка интерфейса

**Поддерживаемые языки:**
- Русский (ru) — основной
- English (en) — полный перевод

**Структура переводов:**
```python
STRINGS = {
    "key_name": {
        "ru": "Русский текст",
        "en": "English text"
    }
}
```

**Основные функции:**
- `get_text(key, lang)` — Получение перевода (алиас `_()`)
- `get_user_lang(user_id)` — Язык пользователя из кэша
- `set_user_lang(user_id, lang)` — Установка языка
- `I18nFilter` — Aiogram-фильтр для перехвата кнопок на любом языке

**Хранилище:** Настройки языка в `shared_state.USER_SETTINGS`

---

#### **keyboards.py** — Генератор UI
**Назначение:** Динамическое создание клавиатур для Telegram

**Типы клавиатур:**
1. **Reply Keyboard** — Основное категоризированное меню
2. **Inline Keyboard** — Callback кнопки в сообщениях

**Функции:**
- `get_main_reply_keyboard(user_id)` — Главное меню (5 категорий)
- `get_subcategory_keyboard(category, user_id)` — Подменю категории
- `get_manage_users_keyboard()` — Управление пользователями
- `get_keyboard_settings_inline()` — Настройка видимости кнопок

**Адаптивность:** Кнопки автоматически скрываются/показываются в зависимости от:
- Роли пользователя (Root/Admin/User)
- Режима установки (`DEPLOY_MODE`: root/secure)
- Конфигурации видимости (`KEYBOARD_CONFIG`)



**Особенности генерации:**
- **Динамическая пагинация:** Кнопки адаптивно выстраиваются по 2 в ряд (`get_subcategory_keyboard`).
- **Управление видимостью:** Администраторы могут скрывать/показывать модули через `KEYBOARD_CONFIG`.
- **Ролевой доступ:** Фильтрация кнопок в зависимости от роли (Root/Admin/User) и режима установки.
---

#### **messaging.py** — Система уведомлений
**Назначение:** Централизованная отправка сообщений и алертов

**Функции:**
- `send_alert()` — Отправка уведомления всем админам
  - Поддержка HTML разметки
  - Автоматический перевод на язык получателя
  - Дублирование в веб-панель через SSE
- `delete_previous_message()` — Удаление старого сообщения (anti-spam)
- `send_support_message()` — Ссылка на техподдержку

**Типы уведомлений:**
- ⚠️ Превышение порогов ресурсов (CPU/RAM/Disk)
- 🔒 SSH-входы на сервер
- 🛡️ Бан IP через Fail2Ban
- 📡 Даунтайм ноды (нода офлайн > 60 сек)
- 🚀 Системные события (старт/рестарт бота)

**Каналы доставки:**
- Telegram API (прямая доставка)
- Веб-панель через `WEB_NOTIFICATIONS` deque + SSE
- Логирование в `logs/bot/bot.log`

---

#### **middlewares.py** — Middleware слой (Telegram)
**Назначение:** Обработка запросов до вызова хендлеров бота

**1. SpamThrottleMiddleware:**
- Защита от флуда (макс. 1 запрос в секунду на пользователя)
- Хранение времени последнего запроса в памяти
- Применяется глобально для messages и callback queries

**2. AutoDeleteMessageMiddleware:**
- Автоматически удаляет текстовые команды и нажатия меню для сохранения чистоты чата

**3. CallbackTTLMiddleware:**
- Защита от устаревших меню (30 секунд) с автоматическим уведомлением об обновлении

---

#### **utils.py** — Утилиты и хелперы
**Назначение:** Общие вспомогательные функции

**Форматирование:**
- `format_bytes(bytes)` — Конвертация байт в KB/MB/GB
- `format_uptime(seconds)` — Преобразование секунд в читаемый формат
- `get_country_flag(ip)` — Получение флага страны по IP (GeoIP)

**Безопасность:**
- `encrypt_for_web(data)` — AES-256-CBC + Base64 шифрование для SSE
- `decrypt_for_web(data)` — Расшифровка на стороне клиента
- `log_audit_event()` — запись событий аудита; эксплуатация должна отдельно определить срок хранения и требования compliance
- `mask_sensitive_data()` — Маскировка IP, токенов, паролей в логах

**Система:**
- `get_host_path()` — Корректные пути для Docker (`/proc_host`)
- `get_app_version()` — Версия из CHANGELOG
- `get_server_timezone_label()` — Часовой пояс сервера
- `generate_favicons()` — Генерация иконок для PWA

**Конфигурация сервисов:**
- `load_services_config()` / `save_services_config()` — Работа с `config/services.json` (Fernet)

---

#### **nodes_db.py** — База данных нод
**Назначение:** Управление удаленными серверами через Tortoise ORM

**ORM:** Tortoise ORM + SQLite (`config/nodes.db`)

**Основные функции:**
- `init_db()` — Инициализация базы и схемы
- `add_node()` — Регистрация новой ноды (генерация токена)
- `get_node_by_token()` — Поиск по токену авторизации
- `update_node_metrics()` — Обновление метрик (CPU, RAM, Disk)
- `get_all_nodes()` — Список всех серверов
- `delete_node()` — Удаление ноды (вместе с её историей метрик)

Каждый heartbeat также передаёт замер в `metrics_history` (скорость сети считается по разнице счётчиков `net_rx`/`net_tx` между heartbeat).

---

#### **metrics_history.py** — История метрик для графиков
**Назначение:** хранение CPU/RAM/диск/сеть агента и нод для графиков с выбором периода (как в Zabbix/Grafana)

**Хранение (таблица `metric_samples`, скользящее окно как в RRD):**

| Уровень (`res`) | Шаг | Хранится | Обслуживает периоды |
|-----------------|-----|----------|---------------------|
| `0` — сырые замеры | 2 с (агент) / heartbeat (нода) | 1 ч 10 мин | 3m, 10m, 30m, 1h |
| `60` — минутные корзины | 60 с | 25 ч | 3h, 6h, 12h |
| `300` — пятиминутные корзины | 300 с | 7 д 2 ч | 1d, 3d, 7d |

**Принцип работы:**
- `record_sample()` — кладёт замер в буфер в памяти; скорость сети хранится в байтах/с (из счётчиков или готовой скорости)
- `maintenance_loop()` (фоновая задача `metrics-history`): каждые 10 с сбрасывает буфер в БД одним `bulk_create`, раз в минуту идемпотентно пересчитывает корзины 60/300 с за последние 3/15 минут (после старта — за весь срок хранения нижнего уровня), раз в 10 минут удаляет строки старше срока хранения
- `query_series(source, range, since)` — выбирает уровень по периоду и при необходимости доусредняет до шага вывода (6h → 120 с, 12h → 180 с, 3d → 15 мин, 7d → 30 мин); `since` даёт инкременты для SSE-потока `/api/events/metrics`
- Источники: `agent` и `node:<id>`; при удалении ноды её история удаляется

**Объём:** в установившемся режиме ≈ 5–6 тыс. строк на источник (~0,5 МБ); база не растёт бесконечно, SQLite переиспользует освобождённые страницы.

---

#### **models.py** — ORM модели
**Назначение:** Определение структуры данных (Tortoise ORM)

**Модели:**
- `User` — Пользователи бота (Telegram ID, роль, язык)
- `Node` — Удаленные серверы (токен, имя, IP, метрики)
- `MetricSample` — Точка истории метрик (`source`, `res`, `t`, `cpu`, `ram`, `disk`, `rx`, `tx`)
- `Alert` — История уведомлений
- `TrafficLog` — Логи сетевого трафика

**Миграции:** Управляются через Aerich (`aerich.ini`)

---

#### **orchestrator.py** — Memory Orchestrator
**Назначение:** Динамическое управление загрузкой модулей для экономии RAM

**Функции:**
- Отложенная загрузка (Lazy Loading) "тяжелых" модулей (например, matplotlib в speedtest)
- Выгрузка модулей из памяти после 5 минут неактивности (Garbage Collection)
- Защита от перегрузки оперативной памяти на слабых VPS
- Управление зависимостями и регистрацией обработчиков (aiogram)

---

#### **shared_state.py** — Глобальное состояние
**Назначение:** In-memory хранилище для высокой производительности

**Основные структуры:**
- `ALLOWED_USERS: dict` — Кэш авторизованных пользователей
- `USER_SETTINGS: dict` — Языковые настройки
- `USER_NAMES: dict` — Имена пользователей (Telegram)
- `AUTH_TOKENS: dict` — Токены нод для heartbeat
- `NODE_TRAFFIC_MONITORS: dict` — Активные мониторы трафика
- `ALERTS_CONFIG: dict` — Конфигурация порогов уведомлений
- `AGENT_HISTORY: deque` — Последние 60 замеров агента для SSE (текущая скорость сети); долгая история — в `metrics_history`
- `WEB_NOTIFICATIONS: deque` — Уведомления для веб-панели
- `WEB_USER_LAST_READ: dict` — Последнее прочитанное уведомление

**Особенности:**
- Использование `collections.deque` для ограничения памяти
- Периодическая очистка через `gc.collect()`

---

#### **tasks.py** — Фоновые задачи
**Назначение:** Периодические процессы, запускаемые при старте веб-сервера

**agent_monitor():**
- Обновляет кэш публичного IP агента (`AGENT_IP_CACHE`)
- Обновляет флаг страны (`AGENT_FLAG`)
- Измеряет пинг агента (`AGENT_PING_CACHE`)
- Записывает историю метрик в `AGENT_HISTORY` (CPU%, RAM%, RX, TX) и передаёт замер в `metrics_history.record_sample()`

**metrics_history.maintenance_loop() — каждые 10 секунд:**
- Сбрасывает буфер замеров в таблицу `metric_samples`
- Раз в минуту строит минутные и пятиминутные корзины
- Раз в 10 минут удаляет данные старше срока хранения (1 ч / 25 ч / 7 д)

**cleanup_monitor() — каждые 600 секунд:**
- Удаляет истекшие веб-сессии
- Очищает `RESET_TOKENS` (TTL 10 мин)
- Очищает `AUTH_TOKENS` (TTL 5 мин)
- Очищает `CSRF_TOKENS` (TTL 1 час)
- Сбрасывает `LOGIN_ATTEMPTS` по IP (окно 5 мин)

---

### 🔹 Директория `core/web/` — Веб-сервер

Веб-слой реализован как отдельный пакет с четким разделением ответственности:

```
core/web/
├── app.py              # Инициализация, маршрутизация, lifecycle
├── auth.py             # Аутентификация (пароль, magic link, Telegram widget)
├── middlewares.py      # WAF, Rate Limiting, CSRF Protection
├── api_nodes.py        # API на базе aiohttp для нод (heartbeat, CRUD, команды)
├── api_system.py       # API на базе aiohttp для настроек, логов, пользователей
├── streaming.py        # Server-Sent Events (5 потоков, включая историю графиков)
└── views.py            # HTML-страницы (Jinja2 рендеринг)
```

#### **app.py** — Точка входа веб-сервера
**Назначение:** Создание и конфигурация aiohttp Application

**Функции:**
- Создает `aiohttp.web.Application` с middleware стеком
- Регистрирует маршруты из 5 модулей (views, auth, nodes, system, streaming)
- Подключает статические файлы (`/static/`)
- Запускает фоновые задачи из `tasks.py` при startup
- Обрабатывает graceful shutdown через `shutdown_event`

**Маршрутизация:**
```python
view_routes      → HTML-страницы
auth_routes      → Аутентификация
node_routes      → API нод
system_routes    → Системные API
streaming_routes → SSE потоки
```

---

#### **auth.py** (web) — Аутентификация веб-панели
**Назначение:** Множественные методы входа с разным TTL сессий

**Методы аутентификации:**

| Метод | TTL сессии | Кому доступен |
|-------|-----------|---------------|
| Пароль (Argon2) | 7 дней | Только главный админ |
| Magic Link | 30 дней (сессия) / 5 мин (ссылка) | Все пользователи бота |
| Telegram Widget | 30 дней | Все пользователи бота |

**Эндпоинты:**
- `POST /api/login/password` — Вход по паролю (только ADMIN)
- `POST /api/login/request` — Запрос magic link (отправка в Telegram)
- `GET /api/login/magic?token=...` — Активация magic link
- `POST /api/auth/telegram` — Вход через Telegram Widget (HMAC validation)
- `POST /api/logout` — Выход и удаление сессии
- `POST /api/request_reset` — Запрос сброса пароля
- `POST /api/reset_password` — Сброс пароля по токену

**Защита:**
- Rate limiting: 5 попыток за 5 минут (по IP)
- Constant-time comparison (Argon2)
- HMAC validation для Telegram Widget
- CSRF-токены на каждый запрос (TTL 1 час)

---

#### **middlewares.py** (web) — 3 слоя защиты
**Назначение:** Безопасность на уровне HTTP-запросов

**1. Rate Limit Middleware:**
- 100 запросов/мин на IP на endpoint
- Ограничение частоты запросов; клиентский IP учитывает только доверенную proxy-конфигурацию
- **Logging and privacy:**
- Наличие audit log само по себе не гарантирует соответствие законодательству
- xterm.js — браузерный SSH-терминал (не VNC)
- Автоматический сброс окна

**2. CSRF Middleware:**
- Генерация CSRF-токена при загрузке страницы
- Валидация для всех POST/PUT/DELETE запросов
- Исключение: маршруты heartbeat нод

**3. WAF Middleware (Web Application Firewall):**
```
Обнаруживаемые атаки:
├── SQL Injection (UNION, SELECT, DROP, INSERT)
├── XSS (<script>, javascript:, on* атрибуты)
├── Path Traversal (../, %2e%2e/)
├── Command Injection (bash, sh, wget, curl)
└── LDAP Injection
```

---

#### **api_nodes.py** — API управления нодами
**Назначение:** CRUD операции и heartbeat протокол

**Примечание:**
- `GET /api` и `GET /api/` возвращают JSON-индекс API, а не метрики.
- Прямой переход браузером на `GET /api/events*` не должен использоваться: эти маршруты работают только как внутренние SSE-потоки WebUI.

**Ключевой эндпоинт — `/api/heartbeat`:**
- Ноды отправляют статус с HMAC-подписью
- Обновляет метрики: CPU, RAM, Disk, Uptime, Network Speed
- Обрабатывает SSH-логины → отправляет alerts
- Возвращает очередь команд для ноды

**Эндпоинты:**
```
GET  /api/heartbeat                     — Health probe
GET  /api/agent/https                   — Публичный HTTPS origin агента
GET  /api/node/bootstrap                — Bootstrap по X-Node-Token
POST /api/heartbeat                     — Heartbeat от ноды с HMAC-подписью
GET  /api/nodes/list                    — Список нод (зашифровано)
POST /api/nodes/add                     — Добавить ноду
POST /api/nodes/delete                  — Удалить ноду
POST /api/nodes/rename                  — Переименовать (admin only)
GET  /api/nodes/monitor/list            — Данные для страницы мониторинга
GET  /api/nodes/monitor/detail?node_id= — Детали ноды по числовому ID (WebUI session)
GET  /api/nodes/monitor/services?node_id= — Сервисы по числовому ID (WebUI session)
POST /api/nodes/monitor/command         — Отправить команду на ноду
POST /api/nodes/monitor/service_action  — Управление сервисом на ноде
GET  /api/services                      — Список управляемых сервисов
GET  /api/services/available            — Список доступных сервисов
GET  /api/services/info/{name}          — Детали сервиса
POST /api/services/{action}             — Start/Stop/Restart сервиса
POST /api/services/manage               — Добавить/удалить сервис из мониторинга
```

---

#### **api_system.py** — Системные API
**Назначение:** Настройки, логи, пользователи, обновления

**Эндпоинты:**
```
GET  /api/logs                 — Логи бота (последние 300 строк)
GET  /api/logs/system          — Системные логи (journalctl)
POST /api/logs/clear           — Очистить логи

POST /api/settings/save        — Сохранить уведомления (алерты)
POST /api/settings/system      — Пороги CPU/RAM/Disk
POST /api/settings/keyboard    — Видимость кнопок бота
POST /api/settings/metadata    — Favicon, Title, Description (SEO)
POST /api/settings/language    — Смена языка WebUI

POST /api/users/action         — Добавление/удаление пользователей
GET  /api/sessions/list        — Активные веб-сессии
POST /api/sessions/revoke      — Отзыв сессии
POST /api/sessions/revoke_all  — Отзыв всех остальных сессий

GET  /api/update/check         — Проверка обновлений (GitHub)
POST /api/update/run           — Запуск обновления

GET  /api/notifications/list   — Список уведомлений
POST /api/notifications/read   — Отметить прочитанным
POST /api/notifications/clear  — Очистить все
POST /api/traffic/reset        — Сброс статистики трафика
GET  /api/agent/ipv4           — IPv4 адреса агента
```

---

#### **streaming.py** — Server-Sent Events
**Назначение:** Real-time обновления без WebSocket

**SSE-потоки:**

**1. `GET /api/events` — Главный поток:**
- `agent_stats` — CPU, RAM, Disk, Network, последние 60 замеров (для текущей скорости); сами графики получают данные из потока `/api/events/metrics`
- `nodes_list` — Список всех нод со статусами
- `notifications` — Уведомления (фильтрация по последнему прочтению)

**2. `GET /api/events/logs` — Логи в реальном времени:**
- Bot logs — слежение за файлом (`tail -f` стиль)
- System logs — `journalctl --follow`

**3. `GET /api/events/node` — Детали конкретной ноды:**
- Статистика, доступность, биллинг (графики модального окна подписаны на `/api/events/metrics`)
- Обновления через параметр `?token=...`
- Обновления по числовому параметру `node_id`; agent token не передается браузеру

**4. `GET /api/events/services` — Поток менеджера сервисов:**
- Статусы systemd-сервисов в реальном времени
- Обновления для страницы Service Manager

**5. `GET /api/events/metrics?source=agent|node&node_id=…&range=3m…7d` — История для графиков:**
- Событие `metrics_history`: `{range, step, span, now, full, data}` — `data` это зашифрованный (`encrypt_for_web`) JSON-массив точек `[{t, c, r, d, rx, tx}]`, `rx`/`tx` в байтах/с, `step` в секундах (`0` = сырые точки)
- Первое сообщение — полный снимок (`full: true`), далее инкременты с интервалом по периоду (3 с для 3m … 5 мин для 7d); последняя корзина пересылается, пока не заполнится
- Смена периода в браузере переоткрывает поток с новым `range`; нода адресуется числовым `node_id`

**Ограничение:** при обычном переходе из браузера `GET /api/events*` возвращает информационный текст, а не метрики. Для работы требуется `EventSource` с `Accept: text/event-stream`. Аналогично `GET /api/terminal/ws` требует `Upgrade: websocket` и для обычного HTTP-запроса отвечает `426 Upgrade Required`.

**Шифрование:** Все данные шифруются AES-256-CBC + Base64 через `encrypt_for_web()` перед отправкой.

---

#### **views.py** — HTML-представления
**Назначение:** Серверный рендеринг страниц через Jinja2

**Маршруты:**
```
GET  /                → dashboard.html (требуется авторизация)
GET  /login           → login.html
GET  /nodes           → nodes_monitor.html
GET  /settings        → settings.html
GET  /terminal        → terminal.html (веб-терминал)
GET  /reset-password  → reset_password.html
GET  /site.webmanifest → PWA manifest (JSON)
```

**Контекст шаблонов:**
```python
{
    "I18N": { ... },         # Локализованные строки
    "USER_ROLE": "owner",    # Роль текущего пользователя
    "IS_MAIN_ADMIN": True,   # Является ли главным админом
    "WEB_KEY": "...",        # Ключ для AES-дешифровки
    "CSRF_TOKEN": "...",     # CSRF-токен
}
```

---

### 🔹 Директория `modules/` — Функциональные модули

```
modules/
├── selftest.py             # Сводка о сервере (CPU/RAM/Disk/IP)
├── traffic.py              # Мониторинг сетевого трафика
├── uptime.py               # Время работы без перезагрузки
├── top.py                  # Топ-10 процессов по CPU
├── speedtest.py            # Тест скорости (iperf3 / Ookla)
├── notifications.py        # Фоновые проверки и алерты
├── users.py                # Управление пользователями
├── client_alerts.py        # Gateway Bot / Alert System (Тикеты, Рассылки)
├── nodes.py                # Управление нодами (Мониторинг, Биллинг, UI)
├── services.py             # Менеджер системных сервисов
├── backups.py              # Менеджер бэкапов (Traffic/Config/Logs/Nodes)
├── vless.py                # Генерация VLESS ссылок
├── xray.py                 # Обновление Xray Core
├── sshlog.py               # Логи SSH входов
├── fail2ban.py             # Логи заблокированных IP
├── logs.py                 # Системные логи (journalctl)
├── update.py               # Обновление бота и системы
├── reboot.py               # Перезагрузка сервера
├── restart.py              # Перезапуск бота
└── optimize.py             # Оптимизация системы
```


#### **client_alerts.py** — Gateway Bot (Шлюз Поддержки)
**Назначение:** Отдельный Telegram-бот для связи с клиентами, рассылок и уведомлений.
**Особенности:**
- Работает параллельно с основным ботом, используя отдельный токен (ALERT_BOT_TOKEN).
- **Тикет-система:** Сообщения от клиентов пересылаются администраторам в виде тикетов с поддержкой Reply.
- **Массовые рассылки:** Функционал для отправки информационных сообщений всем клиентам (подписчикам).
- **Anti-Flood:** Встроенная защита от спама (Throttle), предотвращающая перегрузку бота.
- Подписчики и их настройки уведомлений хранятся в shared_state.

#### **nodes.py** — Управление нодами (Telegram UI)
**Назначение:** Интерактивное управление удаленными серверами напрямую через Telegram-бота.
**Особенности:**
- Генерация токенов авторизации для новых нод в пару кликов.
- **Биллинг (Отслеживание аренды):** Встроенный функционал учета дней и стоимости аренды мастер-сервера и нод.
- Детальный мониторинг состояния нод (CPU/RAM/Disk/Network) в виде удобных карточек.
- Удаление и переименование нод через интерактивное меню.

#### Интерфейс модуля

Каждый модуль реализует единый контракт:

```python
# Обязательные функции:
BUTTON_KEY = "btn_my_feature"       # Ключ кнопки в i18n

def get_button() -> KeyboardButton:
    """Кнопка для клавиатуры"""
    
def register_handlers(dp: Dispatcher):
    """Регистрация Aiogram-хендлеров"""

# Опциональные:
def start_background_tasks(bot) -> list[asyncio.Task]:
    """Фоновые задачи модуля"""

def get_subcategory() -> str:
    """Категория: monitoring/management/security/tools"""
    
def has_subcategory() -> bool:
    """Имеет ли подменю"""
```

---

#### **notifications.py** — Система алертов
**Назначение:** Фоновый мониторинг и уведомления

**Проверяемые метрики:**
- CPU > 80% (порог настраиваемый, 50–99%)
- RAM > 90%
- Disk > 85%
- Даунтайм ноды > 60 секунд

**Механизм:**
- Асинхронная задача `asyncio.create_task(check_alerts_loop())`
- Интервал проверки: 30 секунд
- Дебаунс: повторное уведомление через 5 минут
- Grace-период при старте (против ложных алертов)

**Конфигурация:**
- Глобальные пороги (для агента)
- Индивидуальные пороги (для каждой ноды)
- Синхронизация между ботом и WebUI в реальном времени

---

#### **services.py** — Менеджер сервисов
**Назначение:** Управление systemd сервисами через бот и WebUI

**Возможности:**
- Просмотр статуса всех сервисов (ssh, docker, nginx, mysql, etc.)
- Start/Stop/Restart сервисов
- Добавление/удаление из списка мониторинга
- Real-time обновления через SSE

**Безопасность:**
- Шифрование данных: AES-256-CBC + Base64 (бэкенд → фронтенд)
- Персистентная конфигурация: `config/services.json` (Fernet)

---

#### **backups.py** — Менеджер бэкапов
**Назначение:** Управление резервными копиями

**Категории:** Traffic / Config / Logs / Nodes

**Возможности:**
- Ручное создание бэкапа с отправкой файла в Telegram
- Автобэкап с настраиваемым таймером (шаг 30 сек → x2 после 10 мин)
- Ротация: хранение 5 последних копий, автоудаление старых
- Восстановление и массовое удаление

---

### 🔹 Директория `node/` — Клиент для удаленных серверов

```
node/
└── node.py                 # Агент для отправки метрик
```

#### **node.py** — Агент ноды
**Назначение:** Легковесный клиент для удаленных VPS

**Функции:**
- Сбор метрик системы (CPU, RAM, Disk, Uptime, Network Speed)
- Heartbeat на главный сервер (`POST /api/heartbeat`) с HMAC-подписью
- Выполнение команд по запросу от агента (selftest, speedtest, reboot)
- SSH-мониторинг с отправкой логов входов
- Управление сервисами на ноде (по запросу из WebUI)

**Требования:**
- Python 3.10+
- Библиотеки: requests, psutil; PyYAML для дополнительных YAML-based checks
- Доступный публичный HTTPS origin master; managed TLS дополнительно требует inbound TCP/80

---

## 🔐 Система безопасности

### Уровни защиты

#### 1️⃣ Telegram Bot Security
- **Whitelist** — Только авторизованные Telegram ID
- **Role-based Access Control** — Root / Admin / User
- **Anti-spam middleware** — Throttling 1 req/sec per user

#### 2️⃣ Web Panel Security
- **Argon2** — Password hashing (OWASP recommended)
- **Server-side sessions** — Безопасные куки (7–30 дней TTL)
- **CSRF Protection** — Токены для всех POST запросов (TTL 1 час)
- **Brute-force Protection** — 5 попыток → блокировка IP на 5 минут
- **Rate Limiting** — 100 запросов/мин на IP на endpoint
- **Magic Link** — Безпарольный вход через Telegram (TTL 5 мин)
- **Telegram Widget** — OAuth через HMAC-валидацию

#### 3️⃣ WAF (Web Application Firewall)
Паттерны атак:
- SQL Injection (`UNION SELECT`, `OR 1=1`, `DROP TABLE`)
- XSS (`<script>`, `javascript:`, `on*` атрибуты)
- Path Traversal (`../`, `%2e%2e`)
- Command Injection (`bash`, `sh`, `wget`, `curl`)
- LDAP Injection

#### 4️⃣ Data Encryption
- **Fernet (AES)** — шифрование конфигурационных JSON-файлов
- **AES-256-CBC + Base64** — шифрование payload для SSE-клиента
- **HMAC-SHA256** — проверка подлинности heartbeat от нод

#### 5️⃣ Audit Logging
**Местоположение:** `logs/audit/audit.log`

Журнал содержит события аудита; IP и секреты в предупреждениях маскируются. Настройте собственные сроки хранения и доступа к логам, не рассматривайте сам факт наличия audit log как гарантию соответствия требованиям.

---

## 🔄 Жизненный цикл приложения

### Startup Sequence

```
1. Загрузка .env и настройка логирования
2. Инициализация SQLite/Tortoise ORM и конфигурации
3. Создание Telegram Bot и Dispatcher
4. Настройка `ModuleOrchestrator` и регистрация модулей из `MODULE_CONFIG`
5. Запуск aiohttp WebUI согласно `WEB_SERVER_HOST/PORT`
6. Запуск фоновых задач приложения и модулей
7. Запуск Telegram polling
```

### Shutdown Sequence

```
1. Получение сигнала (SIGTERM/SIGINT)
2. Остановка Aiogram polling
3. Отмена фоновых задач (graceful, timeout 5 сек)
4. Остановка веб-сервера (cleanup, timeout 5 сек)
5. Закрытие соединений с БД (Tortoise ORM)
6. Закрытие HTTP-сессии бота
7. Логирование завершения
```

### Watchdog Flow

```
while True:
    if bot_process_alive():
        send_heartbeat()
    else:
        log_crash_event()
        send_alert("Bot crashed, restarting...")
        restart_bot_process()
    sleep(30)
```

---

## 📊 Потоки данных

### Metrics Collection Flow (Ноды → Агент)

```
Remote Node (node.py)
    ↓ (heartbeat с настраиваемым интервалом)
POST /api/heartbeat (HMAC signature)
    {
        "cpu": 45.2, "ram": 72.1,
        "disk": 38.5, "uptime": 864000,
        "net_speed": {"rx": 1024, "tx": 512}
    }
    ↓
api_nodes.py → Валидация HMAC
    ↓
Обновление nodes_db (SQLite) + замер в metrics_history
    ↓
Проверка порогов → Отправка алерта (если нужно)
    ↓
Трансляция через SSE → WebUI обновляется в реальном времени
```

### Chart History Flow (История графиков)

```
agent_monitor (каждые 2 с) / heartbeat ноды
    ↓ record_sample()
Буфер в памяти → (10 с) → metric_samples res=0
    ↓ (1 мин, идемпотентно)
res=60 (среднее за минуту) → res=300 (среднее за 5 минут)
    ↓ (10 мин) удаление старше 1 ч / 25 ч / 7 д

Браузер: chart_range.js → EventSource /api/events/metrics?range=…
    ↓ полный снимок, затем инкременты каждые 3 с … 5 мин (зависит от периода); `data` расшифровывается decryptData(); в фоновой вкладке поток закрывается
Chart.js: разрывы при пропусках, подписи оси по длине периода, сброс зума при смене периода
```

### User Interaction Flow (Telegram)

```
User (Telegram)
    ↓
Отправка команды или нажатие кнопки
    ↓
SpamThrottleMiddleware (1 req/sec)
    ↓
Auth check (is_allowed → role-based)
    ↓
I18nFilter (языковая маршрутизация)
    ↓
Module handler (например, selftest.py)
    ↓
Выполнение системной команды (если root mode)
    ↓
Форматирование ответа (HTML)
    ↓
Отправка сообщения + сохранение ID для удаления
```

### SSE Event Flow (Сервер → Браузер)

```
Backend Event (метрика, уведомление)
    ↓
encrypt_for_web(data) → AES-256-CBC + Base64
    ↓
Push в WEB_NOTIFICATIONS deque
    ↓
streaming.py → SSE endpoint проверяет очередь
    ↓
"data: {encrypted_json}\n\n"
    ↓
Frontend EventSource (JavaScript)
    ↓
decrypt() → AES-256-CBC + Base64
    ↓
Обновление DOM в реальном времени
```

---

## 🎨 Фронтенд архитектура

### Технологии
- **xterm.js** — браузерный SSH-терминал
### Ключевые файлы

#### **dashboard.js**
- `initSSE()` — Подключение к главному SSE потоку
- `initServicesSSE()` — SSE для менеджера сервисов
- `updateAgentStatsUI()` — Обновление карточек CPU/RAM/Disk и мини-графиков
- `renderAgentChart(series)` / `renderNodeResChart(series)` / `renderNodeNetChart(series)` — Графики по данным контроллера периода
- `fetchNodesList()` — Рендеринг списка нод

#### **chart_range.js**
- `createChartRangeController({ key, mount, canvasId, getSource, render })` — кнопка-дропдаун периода (Минуты / Часы / Дни) рядом с графиком
- Подписывается на SSE `/api/events/metrics` (`EventSource`), получает полный снимок и инкременты, расшифровывает `data` через `decryptData()`; при смене периода переоткрывает поток, при обрыве переподключается
- Передаёт в `render` нормализованный `series` (`labels`, `cpu`, `ram`, `disk`, `rx`/`tx` в Kbps, `null` на разрывах)
- Запоминает выбор в `localStorage` (`chartRange:<key>`), показывает индикатор «Live» для периодов ≤ 1 ч, сбрасывает зум при смене периода, останавливается при закрытии модалки или SPA-переходе

#### **nodes_monitor.js**
- `loadNodes()` — Загрузка нод через API
- Фильтрация: по статусу (online/offline), по CPU нагрузке
- Поиск по имени и IP
- Сортировка (имя, CPU, RAM, ping)
- Множественный выбор + массовые команды
- Модальное окно: графики Resources/Network с выбором периода (`chart_range.js`), сервисы, действия

#### **settings.js**
- Центр уведомлений (переключатели алертов с hint-подсказками)
- Пороги: CPU/RAM/Disk (range 50–99%)
- Интервалы: traffic, services, ping, timeout
- Смена пароля с валидацией
- Загрузка favicon (resize → 512x512 → base64 PNG)
- Управление пользователями, сессиями, обновлениями

#### **common.js**
- `encrypt()` / `decrypt()` — AES-256-CBC шифрование/дешифровка
- `animateModalOpen()` / `animateModalClose()` — Анимации модалок
- `showNotification()` — Toast уведомления
- `formatBytes()` — Форматирование размеров

#### **theme_init.js**
- Автоопределение системной темы (prefers-color-scheme)
- Переключение light/dark, сохранение в localStorage
- Синхронизация между вкладками
- Динамический status-bar (iOS)

---

## 🗄️ Структура данных

### SQLite Database Schema

#### Table: `nodes`
```sql
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    ip TEXT,
    last_seen DATETIME,
    cpu_percent REAL DEFAULT 0.0,
    ram_percent REAL DEFAULT 0.0,
    disk_percent REAL DEFAULT 0.0,
    uptime INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Table: `users`
```sql
CREATE TABLE users (
    telegram_id BIGINT PRIMARY KEY,
    role TEXT DEFAULT 'users',
    language TEXT DEFAULT 'en',
    username TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME
);
```

#### Table: `metric_samples`
```sql
CREATE TABLE metric_samples (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    source VARCHAR(32) NOT NULL,   -- 'agent' или 'node:<id>'
    res    SMALLINT NOT NULL DEFAULT 0, -- 0 = сырой замер, 60 / 300 = усреднённая корзина (сек)
    t      INT NOT NULL,           -- unix time замера / начала корзины
    cpu    REAL NOT NULL DEFAULT 0, -- %
    ram    REAL NOT NULL DEFAULT 0, -- %
    disk   REAL NOT NULL DEFAULT 0, -- %
    rx     REAL NOT NULL DEFAULT 0, -- байт/с
    tx     REAL NOT NULL DEFAULT 0  -- байт/с
);
CREATE INDEX idx_metric_samples_source_res_t ON metric_samples (source, res, t);
```
Скользящее окно: сырые замеры хранятся ~1 ч, минутные — 25 ч, пятиминутные — 7 дней; таблица создаётся автоматически (`generate_schemas` / Aerich).

### Encrypted JSON Configs

#### `config/users.json` (Fernet)
```json
{
    "12345678": { "role": "admins", "name": "John Doe", "lang": "en" }
}
```

#### `config/services.json` (Fernet)
```json
["ssh", "docker", "nginx", "mysql", "postgresql"]
```

#### `config/alerts_config.json` (Fernet)
```json
{
    "global_enabled": true,
    "thresholds": { "cpu": 80, "ram": 90, "disk": 85 },
    "nodes": { "node_token_123": { "enabled": true } }
}
```

---

## 🚀 Режимы установки

### Root Mode
- Полный доступ к системе
- Монтирование `/proc` хоста → `/proc_host` в Docker
- ✅ Перезагрузка сервера, чтение journalctl, apt upgrade

### Secure Mode (Рекомендуется)
- Изоляция в контейнере, пользователь `tgbot` (UID 1000)
- ✅ Мониторинг, веб-панель, управление ботом
- ❌ Нет перезагрузки, нет системных логов

---

## 📚 Зависимости

### Python Packages (Core)
- `aiogram==3.x` — Telegram Bot API
- `aiohttp` — Async HTTP сервер
- `tortoise-orm` — ORM для SQLite
- `cryptography` — Fernet шифрование
- `argon2-cffi` — Хеширование паролей (OWASP)
- `psutil` — Системные метрики
- `aiosqlite` — Async SQLite
- `python-dotenv` — Загрузка .env
- `jinja2` — HTML шаблонизатор
- `sentry-sdk` — Мониторинг ошибок (опционально)
- `aerich` — Миграции БД
