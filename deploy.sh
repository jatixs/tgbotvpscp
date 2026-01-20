#!/bin/bash

GIT_BRANCH="main"
AUTO_AGENT_URL=""
AUTO_NODE_TOKEN=""
AUTO_MODE=false

for arg in "$@"; do
    case $arg in
        --agent=*) AUTO_AGENT_URL="${arg#*=}"; AUTO_MODE=true ;;
        --token=*) AUTO_NODE_TOKEN="${arg#*=}"; AUTO_MODE=true ;;
        --branch=*) GIT_BRANCH="${arg#*=}" ;;
        main|develop) GIT_BRANCH="$arg" ;;
    esac
done

export DEBIAN_FRONTEND=noninteractive

BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
NODE_SERVICE_NAME="tg-node"
SERVICE_USER="tgbot"

# --- ИЗОЛЯЦИЯ: Используем Python 3.12 только для venv ---
# Если бинарника нет, он установится в common_install_steps
PYTHON_FOR_VENV="/usr/bin/python3.12"

VENV_PATH="${BOT_INSTALL_PATH}/venv"
README_FILE="${BOT_INSTALL_PATH}/README.md"
DOCKER_COMPOSE_FILE="${BOT_INSTALL_PATH}/docker-compose.yml"
ENV_FILE="${BOT_INSTALL_PATH}/.env"
STATE_FILE="${BOT_INSTALL_PATH}/.install_state"

GITHUB_REPO="jatixs/tgbotvpscp"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"

C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; };

msg_question() {
    local prompt="$1"
    local var_name="$2"
    if [ -z "${!var_name}" ]; then
        read -p "$(echo -e "${C_YELLOW}❓ $prompt${C_RESET}")" $var_name
    fi
}

spinner() {
    local pid=$1
    local msg=$2
    local spin='|/-\'
    local i=0
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) % 4 ))
        printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"
        sleep .1
    done
    printf "\r"
}

run_with_spinner() {
    local msg=$1
    shift
    ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) &
    local pid=$!
    spinner "$pid" "$msg"
    wait $pid
    local exit_code=$?
    echo -ne "\033[2K\r"
    if [ $exit_code -ne 0 ]; then
        msg_error "Ошибка во время '$msg'. Код: $exit_code"
        msg_error "Подробности в логе: /tmp/${SERVICE_NAME}_install.log"
    fi
    return $exit_code
}

# --- ФУНКЦИЯ ИСПРАВЛЕНИЯ СОВМЕСТИМОСТИ (Патч f-строк) ---
apply_python_compat_fixes() {
    msg_info "Применение патчей совместимости кода (f-strings)..."
    local fix_script="${BOT_INSTALL_PATH}/fix_compat.py"
    
    # Создаем временный Python-скрипт
    cat > "$fix_script" <<EOF
import os
import re

def fix_fstring_content(content):
    # Паттерн ищет f-строки: f"...", f'...', f"""...""", f'''...'''
    pattern = re.compile(r'f(\'\'\'|\"\"\"|\'|\")(.*?)\1', re.DOTALL)
    
    def replacement(match):
        quotes = match.group(1)
        body = match.group(2)
        new_quotes = quotes
        
        # Если внутри f-строки есть переносы, а кавычки одинарные -> меняем на тройные
        if '\n' in body and len(quotes) == 1:
            new_quotes = quotes * 3
            
        # Функция для очистки выражений внутри { ... } от переносов строк
        def fix_braces(br_match):
            inner = br_match.group(0)
            if '\n' in inner:
                return re.sub(r'\s+', ' ', inner)
            return inner
            
        fixed_body = re.sub(r'\{.*?\}', fix_braces, body, flags=re.DOTALL)
        return f'f{new_quotes}{fixed_body}{new_quotes}'

    return pattern.sub(replacement, content)

for root, _, files in os.walk("${BOT_INSTALL_PATH}"):
    for file in files:
        if file.endswith('.py') and file != 'fix_compat.py':
            path = os.path.join(root, file)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    old_content = f.read()
                new_content = fix_fstring_content(old_content)
                if old_content != new_content:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
            except Exception:
                pass
EOF
    # Запускаем фиксатор системным python3 (он точно есть)
    python3 "$fix_script" > /dev/null 2>&1
}

get_file_hash() {
    local file_path=$1
    if [ -f "$file_path" ]; then
        sha256sum "$file_path" | awk '{print $1}'
    else
        echo "none"
    fi
}

update_state_hash() {
    local key=$1
    local hash=$2
    if [ ! -f "$STATE_FILE" ]; then touch "$STATE_FILE"; fi
    sed -i "/^$key=/d" "$STATE_FILE"
    echo "$key=$hash" >> "$STATE_FILE"
}

check_hash_match() {
    local key=$1
    local current_hash=$2
    if [ -f "$STATE_FILE" ]; then
        local stored_hash=$(grep "^$key=" "$STATE_FILE" | cut -d'=' -f2)
        if [ "$stored_hash" == "$current_hash" ]; then
            return 0 
        fi
    fi
    return 1 
}

get_remote_version() {
    local remote_ver=$(curl -s "https://raw.githubusercontent.com/${GITHUB_REPO}/${GIT_BRANCH}/README.md" | grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+')
    if [ -z "$remote_ver" ]; then echo "Не удалось получить"; else echo "$remote_ver"; fi
}

save_current_version() {
    if [ -f "$README_FILE" ]; then
        local ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
        if [ -n "$ver" ]; then
            if [ -f "${ENV_FILE}" ]; then
                if grep -q "^INSTALLED_VERSION=" "${ENV_FILE}"; then
                    sudo sed -i "s/^INSTALLED_VERSION=.*/INSTALLED_VERSION=$ver/" "${ENV_FILE}"
                else
                    echo "INSTALLED_VERSION=$ver" | sudo tee -a "${ENV_FILE}" > /dev/null
                fi
            fi
        fi
    fi
}

get_local_version() { 
    local ver=""
    if [ -f "${ENV_FILE}" ]; then
        ver=$(grep '^INSTALLED_VERSION=' "${ENV_FILE}" | cut -d'=' -f2)
    fi
    if [ -z "$ver" ] && [ -f "$README_FILE" ]; then
        ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
    fi
    if [ -z "$ver" ]; then echo "Не определена"; else echo "$ver"; fi
}

INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Проверка не проводилась."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Бот не установлен."; return;
    fi
    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="НОДА (Клиент)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}"; else STATUS_MESSAGE="${C_RED}Неактивен${C_RESET}"; fi
        return
    fi
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="АГЕНТ (Docker)"
        if command -v docker &> /dev/null && docker ps | grep -q "tg-bot"; then STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"; fi
    else
        INSTALL_TYPE="АГЕНТ (Systemd)"
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"; fi
    fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    # Проверяем наличие именно Python 3.12 (бинарник)
    if command -v python3.12 >/dev/null && command -v git >/dev/null; then
        msg_success "Python 3.12 и Git уже установлены."
    else
        msg_info "1. Обновление системы и установка Python 3.12..."
        run_with_spinner "Apt update" sudo apt-get update -y -q
        # Устанавливаем python3.12 отдельно, не трогая дефолтный python3
        run_with_spinner "Установка пакетов" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3.12 python3.12-venv python3.12-dev git curl wget sudo python3-pip
    fi
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    cd /
    msg_info "Подготовка файлов (Ветка: ${GIT_BRANCH})..."
    
    if [ -f "${ENV_FILE}" ]; then cp "${ENV_FILE}" /tmp/tgbot_env.bak; fi
    if [ -f "${STATE_FILE}" ]; then cp "${STATE_FILE}" /tmp/tgbot_state.bak; fi
    if [ -d "${VENV_PATH}" ]; then 
        msg_info "Сохранение venv..."
        sudo mv "${VENV_PATH}" /tmp/tgbot_venv.bak
    fi

    if [ -d "${BOT_INSTALL_PATH}" ]; then run_with_spinner "Удаление старых файлов" sudo rm -rf "${BOT_INSTALL_PATH}"; fi
    sudo mkdir -p ${BOT_INSTALL_PATH}
    run_with_spinner "Клонирование репозитория" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    
    if [ -f "/tmp/tgbot_env.bak" ]; then sudo mv /tmp/tgbot_env.bak "${ENV_FILE}"; fi
    if [ -f "/tmp/tgbot_state.bak" ]; then sudo mv /tmp/tgbot_state.bak "${STATE_FILE}"; fi
    if [ -d "/tmp/tgbot_venv.bak" ]; then 
        sudo mv /tmp/tgbot_venv.bak "${VENV_PATH}"
        msg_success "Venv восстановлен."
    fi

    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

load_cached_env() {
    local env_file="${ENV_FILE}"
    if [ ! -f "$env_file" ] && [ -f "/tmp/tgbot_env.bak" ]; then env_file="/tmp/tgbot_env.bak"; fi

    if [ -f "$env_file" ]; then
        echo -e "${C_YELLOW}⚠️  Обнаружена сохраненная конфигурация.${C_RESET}"
        read -p "$(echo -e "${C_CYAN}❓ Восстановить настройки? (y/n) [y]: ${C_RESET}")" RESTORE_CHOICE
        RESTORE_CHOICE=${RESTORE_CHOICE:-y}

        if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]]; then
            msg_info "Загружаю данные..."
            get_env_val() { grep "^$1=" "$env_file" | cut -d'=' -f2- | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//"; }
            [ -z "$T" ] && T=$(get_env_val "TG_BOT_TOKEN")
            [ -z "$A" ] && A=$(get_env_val "TG_ADMIN_ID")
            [ -z "$U" ] && U=$(get_env_val "TG_ADMIN_USERNAME")
            [ -z "$N" ] && N=$(get_env_val "TG_BOT_NAME")
            [ -z "$P" ] && P=$(get_env_val "WEB_SERVER_PORT")
            [ -z "$SENTRY_DSN" ] && SENTRY_DSN=$(get_env_val "SENTRY_DSN")
            if [ -z "$W" ]; then
                local val=$(get_env_val "ENABLE_WEB_UI"); if [[ "$val" == "false" ]]; then W="n"; else W="y"; fi
            fi
            [ -z "$AGENT_URL" ] && AGENT_URL=$(get_env_val "AGENT_BASE_URL")
            [ -z "$NODE_TOKEN" ] && NODE_TOKEN=$(get_env_val "AGENT_TOKEN")
        else
            T=""; A=""; U=""; N=""; P=""; SENTRY_DSN=""; ENABLE_WEB=""; SETUP_HTTPS=""; HTTPS_DOMAIN=""; HTTPS_EMAIL=""; HTTPS_PORT=""; AGENT_URL=""; NODE_TOKEN=""
        fi
    fi
}

cleanup_node_files() { cd ${BOT_INSTALL_PATH} && sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git .github config/users.json config/alerts_config.json deploy.sh deploy_en.sh requirements.txt LICENSE CHANGELOG* .gitignore aerich.ini .env.example migrate.py manage.py ARCHITECTURE* custom_module* README*; }
cleanup_agent_files() { cd ${BOT_INSTALL_PATH} && sudo rm -rf node; }
cleanup_files() {
    msg_info "🧹 Финальная очистка..."
    # Удаляем скрипт-фиксатор
    sudo rm -f "${BOT_INSTALL_PATH}/fix_compat.py"
    
    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then sudo rm -rf "$BOT_INSTALL_PATH/assets"; fi
    sudo rm -f "$BOT_INSTALL_PATH/custom_module.md" "$BOT_INSTALL_PATH/custom_module_en.md" "$BOT_INSTALL_PATH/.gitignore" "$BOT_INSTALL_PATH/LICENSE" "$BOT_INSTALL_PATH/aerich.ini" "$BOT_INSTALL_PATH/README.md" "$BOT_INSTALL_PATH/README.en.md" "$BOT_INSTALL_PATH/ARCHITECTURE.md" "$BOT_INSTALL_PATH/ARCHITECTURE.en.md" "$BOT_INSTALL_PATH/CHANGELOG.md" "$BOT_INSTALL_PATH/CHANGELOG.en.md" "$BOT_INSTALL_PATH/.env.example" "$BOT_INSTALL_PATH/migrate.py" "$BOT_INSTALL_PATH/requirements.txt"
    if [ -f "${ENV_FILE}" ]; then
        DEPLOY_MODE_VAL=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ "$DEPLOY_MODE_VAL" != "docker" ]; then sudo rm -f "$BOT_INSTALL_PATH/Dockerfile" "$BOT_INSTALL_PATH/docker-compose.yml"; fi
    fi
    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    msg_success "Очистка завершена."
}

install_extras() {
    if command -v fail2ban-client &> /dev/null; then msg_success "Fail2Ban уже установлен."; else
        msg_question "Fail2Ban не найден. Установить? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Установка Fail2ban" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" fail2ban; fi
    fi
    if command -v iperf3 &> /dev/null; then msg_success "iperf3 уже установлен."; else
        msg_question "iperf3 не найден. Установить? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then 
            # --- Автоматизация iperf3 (без вопроса про демона) ---
            echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections
            run_with_spinner "Установка iperf3" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" iperf3
        fi
    fi
}

ask_env_details() {
    msg_info "Ввод данных .env..."
    msg_question "Токен Ботa: " T; msg_question "ID Админа: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Внутренний Web Port [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN
    msg_question "Включить Web-UI? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then ENABLE_WEB="false"; SETUP_HTTPS="false"; else
        ENABLE_WEB="true"; GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        msg_question "Настроить HTTPS (Nginx)? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"; msg_question "Домен: " HTTPS_DOMAIN; msg_question "Email: " HTTPS_EMAIL; msg_question "Внешний порт [8443]: " HP
            if [ -z "$HP" ]; then HTTPS_PORT="8443"; else HTTPS_PORT="$HP"; fi
        else SETUP_HTTPS="false"; fi
    fi
    export T A U N WEB_PORT ENABLE_WEB SETUP_HTTPS HTTPS_DOMAIN HTTPS_EMAIL HTTPS_PORT GEN_PASS SENTRY_DSN
}

write_env_file() {
    local dm=$1; local im=$2; local cn=$3
    local debug_setting="true"; if [ "$GIT_BRANCH" == "main" ]; then debug_setting="false"; fi
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
TG_BOT_TOKEN="${T}"
TG_ADMIN_ID="${A}"
TG_ADMIN_USERNAME="${U}"
TG_BOT_NAME="${N}"
WEB_SERVER_HOST="0.0.0.0"
WEB_SERVER_PORT="${WEB_PORT}"
INSTALL_MODE="${im}"
DEPLOY_MODE="${dm}"
TG_BOT_CONTAINER_NAME="${cn}"
ENABLE_WEB_UI="${ENABLE_WEB}"
TG_WEB_INITIAL_PASSWORD="${GEN_PASS}"
DEBUG="${debug_setting}"
SENTRY_DSN="${SENTRY_DSN}"
EOF
    sudo chmod 600 "${ENV_FILE}"
}

check_docker_deps() {
    if ! command -v docker &> /dev/null; then curl -sSL https://get.docker.com -o /tmp/get-docker.sh; run_with_spinner "Установка Docker" sudo sh /tmp/get-docker.sh; fi
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
# Docker полностью изолирован, используем 3.12
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y python3-yaml iperf3 git curl wget sudo procps iputils-ping net-tools gnupg docker.io coreutils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir docker aiohttp aiosqlite argon2-cffi sentry-sdk tortoise-orm aerich cryptography tomlkit
RUN groupadd -g 1001 tgbot && useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
WORKDIR /opt/tg-bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && chown -R tgbot:tgbot /opt/tg-bot
USER tgbot
CMD ["python", "bot.py"]
EOF
}

create_docker_compose_yml() {
    sudo tee "${BOT_INSTALL_PATH}/docker-compose.yml" > /dev/null <<EOF
x-bot-base: &bot-base
  build: .
  image: tg-vps-bot:latest
  restart: always
  env_file: .env
services:
  bot-secure:
    <<: *bot-base
    container_name: tg-bot-secure
    profiles: ["secure"]
    user: "tgbot"
    ports:
      - "${WEB_PORT}:${WEB_PORT}"
    environment:
      - INSTALL_MODE=secure
      - DEPLOY_MODE=docker
      - TG_BOT_CONTAINER_NAME=tg-bot-secure
    volumes:
      - ./config:/opt/tg-bot/config
      - ./logs/bot:/opt/tg-bot/logs/bot
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /proc/uptime:/proc_host/uptime:ro
      - /proc/stat:/proc_host/stat:ro
      - /proc/meminfo:/proc_host/meminfo:ro
      - /proc/net/dev:/proc_host/net/dev:ro
    cap_drop: [ALL]
    cap_add: [NET_RAW]
  bot-root:
    <<: *bot-base
    container_name: tg-bot-root
    profiles: ["root"]
    user: "root"
    ports:
      - "${WEB_PORT}:${WEB_PORT}"
    environment:
      - INSTALL_MODE=root
      - DEPLOY_MODE=docker
      - TG_BOT_CONTAINER_NAME=tg-bot-root
    privileged: true
    pid: "host"
    network_mode: "host"
    ipc: "host"
    volumes:
      - ./config:/opt/tg-bot/config
      - ./logs/bot:/opt/tg-bot/logs/bot
      - /:/host
      - /var/run/docker.sock:/var/run/docker.sock:ro
  watchdog:
    <<: *bot-base
    container_name: tg-watchdog
    command: python watchdog.py
    user: "root"
    restart: always
    volumes:
      - ./config:/opt/tg-bot/config
      - ./logs/watchdog:/opt/tg-bot/logs/watchdog
      - /var/run/docker.sock:/var/run/docker.sock:ro
EOF
}

create_and_start_service() {
    local svc=$1; local script=$2; local mode=$3; local desc=$4
    local user="root"; if [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ]; then user=${SERVICE_USER}; fi
    sudo tee "/etc/systemd/system/${svc}.service" > /dev/null <<EOF
[Unit]
Description=${desc}
After=network.target
[Service]
Type=simple
User=${user}
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python ${script}
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload; sudo systemctl enable ${svc} &> /dev/null; sudo systemctl restart ${svc}
}

run_db_migrations() {
    local exec_user=$1
    msg_info "Проверка БД..."
    cd "${BOT_INSTALL_PATH}" || return 1
    if [ -f "${ENV_FILE}" ]; then set -a; source "${ENV_FILE}"; set +a; fi
    local cmd_prefix=""; if [ -n "$exec_user" ]; then cmd_prefix="sudo -E -u ${SERVICE_USER}"; fi
    local db_models_hash=$(get_file_hash "${BOT_INSTALL_PATH}/core/models.py")
    local db_exists=false; if [ -f "${BOT_INSTALL_PATH}/config/nodes.db" ]; then db_exists=true; fi
    if $db_exists && check_hash_match "DB_HASH" "$db_models_hash"; then msg_success "БД актуальна."; return; fi
    if [ -f "${BOT_INSTALL_PATH}/aerich.ini" ]; then rm -f "${BOT_INSTALL_PATH}/aerich.ini"; fi
    $cmd_prefix ${VENV_PATH}/bin/aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    if $db_exists; then
        if [ -d "${BOT_INSTALL_PATH}/migrations" ]; then $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1; fi
    else
        if [ ! -d "${BOT_INSTALL_PATH}/migrations" ]; then $cmd_prefix ${VENV_PATH}/bin/aerich init-db >/dev/null 2>&1
        else $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1; fi
    fi
    update_state_hash "DB_HASH" "$db_models_hash"
    if [ -f "${BOT_INSTALL_PATH}/migrate.py" ]; then $cmd_prefix ${VENV_PATH}/bin/python "${BOT_INSTALL_PATH}/migrate.py"; fi
}

install_systemd_logic() {
    local mode=$1; common_install_steps; install_extras
    local exec_cmd=""; local req_hash=$(get_file_hash "${BOT_INSTALL_PATH}/requirements.txt"); local install_pip=true
    if [ -d "${VENV_PATH}" ] && [ -f "${VENV_PATH}/bin/python" ]; then
        if check_hash_match "REQ_HASH" "$req_hash"; then install_pip=false; msg_success "Venv актуален."; fi
    fi
    if [ "$mode" == "secure" ]; then
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}; fi
        setup_repo_and_dirs "${SERVICE_USER}"
        # ИЗОЛЯЦИЯ: Создаем venv используя именно Python 3.12
        if [ ! -d "${VENV_PATH}" ]; then sudo -u ${SERVICE_USER} ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"; fi
        
        # ЗАПУСК ФИКСАТОРА ПЕРЕД УСТАНОВКОЙ
        apply_python_compat_fixes
        
        if $install_pip; then
            run_with_spinner "Установка зависимостей" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
            run_with_spinner "Установка tomlkit" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install tomlkit
            update_state_hash "REQ_HASH" "$req_hash"
        fi
        exec_cmd="sudo -u ${SERVICE_USER}"
    else
        setup_repo_and_dirs "root"
        # ИЗОЛЯЦИЯ:
        if [ ! -d "${VENV_PATH}" ]; then ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"; fi
        
        apply_python_compat_fixes
        
        if $install_pip; then
            run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
            run_with_spinner "Установка tomlkit" "${VENV_PATH}/bin/pip" install tomlkit
            update_state_hash "REQ_HASH" "$req_hash"
        fi
        exec_cmd=""
    fi
    load_cached_env; ask_env_details; write_env_file "systemd" "$mode" ""
    run_db_migrations "$exec_cmd"
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель"
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then set -a; source .env; set +a; fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot
    save_current_version; cleanup_agent_files; cleanup_files
    local ip=$(curl -s ipinfo.io/ip)
    echo ""; msg_success "Готово! Агент: http://${ip}:${WEB_PORT}"; if [ "${ENABLE_WEB}" == "true" ]; then echo -e "🔑 ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
}

install_docker_logic() {
    local mode=$1; common_install_steps; install_extras; setup_repo_and_dirs "root"; check_docker_deps; load_cached_env; ask_env_details
    
    # Применяем фиксы до сборки образа
    apply_python_compat_fixes
    
    create_dockerfile; create_docker_compose_yml; local container_name="tg-bot-${mode}"; write_env_file "docker" "$mode" "${container_name}"
    cd ${BOT_INSTALL_PATH}
    local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
    run_with_spinner "Сборка Docker" sudo $dc_cmd build --no-cache
    run_with_spinner "Запуск Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init-db >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich upgrade >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python migrate.py >/dev/null 2>&1
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot
    save_current_version; cleanup_agent_files; cleanup_files
    msg_success "Docker готов!"; if [ "${ENABLE_WEB}" == "true" ]; then echo -e "🔑 ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Установка НОДЫ ===${C_RESET}"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi
    common_install_steps
    if command -v iperf3 &> /dev/null; then msg_success "iperf3 уже установлен."; else
        msg_question "iperf3 не найден. Установить? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then 
            # Автоматизация iperf3
            echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections
            run_with_spinner "Установка iperf3" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" iperf3
        fi
    fi
    setup_repo_and_dirs "root"; local node_deps_hash=$(echo "psutil requests" | sha256sum | awk '{print $1}'); local install_pip=true
    
    # Изолированный venv
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
    else if check_hash_match "NODE_REQ_HASH" "$node_deps_hash"; then install_pip=false; msg_success "Venv актуален."; fi; fi
    
    apply_python_compat_fixes
    
    if $install_pip; then run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install psutil requests; update_state_hash "NODE_REQ_HASH" "$node_deps_hash"; fi
    load_cached_env; msg_question "Agent URL: " AGENT_URL; msg_question "Token: " NODE_TOKEN
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
EOF
    sudo chmod 600 "${ENV_FILE}"; sudo tee "/etc/systemd/system/${NODE_SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=Telegram Bot Node Client
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python node/node.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload; sudo systemctl enable ${NODE_SERVICE_NAME}; run_with_spinner "Запуск Ноды" sudo systemctl restart ${NODE_SERVICE_NAME}
    save_current_version; cleanup_node_files; msg_success "Нода установлена!"
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Удаление ===${C_RESET}"
    sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &> /dev/null; fi
    sudo rm -rf "${BOT_INSTALL_PATH}" /usr/local/bin/tgcp-bot
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Удалено."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Обновление ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then install_node_logic; return; fi
    local exec_cmd=""; if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi
    cd "${BOT_INSTALL_PATH}"
    run_with_spinner "Git fetch" $exec_cmd git fetch origin
    run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"
    if [ -f "${ENV_FILE}" ] && grep -q "DEPLOY_MODE=docker" "${ENV_FILE}"; then
        local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
        
        apply_python_compat_fixes
        
        run_with_spinner "Docker Up" sudo $dc_cmd up -d --build --no-cache
        local mode=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        sudo $dc_cmd --profile "${mode}" exec -T "tg-bot-${mode}" aerich upgrade >/dev/null 2>&1
    else
        apply_python_compat_fixes
        
        local req_hash=$(get_file_hash "${BOT_INSTALL_PATH}/requirements.txt")
        if ! check_hash_match "REQ_HASH" "$req_hash"; then
             run_with_spinner "Обновление pip" $exec_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
             update_state_hash "REQ_HASH" "$req_hash"
        fi
        run_db_migrations "$exec_cmd"
        if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then sudo systemctl restart ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME}; fi
    fi
    save_current_version; cleanup_agent_files; cleanup_files; msg_success "Обновлено."
}

# --- Main Entry ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Нужен root."; exit 1; fi
if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then install_node_logic; exit 0; fi

check_integrity
if [ "$INSTALL_TYPE" == "НЕТ" ]; then
    echo -e "Выберите установку:\n1) Агент Systemd\n3) Агент Docker\n8) Нода\n0) Выход"
    read -p "Ваш выбор: " ch
    case $ch in
        1) uninstall_bot; install_systemd_logic "secure" ;;
        3) uninstall_bot; install_docker_logic "secure" ;;
        8) uninstall_bot; install_node_logic ;;
        0) exit 0 ;;
    esac
else
    echo -e "Меню:\n1) Обновить\n2) Удалить\n0) Выход"
    read -p "Ваш выбор: " ch
    case $ch in
        1) update_bot ;;
        2) uninstall_bot ;;
        0) exit 0 ;;
    esac
fi