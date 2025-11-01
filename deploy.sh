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
README_FILE="${BOT_INSTALL_PATH}/README.md"
# --- ДОБАВЛЕНЫ ПЕРЕМЕННЫЕ DOCKER ---
DOCKER_COMPOSE_FILE="${BOT_INSTALL_PATH}/docker-compose.yml"
ENV_FILE="${BOT_INSTALL_PATH}/.env"

# --- GitHub Репозиторий и Ветка ---
GITHUB_REPO="jatixs/tgbotvpscp"
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

# --- Цвета и функции вывода ---
C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }; msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }
spinner() { local pid=$1; local msg=$2; local spin='|/-\'; local i=0; while kill -0 $pid 2>/dev/null; do i=$(( (i+1) %4 )); printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"; sleep .1; done; printf "\r"; }
run_with_spinner() { local msg=$1; shift; ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) & local pid=$!; spinner "$pid" "$msg"; wait $pid; local exit_code=$?; echo -ne "\033[2K\r"; if [ $exit_code -ne 0 ]; then msg_error "Ошибка во время '$msg'. Код: $exit_code"; msg_error "Лог: /tmp/${SERVICE_NAME}_install.log"; fi; return $exit_code; }

# --- Проверка загрузчика ---
if command -v wget &> /dev/null; then DOWNLOADER="wget -qO-"; elif command -v curl &> /dev/null; then DOWNLOADER="curl -sSLf"; else msg_error "Ни wget, ни curl не найдены."; exit 1; fi
if command -v curl &> /dev/null; then DOWNLOADER_PIPE="curl -s"; else DOWNLOADER_PIPE="wget -qO-"; fi

# --- Функции версий ---
get_local_version() { local readme_path="$1"; local version="Не найдена"; if [ -f "$readme_path" ]; then version=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$readme_path" || true); if [ -z "$version" ]; then version=$(grep -oP '<b\s*>v\K[\d\.]+(?=</b>)' "$readme_path" || true); fi; if [ -z "$version" ]; then version="Не найдена"; else version="v$version"; fi; else version="Не установлен"; fi; echo "$version"; }
get_latest_version() { local api_url="$1"; local latest_tag=$($DOWNLOADER_PIPE "$api_url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "Ошибка API"); if [[ "$latest_tag" == *"API rate limit exceeded"* ]]; then latest_tag="Лимит API"; elif [[ "$latest_tag" == "Ошибка API" ]] || [ -z "$latest_tag" ]; then latest_tag="Неизвестно"; fi; echo "$latest_tag"; }

# --- [СИЛЬНО ИЗМЕНЕНО] Проверка целостности ---
INSTALL_TYPE="NONE"; STATUS_MESSAGE="Проверка не проводилась."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Бот не установлен."; return;
    fi

    # Определяем тип установки (Docker или Systemd)
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "unknown")

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="DOCKER ($INSTALL_MODE_FROM_ENV)"
        if ! command -v docker &> /dev/null; then
            STATUS_MESSAGE="${C_RED}Установка Docker повреждена (Docker не найден).${C_RESET}"; return;
        fi
        if ! (command -v docker-compose &> /dev/null || docker compose version &> /dev/null); then
            STATUS_MESSAGE="${C_RED}Установка Docker повреждена (Docker Compose не найден).${C_RESET}"; return;
        fi
        if [ ! -f "${DOCKER_COMPOSE_FILE}" ]; then
            STATUS_MESSAGE="${C_RED}Установка Docker повреждена (Нет docker-compose.yml).${C_RESET}"; return;
        fi
        
        local bot_container_name=$(grep '^TG_BOT_CONTAINER_NAME=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ -z "$bot_container_name" ]; then
            bot_container_name="tg-bot-${INSTALL_MODE_FROM_ENV}" # Запасной вариант
        fi
        local watchdog_container_name="tg-watchdog"
        
        local bot_status; local watchdog_status;
        if docker ps -f "name=${bot_container_name}" --format '{{.Names}}' | grep -q "${bot_container_name}"; then bot_status="${C_GREEN}Активен${C_RESET}"; else bot_status="${C_RED}Неактивен${C_RESET}"; fi
        if docker ps -f "name=${watchdog_container_name}" --format '{{.Names}}' | grep -q "${watchdog_container_name}"; then watchdog_status="${C_GREEN}Активен${C_RESET}"; else watchdog_status="${C_RED}Неактивен${C_RESET}"; fi
        
        STATUS_MESSAGE="Установка Docker OK (Бот: ${bot_status} | Наблюдатель: ${watchdog_status})"

    else # Systemd
        INSTALL_TYPE="SYSTEMD ($INSTALL_MODE_FROM_ENV)"
        INSTALL_STATUS="OK"; local errors=();
        if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || [ ! -d "${BOT_INSTALL_PATH}/core" ] || [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then errors+=("- Отсутствуют основные файлы"); INSTALL_STATUS="PARTIAL"; fi;
        if [ ! -f "${VENV_PATH}/bin/python" ]; then errors+=("- Отсутствует venv"); INSTALL_STATUS="PARTIAL"; fi;
        if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then errors+=("- Отсутствует ${SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi;
        if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then errors+=("- Отсутствует ${WATCHDOG_SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi;
        
        if [ "$INSTALL_STATUS" == "OK" ]; then
            local bot_status; local watchdog_status;
            if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Активен${C_RESET}"; else bot_status="${C_RED}Неактивен${C_RESET}"; fi;
            if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Активен${C_RESET}"; else watchdog_status="${C_RED}Неактивен${C_RESET}"; fi;
            STATUS_MESSAGE="Установка Systemd OK (Бот: ${bot_status} | Наблюдатель: ${watchdog_status})"
        else
            STATUS_MESSAGE="${C_RED}Установка Systemd повреждена.${C_RESET}\n  Проблема: ${errors[0]}"
        fi
    fi
}


# --- Функции установки ---
install_extras() {
    local packages_to_install=()
    local packages_to_remove=()

    # Fail2Ban Check
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then
            packages_to_install+=("fail2ban")
        else
            msg_info "Пропуск Fail2Ban."
        fi
    else
        msg_success "Fail2Ban уже установлен."
    fi

    # iperf3 Check
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 не найден. Он необходим для модуля 'Скорость сети'. Установить? (y/n): " INSTALL_IPERF3
        if [[ "$INSTALL_IPERF3" =~ ^[Yy]$ ]]; then
            packages_to_install+=("iperf3")
        else
            msg_info "Пропуск iperf3. Модуль 'Скорость сети' не будет работать."
        fi
    else
        msg_success "iperf3 уже установлен."
    fi

    # Speedtest CLI Check for removal
    if command -v speedtest &> /dev/null || dpkg -s speedtest-cli &> /dev/null; then
        msg_warning "Обнаружен старый пакет 'speedtest-cli'."
        msg_question "Удалить 'speedtest-cli'? (Рекомендуется, т.к. бот теперь использует iperf3) (y/n): " REMOVE_SPEEDTEST
        if [[ "$REMOVE_SPEEDTEST" =~ ^[Yy]$ ]]; then
            packages_to_remove+=("speedtest-cli")
        else
            msg_info "Пропуск удаления speedtest-cli."
        fi
    fi

    # Package Removal
    if [ ${#packages_to_remove[@]} -gt 0 ]; then
        msg_info "Удаление пакетов: ${packages_to_remove[*]}"
        run_with_spinner "Удаление пакетов" sudo apt-get remove --purge -y "${packages_to_remove[@]}"
        run_with_spinner "Очистка apt" sudo apt-get autoremove -y
        msg_success "Указанные пакеты удалены."
    fi

    # Package Installation
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Установка дополнительных пакетов: ${packages_to_install[*]}"
        run_with_spinner "Обновление списка пакетов" sudo apt-get update -y
        run_with_spinner "Установка пакетов" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages_to_install[@]}"
        if [ $? -ne 0 ]; then msg_error "Ошибка при установке доп. пакетов."; exit 1; fi

        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then
             sudo systemctl enable fail2ban &> /dev/null
             sudo systemctl start fail2ban &> /dev/null
             msg_success "Fail2Ban установлен и запущен."
        fi
        if [[ " ${packages_to_install[*]} " =~ " iperf3 " ]]; then
             msg_success "iperf3 установлен."
        fi
        msg_success "Дополнительные пакеты установлены."
    fi
}
# --- [ИЗМЕНЕНО] common_install_steps ---
common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Обновление пакетов и установка базовых зависимостей..."
    run_with_spinner "Обновление списка пакетов" sudo apt-get update -y || { msg_error "Не удалось обновить пакеты"; exit 1; }
    # Добавляем python3-yaml к основным зависимостям
    run_with_spinner "Установка зависимостей (python3, pip, venv, git, curl, wget, sudo, yaml)" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo python3-yaml || { msg_error "Не удалось установить базовые зависимости"; exit 1; }
    install_extras
}
# --- [КОНЕЦ ИЗМЕНЕНИЙ] common_install_steps ---

# --- НОВАЯ ФУНКЦИЯ: Запрос данных .env ---
ask_env_details() {
    msg_info "Пожалуйста, введите данные для .env файла..."
    msg_question "Токен Бота (TG_BOT_TOKEN): " T
    msg_question "ID Администратора (TG_ADMIN_ID): " A
    msg_question "Имя (Username) Админа (TG_ADMIN_USERNAME, опц): " U
    msg_question "Имя Бота (TG_BOT_NAME, опц, напр. 'Мой VPS'): " N
    
    # Экспортируем их для использования в вызывающих функциях
    export T A U N
}

# --- НОВАЯ ФУНКЦИЯ: Запись .env ---
write_env_file() {
    local deploy_mode=$1 # "systemd" или "docker"
    local install_mode=$2 # "secure" или "root"
    local container_name=$3 # "tg-bot-secure" / "tg-bot-root" / ""

    msg_info "Создание .env файла..."
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
# --- Настройки Telegram-бота ---
TG_BOT_TOKEN="${T}"
TG_ADMIN_ID="${A}"
TG_ADMIN_USERNAME="${U}"
TG_BOT_NAME="${N}"

# --- Настройки развертывания (НЕ ИЗМЕНЯТЬ ВРУЧНУЮ) ---
INSTALL_MODE="${install_mode}"
DEPLOY_MODE="${deploy_mode}"
TG_BOT_CONTAINER_NAME="${container_name}"
EOF
    sudo chmod 600 "${ENV_FILE}"
    msg_success ".env файл создан."
}

# --- НОВАЯ ФУНКЦИЯ: Клонирование репо и настройка прав ---
setup_repo_and_dirs() {
    local owner_user="root"
    if [ "$1" == "secure" ]; then
        msg_info "Создание пользователя '${SERVICE_USER}'..."
        if ! id "${SERVICE_USER}" &>/dev/null; then
            sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || exit 1
        fi
        owner_user=${SERVICE_USER}
    fi
    
    sudo mkdir -p ${BOT_INSTALL_PATH}
    msg_info "Клонирование репозитория (ветка ${GIT_BRANCH})..."
    run_with_spinner "Клонирование репозитория" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    
    msg_info "Создание .gitignore, logs/, config/..."
    # [ИСПРАВЛЕНИЕ] Убираем docker-compose.yml из .gitignore
    sudo -u ${owner_user} bash -c "cat > ${BOT_INSTALL_PATH}/.gitignore" <<< $'/venv/\n/__pycache__/\n*.pyc\n/.env\n/config/\n/logs/\n*.log\n*_flag.txt'
    sudo chmod 644 "${BOT_INSTALL_PATH}/.gitignore"
    sudo -u ${owner_user} mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/config"
    
    # Установка владельца для всего, кроме .git
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
    sudo chown -R root:root ${BOT_INSTALL_PATH}/.git
    
    # Экспортируем владельца для .env
    export OWNER_USER=${owner_user}
}

# --- [ИСПРАВЛЕНО] НОВАЯ ФУНКЦИЯ: Проверка Docker ---
check_docker_deps() {
    msg_info "Проверка зависимостей Docker..."
    if ! command -v docker &> /dev/null; then
        msg_warning "Docker не найден. Попытка установки..."
        run_with_spinner "Установка Docker (docker.io)" sudo apt-get install -y docker.io || { msg_error "Не удалось установить docker.io."; exit 1; }
        sudo systemctl start docker
        sudo systemctl enable docker
    else
        msg_success "Docker найден."
    fi
    
    # Проверяем и v2 (docker compose) и v1 (docker-compose)
    if command -v docker-compose &> /dev/null; then
        msg_success "Docker Compose v1 (docker-compose) найден."
    elif docker compose version &> /dev/null; then
        msg_success "Docker Compose v2 (docker compose) найден."
    else
        msg_warning "Docker Compose не найден. Попытка установки..."
        
        # Попытка №1: Установить v2 плагин через apt (как было)
        msg_info "Попытка 1: Установка 'docker-compose-plugin' через apt..."
        sudo apt-get install -y docker-compose-plugin &> /tmp/${SERVICE_NAME}_install.log
        
        if docker compose version &> /dev/null; then
            msg_success "Успешно установлен 'docker-compose-plugin' (v2) через apt."
            # v2 не нуждается в симлинке /usr/bin/docker-compose
        else
            msg_warning "Не удалось установить v2 через apt. Попытка 2: Установка v1 ('docker-compose') через apt..."
            # Попытка №2: Установить v1 через apt
            sudo apt-get install -y docker-compose &> /tmp/${SERVICE_NAME}_install.log
            
            if command -v docker-compose &> /dev/null; then
                 msg_success "Успешно установлен 'docker-compose' (v1) через apt."
            else
                msg_warning "Не удалось установить v1 через apt. Попытка 3: Загрузка бинарного файла v2..."
                # Попытка №3: Скачать бинарный файл v2 (самый надежный способ)
                local DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
                if [ -z "$DOCKER_COMPOSE_VERSION" ] || [[ "$DOCKER_COMPOSE_VERSION" == *"API rate limit"* ]]; then
                    msg_error "Не удалось определить последнюю версию Docker Compose с GitHub (возможно, лимит API)."
                    msg_error "Пожалуйста, установите Docker Compose (v1 или v2) вручную."
                    exit 1;
                fi
                
                local LATEST_COMPOSE_URL="https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)"
                # [ИСПРАВЛЕНИЕ] Используем /usr/local/bin (стандартный) или /usr/libexec/docker/cli-plugins
                local DOCKER_CLI_PLUGIN_DIR="/usr/libexec/docker/cli-plugins"
                local DOCKER_COMPOSE_PATH="${DOCKER_CLI_PLUGIN_DIR}/docker-compose"

                sudo mkdir -p ${DOCKER_CLI_PLUGIN_DIR}
                
                msg_info "Загрузка Docker Compose ${DOCKER_COMPOSE_VERSION} в ${DOCKER_COMPOSE_PATH}..."
                run_with_spinner "Загрузка docker-compose" sudo curl -SLf "${LATEST_COMPOSE_URL}" -o "${DOCKER_COMPOSE_PATH}"
                if [ $? -ne 0 ]; then
                    msg_error "Не удалось скачать Docker Compose с ${LATEST_COMPOSE_URL}."
                    msg_error "Пожалуйста, установите Docker Compose (v1 или v2) вручную."
                    exit 1;
                fi
                
                sudo chmod +x "${DOCKER_COMPOSE_PATH}"
                
                # Проверяем еще раз
                if docker compose version &> /dev/null; then
                    msg_success "Успешно установлен Docker Compose v2 (бинарный файл)."
                else
                    msg_error "Не удалось установить Docker Compose. Пожалуйста, установите его вручную."
                    exit 1;
                fi
            fi
        fi
    fi
}


# --- Старые функции установки (Systemd) ---
create_and_start_service() { local svc=$1; local script=$2; local mode=$3; local desc=$4; local user="root"; local group="root"; local env=""; local suffix=""; local after="After=network.target"; local req=""; if [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ]; then user=${SERVICE_USER}; group=${SERVICE_USER}; suffix="(Безопасно)"; elif [ "$svc" == "$SERVICE_NAME" ]; then user="root"; group="root"; suffix="(Root)"; elif [ "$svc" == "$WATCHDOG_SERVICE_NAME" ]; then user="root"; group="root"; after="After=network.target ${SERVICE_NAME}.service"; fi; env="EnvironmentFile=${BOT_INSTALL_PATH}/.env"; msg_info "Создание systemd для ${svc}..."; FILE="/etc/systemd/system/${svc}.service"; sudo tee ${FILE} > /dev/null <<EOF
[Unit]
Description=${desc} Служба ${suffix}
${after}
${req}
[Service]
Type=simple
User=${user}
Group=${group}
WorkingDirectory=${BOT_INSTALL_PATH}
${env}
ExecStart=${VENV_PATH}/bin/python ${script}
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
msg_info "Запуск ${svc}..."; sudo systemctl daemon-reload; sudo systemctl enable ${svc}.service &> /dev/null; run_with_spinner "Запуск ${svc}" sudo systemctl restart ${svc}; sleep 2; if sudo systemctl is-active --quiet ${svc}.service; then msg_success "${svc} запущен!"; msg_info "Статус: sudo systemctl status ${svc}"; else msg_error "${svc} НЕ ЗАПУСТИЛСЯ. Логи: sudo journalctl -u ${svc} -n 50 --no-pager"; if [ "$svc" == "$SERVICE_NAME" ]; then exit 1; fi; fi; }

install_systemd_logic() { 
    local mode=$1 # "secure" или "root"
    local branch_to_use=$2
    
    common_install_steps
    setup_repo_and_dirs "$mode" # Клонирует репо и создает пользователя/папки
    
    local exec_user_cmd=""
    if [ "$mode" == "secure" ]; then
        exec_user_cmd="sudo -u ${SERVICE_USER}"
    fi

    msg_info "Настройка venv для Systemd..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" $exec_user_cmd ${PYTHON_BIN} -m venv "${VENV_PATH}" || exit 1; fi;
    run_with_spinner "Обновление pip" $exec_user_cmd "${VENV_PATH}/bin/pip" install --upgrade pip || msg_warning "Не удалось обновить pip...";
    run_with_spinner "Установка зависимостей Python" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" || exit 1;
    
    ask_env_details # Запрашивает T, A, U, N
    write_env_file "systemd" "$mode" "" # Пишет .env
    sudo chown ${OWNER_USER}:${OWNER_USER} "${ENV_FILE}" # Устанавливает владельца .env
    
    if [ "$mode" == "root" ]; then msg_info "Настройка sudo (root)..."; F="/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo tee ${F} > /dev/null <<< $'root ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-bot.service\nroot ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-watchdog.service\nroot ALL=(ALL) NOPASSWD: /sbin/reboot'; sudo chmod 440 ${F}; elif [ "$mode" == "secure" ]; then F="/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo tee ${F} > /dev/null <<< $'Defaults:tgbot !requiretty\ntgbot ALL=(root) NOPASSWD: /bin/systemctl restart tg-bot.service'; sudo chmod 440 ${F}; msg_info "Настройка sudo (secure)..."; fi;
    
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "${mode}" "Telegram Бот";
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель";
    
    local ip=$(curl -s --connect-timeout 5 ipinfo.io/ip || echo "Не удалось определить"); echo ""; echo "---"; msg_success "Установка (Systemd) завершена!"; msg_info "IP: ${ip}"; echo "---";
}

install_systemd_secure() { echo -e "\n${C_BOLD}=== Установка Systemd (Secure) (ветка: ${GIT_BRANCH}) ===${C_RESET}"; install_systemd_logic "secure" "${GIT_BRANCH}"; }
install_systemd_root() { echo -e "\n${C_BOLD}=== Установка Systemd (Root) (ветка: ${GIT_BRANCH}) ===${C_RESET}"; install_systemd_logic "root" "${GIT_BRANCH}"; }


# --- [ИСПРАВЛЕНО] НОВЫЕ ФУНКЦИИ УСТАНОВКИ (Docker) ---
create_dockerfile() {
    msg_info "Создание Dockerfile..."
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
# /opt/tg-bot/Dockerfile

# 1. Базовый образ
FROM python:3.10-slim-bookworm

LABEL maintainer="Jatixs"
LABEL description="Telegram VPS Bot"

# 2. Установка системных зависимостей
# Нужны для модулей бота (iperf3, yaml, ps, ping) и для сборки
RUN apt-get update && apt-get install -y \
    python3-yaml \
    iperf3 \
    git \
    curl \
    wget \
    sudo \
    procps \
    iputils-ping \
    net-tools \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 3. Установка Python-библиотеки Docker (для watchdog)
RUN pip install --no-cache-dir docker

# 4. Создание пользователя 'tgbot' (для режима secure)
# UID/GID 1001.
RUN groupadd -g 1001 tgbot && \
    useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && \
    # Даем пользователю tgbot права sudo внутри контейнера (для режима secure)
    echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# 5. Настройка рабочей директории
WORKDIR /opt/tg-bot

# 6. Установка зависимостей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 7. Копирование всего кода приложения
COPY . .

# 8. Создание и выдача прав на директории config и logs
# (Они будут переопределены volumes, но это гарантирует правильные права)
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && \
    chown -R tgbot:tgbot /opt/tg-bot

# 9. Установка пользователя 'tgbot' по умолчанию
# (docker-compose переопределит это на 'root' для root-режима)
USER tgbot

# 10. Команда по умолчанию
CMD ["python", "bot.py"]
EOF
    sudo chown ${OWNER_USER}:${OWNER_USER} "${BOT_INSTALL_PATH}/Dockerfile"
    sudo chmod 644 "${BOT_INSTALL_PATH}/Dockerfile"
}

create_docker_compose_yml() {
    msg_info "Создание docker-compose.yml..."
    sudo tee "${BOT_INSTALL_PATH}/docker-compose.yml" > /dev/null <<'EOF'
# /opt/tg-bot/docker-compose.yml
version: '3.8'

services:
  # --- БАЗОВАЯ КОНФИГУРАЦИЯ БОТА ---
  # (Используется для обоих режимов)
  bot-base: &bot-base
    build: .
    image: tg-vps-bot:latest
    restart: always
    env_file: .env # Подтягивает .env файл

  # --- РЕЖИМ SECURE (Docker) ---
  bot-secure:
    <<: *bot-base # Наследует 'bot-base'
    container_name: tg-bot-secure
    profiles: ["secure"] # Запускается командой: docker-compose --profile secure up
    user: "tgbot" # Запуск от пользователя 'tgbot' (UID 1001 из Dockerfile)
    environment:
      - INSTALL_MODE=secure # Сообщает боту, что он в secure режиме
      - DEPLOY_MODE=docker
      - TG_BOT_CONTAINER_NAME=tg-bot-secure # Имя для watchdog
    volumes:
      - ./config:/opt/tg-bot/config
      - ./logs/bot:/opt/tg-bot/logs/bot
      # --- Минимальный доступ к хосту ---
      - /var/run/docker.sock:/var/run/docker.sock:ro # Для модулей (xray)
      - /proc/uptime:/proc/uptime:ro                 # Для uptime
      - /proc/stat:/proc/stat:ro                     # Для selftest (cpu)
      - /proc/meminfo:/proc/meminfo:ro               # Для selftest (ram)
      - /proc/net/dev:/proc/net/dev:ro               # Для traffic
    cap_drop: [ALL]   # Сбрасываем все привилегии
    cap_add: [NET_RAW] # Добавляем только 'ping'

  # --- РЕЖИМ ROOT (Docker) ---
  bot-root:
    <<: *bot-base # Наследует 'bot-base'
    container_name: tg-bot-root
    profiles: ["root"] # Запускается командой: docker-compose --profile root up
    user: "root"
    environment:
      - INSTALL_MODE=root # Сообщает боту, что он в root режиме
      - DEPLOY_MODE=docker
      - TG_BOT_CONTAINER_NAME=tg-bot-root # Имя для watchdog
    # --- Полный доступ к хосту ---
    privileged: true     # Включает --privileged
    pid: "host"          # Доступ к процессам хоста (для 'top')
    network_mode: "host" # Использует сеть хоста
    ipc: "host"          # Использует IPC хоста
    volumes:
      # Монтируем config и logs
      - ./config:/opt/tg-bot/config
      - ./logs/bot:/opt/tg-bot/logs/bot
      # Монтируем всю ФС хоста, чтобы команды 'apt update', 'reboot'
      # и чтение логов работали без изменения путей в модулях
      - /:/host

  # --- НАБЛЮДАТЕЛЬ (WATCHDOG) ---
  watchdog:
    <<: *bot-base # Наследует 'bot-base'
    container_name: tg-watchdog
    # Не имеет профиля, запускается всегда (когда запущен docker-compose)
    command: python watchdog.py
    user: "root" # Нужен root для доступа к docker.sock
    restart: always
    volumes:
      - ./config:/opt/tg-bot/config # Для чтения RESTART_FLAG
      - ./logs/watchdog:/opt/tg-bot/logs/watchdog
      - /var/run/docker.sock:/var/run/docker.sock:ro # Доступ к Docker API
EOF
    sudo chown ${OWNER_USER}:${OWNER_USER} "${BOT_INSTALL_PATH}/docker-compose.yml"
    sudo chmod 644 "${BOT_INSTALL_PATH}/docker-compose.yml"
}


install_docker_logic() {
    local mode=$1 # "secure" или "root"
    local branch_to_use=$2
    local container_name="tg-bot-${mode}"
    
    check_docker_deps # Проверяет/ставит docker и compose
    setup_repo_and_dirs "$mode" # Клонирует репо и создает пользователя/папки (OWNER_USER экспортируется)
    
    # --- [ИСПРАВЛЕНИЕ] Создаем файлы ДО сборки ---
    create_dockerfile
    create_docker_compose_yml
    # ----------------------------------------
    
    ask_env_details # Запрашивает T, A, U, N
    write_env_file "docker" "$mode" "$container_name" # Пишет .env
    sudo chown ${OWNER_USER}:${OWNER_USER} "${ENV_FILE}" # Устанавливает владельца .env

    # --- [ИСПРАВЛЕНИЕ] Определяем команду compose ---
    local COMPOSE_CMD=""
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="sudo docker-compose"
    elif docker compose version &> /dev/null; then
        COMPOSE_CMD="sudo docker compose"
    else
        msg_error "[Install] Не найдена команда docker-compose. Установка Docker прервана."
        exit 1
    fi
    
    msg_info "Сборка Docker образа..."
    (cd ${BOT_INSTALL_PATH} && run_with_spinner "Сборка образа tg-vps-bot:latest" $COMPOSE_CMD build) || { msg_error "Сборка Docker не удалась."; exit 1; }
    
    msg_info "Запуск Docker Compose (Профиль: ${mode})..."
    (cd ${BOT_INSTALL_PATH} && run_with_spinner "Запуск контейнеров" $COMPOSE_CMD --profile "${mode}" up -d) || { msg_error "Запуск Docker Compose не удался."; exit 1; }
    
    sleep 2
    msg_success "Установка (Docker) завершена!"
    msg_info "Контейнеры:"
    (cd ${BOT_INSTALL_PATH} && $COMPOSE_CMD ps)
    msg_info "Логи бота: $COMPOSE_CMD logs -f ${container_name}"
    msg_info "Логи наблюдателя: $COMPOSE_CMD logs -f tg-watchdog"
}

install_docker_secure() { echo -e "\n${C_BOLD}=== Установка Docker (Secure) (ветка: ${GIT_BRANCH}) ===${C_RESET}"; install_docker_logic "secure" "${GIT_BRANCH}"; }
install_docker_root() { echo -e "\n${C_BOLD}=== Установка Docker (Root) (ветка: ${GIT_BRANCH}) ===${C_RESET}"; install_docker_logic "root" "${GIT_BRANCH}"; }


# --- [СИЛЬНО ИЗМЕНЕНО] ОБНОВЛЕННАЯ ФУНКЦИЯ УДАЛЕНИЯ ---
uninstall_bot() {
    echo -e "\n${C_BOLD}=== Удаление Бота ===${C_RESET}";
    
    # 1. Остановка Systemd
    msg_info "1. Остановка служб Systemd (если есть)...";
    if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then
        sudo systemctl stop ${SERVICE_NAME} &> /dev/null
        sudo systemctl disable ${SERVICE_NAME} &> /dev/null
    fi
    if systemctl list-units --full -all | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then
        sudo systemctl stop ${WATCHDOG_SERVICE_NAME} &> /dev/null
        sudo systemctl disable ${WATCHDOG_SERVICE_NAME} &> /dev/null
    fi
    
    # 2. Остановка Docker
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then
        msg_info "2. Остановка контейнеров Docker (если есть)...";
        # [ИСПРАВЛЕНИЕ] Определяем команду compose
        local COMPOSE_CMD=""
        if command -v docker-compose &> /dev/null; then
            COMPOSE_CMD="sudo docker-compose"
        elif docker compose version &> /dev/null; then
            COMPOSE_CMD="sudo docker compose"
        fi
        
        if [ -n "$COMPOSE_CMD" ]; then
            (cd ${BOT_INSTALL_PATH} && $COMPOSE_CMD down -v --remove-orphans &> /tmp/${SERVICE_NAME}_install.log)
        else
            msg_warning "Не удалось найти команду docker-compose/docker compose для остановки контейнеров."
        fi
    fi
    
    # 3. Удаление файлов Systemd
    msg_info "3. Удаление системных файлов (systemd, sudoers)...";
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service"
    sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"
    sudo rm -f "/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"
    sudo systemctl daemon-reload
    
    # 4. Удаление директории
    msg_info "4. Удаление директории бота (${BOT_INSTALL_PATH})...";
    sudo rm -rf "${BOT_INSTALL_PATH}"
    
    # 5. Удаление пользователя
    msg_info "5. Удаление пользователя '${SERVICE_USER}' (если есть)...";
    if id "${SERVICE_USER}" &>/dev/null; then
        sudo userdel -r "${SERVICE_USER}" &> /dev/null || msg_warning "Не удалось полностью удалить пользователя ${SERVICE_USER}."
    fi

    # 6. Удаление Docker образа (опционально)
    if command -v docker &> /dev/null && docker image inspect tg-vps-bot:latest &> /dev/null; then
        msg_question "Удалить Docker образ 'tg-vps-bot:latest'? (y/n): " confirm_docker_rmi
        if [[ "$confirm_docker_rmi" =~ ^[Yy]$ ]]; then
            sudo docker rmi tg-vps-bot:latest &> /dev/null
        fi
    fi
    
    msg_success "Удаление завершено.";
}

# --- [СИЛЬНО ИЗМЕНЕНО] ОБНОВЛЕННАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ ---
update_bot() {
    echo -e "\n${C_BOLD}=== Обновление Бота (ветка: ${GIT_BRANCH}) ===${C_RESET}";
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Репозиторий Git не найден. Невозможно обновить."; return 1; fi
    
    local exec_user="";
    if [ ! -f "${ENV_FILE}" ]; then msg_error "Файл .env не найден. Не могу определить режим обновления."; return 1; fi
    
    local DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    local INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    
    if [ "$INSTALL_MODE_FROM_ENV" == "secure" ]; then
        exec_user="sudo -u ${SERVICE_USER}"
    fi

    msg_warning "Обновление перезапишет локальные изменения.";
    msg_warning ".env, config/, logs/ будут сохранены.";
    
    msg_info "1. Получение обновлений (ветка ${GIT_BRANCH})...";
    pushd "${BOT_INSTALL_PATH}" > /dev/null;
    run_with_spinner "Git fetch (загрузка)" $exec_user git fetch origin;
    run_with_spinner "Git reset --hard (сброс)" $exec_user git reset --hard "origin/${GIT_BRANCH}";
    local st=$?;
    popd > /dev/null;
    if [ $st -ne 0 ]; then msg_error "Обновление Git не удалось."; return 1; fi;
    msg_success "Файлы проекта обновлены.";

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        # [ИСПРАВЛЕНИЕ] Определяем команду compose
        local COMPOSE_CMD=""
        if command -v docker-compose &> /dev/null; then
            COMPOSE_CMD="sudo docker-compose"
        elif docker compose version &> /dev/null; then
            COMPOSE_CMD="sudo docker compose"
        else
            msg_error "[Update] Не найдена команда docker-compose. Обновление Docker прервано."
            return 1
        fi
        
        # [ИСПРАВЛЕНИЕ] Создаем файлы, если их вдруг нет (например, после старой установки)
        if [ ! -f "${BOT_INSTALL_PATH}/Dockerfile" ]; then create_dockerfile; fi
        if [ ! -f "${BOT_INSTALL_PATH}/docker-compose.yml" ]; then create_docker_compose_yml; fi
    
        msg_info "2. [Docker] Пересборка образа...";
        (cd ${BOT_INSTALL_PATH} && run_with_spinner "Сборка Docker образа" $COMPOSE_CMD build) || { msg_error "Сборка Docker не удалась."; return 1; }
        msg_info "3. [Docker] Перезапуск контейнеров (Профиль: ${INSTALL_MODE_FROM_ENV})...";
        (cd ${BOT_INSTALL_PATH} && run_with_spinner "Перезапуск Docker Compose" $COMPOSE_CMD --profile "${INSTALL_MODE_FROM_ENV}" up -d) || { msg_error "Перезапуск Docker Compose не удался."; return 1; }
    
    else # Systemd
        msg_info "2. [Systemd] Обновление зависимостей Python...";
        run_with_spinner "Установка Pip" $exec_user "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade;
        if [ $? -ne 0 ]; then msg_error "Установка Pip не удалась."; return 1; fi;
        
        msg_info "3. [Systemd] Перезапуск служб...";
        if sudo systemctl restart ${SERVICE_NAME}; then msg_success "${SERVICE_NAME} перезапущен."; else msg_error "Не удалось перезапустить ${SERVICE_NAME}."; return 1; fi;
        sleep 1;
        if sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; then msg_success "${WATCHDOG_SERVICE_NAME} перезапущен."; else msg_error "Не удалось перезапустить ${WATCHDOG_SERVICE_NAME}."; fi;
    fi

    echo -e "\n${C_GREEN}${C_BOLD}🎉 Обновление завершено!${C_RESET}\n";
}


# --- [СИЛЬНО ИЗМЕНЕНО] Меню управления ---
main_menu() {
    local local_version=$(get_local_version "$README_FILE")
    local latest_version=$(get_latest_version "$GITHUB_API_URL")
    
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║    Менеджер VPS Telegram Бот      ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        
        local current_branch=$(cd "$BOT_INSTALL_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Не установлено")
        echo -e "  Текущая ветка (установлена): ${C_YELLOW}${current_branch}${C_RESET}"
        echo -e "  Целевая ветка (для действия): ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "  Локальная версия: ${C_GREEN}${local_version}${C_RESET}"
        echo -e "  Последняя версия: ${C_CYAN}${latest_version}${C_RESET}"
        if [ -z "$orig_arg1" ] && [ "$GIT_BRANCH" == "main" ]; then
            echo -e "  ${C_YELLOW}(Подсказка: Для действия с другой веткой, запустите:${C_RESET}";
            echo -e "  ${C_YELLOW} sudo bash $0 <имя_ветки>)${C_RESET}";
        fi
        
        check_integrity # Проверяем статус
        echo "--------------------------------------------------------"
        echo -n -e "  Тип установки: ${C_GREEN}${INSTALL_TYPE}${C_RESET}\n"
        echo -n -e "  Статус: ";
        if [[ "$STATUS_MESSAGE" == *"OK"* ]]; then
            echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"
        else
            echo -e "${C_RED}${STATUS_MESSAGE}${C_RESET}"
            msg_warning "  Рекомендуется переустановка."
        fi
        echo "--------------------------------------------------------"
        echo -e "  ${C_BOLD}УПРАВЛЕНИЕ:${C_RESET}"
        echo -e "  1) ${C_CYAN}${C_BOLD}Обновить бота:${C_RESET}               ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "  2) ${C_RED}${C_BOLD}Удалить бота${C_RESET}"
        echo -e "\n  ${C_BOLD}ПЕРЕУСТАНОВКА (Ветка: ${C_YELLOW}${GIT_BRANCH}${C_RESET}):"
        echo -e "  3) ${C_GREEN}Установка (Systemd - Secure)${C_RESET}"
        echo -e "  4) ${C_YELLOW}Установка (Systemd - Root)${C_RESET}"
        echo -e "  5) ${C_BLUE}Установка (Docker - Secure)${C_RESET}"
        echo -e "  6) ${C_BLUE}Установка (Docker - Root)${C_RESET}"
        echo -e "\n  7) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-7]: ${C_RESET}")" choice
        
        case $choice in
            1) rm -f /tmp/${SERVICE_NAME}_install.log; update_bot && local_version=$(get_local_version "$README_FILE") ;;
            2) msg_question "Удалить бота ПОЛНОСТЬЮ? (y/n): " confirm_uninstall;
               if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then uninstall_bot; msg_info "Бот удален. Выход."; return; else msg_info "Удаление отменено."; fi ;;
            
            3) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (Systemd - Secure, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_systemd_secure; local_version=$(get_local_version "$README_FILE"); else msg_info "Отменено."; fi ;;
            4) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (Systemd - Root, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_systemd_root; local_version=$(get_local_version "$README_FILE"); else msg_info "Отменено."; fi ;;
            5) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (Docker - Secure, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_docker_secure; local_version=$(get_local_version "$README_FILE"); else msg_info "Отменено."; fi ;;
            6) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (Docker - Root, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_docker_root; local_version=$(get_local_version "$README_FILE"); else msg_info "Отменено."; fi ;;

            7) break ;;
            *) msg_error "Неверный выбор." ;;
        esac
        if [[ "$choice" != "2" || ! "$confirm_uninstall" =~ ^[Yy]$ ]]; then
            echo; read -n 1 -s -r -p "Нажмите любую клавишу для возврата в меню...";
        fi
    done
}

# --- [СИЛЬНО ИЗМЕНЕНО] Главный "Роутер" ---
main() {
    clear
    msg_info "Запуск скрипта управления ботом (Целевая ветка: ${GIT_BRANCH})..."
    check_integrity # Первая проверка статуса

    if [ "$INSTALL_TYPE" == "NONE" ] || [[ "$STATUS_MESSAGE" == *"повреждена"* ]]; then
        if [[ "$STATUS_MESSAGE" == *"повреждена"* ]]; then
            msg_error "Обнаружена поврежденная установка."
            msg_warning "${STATUS_MESSAGE}" # Показываем детали проблемы
            msg_question "Обнаружены проблемы. Удалить старые файлы и переустановить? (y/n): " confirm_delete
            if [[ "$confirm_delete" =~ ^[Yy]$ ]]; then
                uninstall_bot # Удаляем только если пользователь согласился
            else
                msg_error "Установка отменена из-за поврежденных файлов. Запустите скрипт снова для управления.";
                exit 1;
            fi
        fi

        # Меню Первой Установки
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║      Установка VPS Telegram Бот   ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        echo -e "  ${C_YELLOW}Бот не найден или установка повреждена.${C_RESET}"
        echo -e "  Выберите режим установки для ветки: ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo "--------------------------------------------------------"
        echo -e "  ${C_BOLD}РЕЖИМ SYSTEMD (Классический):${C_RESET}"
        echo -e "  1) ${C_GREEN}Secure:${C_RESET}   Рекомендуется (Запуск от пользователя 'tgbot')"
        echo -e "  2) ${C_YELLOW}Root:${C_RESET}     Для полного доступа (Запуск от 'root')"
        echo ""
        echo -e "  ${C_BOLD}РЕЖИМ DOCKER (Изолированный):${C_RESET}"
        echo -e "  3) ${C_BLUE}Secure:${C_RESET}   Рекомендуется (Ограниченный доступ к хосту)"
        echo -e "  4) ${C_BLUE}Root:${C_RESET}     Для полного доступа (Привилегированный контейнер)"
        echo ""
        echo -e "  5) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-5]: ${C_RESET}")" install_choice

        local install_done=false
        rm -f /tmp/${SERVICE_NAME}_install.log
        case $install_choice in
            1) install_systemd_secure; install_done=true ;;
            2) install_systemd_root; install_done=true ;;
            3) install_docker_secure; install_done=true ;;
            4) install_docker_root; install_done=true ;;
            5) msg_info "Установка отменена."; exit 0 ;;
            *) msg_error "Неверный выбор."; exit 1 ;;
        esac

        # Проверка после установки
        if [ "$install_done" = true ]; then
            msg_info "Проверка после установки...";
            check_integrity; # Проверяем снова
            if [[ "$STATUS_MESSAGE" == *"OK"* ]]; then
                msg_success "Установка завершена успешно!"
                echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"
                read -n 1 -s -r -p "Нажмите Enter для перехода в Главное Меню..."
                main_menu
                echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
                exit 0
            else
                msg_error "Установка завершилась с ошибками!"
                msg_error "${C_RED}${STATUS_MESSAGE}${C_RESET}"
                msg_error "Лог: /tmp/${SERVICE_NAME}_install.log";
                exit 1;
            fi
        fi
    else
        # Если бот уже установлен (INSTALL_TYPE != "NONE"), сразу показываем меню
        main_menu;
        echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
    fi
}

# --- Проверка Root ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Запустите скрипт от имени root или с правами sudo."; exit 1; fi

# --- Запуск ---
main

