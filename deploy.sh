#!/bin/bash
# 
# Скрипт автоматического развертывания Telegram-бота на VPS
#
# Скрипт выполняет следующие действия:
# 1. Устанавливает необходимые пакеты (Python, git, venv).
# 2. Создает пользователя 'tgbot' для безопасного запуска сервиса.
# 3. Клонирует или обновляет репозиторий.
# 4. Создает и активирует виртуальное окружение Python (venv).
# 5. Устанавливает зависимости.
# 6. Настраивает файл .env с токеном и ID администратора.
# 7. Создает systemd-сервис для автозапуска бота.
# 8. Запускает и включает сервис.

# --- КОНФИГУРАЦИЯ ---
# Читаем конфигурацию из .env.example
source .env.example
# Путь установки по умолчанию, если не задан в .env.example
BOT_INSTALL_PATH="${BOT_INSTALL_PATH:-/opt/tg-bot}"
SERVICE_NAME="tg-bot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"
SERVICE_USER="tgbot"

echo "=== Запуск скрипта развертывания ${SERVICE_NAME} ==="

# --- 1. ПРОВЕРКА И УСТАНОВКА ОСНОВНЫХ ПАКЕТОВ ---
echo "1. Обновление пакетов и установка зависимостей..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git curl sudo speedtest-cli

if [ $? -ne 0 ]; then
    echo "❌ Ошибка при установке базовых пакетов. Проверьте подключение и права."
    exit 1
fi

# --- 2. НАСТРОЙКА ПАПОК И ПОЛЬЗОВАТЕЛЯ ---
echo "2. Настройка папок и создание пользователя '${SERVICE_USER}'..."

# Создаем пользователя, если он не существует
if ! id "${SERVICE_USER}" &>/dev/null; then
    sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}
    echo "Создан системный пользователь '${SERVICE_USER}'."
else
    echo "Системный пользователь '${SERVICE_USER}' уже существует."
fi

# Создаем директорию для бота
sudo mkdir -p ${BOT_INSTALL_PATH}
sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
sudo chmod -R 755 ${BOT_INSTALL_PATH}

# --- 3. КОПИРОВАНИЕ ФАЙЛОВ И НАСТРОЙКА VENV ---
echo "3. Копирование файлов и настройка Python VENV..."

# Копируем текущие файлы в целевую директорию
sudo cp -r ./* ${BOT_INSTALL_PATH}/

# Переключаемся в директорию установки
cd ${BOT_INSTALL_PATH} || { echo "❌ Не удалось перейти в директорию ${BOT_INSTALL_PATH}"; exit 1; }

# Создание виртуального окружения
if [ ! -d "${VENV_PATH}" ]; then
    echo "Создание виртуального окружения..."
    sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv venv
fi

# Активация и установка зависимостей
echo "Установка зависимостей Python..."
sudo -u ${SERVICE_USER} ${VENV_PATH}/bin/pip install --upgrade pip
sudo -u ${SERVICE_USER} ${VENV_PATH}/bin/pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Ошибка при установке зависимостей Python. Проверьте requirements.txt."
    exit 1
fi

# --- 4. НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (TG_BOT_TOKEN и TG_ADMIN_ID) ---
echo "4. Настройка файла .env..."

# Запрашиваем данные у пользователя
read -p "Введите TG_BOT_TOKEN: " TG_BOT_TOKEN_USER
read -p "Введите TG_ADMIN_ID (ваш числовой ID): " TG_ADMIN_ID_USER

# Создаем .env файл
sudo tee .env > /dev/null <<EOF
# Файл переменных окружения для systemd сервиса

# Токен Telegram-бота
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"

# ID Главного Администратора (числовой)
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
EOF

# Устанавливаем права для .env
sudo chown ${SERVICE_USER}:${SERVICE_USER} .env
sudo chmod 600 .env
echo "Файл .env успешно создан."

# --- 5. СОЗДАНИЕ СЕРВИСА SYSTEMD ---
echo "5. Создание systemd сервиса..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${SERVICE_NAME} Telegram Bot
After=network.target

[Service]
# Перезапуск, если бот упадет
Restart=always
# Задержка перед перезапуском
RestartSec=5
# Пользователь, от имени которого запускается сервис
User=${SERVICE_USER}
# Рабочая директория
WorkingDirectory=${BOT_INSTALL_PATH}
# Загружаем переменные окружения из .env
EnvironmentFile=${BOT_INSTALL_PATH}/.env
# Команда для запуска: venv/bin/python bot.py
ExecStart=${VENV_PATH}/bin/python ${BOT_INSTALL_PATH}/bot.py

[Install]
WantedBy=multi-user.target
EOF

# --- 6. ЗАПУСК СЕРВИСА ---
echo "6. Перезагрузка systemd, запуск и включение сервиса..."

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}.service
sudo systemctl start ${SERVICE_NAME}.service

if sudo systemctl is-active --quiet ${SERVICE_NAME}.service; then
    echo "✅ Сервис ${SERVICE_NAME}.service успешно запущен и включен в автозапуск!"
    echo "   Проверьте статус: sudo systemctl status ${SERVICE_NAME}.service"
    echo "   Проверьте логи: sudo journalctl -u ${SERVICE_NAME}.service -f"
    echo ""
    echo "🎉 **Установка завершена!** Напишите боту /start."
else
    echo "❌ **Ошибка!** Сервис ${SERVICE_NAME}.service не запущен. Проверьте логи: sudo journalctl -u ${SERVICE_NAME}.service -xe"
    exit 1
fi
