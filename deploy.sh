#!/bin/bash

# --- Запоминаем исходный аргумент ---
orig_arg1="$1"

# --- Конфигурация ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"

# --- GitHub Репозиторий и Ветка ---
GITHUB_REPO="jatixs/tgbotvpscp"
# Используем $orig_arg1 если он есть, иначе 'main'.
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"

# --- Цвета и функции вывода ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'
C_BOLD='\033[1m'

msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }
msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }
msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
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
    "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 &
    local pid=$!
    spinner "$pid" "$msg" # Исправлен порядок аргументов для spinner
    wait $pid
    local exit_code=$?
    # Убираем \r перед выводом ошибки/успеха
    echo -ne "\033[2K\r"
    if [ $exit_code -ne 0 ]; then
        msg_error "Ошибка во время '$msg'. Код выхода: $exit_code"
        msg_error "Смотрите лог для деталей: /tmp/${SERVICE_NAME}_install.log"
    # else # Можно добавить сообщение об успехе, если нужно
    #    msg_success "'$msg' завершено."
    fi
    return $exit_code
}


# --- Проверка загрузчика ---
if command -v wget &> /dev/null; then
    DOWNLOADER="wget -qO-"
    # DOWNLOADER_PIPE="wget -qO-" # wget не очень хорошо работает с пайпами для скриптов, curl лучше
elif command -v curl &> /dev/null; then
    DOWNLOADER="curl -sSLf"
    # DOWNLOADER_PIPE="curl -s" # Аналогично
else
    msg_error "Ни wget, ни curl не найдены. Пожалуйста, установите один из них (sudo apt install curl wget) и запустите скрипт снова."
    exit 1
fi
# Используем curl для скачивания скриптов в пайп, если он есть, иначе wget
if command -v curl &> /dev/null; then DOWNLOADER_PIPE="curl -s"; else DOWNLOADER_PIPE="wget -qO-"; fi


# --- Проверка целостности ---
INSTALL_STATUS="NOT_FOUND"
STATUS_MESSAGE="Проверка не проводилась."

check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ]; then
        INSTALL_STATUS="NOT_FOUND"
        STATUS_MESSAGE="Бот не установлен."
        return
    fi
    INSTALL_STATUS="OK" # Предполагаем, что все хорошо
    local errors=()
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then errors+=("- Отсутствует .git (обновление будет невозможно)"); INSTALL_STATUS="PARTIAL"; fi
    if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || \
       [ ! -f "${BOT_INSTALL_PATH}/watchdog.py" ] || \
       [ ! -d "${BOT_INSTALL_PATH}/core" ] || \
       [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then
         errors+=("- Отсутствуют основные файлы (bot.py, core/, modules/)")
         INSTALL_STATUS="PARTIAL"
    fi
    if [ ! -f "${VENV_PATH}/bin/python" ]; then errors+=("- Отсутствует venv (${VENV_PATH}/bin/python)"); INSTALL_STATUS="PARTIAL"; fi
    if [ ! -f "${BOT_INSTALL_PATH}/.env" ]; then errors+=("- (Предупреждение) Отсутствует файл .env"); fi
    if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then errors+=("- Отсутствует файл ${SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi
    if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then errors+=("- Отсутствует файл ${WATCHDOG_SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi

    if [ "$INSTALL_STATUS" == "OK" ]; then
        local bot_status; local watchdog_status
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Активен${C_RESET}"; else bot_status="${C_RED}Неактивен${C_RESET}"; fi
        if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Активен${C_RESET}"; else watchdog_status="${C_RED}Неактивен${C_RESET}"; fi
        STATUS_MESSAGE="Установка OK (Бот: ${bot_status} | Watchdog: ${watchdog_status})"
        if [[ " ${errors[*]} " =~ " .env" ]]; then STATUS_MESSAGE+=" ${C_YELLOW}(Нет .env!)${C_RESET}"; fi
    elif [ "$INSTALL_STATUS" == "PARTIAL" ]; then
        STATUS_MESSAGE="${C_RED}Установка повреждена.${C_RESET}\n  Проблема: ${errors[0]}"
    fi
}

# --- Функции установки ---
install_extras() {
    local packages_to_install=()
    if ! command -v fail2ban-client &> /dev/null; then msg_question "Fail2Ban не найден. Установить? (y/n): " INSTALL_F2B; if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then packages_to_install+=("fail2ban"); else msg_info "Пропуск Fail2Ban."; fi; else msg_success "Fail2Ban уже установлен."; fi
    if ! command -v speedtest &> /dev/null; then msg_question "Speedtest CLI не найден. Установить? (y/n): " INSTALL_SPEEDTEST; if [[ "$INSTALL_SPEEDTEST" =~ ^[Yy]$ ]]; then packages_to_install+=("speedtest-cli"); else msg_info "Пропуск Speedtest CLI."; fi; else msg_success "Speedtest CLI уже установлен."; fi # Используем speedtest-cli из стандартных репо, если возможно
    if [ ${#packages_to_install[@