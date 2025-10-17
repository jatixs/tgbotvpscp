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
        if ! id "${SERVICE_USER}" &