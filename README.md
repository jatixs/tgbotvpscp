<p align="center">
  <a href="README.en.md">English Version</a> | Русская Версия
</p>

<h1 align="center">🤖 VPS Manager Telegram Bot</h1>

<p align="center">
  <b>v1.21.0</b> — профессиональная экосистема для мониторинга и управления серверной инфраструктурой<br>
  <b>v2.5.0-beta</b> — <i>Mobile Support Edition</i><br>
</p>

<p align="center">
  <a href="https://github.com/jatixs/tgbotvpscp/releases/latest"><img src="https://img.shields.io/badge/version-v1.21.0-blue?style=flat-square" alt="Version 1.21.0"/></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/build-70-purple?style=flat-square" alt="Build 70"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+"/></a>
  <a href="https://choosealicense.com/licenses/gpl-3.0/"><img src="https://img.shields.io/badge/license-GPL--3.0-lightgrey?style=flat-square" alt="License GPL-3.0"/></a>
  <a href="https://github.com/aiogram/aiogram"><img src="https://img.shields.io/badge/aiogram-3.x-orange?style=flat-square" alt="Aiogram 3.x"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/docker-ready-blueviolet?style=flat-square" alt="Docker"/></a>
  <a href="https://releases.ubuntu.com/focal/"><img src="https://img.shields.io/badge/platform-Ubuntu%2020.04%2B-important?style=flat-square" alt="Platform Ubuntu 20.04+"/></a>
</p>

---

## 📘 Оглавление

1. [О проекте](#-о-проекте)
2. [Ключевые возможности](#-ключевые-возможности)
3. [Архитектура](#-архитектура)
4. [Быстрый старт](#-быстрый-старт)
5. [Веб-интерфейс](#-веб-интерфейс)
6. [Безопасность](#-безопасность)
7. [Структура проекта](#️-структура-проекта)
8. [Документация](#-документация)
9. [Лицензия](#-лицензия)

---

## 🧩 О проекте

**VPS Manager Telegram Bot** — это комплексное решение enterprise-класса для управления серверной инфраструктурой через Telegram и веб-интерфейс.

### 🎯 Для кого этот проект?

- **Системные администраторы** — автоматизация рутинных задач
- **DevOps инженеры** — мониторинг множества серверов из одной точки
- **VPN провайдеры** — управление X-ray/VLESS панелями
- **Хостинг-провайдеры** — клиентский мониторинг

### 💡 Проблемы, которые решает проект

✅ **Централизованное управление** — один интерфейс для всех серверов  
✅ **Real-time мониторинг** — мгновенные обновления без перезагрузки  
✅ **Безопасность** — enterprise-класса защита с WAF и аудитом  
✅ **Масштабируемость** — от 1 до 1000+ серверов  
✅ **Мобильность** — управление с телефона через Telegram  

---

## ⚡ Ключевые возможности

### 🚀 Производительность

- ✅ **Полная асинхронность** — AsyncIO, aiohttp, aiosqlite
- ✅ **Низкое потребление** — ~100MB RAM на агенте
- ✅ **Кольцевые буферы** — оптимизация памяти через deque
- ✅ **Garbage Collection** — автоматическая очистка

### 🖥 Мульти-серверное управление

- ✅ **Неограниченное количество нод** — масштабируемая архитектура
- ✅ **Real-time метрики** — CPU, RAM, Disk, Network
- ✅ **Удаленное выполнение** — команды на любом сервере
- ✅ **Централизованный dashboard** — единая панель управления

### 🛡️ Безопасность Enterprise-класса

- ✅ **WAF** — защита от SQL Injection, XSS, Path Traversal
- ✅ **Rate Limiting** — защита от DDoS (100 req/min)
- ✅ **Brute-force Protection** — автоблокировка после 5 попыток
- ✅ **Audit Logging** — детальные логи всех событий
- ✅ **E2E Encryption** — Fernet + XOR шифрование
- ✅ **RBAC** — роли Root/Admin/User

### 🎨 Современный веб-интерфейс

- ✅ **PWA** — работает как нативное приложение
- ✅ **SSE (Server-Sent Events)** — обновления без перезагрузки
- ✅ **Темная тема** — автоматическое переключение
- ✅ **Адаптивный дизайн** — Mobile-first подход
- ✅ **Графики в реальном времени** — Chart.js визуализация

### ⚙️ Менеджер сервисов 

- ✅ **Real-time статус** — все systemd сервисы
- ✅ **SSE стриминг** — обновления каждые 5 секунд
- ✅ **Start/Stop/Restart** — управление одной кнопкой
- ✅ **Зашифрованное хранилище** — персистентная конфигурация
- ✅ **Детальная информация** — логи, uptime, PID

### 🔔 Умные уведомления

- ✅ **Настраиваемые пороги** — CPU/RAM/Disk по выбору
- ✅ **Глобальные и индивидуальные** — для агента и каждой ноды
- ✅ **Даунтайм алерты** — нода недоступна > 60 сек
- ✅ **SSH мониторинг** — уведомления о входах
- ✅ **Fail2Ban интеграция** — блокировка IP

### 🌐 Интернационализация

- ✅ **Русский язык** — полная локализация
- ✅ **English** — complete translation
- ✅ **Переключение на лету** — без перезапуска

### 🐳 Docker & DevOps

- ✅ **Docker Compose** — простой деплой
- ✅ **Два режима** — Root (полный доступ) / Secure (изоляция)
- ✅ **Автообновление** — git pull + restart
- ✅ **Watchdog** — автоперезапуск при сбое
- ✅ **Health checks** — мониторинг состояния

---

## 🏗 Архитектура

**Паттерн Agent-Client** с централизованным управлением:

```
┌─────────────────────────────────────────────────┐
│  🤖 Telegram Bot (Main Agent)                   │
│  ├── 📊 SQLite DB (nodes, users, metrics)       │
│  ├── 🌐 Web Dashboard (Aiohttp + SSE)            │
│  ├── 🔌 API Server (REST + Real-time)           │
│  └── ⏰ Background Tasks (monitoring, alerts)    │
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
- **Security:** Argon2, Fernet, XOR encryption
- **Infrastructure:** Docker, Docker Compose, Systemd

📖 Подробнее: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 🚀 Быстрый старт

### Системные требования

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

**Выберите режим установки:**
- `1) Docker - Secure Mode` — **Рекомендуется** (изоляция, безопасность)
- `3) Docker - Root Mode` — Полный доступ (для перезагрузки сервера)

**Введите данные:**
- Bot Token (от BotFather)
- Admin User ID (ваш Telegram ID)

🎉 Бот запущен! API доступен на `http://YOUR_IP:8080`

### 3️⃣ Подключение удаленных серверов (Нод)

#### На главном боте:
1. Откройте Telegram → **🖥 Ноды**
2. Нажмите **➕ Добавить ноду**
3. Введите имя → Скопируйте **токен**

#### На удаленном сервере:
```bash
bash <(wget -qO- https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/deploy.sh)
```

Выберите **8) Установить НОДУ (Клиент)**

Введите:
- **URL агента:** `http://MAIN_SERVER_IP:8080`
- **Токен:** полученный от бота

✅ Нода появится в списке через несколько секунд!

---

## 💻 Веб-интерфейс

### Доступ к Dashboard

```
http://YOUR_SERVER_IP:8080
```

**Первый вход:**
- Username: `admin`
- Password: `admin` (измените после входа!)

### Основные функции

#### 📊 Dashboard
- Real-time графики CPU/RAM/Disk
- Список всех нод с статусами
- Сетевой трафик (текущий и исторический)
- Быстрые действия (перезагрузка, обновление)

#### ⚙️ Settings
- **Alerts Config** — пороги уведомлений (CPU 80%, RAM 90%, Disk 85%)
- **Keyboard Config** — видимость кнопок в Telegram
- **User Management** — добавление/удаление пользователей
- **Language** — смена языка интерфейса

#### ⚙️ Service Manager <sup>NEW</sup>
- Статус всех systemd сервисов
- Управление (Start/Stop/Restart)
- Добавление в мониторинг
- Детальная информация (PID, uptime, logs)

#### 📜 Logs
- Bot logs (real-time)
- Watchdog logs
- Node logs (для каждой ноды отдельно)
- Audit logs (события безопасности)

### PWA Features

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

#### 🔹 Уровень 1: Telegram Bot
- Whitelist — только авторизованные Telegram ID
- Role-Based Access Control (RBAC)
- Anti-spam middleware (1 запрос/сек на пользователя)

#### 🔹 Уровень 2: Web Panel
- **Argon2** — рекомендованное OWASP хеширование паролей
- **Server-side sessions** — безопасные куки
- **CSRF Protection** — токены для всех POST запросов
- **Brute-force Protection** — блокировка после 5 попыток на 5 минут
- **Rate Limiting** — 100 API запросов/мин на IP

#### 🔹 Уровень 3: WAF (Web Application Firewall)

Автоматическое обнаружение:
- ❌ SQL Injection (`UNION SELECT`, `OR 1=1`)
- ❌ XSS (`<script>`, `javascript:`)
- ❌ Path Traversal (`../`, `%2e%2e`)
- ❌ Command Injection (`;`, `|`, `` ` ``)
- ❌ LDAP Injection

#### 🔹 Уровень 4: Data Encryption
- **Fernet** — симметричное шифрование конфигов (`users.json`, `services.json`)
- **XOR + Base64** — легковесное шифрование для веб-клиента (SSE events)

#### 🔹 Уровень 5: Audit Logging

**Записываются:**
- Login attempts (success/fail)
- Password resets
- User additions/deletions
- Configuration changes
- WAF triggers

**Privacy:**
- IP маскируются (203.0.113.XXX)
- Токены скрываются (abc123...)
- GDPR compliant

**Файл:** `logs/audit/audit.log`

---

## 🗂️ Структура проекта

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
│   ├── server.py            # Web-сервер + API
│   ├── auth.py              # Авторизация
│   ├── i18n.py              # Мультиязычность
│   ├── keyboards.py         # UI генератор
│   ├── messaging.py         # Уведомления
│   ├── utils.py             # Утилиты
│   ├── nodes_db.py          # База данных нод
│   ├── static/              # CSS, JS
│   └── templates/           # HTML шаблоны
├── modules/                 # Функциональные модули
│   ├── selftest.py          # Сводка о сервере
│   ├── traffic.py           # Мониторинг трафика
│   ├── services.py          # Менеджер сервисов
│   ├── nodes.py             # Управление нодами
│   ├── users.py             # Управление пользователями
│   ├── notifications.py     # Фоновые алерты
│   └── ...                  # +15 модулей
└── node/                    # Клиент для удаленных серверов
    └── node.py              # Агент ноды
```

📖 Подробная документация: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📚 Документация

### Руководства

- 📘 [**ARCHITECTURE.md**](ARCHITECTURE.md) — Полная архитектура проекта
- 🧩 [**custom_module.md**](custom_module.md) — Создание своего модуля
- 📝 [**CHANGELOG.md**](CHANGELOG.md) — История изменений

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
# Telegram → 🔧 Утилиты → 🔄 Обновить VPS → Обновить бота

# Ручное
cd /opt/tg-bot
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart tg-bot
```

---

## 📊 API Endpoints

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

📖 Полная документация API: [ARCHITECTURE.md#api](ARCHITECTURE.md)

---

## 🤝 Участие в проекте

Мы приветствуем вклад в проект! 

### Как помочь:

1. 🐛 **Сообщить о баге** — [Issues](https://github.com/jatixs/tgbotvpscp/issues)
2. 💡 **Предложить функцию** — [Discussions](https://github.com/jatixs/tgbotvpscp/discussions)
3. 🔧 **Отправить Pull Request**
4. 📖 **Улучшить документацию**
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

## 🌟 Поддержать проект

Если проект оказался полезным, поддержите его:

- ⭐ **Поставь звезду** на GitHub
- 🔄 **Поделись** с друзьями
- 💰 **[Донат](https://yoomoney.ru/to/410011639584793)**

---

<p align="center">
  <b>Версия:</b> 1.21.0 (Build 71)<br>
  <b>Дата обновления:</b> 3 Февраля 2026 г.<br>
  <b>Статус:</b> Релиз<br>
  <br>
  Сделано с ❤️ для сообщества DevOps
</p>
