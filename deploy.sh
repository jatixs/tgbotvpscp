#!/bin/bash

# --- Конфигурация ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"

# --- GitHub Репозиторий и Ветка ---
GITHUB_REPO="jatixs/tgbotvpscp"
GIT_BRANCH="${1:-main}" # Используем $1 или 'main' по умолчанию
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
    spinner "$msg" "$@"
    wait $pid
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        msg_error "Ошибка во время '$msg'. Код выхода: $exit_code"
        msg_error "Смотрите лог для деталей: /tmp/${SERVICE_NAME}_install.log"
    fi
    return $exit_code
}

# --- Проверка загрузчика (для install_extras) ---
if command -v curl &> /dev/null; then
    DOWNLOADER="curl -sSLf"
    DOWNLOADER_PIPE="curl -s"
else
    msg_error "Curl не найден. Пожалуйста, установите curl (sudo apt install curl) и запустите скрипт снова."
    exit 1
fi

# --- (НОВАЯ ФУНКЦИЯ) Проверка целостности ---
INSTALL_STATUS="NOT_FOUND"
STATUS_MESSAGE="Проверка не проводилась."

check_integrity() {
    # 1. Проверка базовой директории
    if [ ! -d "${BOT_INSTALL_PATH}" ]; then
        INSTALL_STATUS="NOT_FOUND"
        STATUS_MESSAGE="Бот не установлен."
        return
    fi

    # Если директория есть, считаем установку частичной и ищем ошибки
    INSTALL_STATUS="OK" # Предполагаем, что все хорошо
    local errors=()

    # 2. Проверка Git
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then
        errors+=("- Отсутствует .git (обновление будет невозможно)")
        INSTALL_STATUS="PARTIAL"
    fi

    # 3. Проверка ключевых файлов и директорий
    if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || \
       [ ! -f "${BOT_INSTALL_PATH}/watchdog.py" ] || \
       [ ! -d "${BOT_INSTALL_PATH}/core" ] || \
       [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then
         errors+=("- Отсутствуют основные файлы (bot.py, core/, modules/)")
         INSTALL_STATUS="PARTIAL"
    fi

    # 4. Проверка Venv
    if [ ! -f "${VENV_PATH}/bin/python" ]; then
        errors+=("- Отсутствует venv (${VENV_PATH}/bin/python)")
        INSTALL_STATUS="PARTIAL"
    fi

    # 5. Проверка .env (предупреждение)
    if [ ! -f "${BOT_INSTALL_PATH}/.env" ]; then
        errors+=("- (Предупреждение) Отсутствует файл .env")
        # Не меняем статус на PARTIAL, т.к. сервисы могут просто не запуститься
    fi

    # 6. Проверка файлов сервисов
    if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then
         errors+=("- Отсутствует файл ${SERVICE_NAME}.service")
         INSTALL_STATUS="PARTIAL"
    fi
     if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then
         errors+=("- Отсутствует файл ${WATCHDOG_SERVICE_NAME}.service")
         INSTALL_STATUS="PARTIAL"
    fi

    # 7. Формирование итогового сообщения
    if [ "$INSTALL_STATUS" == "OK" ]; then
        local bot_status
        local watchdog_status
        
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then
            bot_status="${C_GREEN}Активен${C_RESET}"
        else
            bot_status="${C_RED}Неактивен${C_RESET}"
        fi
        
        if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then
            watchdog_status="${C_GREEN}Активен${C_RESET}"
        else
            watchdog_status="${C_RED}Неактивен${C_RESET}"
        fi
        
        STATUS_MESSAGE="Установка OK (Бот: ${bot_status} | Watchdog: ${watchdog_status})"
        
        if [[ " ${errors[*]} " =~ " .env" ]]; then
            STATUS_MESSAGE+=" ${C_YELLOW}(Нет .env!)${C_RESET}"
        fi
        
    elif [ "$INSTALL_STATUS" == "PARTIAL" ]; then
        STATUS_MESSAGE="${C_RED}Установка повреждена.${C_RESET}\n  Проблема: ${errors[0]}"
    fi
}


# --- (Все остальные функции install_*, create_service_*, uninstall_bot, update_bot... БЕЗ ИЗМЕНЕНИЙ) ---
install_extras() {
    local packages_to_install=()
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then
            packages_to_install+=("fail2ban")
        else msg_info "Пропуск Fail2Ban."; fi
    else msg_success "Fail2Ban уже установлен."; fi

    if ! command -v speedtest &> /dev/null; then
        msg_question "Speedtest CLI не найден. Установить? (y/n): " INSTALL_SPEEDTEST
        if [[ "$INSTALL_SPEEDTEST" =~ ^[Yy]$ ]]; then
            packages_to_install+=("speedtest") # Используем метапакет ookla
        else msg_info "Пропуск Speedtest CLI."; fi
    else msg_success "Speedtest CLI уже установлен."; fi

    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Установка дополнительных пакетов: ${packages_to_install[*]}"
        if [[ " ${packages_to_install[*]} " =~ " speedtest " ]]; then
             run_with_spinner "Добавление репозитория Speedtest" bash -c "${DOWNLOADER_PIPE} https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash"
             if [ -f /etc/os-release ]; then . /etc/os-release; if [ "$VERSION_CODENAME" == "noble" ]; then sudo sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list; fi; fi
        fi
        run_with_spinner "Обновление списка пакетов после добавления репо" sudo apt-get update -y
        run_with_spinner "Установка пакетов" sudo apt-get install -y "${packages_to_install[@]}"
        if [ $? -ne 0 ]; then msg_error "Ошибка при установке доп. пакетов."; exit 1; fi
        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then
            sudo systemctl enable fail2ban &> /dev/null
            sudo systemctl start fail2ban &> /dev/null
            msg_success "Fail2Ban установлен и запущен."
        fi
        msg_success "Дополнительные пакеты установлены."
    fi
}

common_install_steps() {
    msg_info "1. Обновление пакетов и установка базовых зависимостей..."
    run_with_spinner "Обновление списка пакетов" sudo apt-get update -y || { msg_error "Не удалось обновить пакеты"; exit 1; }
    run_with_spinner "Установка зависимостей (python3, pip, venv, git, curl, sudo)" sudo apt-get install -y python3 python3-pip python3-venv git curl wget sudo || { msg_error "Не удалось установить базовые зависимости"; exit 1; }
    install_extras
}

install_logic() {
    local mode=$1
    local exec_user_cmd=""
    local owner="root:root"
    local owner_user="root" 

    if [ "$mode" == "secure" ]; then
        msg_info "2. Создание системного пользователя '${SERVICE_USER}'..."
        if ! id "${SERVICE_USER}" &>/dev/null; then
            sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || { msg_error "Не удалось создать пользователя ${SERVICE_USER}"; exit 1; }
        fi
        sudo mkdir -p ${BOT_INSTALL_PATH}
        sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
        msg_info "3. Клонирование репозитория (ветка ${GIT_BRANCH}) от имени ${SERVICE_USER}..."
        run_with_spinner "Клонирование репозитория" \
            sudo -u ${SERVICE_USER} git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}"
        if [ $? -ne 0 ]; then msg_error "Не удалось клонировать репозиторий. Проверьте URL и имя ветки."; exit 1; fi
        exec_user_cmd="sudo -u ${SERVICE_USER}"
        owner="${SERVICE_USER}:${SERVICE_USER}"
        owner_user=${SERVICE_USER}
    else # Root mode
        msg_info "2. Создание директории для бота..."
        sudo mkdir -p ${BOT_INSTALL_PATH}
        msg_info "3. Клонирование репозитория (ветка ${GIT_BRANCH}) от имени root..."
        run_with_spinner "Клонирование репозитория" \
            sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT