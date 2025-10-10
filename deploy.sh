#!/bin/bash
#
# Скрипт для установки или удаления Telegram-бота на VPS

# --- КОНФИГУРАЦИЯ ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"


# =================================================================================
# ФУНКЦИЯ УСТАНОВКИ БОТА
# =================================================================================
install_bot() {
    echo "=== Начало установки Telegram-бота ==="

    # --- 1. УСТАНОВКА ЗАВИСИМОСТЕЙ ---
    echo "1. Обновление пакетов и установка зависимостей..."
    sudo apt update -y
    sudo apt install -y python3 python3-pip python3-venv git curl sudo rsync docker.io
    if [ $? -ne 0 ]; then
        echo "❌ Ошибка при установке базовых пакетов."
        exit 1
    fi

    # --- ЗАПРОС НА УСТАНОВКУ FAIL2BAN И SPEEDTEST ---
    read -p "❓ Желаете установить Fail2Ban для повышения безопасности и Speedtest-CLI для проверки скорости? (y/n): " INSTALL_EXTRAS
    if [[ "$INSTALL_EXTRAS" == "y" || "$INSTALL_EXTRAS" == "Y" ]]; then
        echo "Установка Fail2Ban и Speedtest-CLI..."
        sudo apt install -y fail2ban speedtest-cli
        sudo systemctl enable fail2ban
        sudo systemctl start fail2ban
        echo "✅ Fail2Ban и Speedtest-CLI установлены и настроены."
    else
        echo "Пропускаем установку Fail2Ban и Speedtest-CLI."
    fi

    # --- 2. НАСТРОЙКА ПОЛЬЗОВАТЕЛЯ И ПАПОК ---
    echo "2. Создание системного пользователя '${SERVICE_USER}'..."
    if ! id "${SERVICE_USER}" &>/dev/null; then
        sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}
        echo "Пользователь '${SERVICE_USER}' создан."
    else
        echo "Пользователь '${SERVICE_USER}' уже существует."
    fi
    sudo mkdir -p ${BOT_INSTALL_PATH}

    # --- 3. КОПИРОВАНИЕ ФАЙЛОВ И УСТАНОВКА ПРАВ ---
    echo "3. Копирование файлов проекта..."
    sudo rsync -a --delete \
        --exclude='deploy.sh' --exclude='.git/' --exclude='__pycache__/' \
        ./ "${BOT_INSTALL_PATH}/"
    sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
    sudo chmod -R 755 ${BOT_INSTALL_PATH}

    # --- 4. НАСТРОЙКА PYTHON VENV ---
    echo "4. Настройка виртуального окружения Python..."
    cd ${BOT_INSTALL_PATH} || { echo "❌ Не удалось перейти в ${BOT_INSTALL_PATH}"; exit 1; }
    if [ ! -d "${VENV_PATH}" ]; then
        sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv venv
    fi
    sudo -u ${SERVICE_USER} ${VENV_PATH}/bin/pip install --upgrade pip
    sudo -u ${SERVICE_USER} ${VENV_PATH}/bin/pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Ошибка при установке зависимостей Python."
        exit 1
    fi

    # --- 5. НАСТРОЙКА .env ФАЙЛА ---
    echo "5. Настройка переменных окружения..."
    read -p "Введите TG_BOT_TOKEN: " TG_BOT_TOKEN_USER
    read -p "Введите TG_ADMIN_ID (ваш числовой ID): " TG_ADMIN_ID_USER
    sudo tee .env > /dev/null <<EOF
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
EOF
    sudo chown ${SERVICE_USER}:${SERVICE_USER} .env
    sudo chmod 600 .env

    # --- 6. НАСТРОЙКА ПРАВ SUDO ---
    echo "6. Настройка прав sudo для пользователя '${SERVICE_USER}'..."
    SUDOERS_FILE="/etc/sudoers.d/99-${SERVICE_USER}"
    sudo tee ${SUDOERS_FILE} > /dev/null <<EOF
# Разрешения для Telegram-бота
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart ${SERVICE_NAME}.service
${SERVICE_USER} ALL=(ALL) NOPASSWD: /sbin/reboot
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/apt update
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/apt upgrade -y
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/apt autoremove -y
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/tail *
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/grep *
${SERVICE_USER} ALL=(ALL) NOPASSWD: /usr/bin/docker *
EOF
    sudo chmod 440 ${SUDOERS_FILE}
    echo "Права sudo настроены."

    # --- 7. СОЗДАНИЕ SYSTEMD СЕРВИСА ---
    echo "7. Создание сервиса systemd..."
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
    echo "8. Запуск и активация сервиса..."
    sudo systemctl daemon-reload
    sudo systemctl enable ${SERVICE_NAME}.service
    sudo systemctl start ${SERVICE_NAME}.service

    if sudo systemctl is-active --quiet ${SERVICE_NAME}.service; then
        echo "✅ Сервис ${SERVICE_NAME} успешно запущен!"
        echo "   Для проверки статуса: sudo systemctl status ${SERVICE_NAME}"
        echo "🎉 Установка завершена! Напишите боту /start."
    else
        echo "❌ Ошибка! Сервис не запустился. Проверьте логи: sudo journalctl -u ${SERVICE_NAME} -xe"
        exit 1
    fi
}

# =================================================================================
# ФУНКЦИЯ УДАЛЕНИЯ БОТА
# =================================================================================
uninstall_bot() {
    echo "=== Начало удаления Telegram-бота ==="

    # 1. Остановка и отключение сервиса
    echo "1. Остановка сервиса ${SERVICE_NAME}..."
    if sudo systemctl is-active --quiet ${SERVICE_NAME}; then
        sudo systemctl stop ${SERVICE_NAME}
    fi
    if sudo systemctl is-enabled --quiet ${SERVICE_NAME}; then
        sudo systemctl disable ${SERVICE_NAME}
    fi
    echo "Сервис остановлен и отключен."

    # 2. Удаление файлов сервиса и sudoers
    echo "2. Удаление системных файлов..."
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo rm -f "/etc/sudoers.d/99-${SERVICE_USER}"
    sudo systemctl daemon-reload
    echo "Файлы systemd и sudoers удалены."

    # 3. Удаление директории с ботом
    echo "3. Удаление директории ${BOT_INSTALL_PATH}..."
    if [ -d "${BOT_INSTALL_PATH}" ]; then
        sudo rm -rf "${BOT_INSTALL_PATH}"
        echo "Директория удалена."
    else
        echo "Директория не найдена."
    fi

    # 4. Удаление пользователя
    echo "4. Удаление пользователя ${SERVICE_USER}..."
    if id "${SERVICE_USER}" &>/dev/null; then
        sudo userdel -r "${SERVICE_USER}"
        echo "Пользователь удален."
    else
        echo "Пользователь не найден."
    fi

    echo "✅ Удаление завершено."
    echo "Внимание: Системные пакеты (python, git, fail2ban и т.д.) не были удалены, так как они могут использоваться другими приложениями."
}

# =================================================================================
# ГЛАВНОЕ МЕНЮ
# =================================================================================
clear
echo "Скрипт управления Telegram-ботом"
echo "-----------------------------------"
echo "Выберите действие:"
echo "  1) Установить бота"
echo "  2) Удалить бота"
echo "  3) Выход"
echo "-----------------------------------"
read -p "Введите номер опции [1-3]: " choice

case $choice in
    1)
        install_bot
        ;;
    2)
        read -p "⚠️ ВЫ УВЕРЕНЫ, что хотите ПОЛНОСТЬЮ удалить бота и все его данные? (y/n): " confirm_uninstall
        if [[ "$confirm_uninstall" == "y" || "$confirm_uninstall" == "Y" ]]; then
            uninstall_bot
        else
            echo "Удаление отменено."
        fi
        ;;
    3)
        echo "Выход."
        exit 0
        ;;
    *)
        echo "Неверный выбор. Пожалуйста, запустите скрипт снова."
        exit 1
        ;;
esac