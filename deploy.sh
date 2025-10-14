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
# ФУНКЦИЯ ПРОВЕРКИ И УСТАНОВКИ ДОПОЛНЕНИЙ
# =================================================================================
install_extras() {
    # Проверка и установка Fail2Ban
    if ! command -v fail2ban-client &> /dev/null; then
        read -p "❓ Fail2Ban не найден. Хотите установить его для повышения безопасности? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" == "y" || "$INSTALL_F2B" == "Y" ]]; then
            echo "Установка Fail2Ban..."
            sudo apt install -y fail2ban
            sudo systemctl enable fail2ban
            sudo systemctl start fail2ban
            echo "✅ Fail2Ban установлен и запущен."
        else
            echo "Пропускаем установку Fail2Ban."
        fi
    else
        echo "✅ Fail2Ban уже установлен."
    fi

    # Проверка и установка Speedtest-CLI
    if ! command -v speedtest &> /dev/null; then
        read -p "❓ Speedtest-CLI не найден. Хотите установить его для проверки скорости сети? (y/n): " INSTALL_SPEEDTEST
        if [[ "$INSTALL_SPEEDTEST" == "y" || "$INSTALL_SPEEDTEST" == "Y" ]]; then
            echo "Установка Speedtest-CLI..."
            # Проверяем версию Ubuntu
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                if [ "$VERSION_CODENAME" == "noble" ]; then
                    echo "Обнаружена Ubuntu Noble. Используется специальный метод установки Speedtest-CLI."
                    sudo apt-get install -y curl
                    curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash
                    # Автоматически заменяем 'noble' на 'jammy'
                    sudo sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list
                    sudo apt update
                    sudo apt-get install -y speedtest
                else
                    echo "Используется стандартный метод установки Speedtest-CLI."
                    sudo apt install -y speedtest-cli
                fi
            else
                 # Стандартный метод для систем без /etc/os-release
                 sudo apt install -y speedtest-cli
            fi
            echo "✅ Speedtest-CLI установлен."
        else
            echo "Пропускаем установку Speedtest-CLI."
        fi
    else
        echo "✅ Speedtest-CLI уже установлен."
    fi
}

# =================================================================================
# ОБЩАЯ ЧАСТЬ УСТАНОВКИ
# =================================================================================
common_install_steps() {
    echo "1. Обновление пакетов и установка базовых зависимостей..."
    sudo apt update -y
    sudo apt install -y python3 python3-pip python3-venv git curl sudo rsync docker.io
    if [ $? -ne 0 ]; then
        echo "❌ Ошибка при установке базовых пакетов."
        exit 1
    fi

    install_extras

    sudo mkdir -p ${BOT_INSTALL_PATH}

    echo "3. Копирование файлов проекта..."
    sudo rsync -a --delete \
        --exclude='deploy.sh' --exclude='.git/' --exclude='__pycache__/' \
        ./ "${BOT_INSTALL_PATH}/"
}


# =================================================================================
# ФУНКЦИЯ УСТАНОВКИ (SECURE - ОТДЕЛЬНЫЙ ПОЛЬЗОВАТЕЛЬ)
# =================================================================================
install_secure() {
    echo -e "\n=== Начало безопасной установки (отдельный пользователь) ==="
    common_install_steps

    echo "2. Создание системного пользователя '${SERVICE_USER}'..."
    if ! id "${SERVICE_USER}" &>/dev/null; then
        sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}
        echo "Пользователь '${SERVICE_USER}' создан."
    else
        echo "Пользователь '${SERVICE_USER}' уже существует."
    fi
    sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
    sudo chmod -R 750 ${BOT_INSTALL_PATH}

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

    echo "5. Настройка переменных окружения..."
    read -p "Введите ваш Telegram Bot Token: " TG_BOT_TOKEN_USER
    read -p "Введите ваш Telegram User ID (только цифры): " TG_ADMIN_ID_USER
    sudo tee .env > /dev/null <<EOF
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
INSTALL_MODE="secure"
EOF
    sudo chown ${SERVICE_USER}:${SERVICE_USER} .env
    sudo chmod 600 .env

    echo "6. Создание systemd сервиса..."
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${SERVICE_NAME} Telegram Bot (Secure Mode)
After=network.target

[Service]
Restart=always
RestartSec=5
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python ${BOT_INSTALL_PATH}/bot.py

[Install]
WantedBy=multi-user.target
EOF

    start_and_enable_service
}

# =================================================================================
# ФУНКЦИЯ УСТАНОВКИ (ROOT)
# =================================================================================
install_root() {
    echo -e "\n=== Начало установки от имени Root ==="
    common_install_steps

    sudo chown -R root:root ${BOT_INSTALL_PATH}
    sudo chmod -R 755 ${BOT_INSTALL_PATH}

    echo "4. Настройка виртуального окружения Python..."
    cd ${BOT_INSTALL_PATH} || { echo "❌ Не удалось перейти в ${BOT_INSTALL_PATH}"; exit 1; }
    if [ ! -d "${VENV_PATH}" ]; then
        ${PYTHON_BIN} -m venv venv
    fi
    ${VENV_PATH}/bin/pip install --upgrade pip
    ${VENV_PATH}/bin/pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Ошибка при установке зависимостей Python."
        exit 1
    fi

    echo "5. Настройка переменных окружения..."
    read -p "Введите ваш Telegram Bot Token: " TG_BOT_TOKEN_USER
    read -p "Введите ваш Telegram User ID (только цифры): " TG_ADMIN_ID_USER
    sudo tee .env > /dev/null <<EOF
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
INSTALL_MODE="root"
EOF
    sudo chown root:root .env
    sudo chmod 600 .env

    echo "6. Настройка прав sudo для пользователя 'root'..."
    SUDOERS_FILE="/etc/sudoers.d/98-${SERVICE_NAME}-root"
    sudo tee ${SUDOERS_FILE} > /dev/null <<EOF
# Разрешения для Telegram-бота (установка от root)
root ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}.service
root ALL=(ALL) NOPASSWD: /sbin/reboot
EOF
    sudo chmod 440 ${SUDOERS_FILE}
    echo "Права sudo настроены."

    echo "7. Создание systemd сервиса..."
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${SERVICE_NAME} Telegram Bot (Root Mode)
After=network.target

[Service]
Restart=always
RestartSec=5
User=root
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python ${BOT_INSTALL_PATH}/bot.py

[Install]
WantedBy=multi-user.target
EOF

    start_and_enable_service
}

# =================================================================================
# ФУНКЦИЯ ЗАПУСКА СЕРВИСА
# =================================================================================
start_and_enable_service() {
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

    echo "1. Остановка и отключение сервиса..."
    if sudo systemctl is-active --quiet ${SERVICE_NAME}; then
        sudo systemctl stop ${SERVICE_NAME}
    fi
    if sudo systemctl is-enabled --quiet ${SERVICE_NAME}; then
        sudo systemctl disable ${SERVICE_NAME}
    fi
    echo "Сервис остановлен и отключен."

    echo "2. Удаление системных файлов..."
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root" # Файл для root
    sudo rm -f "/etc/sudoers.d/99-${SERVICE_USER}"      # Файл для secure
    sudo systemctl daemon-reload
    echo "Файлы systemd и sudoers удалены."

    echo "3. Удаление директории с ботом..."
    if [ -d "${BOT_INSTALL_PATH}" ]; then
        sudo rm -rf "${BOT_INSTALL_PATH}"
        echo "Директория удалена."
    else
        echo "Директория не найдена."
    fi

    echo "4. Удаление пользователя (если существует)..."
    if id "${SERVICE_USER}" &>/dev/null; then
        sudo userdel -r "${SERVICE_USER}"
        echo "Пользователь '${SERVICE_USER}' удален."
    else
        echo "Пользователь '${SERVICE_USER}' не найден (это нормально для root-установки)."
    fi

    echo "✅ Удаление завершено."
    echo "Внимание: Системные пакеты (python, git и т.д.) не были удалены."
}

# =================================================================================
# ГЛАВНОЕ МЕНЮ
# =================================================================================
clear
echo "Скрипт управления Telegram-ботом"
echo "-----------------------------------"
echo "Выберите действие:"
echo "  1) Установить бота (Root) - Полный функционал, запуск от имени root."
echo "  2) Установить бота (Secure) - Ограниченный функционал, запуск от отдельного пользователя '${SERVICE_USER}'."
echo "  3) Удалить бота"
echo "  4) Выход"
echo "-----------------------------------"
read -p "Введите номер опции [1-4]: " choice

case $choice in
    1)
        if [ "$(id -u)" -ne 0 ]; then
            echo "❌ Для установки от имени root, пожалуйста, запустите скрипт с 'sudo'."
            exit 1
        fi
        install_root
        ;;
    2)
        install_secure
        ;;
    3)
        read -p "⚠️ ВЫ УВЕРЕНЫ, что хотите ПОЛНОСТЬЮ удалить бота и все его данные? (y/n): " confirm_uninstall
        if [[ "$confirm_uninstall" == "y" || "$confirm_uninstall" == "Y" ]]; then
            uninstall_bot
        else
            echo "Удаление отменено."
        fi
        ;;
    4)
        echo "Выход."
        exit 0
        ;;
    *)
        echo "Неверный выбор. Пожалуйста, запустите скрипт снова."
        exit 1
        ;;
esac