#!/bin/bash
# 
# Скрипт автоматического развертывания Telegram-бота на VPS
#
# Скрипт выполняет следующие действия:
# 1. Устанавливает необходимые пакеты (Python, git, venv).
# 2. Создает пользователя 'tgbot' для безопасного запуска сервиса.
# 3. Копирует файлы проекта в директорию установки.
# 4. Создает и активирует виртуальное окружение Python (venv) и устанавливает зависимости.
# 5. Настраивает файл .env с токеном и ID администратора.
# 6. НАСТРАИВАЕТ ПРАВА SUDO для пользователя 'tgbot'.
# 7. Создает systemd-сервис для автозапуска бота.
# 8. Запускает и включает сервис.

# --- КОНФИГУРАЦИЯ ---
# БЕЗОПАСНОЕ ЧТЕНИЕ КОНФИГУРАЦИИ ИЗ .env.example
if [ -f .env.example ]; then
    BOT_INSTALL_PATH=$(grep '^BOT_INSTALL_PATH' .env.example | cut -d'=' -f2 | tr -d '"')
fi

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
sudo apt install -y python3 python3-pip python3-venv git curl sudo rsync speedtest-cli

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

# --- 3. КОПИРОВАНИЕ ФАЙЛОВ ПРОЕКТА ---
echo "3. Копирование файлов проекта..."

# Используем rsync для безопасного копирования, исключая ненужные файлы
sudo rsync -a --delete \
    --exclude='deploy.sh' \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.swp' \
    ./ "${BOT_INSTALL_PATH}/"

# --- 4. НАСТРОЙКА PYTHON VENV И ЗАВИСИМОСТЕЙ ---
echo "4. Настройка Python VENV..."

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

# --- 5. НАСТРОЙКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (.env) ---
echo "5. Настройка файла .env..."

read -p "Введите TG_BOT_TOKEN: " TG_BOT_TOKEN_USER
read -p "Введите TG_ADMIN_ID (ваш числовой ID): " TG_ADMIN_ID_USER

sudo tee .env > /dev/null <<EOF
# Файл переменных окружения для systemd сервиса
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
EOF

sudo chown ${SERVICE_USER}:${SERVICE_USER} .env
sudo chmod 600 .env
echo "Файл .env успешно создан."

# --- 6. НАСТРОЙКА ПРАВ SUDO ДЛЯ ПОЛЬЗОВАТЕЛЯ БОТА (ВАЖНО!) ---
echo "6. Настройка прав sudo для пользователя '${SERVICE_USER}'..."
SUDOERS_FILE="/etc/sudoers.d/99-${SERVICE_USER}"
# Предоставляем пользователю tgbot права на выполнение строго определённых команд без пароля
sudo tee ${SUDOERS_FILE} > /dev/null <<EOF
# Разрешения для Telegram-бота
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ${SERVICE_NAME}.service
${SERVICE_USER} ALL=(ALL) NOPASSWD: /sbin/reboot
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/apt update
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/apt upgrade -y
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/apt autoremove -y
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/tail -n 25 /var/log/syslog
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/tail -n 50 /var/log/auth.log
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/grep 'Ban ' /var/log/fail2ban.log
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/grep 'Accepted' /var/log/auth.log
EOF
sudo chmod 440 ${SUDOERS_FILE}
echo "Безопасные права sudo настроены."

# --- 7. СОЗДАНИЕ СЕРВИСА SYSTEMD ---
echo "7. Создание systemd сервиса..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${SERVICE_NAME} Telegram Bot
After=network.target

[Service]
Restart=always
RestartSec=5
User=${SERVICE_USER}
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python ${BOT_INSTALL_PATH}/bot.py

[Install]
WantedBy=multi-user.target
EOF

# --- 8. ЗАПУСК СЕРВИСА ---
echo "8. Перезагрузка systemd, запуск и включение сервиса..."

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