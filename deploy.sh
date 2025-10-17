#!/bin/bash

BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"

RELEASE_BOT_PY_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/bot.py"
RELEASE_REQUIREMENTS_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/requirements.txt"

FEATURE_BOT_PY_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/feature/bot.py"
FEATURE_REQUIREMENTS_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/feature/requirements.txt"

C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'
C_BOLD='\033[1m'

msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }
msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }
msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }
msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }

spinner() {
    local pid=$1
    local msg=$2
    local spin='|/-\'
    local i=0
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) %4 ))
        printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"
        sleep .1
    done
    printf "\r"
}

run_with_spinner() {
    local msg=$1
    shift
    "$@" > /dev/null 2>&1 &
    local pid=$!
    spinner $pid "$msg"
    wait $pid
    return $?
}

if command -v curl &> /dev/null; then
    DOWNLOADER="curl -sSLf"
elif command -v wget &> /dev/null; then
    DOWNLOADER="wget -qO-"
else
    msg_error "Ни curl, ни wget не найдены. Установите один из них."
    exit 1
fi

install_extras() {
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Хотите установить его? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then
            run_with_spinner "Установка Fail2Ban" sudo apt install -y fail2ban
            sudo systemctl enable fail2ban &> /dev/null
            sudo systemctl start fail2ban &> /dev/null
            msg_success "Fail2Ban установлен и запущен."
        fi
    fi
    if ! command -v speedtest &> /dev/null; then
        msg_question "Speedtest-CLI не найден. Хотите установить его? (y/n): " INSTALL_SPEEDTEST
        if [[ "$INSTALL_SPEEDTEST" =~ ^[Yy]$ ]]; then
            run_with_spinner "Установка Speedtest-CLI" sudo apt install -y speedtest-cli
            msg_success "Speedtest-CLI установлен."
        fi
    fi
}

common_install_steps() {
    local branch=$1
    if [ "$branch" == "release" ]; then
        BOT_PY_URL=$RELEASE_BOT_PY_URL
        REQUIREMENTS_URL=$RELEASE_REQUIREMENTS_URL
    else
        BOT_PY_URL=$FEATURE_BOT_PY_URL
        REQUIREMENTS_URL=$FEATURE_REQUIREMENTS_URL
    fi

    msg_info "1. Установка базовых зависимостей..."
    run_with_spinner "Обновление списка пакетов" sudo apt update -y
    run_with_spinner "Установка зависимостей (python, git, curl...)" sudo apt install -y python3 python3-pip python3-venv git curl wget sudo
    
    install_extras
    sudo mkdir -p ${BOT_INSTALL_PATH}
    
    msg_info "2. Скачивание файлов проекта из ветки '${branch}'..."
    if ! ${DOWNLOADER} "${BOT_PY_URL}" | sudo tee "${BOT_INSTALL_PATH}/bot.py" > /dev/null; then
        msg_error "Не удалось скачать bot.py."
        exit 1
    fi
    if ! ${DOWNLOADER} "${REQUIREMENTS_URL}" | sudo tee "${BOT_INSTALL_PATH}/requirements.txt" > /dev/null; then
        msg_error "Не удалось скачать requirements.txt."
        exit 1
    fi
    echo "$branch" | sudo tee "${BOT_INSTALL_PATH}/.branch" > /dev/null
}

install_logic() {
    local install_mode=$1
    local branch=$2

    common_install_steps $branch
    
    local exec_user_cmd=""
    if [ "$install_mode" == "secure" ]; then
        msg_info "3. Создание системного пользователя '${SERVICE_USER}'..."
        if ! id "${SERVICE_USER}" &>/dev/null; then
            sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}
        fi
        sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
        sudo chmod -R 750 ${BOT_INSTALL_PATH}
        exec_user_cmd="sudo -u ${SERVICE_USER}"
    else
        sudo chown -R root:root ${BOT_INSTALL_PATH}
        sudo chmod -R 755 ${BOT_INSTALL_PATH}
    fi

    msg_info "4. Настройка виртуального окружения Python..."
    pushd ${BOT_INSTALL_PATH} > /dev/null
    if [ ! -d "${VENV_PATH}" ]; then
        run_with_spinner "Создание venv" $exec_user_cmd ${PYTHON_BIN} -m venv venv
    fi
    run_with_spinner "Обновление pip" $exec_user_cmd ${VENV_PATH}/bin/pip install --upgrade pip
    run_with_spinner "Установка зависимостей Python" $exec_user_cmd ${VENV_PATH}/bin/pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        msg_error "Ошибка при установке зависимостей Python."
        popd > /dev/null
        exit 1
    fi

    msg_info "5. Настройка переменных окружения..."
    msg_question "Введите ваш Telegram Bot Token: " TG_BOT_TOKEN_USER
    msg_question "Введите ваш Telegram User ID (только цифры): " TG_ADMIN_ID_USER

    sudo tee .env > /dev/null <<EOF
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
INSTALL_MODE="${install_mode}"
EOF

    local owner="root:root"
    if [ "$install_mode" == "secure" ]; then owner="${SERVICE_USER}:${SERVICE_USER}"; fi
    sudo chown ${owner} .env
    sudo chmod 600 .env
    popd > /dev/null
    
    if [ "$install_mode" == "root" ]; then
      msg_info "6. Настройка прав sudo..."
      SUDOERS_FILE="/etc/sudoers.d/98-${SERVICE_NAME}-root"
      sudo tee ${SUDOERS_FILE} > /dev/null <<EOF
root ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}.service
root ALL=(ALL) NOPASSWD: /sbin/reboot
EOF
      sudo chmod 440 ${SUDOERS_FILE}
    fi

    create_and_start_service $install_mode
}

create_and_start_service() {
    local install_mode=$1
    local user="root"
    local group="root"
    if [ "$install_mode" == "secure" ]; then
        user=${SERVICE_USER}
        group=${SERVICE_USER}
    fi
    
    msg_info "Создание systemd сервиса..."
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${SERVICE_NAME} Telegram Bot
After=network.target
[Service]
Restart=always
RestartSec=5
User=${user}
Group=${group}
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python ${BOT_INSTALL_PATH}/bot.py
[Install]
WantedBy=multi-user.target
EOF

    msg_info "Запуск и активация сервиса..."
    sudo systemctl daemon-reload
    sudo systemctl enable ${SERVICE_NAME}.service &> /dev/null
    sudo systemctl start ${SERVICE_NAME}.service
    sleep 2

    if sudo systemctl is-active --quiet ${SERVICE_NAME}.service; then
        msg_success "Сервис ${SERVICE_NAME} успешно запущен!"
        echo -e "\n${C_GREEN}${C_BOLD}🎉 Установка завершена! Напишите боту /start.${C_RESET}\n"
    else
        msg_error "Сервис не запустился. Логи: sudo journalctl -u ${SERVICE_NAME} -xe"
        exit 1
    fi
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Начало удаления Telegram-бота ===${C_RESET}"
    msg_question "ВЫ УВЕРЕНЫ, что хотите ПОЛНОСТЬЮ удалить бота? (y/n): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        msg_info "Удаление отменено."
        return
    fi

    msg_info "1. Остановка и отключение сервиса..."
    sudo systemctl stop ${SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} &> /dev/null

    msg_info "2. Удаление системных файлов..."
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"
    sudo systemctl daemon-reload

    msg_info "3. Удаление директории и пользователя..."
    sudo rm -rf "${BOT_INSTALL_PATH}"
    if id "${SERVICE_USER}" &>/dev/null; then
        sudo userdel -r "${SERVICE_USER}"
    fi
    msg_success "Удаление полностью завершено."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Начало обновления bot.py ===${C_RESET}"
    if [ ! -f "${BOT_INSTALL_PATH}/.branch" ]; then
        msg_error "Не удалось определить установленную ветку. Попробуйте переустановить бота."
        exit 1
    fi
    
    local branch=$(sudo cat "${BOT_INSTALL_PATH}/.branch")
    msg_info "Обновление ветки: ${branch}"

    if [ "$branch" == "release" ]; then
        BOT_PY_URL=$RELEASE_BOT_PY_URL
    else
        BOT_PY_URL=$FEATURE_BOT_PY_URL
    fi
    
    msg_info "1. Скачивание новой версии bot.py..."
    if ${DOWNLOADER} "${BOT_PY_URL}" | sudo tee "${BOT_INSTALL_PATH}/bot.py" > /dev/null; then
        msg_success "Файл bot.py успешно обновлен."
    else
        msg_error "Не удалось скачать файл."
        exit 1
    fi

    msg_info "2. Перезапуск сервиса..."
    if sudo systemctl restart ${SERVICE_NAME}; then
        msg_success "Сервис ${SERVICE_NAME} успешно перезапущен."
        echo -e "\n${C_GREEN}${C_BOLD}🎉 Обновление завершено!${C_RESET}\n"
    else
        msg_error "Ошибка при перезапуске. Логи: sudo journalctl -u ${SERVICE_NAME} -xe"
        exit 1
    fi
}

show_install_menu() {
    clear
    echo -e "${C_BOLD}--- Меню Установки ---${C_RESET}"
    echo "1) Release (стабильная версия)"
    echo "2) Feature (тестовая функциональность)"
    read -p "Выберите ветку для установки [1-2]: " branch_choice
    
    local branch="release"
    if [ "$branch_choice" == "2" ]; then
        branch="feature"
    fi

    echo -e "\n${C_BOLD}--- Режим Установки ---${C_RESET}"
    echo "1) Secure (рекомендуемый, безопасный)"
    echo "2) Root (полный доступ, менее безопасный)"
    read -p "Выберите режим установки [1-2]: " mode_choice

    if [ "$mode_choice" == "1" ]; then
        install_logic "secure" "$branch"
    elif [ "$mode_choice" == "2" ]; then
        if [ "$(id -u)" -ne 0 ]; then
            msg_error "Для установки в режиме Root, запустите скрипт с 'sudo'."
            exit 1
        fi
        install_logic "root" "$branch"
    else
        msg_error "Неверный выбор."
    fi
}

main_menu() {
    clear
    echo -e "${C_BLUE}${C_BOLD}"
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║          Скрипт управления Telegram-ботом            ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo -e "${C_RESET}"
    echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Установить / Переустановить бота${C_RESET}"
    echo -e "${C_CYAN}  2)${C_RESET} ${C_BOLD}Обновить бота${C_RESET} (авто-выбор ветки)"
    echo -e "${C_RED}  3)${C_RESET} ${C_BOLD}Удалить бота${C_RESET}"
    echo -e "  4) ${C_BOLD}Выход${C_RESET}"
    echo "--------------------------------------------------------"
    read -p "$(echo -e "${C_BOLD}Введите номер опции [1-4]: ${C_RESET}")" choice

    case $choice in
        1) show_install_menu ;;
        2) update_bot ;;
        3) uninstall_bot ;;
        4) exit 0 ;;
        *) msg_error "Неверный выбор." ;;
    esac
}

main_menu