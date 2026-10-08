<p align="center">
  <a href="docs/README.en.md"><img src="https://flagcdn.com/20x15/gb.png" width="16" alt="EN"> English</a> | <img src="https://flagcdn.com/20x15/ru.png" width="16" alt="RU"> Русский
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b>v1.26.0</b> — профессиональная экосистема для мониторинга и управления серверной инфраструктурой<br>
  (Systemd / Docker / API / WebUI / PWA / Multi-Node / Remote SSH / Backup Manager)<br><br>

  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.26.0-blue?style=flat-square" alt="Version 1.26.0"/></a>
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/build-93-purple?style=flat-square" alt="Build 93"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+"/></a>
  <a href="https://choosealicense.com/licenses/gpl-3.0/"><img src="https://img.shields.io/badge/license-GPL--3.0-lightgrey?style=flat-square" alt="License GPL-3.0"/></a>
  <a href="https://github.com/aiogram/aiogram"><img src="https://img.shields.io/badge/aiogram-3.x-orange?style=flat-square" alt="Aiogram 3.x"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-ready-blueviolet?style=flat-square" alt="Docker"/></a>
  <a href="https://releases.ubuntu.com/focal/"><img src="https://img.shields.io/badge/platform-Ubuntu%2020.04%2B-important?style=flat-square" alt="Platform Ubuntu 20.04+"/></a>
</p>

---

## 📋 Оглавление

1. [О проекте](#ℹ️-о-проекте)
2. [Ключевые возможности](#✨-ключевые-возможности)
3. [Архитектура](#🏗️-архитектура)
4. [Быстрый старт](#🚀-быстрый-старт)
5. [Веб-интерфейс](#🖥️-веб-интерфейс)
6. [Безопасность](#🔒-безопасность)
7. [Структура проекта](#📁-структура-проекта)
8. [Документация](#📚-документация)
9. [Лицензия](#📄-лицензия)

---

## ℹ️ О проекте

**VPS Manager Telegram Bot** — это комплексное решение enterprise-класса для управления серверной инфраструктурой через Telegram и веб-интерфейс.

### 🎯 Для кого этот проект?

- 👨‍💻 **Системные администраторы** — автоматизация рутинных задач
- 🔧 **DevOps инженеры** — мониторинг множества серверов из одной точки
- 🛡️ **VPN провайдеры** — управление X-ray/VLESS панелями
- ☁️ **Хостинг-провайдеры** — клиентский мониторинг

### 💡 Проблемы, которые решает проект

- 🎯 **Централизованное управление** — один интерфейс для всех серверов  
- 📈 **Мониторинг в реальном времени** — мгновенные обновления без перезагрузки  
- 🔐 **Безопасность** — защита корпоративного уровня с WAF и аудитом  
- 🌐 **Масштабируемость** — управление несколькими удаленными серверами
- 📱 **Мобильность** — управление с телефона через Telegram  

---

## ✨ Ключевые возможности

### ⚡ Производительность
- **Полная асинхронность** — AsyncIO, aiohttp, aiosqlite
- **Ограниченное потребление ресурсов** — кэширование и фоновая очистка
- **Кольцевые буферы** — оптимизация памяти через deque
- **Memory Orchestrator** — динамическая выгрузка неиспользуемых модулей

### 🌍 Мульти-серверное управление
- **Неограниченное количество нод** — масштабируемая архитектура
- **Метрики в реальном времени** — CPU, RAM, Disk, Network (HTTP / ICMP ping)
- **Веб-терминал (SSH)** — доступ к терминалу через WebUI с проверкой ключа хоста
- **Оптимизация системы** — интерактивный модуль настройки VPS (BBR, Swap, очистка кэша)

### 💳 Система биллинга и аренды
- **Учет платежей** — отслеживание стоимости аренды нод и мастер-сервера (€/$/₽)
- **Умные напоминания** — автоматические алерты за 3 дня до конца оплаты
- **Информативные бейджи** — отображение оставшихся дней до оплаты в WebUI

### 💬 Умный Telegram-интерфейс
- **Шлюз Поддержки (Gateway Bot)** — выделенный клиентский бот с рассылками и ответами на тикеты прямо из админ-панели, со встроенной защитой от флуда
- **Умная очистка (Smart Cleanup)** — автоматическая очистка чата от команд и старых меню
- **Защита от спама** — встроенный SpamThrottle для защиты Telegram API
- **Интерактивные виджеты** — меню с сохранением состояния (чекбоксы) и живыми таймерами

### 🛡️ Безопасность Enterprise-класса
- **Web-защита** — заголовки безопасности, CSRF, ограничение частоты запросов и фильтрация подозрительных запросов
- **Защита от DDoS и перебора паролей (Rate Limiting & Brute-force)** 
- **Журналирование аудита (Audit Logging)** — детальные логи всех событий
- **Шифрование данных** — Fernet (AES) + AES-256-CBC + Argon2 для паролей
- **DOMPurify** — строгая фильтрация контента на стороне клиента

### 🎨 Современный веб-интерфейс
- **PWA** — работает как нативное приложение (поддержка iOS / Android)
- **SSE (Server-Sent Events)** — обновления графиков и логов без перезагрузки
- **4 вида тем оформления** — Системная, Светлая, Темная и AMOLED
- **Адаптивный дизайн** — подход Mobile-first
- **Перетаскивание (Drag & Drop)** — ручная и автоматическая сортировка серверов

### ⚙️ Менеджер сервисов 
- **Статус в реальном времени** — все systemd сервисы
- **Управление в 1 клик** — Запуск / Остановка / Перезапуск
- **Детальная информация** — логи, uptime, PID

### 📦 Менеджер бэкапов и обновлений
- **Автоматические бэкапы** — резервное копирование трафика и конфигов по таймеру
- **Умное обновление (Smart Update)** — автоматическое обновление бота и системы напрямую из Telegram
- **Автоматические миграции БД** — через \ erich\, без потери данных

### 🔔 Умные уведомления
- **Настраиваемые пороги** — CPU/RAM/Disk по выбору
- **Уведомления о простоях** — интеллектуальное определение недоступности серверов
- **SSH мониторинг** — уведомления о входах (в том числе по SSH-ключам)
- **Интеграция с Fail2Ban** — автоматическая блокировка подозрительных IP
- **Alert-bot** — вспомогательный бот-ретранслятор для уведомлений/новостей. 

### 🌐 Интернационализация
- **Русский язык** — полная локализация
- **English** — complete translation
- **Переключение на лету** — без перезапуска бота

### 🐳 Docker & DevOps
- **Docker Compose** — простой деплой (Secure и Root режимы)
- **Watchdog** — автоперезапуск при сбое
- **Health checks** — мониторинг состояния

---

## 🏗️ Архитектура

**Паттерн Agent-Client** с централизованным управлением:

```
┌─────────────────────────────────────────────────┐
│  Telegram Bot (Main Agent)                      │
│  ├── SQLite DB (nodes, users, metrics)          │
│  ├── Web Dashboard (Aiohttp + SSE)               │
│  ├── API на базе aiohttp (HTTP + Real-time)     │
│  └── Background Tasks (monitoring, alerts)       │
└─────────────────────────────────────────────────┘
              ↓         ↓         ↓
    ┌─────────┴─────────┴─────────┴───────┐
    │                                     │
┌───▼────┐  ┌────────┐  ┌────────┐  ┌─────▼───┐
│ Node 1 │  │ Node 2 │  │ Node 3 │  │ Node N  │
│ (VPS)  │  │ (VPS)  │  │ (VPS)  │  │ (VPS)   │
└────────┘  └────────┘  └────────┘  └─────────┘
```

**Технологический стек:**
- **Backend:** Python 3.10+, Aiogram 3.x, Aiohttp, Tortoise ORM
- **Database:** SQLite (aiosqlite)
- **Frontend:** Tailwind CSS, Vanilla JavaScript, Chart.js
- **Real-time:** Server-Sent Events (SSE)
- **Security:** Argon2, Fernet, AES-256-CBC encryption
- **Infrastructure:** Docker, Docker Compose, Systemd

📖 Подробнее: [ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 🚀 Быстрый старт

### 📌 Системные требования

**Минимальные:**
- Ubuntu 20.04+ / Debian 11+
- Python 3.10+
- 1 GB RAM
- 10 GB Disk

**Рекомендуемые:**
- 2 GB RAM
- 20 GB SSD
- 2 CPU cores

### 1️⃣ Подготовка

1. Получите токен бота в [@BotFather](https://t.me/BotFather)
2. Узнайте свой Telegram ID через [@userinfobot](https://t.me/userinfobot)
3. Убедитесь, что установлены `curl` и `git`:
   ```bash
   sudo apt update && sudo apt install -y curl git
   ```

### 2️⃣ Установка главного бота
```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh)
```

**Режимы установки:**
- `1) Systemd - Secure` — рекомендуемый вариант с отдельным ограниченным пользователем
- `2) Systemd - Root` — полный доступ к хосту
- `3) Docker - Secure` — контейнерный secure-профиль
- `4) Docker - Root` — полный доступ к хосту через root-профиль

Установщик запросит токен Telegram, ID администратора и настройки WebUI. Панель публикуется по HTTPS origin из `WEB_PUBLIC_URL`; внутренний порт не следует открывать напрямую в Интернет.

Managed TLS принимает домен или глобальный публичный IPv4. IP-сертификат Let's Encrypt использует short-lived profile и действует 160 часов; HTTP-01 требует входящий TCP/80, renewal проверяется ежечасно. Частные и локальные IPv4 не поддерживаются. При внешнем reverse proxy укажите его HTTPS origin и настройте сертификат/renewal на proxy.

### 3️⃣ Подключение удаленных серверов (нод)

1. В Telegram откройте **Ноды** → **Добавить ноду**, задайте имя и сохраните выданный секретный token.
2. На удаленном сервере запустите установщик и выберите **7) НОДА (Клиент)**.
3. Укажите HTTPS origin master, например `https://panel.example.com` или `https://203.0.113.10`, и node token.

Для существующих агентов сначала обновите master, затем обновите ноды. Агент проверяет same-host HTTPS endpoint и сохраняет новый URL; временный HTTP bridge принимает только discovery/bootstrap и HMAC-защищенный heartbeat. Проверьте прогресс командой `sudo tgcp-bot tls status`; после подтверждения всех нод закройте bridge: `sudo tgcp-bot tls finalize`.

### 🔑 Доступ к WebUI

Открывайте HTTPS origin, указанный при установке, например `https://panel.example.com/`. Установщик создает случайный initial password и показывает его в конце установки; общего пароля `admin` нет. Сменить пароль можно командой `sudo tgcp-bot webpass`.

Agent routes: `GET /api/agent/https` публикует HTTPS origin без токена; `GET /api/node/bootstrap` принимает token через `X-Node-Token`; `POST /api/heartbeat` принимает HMAC-подписанный heartbeat.

---

## 🖥️ Веб-интерфейс

### Основные функции

#### 📊 Панель управления (Dashboard)
- Графики CPU/RAM/Disk в реальном времени
- Список всех нод с текущими статусами
- Сетевой трафик (текущий и исторический)
- Выбор периода графиков от 3 минут до 7 дней (агент и окна нод), история хранится в базе скользящим окном
- Быстрые действия (перезагрузка, обновление)
- Перетаскивание (Drag & Drop) для сортировки нод
- Визуальные предупреждения при пиковых нагрузках 

#### ⚙️ Настройки (Settings)
- **Настройка уведомлений** — пороги уведомлений (CPU 80%, RAM 90%, Disk 85%)
- **Настройка клавиатуры** — видимость кнопок в Telegram
- **Управление пользователями** — добавление/удаление пользователей
- **Язык** — смена языка интерфейса

#### 🛠️ Диспетчер служб (Service Manager)
- Статус всех systemd сервисов
- Управление (Запуск / Остановка / Перезапуск)
- Добавление в мониторинг
- Детальная информация (PID, uptime, логи)

#### 📝 Журналы (Logs)
- Журналы бота (в реальном времени)
- Журналы Watchdog
- Журналы нод (для каждой ноды отдельно)
- Журналы аудита (события безопасности)

### API Endpoints

**Важно:**
- `GET /api` и `GET /api/` возвращают JSON-индекс с описанием групп маршрутов и не отдают метрики.
- `GET /api/events`, `GET /api/events/logs`, `GET /api/events/node`, `GET /api/events/services` являются внутренними SSE-потоками и не предназначены для прямого открытия в браузере.
- Для SSE требуется клиент с заголовком `Accept: text/event-stream` (`EventSource` в WebUI).
- `GET /api/terminal/ws` является внутренним WebSocket endpoint и для обычного HTTP-запроса возвращает `426 Upgrade Required`.

**Auth API:**
- `POST /api/login/request` — запрос magic link через Telegram
- `POST /api/login/password` — вход по логину и паролю
- `GET /api/login/magic` — вход по magic link
- `POST /api/auth/telegram` — вход через Telegram widget
- `POST /api/auth/webapp` — Авторизация через Telegram WebApp
- `POST /api/login/reset` — запрос сброса пароля
- `POST /api/reset/confirm` — подтверждение сброса пароля
- `GET /api/security/telegram_only_mode` — текущее состояние режима Telegram-only
- `POST /api/security/telegram_only_mode` — переключение режима Telegram-only
- `GET /api/sessions/list` — список активных веб-сессий
- `POST /api/sessions/revoke` — отзыв одной сессии
- `POST /api/sessions/revoke_all` — отзыв всех остальных сессий
- `POST /api/settings/password` — смена пароля веб-панели

**Node API:**
- `GET /api/heartbeat` — health probe для агента/нод
- `GET /api/agent/https` — публичный HTTPS origin для migration discovery
- `GET /api/node/bootstrap` — bootstrap с секретом в `X-Node-Token`
- `POST /api/heartbeat` — heartbeat от ноды с HMAC-подписью
- `GET /api/nodes/list` — список нод
- `POST /api/nodes/add` — добавить ноду
- `POST /api/nodes/delete` — удалить ноду
- `POST /api/nodes/rename` — переименовать ноду
- `POST /api/nodes/reset-uptime` — сброс статистики аптайма ноды
- `GET /api/nodes/monitor/list` — данные страницы мониторинга
- `GET /api/nodes/monitor/detail?node_id=...` — детали ноды, доступны через WebUI-сессию
- `GET /api/nodes/monitor/services?node_id=...` — сервисы ноды, доступны через WebUI-сессию
- `POST /api/nodes/monitor/command` — отправить команду на ноду
- `POST /api/nodes/monitor/service_action` — действие над сервисом ноды

**System API:**
- `GET /api/logs` — последние строки bot log
- `GET /api/logs/system` — системные логи
- `POST /api/logs/clear` — очистка логов
- `POST /api/settings/save` — сохранение настроек уведомлений
- `POST /api/settings/system` — сохранение системных порогов
- `POST /api/settings/keyboard` — сохранение конфигурации клавиатуры
- `POST /api/settings/metadata` — сохранение web metadata
- `POST /api/settings/language` — смена языка WebUI
- `POST /api/users/action` — управление пользователями
- `POST /api/system/reset-uptime` — сброс статистики аптайма мастер-сервера
- `GET /api/update/check` — проверка обновлений
- `POST /api/update/run` — запуск обновления
- `GET /api/notifications/list` — список уведомлений
- `POST /api/notifications/read` — отметить уведомления прочитанными
- `POST /api/notifications/clear` — очистить уведомления
- `POST /api/traffic/reset` — сброс статистики трафика
- `GET /api/services` — список управляемых сервисов
- `GET /api/services/available` — список доступных сервисов
- `GET /api/services/info/{name}` — информация о сервисе
- `POST /api/services/{action}` — действие над сервисом (`start|stop|restart`)
- `POST /api/services/manage` — добавить или удалить сервис из мониторинга

**Streaming / Internal API:**
- `GET /api/events` — основной SSE поток dashboard
- `GET /api/events/logs` — SSE поток логов
- `GET /api/events/node` — SSE поток детальной карточки ноды
- `GET /api/events/node/services` — SSE поток статусов сервисов конкретной ноды
- `GET /api/events/services` — SSE поток менеджера сервисов
- `GET /api/events/metrics` — зашифрованный SSE поток истории для графиков за период (`range=3m…7d`, `source=agent|node&node_id=…`)
- `GET /api/agent/ipv4` — список IPv4 адресов агента
- `GET /api/terminal/creds` — загрузка сохраненных SSH credentials
- `POST /api/terminal/creds` — сохранение SSH credentials
- `GET /api/terminal/stats` — статистика сервера для web terminal
- `GET /api/terminal/ws` — WebSocket endpoint терминала

### 📱 PWA Features

**Установка как приложение:**
1. Откройте Dashboard в браузере
2. Нажмите "Установить" (Chrome) или "Добавить на главный экран" (Mobile)
3. Используйте как нативное приложение

**Преимущества PWA:**
- Работает офлайн (кэширование)
- Иконка на рабочем столе
- Полноэкранный режим
- Push-уведомления (в разработке)

---

## 🔒 Безопасность

### Уровни защиты

#### Уровень 1: Telegram Bot
- Whitelist — только авторизованные Telegram ID
- Role-Based Access Control (RBAC)
- Anti-spam middleware (1 запрос/сек на пользователя)

#### Уровень 2: Web Panel
- **Argon2** — рекомендованное OWASP хеширование паролей
- **Server-side sessions** — безопасные куки
- **CSRF Protection** — токены для всех POST запросов
- **Brute-force Protection** — блокировка после 5 попыток на 5 минут
- **Rate Limiting** — ограничение частоты запросов с учетом доверенной proxy-конфигурации

#### Уровень 3: WAF (Web Application Firewall)

Фильтрация подозрительных запросов — дополнительный уровень защиты, а не замена авторизации, проверок прав и валидации входных данных:
- ⛔ SQL Injection (`UNION SELECT`, `OR 1=1`)
- ⛔ XSS (`<script>`, `javascript:`)
- ⛔ Path Traversal (`../`, `%2e%2e`)
- ⛔ Command Injection (`;`, `|`, `` ` ``)
- ⛔ LDAP Injection

#### Уровень 4: Data Encryption
- **Fernet** — симметричное шифрование конфигов (`users.json`, `services.json`)
- **AES-256-CBC + Base64** — шифрование для веб-клиента (SSE events)

#### Уровень 5: Audit Logging

**Записываются:**
- Login attempts (success/fail)
- Password resets
- User additions/deletions
- Configuration changes
- WAF triggers

**Privacy:**
- IP маскируются (203.0.113.XXX)
- Токены скрываются (abc123...)
- Не публикуйте `.env`, резервные копии и журналы доступа

**Файл:** `logs/audit/audit.log`

Для WebUI задавайте `WEB_PUBLIC_URL` со схемой `https://`. При внешнем reverse proxy сертификатом управляет proxy; при managed TLS установщик настраивает Nginx/Certbot. TCP/80 необходим для ACME HTTP-01. Старые агенты мигрируют после обновления master и node; закройте временный bridge командой `tgcp-bot tls finalize`, когда `tgcp-bot tls status` не показывает ожидающих нод.

---

## 📁 Структура проекта

```
/opt/tg-bot/
├── bot.py                    # Точка входа
├── watchdog.py              # Автоперезапуск
├── migrate.py               # Миграция данных
├── manage.py                # CLI управление
├── .env                     # Конфигурация
├── requirements.txt         # Python зависимости
├── docker-compose.yml       # Docker конфигурация
├── Dockerfile               # Образ контейнера
├── deploy.sh                # Установщик
├── core/                    # Ядро системы
│   ├── tls_config.py        # Проверка TLS endpoint и Certbot arguments
│   ├── config.py            # Загрузка конфигурации
│   ├── auth.py              # Авторизация
│   ├── i18n.py              # Мультиязычность
│   ├── keyboards.py         # UI генератор
│   ├── messaging.py         # Уведомления
│   ├── middlewares.py       # Middleware бота
│   ├── models.py            # ORM модели (Tortoise)
│   ├── nodes_db.py          # База данных нод
│   ├── metrics_history.py   # История метрик для графиков (3 мин … 7 дней)
│   ├── shared_state.py      # Мост Bot ↔ Web
│   ├── tasks.py             # Фоновые задачи
│   ├── utils.py             # Утилиты
│   ├── web/                 # Web-слой (aiohttp)
│   │   ├── app.py           # Маршруты и инициализация
│   │   ├── auth.py          # Web-авторизация (пароль/magic link/Telegram)
│   │   ├── middlewares.py   # WAF, CSRF, Rate Limiting
│   │   ├── api_nodes.py     # API нод на базе aiohttp
│   │   ├── api_system.py    # Системный API на базе aiohttp
│   │   ├── streaming.py     # SSE потоки
│   │   └── views.py         # Jinja2 HTML страницы
│   ├── static/              # CSS, JS
│   └── templates/           # HTML шаблоны
├── modules/                 # Функциональные модули (20 модулей)
│   ├── selftest.py          # Сводка о сервере
│   ├── traffic.py           # Мониторинг трафика
│   ├── services.py          # Менеджер сервисов
│   ├── nodes.py             # Управление нодами
│   ├── users.py             # Управление пользователями
│   ├── backups.py           # Менеджер бэкапов
│   ├── notifications.py     # Фоновые алерты
│   └── ...                  # +11 модулей
├── node/                    # Агент удаленного сервера
│   ├── node.py              # Агент и HTTPS migration flow
│   └── endpoint_migration.py # Проверка same-host перехода на HTTPS
├── scripts/                 # Host-side helpers установщика и CLI
│   └── tls_finalize.py      # Закрытие legacy bridge, в том числе в Docker
└── tests/                   # Unit tests для TLS и миграции агентов
```

📖 Подробная документация: [ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 📚 Документация

### Руководства

- 📖 [**ARCHITECTURE.md**](docs/ARCHITECTURE.md) — Полная архитектура проекта
- 🛡️ [**SECURITY.md**](SECURITY.md) — Безопасный деплой, HTTPS и миграция агентов
- 🛠️ [**CONTRIBUTING.md**](CONTRIBUTING.md) — Разработка и тестирование
- 🧩 [**custom_module.md**](docs/custom_module.md) — Создание модуля для бота
- 💻 [**web_module.md**](docs/web_module.md) — Создание веб-модуля (WebUI + Бот)
- 📝 [**CHANGELOG.md**](docs/CHANGELOG.md) — История изменений

### Полезные команды

#### Управление ботом (Docker)

```bash
# Статус
docker compose -f /opt/tg-bot/docker-compose.yml ps

# Перезапуск
docker compose -f /opt/tg-bot/docker-compose.yml restart bot-secure

# Логи (real-time)
docker compose -f /opt/tg-bot/docker-compose.yml logs -f bot-secure

# Остановка
docker compose -f /opt/tg-bot/docker-compose.yml stop

# Запуск
docker compose -f /opt/tg-bot/docker-compose.yml up -d
```

#### Управление ботом (Systemd)

```bash
# Статус
sudo systemctl status tg-bot

# Перезапуск
sudo systemctl restart tg-bot

# Логи
sudo journalctl -u tg-bot -f

# Остановка
sudo systemctl stop tg-bot
```

#### Бэкап

```bash
# База данных
cp /opt/tg-bot/config/nodes.db /backup/nodes.db.$(date +%F)

# Конфигурации
tar -czf /backup/tg-bot-config-$(date +%F).tar.gz /opt/tg-bot/config/

# Логи
tar -czf /backup/tg-bot-logs-$(date +%F).tar.gz /opt/tg-bot/logs/
```

#### Обновление

```bash
# Автоматическое (через бота)
# Telegram → Утилиты → Обновить VPS → Обновить бота

# Ручное
# Для обновления используйте update flow установщика: он сохраняет .env и runtime state.
# Полезные команды:
sudo tgcp-bot status
sudo tgcp-bot restart
sudo tgcp-bot tls status
sudo tgcp-bot tls check
sudo tgcp-bot tls finalize
```

---

## 🔌 API Endpoints

### Public Endpoints

- `GET /` — Dashboard (требуется авторизация)
- `POST /api/login` — Вход в систему
- `POST /api/logout` — Выход

### Monitoring

- `GET /api/dashboard_data` — Данные дашборда
- `GET /api/events` — SSE stream (уведомления)
- `GET /api/events/services` — SSE stream (сервисы)

### Node Management

- `GET /api/nodes` — Список всех нод
- `POST /api/nodes/register` — Регистрация ноды
- `POST /api/nodes/{token}/metrics` — Отправка метрик
- `POST /api/nodes/{id}/delete` — Удаление ноды

### System

- `GET /api/health` — Health check
- `GET /api/logs/{type}` — Получение логов
- `POST /api/system_config` — Сохранение конфигурации
- `POST /api/alerts_config` — Настройки алертов

📖 Полная документация API: [ARCHITECTURE.md#api](docs/ARCHITECTURE.md)

---

## 🤝 Участие в проекте

Мы приветствуем вклад в проект! 

### Как помочь:

1. 🐛 **Сообщить о баге** — [Issues](https://github.com/jatixs/tgbotvpscp/issues)
2. 💡 **Предложить функцию** — [Discussions](https://github.com/jatixs/tgbotvpscp/discussions)
3. 🔄 **Отправить Pull Request**
4. 📝 **Улучшить документацию**
5. ⭐ **Поставить звезду** — это мотивирует!

### Разработка

```bash
# Клонирование
git clone https://github.com/jatixs/tgbotvpscp.git
cd tgbotvpscp

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Настройка .env
cp .env.example .env
nano .env

# Запуск
python bot.py
```

---

## 📄 Лицензия

Этот проект распространяется под лицензией **GPL-3.0**. См. файл [LICENSE](LICENSE) для деталей.

---

## 👤 Автор

**Jatix**

- 📧 Почта: [jatix.com@mail.ru](jatix.com@mail.ru)
- 💬 Telegram: [@jatix](https://t.me/faridshykhaliev)
- 🌐 GitHub: [@jatixs](https://github.com/jatixs)

---

## 💎 Поддержать проект

Если проект оказался полезным, поддержите его:

- ⭐ **Поставь звезду** на GitHub
- 📢 **Поделись** с друзьями
- ☕ **[Донат](https://yoomoney.ru/to/410011639584793)**

---

<p align="center">
  <b>Версия:</b> 1.26.0 (Build 93)<br>
  <b>Лицензия:</b> GPL-3.0 license<br>
  <b>Статус:</b> Релиз<br>
  <br>
  Сделано с ❤️ для сообщества DevOps
</p>
