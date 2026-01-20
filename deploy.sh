#!/bin/bash

GIT_BRANCH="main"
AUTO_AGENT_URL=""
AUTO_NODE_TOKEN=""
AUTO_MODE=false

# --- Парсинг аргументов ---
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

# --- ИЗОЛЯЦИЯ: Python 3.12 только для venv ---
PYTHON_FOR_VENV="/usr/bin/python3.12"
VENV_PATH="${BOT_INSTALL_PATH}/venv"
README_FILE="${BOT_INSTALL_PATH}/README.md"
DOCKER_COMPOSE_FILE="${BOT_INSTALL_PATH}/docker-compose.yml"
ENV_FILE="${BOT_INSTALL_PATH}/.env"
STATE_FILE="${BOT_INSTALL_PATH}/.install_state"

GITHUB_REPO="jatixs/tgbotvpscp"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"

# --- Цвета ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'
C_BOLD='\033[1m'

# --- Функции вывода ---
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }
msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }
msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }

msg_question() {
    local prompt="$1"
    local var_name="$2"
    eval $var_name=""
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

# --- ФИКСАТОР СОВМЕСТИМОСТИ (ИГНОРИРУЕТ VENV) ---
apply_python_compat_fixes() {
    msg_info "Применение патчей совместимости кода..."
    local fix_script="${BOT_INSTALL_PATH}/fix_compat.py"
    
    cat > "$fix_script" <<EOF
import os
import re

def fix_fstring_content(content):
    pattern = re.compile(r'f(\'\'\'|\"\"\"|\'|\")(.*?)\1', re.DOTALL)
    def replacement(match):
        quotes = match.group(1)
        body = match.group(2)
        new_quotes = quotes
        if '\n' in body and len(quotes) == 1:
            new_quotes = quotes * 3
        def fix_braces(br_match):
            inner = br_match.group(0)
            if '\n' in inner:
                return re.sub(r'\s+', ' ', inner)
            return inner
        fixed_body = re.sub(r'\{.*?\}', fix_braces, body, flags=re.DOTALL)
        return f'f{new_quotes}{fixed_body}{new_quotes}'
    return pattern.sub(replacement, content)

# Исключаем venv из сканирования!
for root, dirs, files in os.walk("${BOT_INSTALL_PATH}"):
    dirs[:] = [d for d in dirs if d not in ["venv", ".git", "__pycache__"]]
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
    python3 "$fix_script" > /dev/null 2>&1
}

# --- Хелперы ---
get_file_hash() { [ -f "$1" ] && sha256sum "$1" | awk '{print $1}' || echo "none"; }
update_state_hash() { [ ! -f "$STATE_FILE" ] && touch "$STATE_FILE"; sed -i "/^$1=/d" "$STATE_FILE"; echo "$1=$2" >> "$STATE_FILE"; }
check_hash_match() { [ -f "$STATE_FILE" ] && [ "$(grep "^$1=" "$STATE_FILE" | cut -d'=' -f2)" == "$2" ] && return 0 || return 1; }

get_remote_version() {
    local v=$(curl -s "https://raw.githubusercontent.com/${GITHUB_REPO}/${GIT_BRANCH}/README.md" | grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+')
    [ -z "$v" ] && echo "Не удалось получить" || echo "$v"
}

save_current_version() {
    if [ -f "$README_FILE" ]; then
        local v=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
        if [ -n "$v" ] && [ -f "${ENV_FILE}" ]; then
            if grep -q "^INSTALLED_VERSION=" "${ENV_FILE}"; then
                sudo sed -i "s/^INSTALLED_VERSION=.*/INSTALLED_VERSION=$v/" "${ENV_FILE}"
            else
                echo "INSTALLED_VERSION=$v" | sudo tee -a "${ENV_FILE}" > /dev/null
            fi
        fi
    fi
}

get_local_version() { 
    local v=""; [ -f "${ENV_FILE}" ] && v=$(grep '^INSTALLED_VERSION=' "${ENV_FILE}" | cut -d'=' -f2)
    [ -z "$v" ] && [ -f "$README_FILE" ] && v=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
    [ -z "$v" ] && echo "Не определена" || echo "$v"
}

check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Бот не установлен."; return;
    fi
    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="НОДА (Клиент)"; systemctl is-active --quiet ${NODE_SERVICE_NAME}.service && STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}" || STATUS_MESSAGE="${C_RED}Неактивен${C_RESET}"; return
    fi
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="АГЕНТ (Docker)"; docker ps | grep -q "tg-bot" && STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}" || STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"
    else
        INSTALL_TYPE="АГЕНТ (Systemd)"; systemctl is-active --quiet ${SERVICE_NAME}.service && STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}" || STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"
    fi
}

setup_nginx_proxy() {
    echo -e "\n${C_CYAN}🔒 Настройка HTTPS (Nginx + Certbot)${C_RESET}"
    run_with_spinner "Установка Nginx и Certbot" sudo apt-get install -y -q nginx certbot python3-certbot-nginx psmisc
    sudo fuser -k 80/tcp 2>/dev/null; sudo systemctl stop nginx 2>/dev/null
    if sudo certbot certonly --standalone --non-interactive --agree-tos --email "${HTTPS_EMAIL}" -d "${HTTPS_DOMAIN}"; then
        msg_success "Сертификат получен!"
    else
        msg_error "Ошибка получения сертификата."; sudo systemctl start nginx; return 1
    fi
    sudo bash -c "cat > /etc/nginx/sites-available/${HTTPS_DOMAIN}" <<EOF
server {
    listen ${HTTPS_PORT} ssl;
    server_name ${HTTPS_DOMAIN};
    ssl_certificate /etc/letsencrypt/live/${HTTPS_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${HTTPS_DOMAIN}/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    sudo ln -sf "/etc/nginx/sites-available/${HTTPS_DOMAIN}" "/etc/nginx/sites-enabled/${HTTPS_DOMAIN}"
    sudo rm -f /etc/nginx/sites-enabled/default
    if sudo nginx -t; then sudo systemctl restart nginx; msg_success "HTTPS настроен успешно!"; return 0; else msg_error "Ошибка Nginx."; return 1; fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    
    msg_info "1. Подготовка системы..."
    # Обязательно обновляем список пакетов
    run_with_spinner "Apt update" sudo apt-get update -y -q
    
    # Исправляем dpkg если надо
    sudo dpkg --configure -a >/dev/null 2>&1

    # Debconf utils для автоматизации iperf3
    if ! command -v debconf-set-selections &> /dev/null; then
        run_with_spinner "Установка utils" sudo apt-get install -y -q debconf-utils
    fi

    # ПРИНУДИТЕЛЬНАЯ установка зависимостей, даже если Python есть (нужен dev и venv)
    msg_info "Установка зависимостей (Python 3.12, venv, dev)..."
    run_with_spinner "Установка пакетов" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" \
        python3.12 python3.12-venv python3.12-dev git curl wget sudo python3-pip build-essential
}

setup_repo_and_dirs() {
    local owner_user=${1:-root}; cd /
    msg_info "Подготовка файлов (Ветка: ${GIT_BRANCH})..."
    [ -f "${ENV_FILE}" ] && cp "${ENV_FILE}" /tmp/tgbot_env.bak
    [ -f "${STATE_FILE}" ] && cp "${STATE_FILE}" /tmp/tgbot_state.bak
    [ -d "${VENV_PATH}" ] && sudo mv "${VENV_PATH}" /tmp/tgbot_venv.bak
    
    [ -d "${BOT_INSTALL_PATH}" ] && sudo rm -rf "${BOT_INSTALL_PATH}"
    sudo mkdir -p "${BOT_INSTALL_PATH}"
    
    run_with_spinner "Клонирование репозитория" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}"
    
    [ -f "/tmp/tgbot_env.bak" ] && sudo mv /tmp/tgbot_env.bak "${ENV_FILE}"
    [ -f "/tmp/tgbot_state.bak" ] && sudo mv /tmp/tgbot_state.bak "${STATE_FILE}"
    [ -d "/tmp/tgbot_venv.bak" ] && sudo mv /tmp/tgbot_venv.bak "${VENV_PATH}"
    
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

load_cached_env() {
    local env_file="${ENV_FILE}"; [ ! -f "$env_file" ] && [ -f "/tmp/tgbot_env.bak" ] && env_file="/tmp/tgbot_env.bak"
    if [ -f "$env_file" ]; then
        echo -e "${C_YELLOW}⚠️  Обнаружена сохраненная конфигурация.${C_RESET}"
        read -p "$(echo -e "${C_CYAN}❓ Восстановить настройки? (y/n) [y]: ${C_RESET}")" RESTORE_CHOICE; RESTORE_CHOICE=${RESTORE_CHOICE:-y}
        if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]]; then
            msg_info "Загружаю данные..."
            get_env_val() { grep "^$1=" "$env_file" | cut -d'=' -f2- | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//"; }
            [ -z "$T" ] && T=$(get_env_val "TG_BOT_TOKEN"); [ -z "$A" ] && A=$(get_env_val "TG_ADMIN_ID")
            [ -z "$U" ] && U=$(get_env_val "TG_ADMIN_USERNAME"); [ -z "$N" ] && N=$(get_env_val "TG_BOT_NAME")
            [ -z "$P" ] && P=$(get_env_val "WEB_SERVER_PORT"); [ -z "$SENTRY_DSN" ] && SENTRY_DSN=$(get_env_val "SENTRY_DSN")
            if [ -z "$W" ]; then local v=$(get_env_val "ENABLE_WEB_UI"); [[ "$v" == "false" ]] && W="n" || W="y"; fi
            [ -z "$AGENT_URL" ] && AGENT_URL=$(get_env_val "AGENT_BASE_URL"); [ -z "$NODE_TOKEN" ] && NODE_TOKEN=$(get_env_val "AGENT_TOKEN")
        else
            T=""; A=""; U=""; N=""; P=""; SENTRY_DSN=""; ENABLE_WEB=""; SETUP_HTTPS=""; AGENT_URL=""; NODE_TOKEN=""
        fi
    fi
}

cleanup_node_files() { cd ${BOT_INSTALL_PATH} && sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git .github config/users.json config/alerts_config.json deploy.sh deploy_en.sh requirements.txt LICENSE CHANGELOG* .gitignore aerich.ini .env.example migrate.py manage.py ARCHITECTURE* custom_module* README*; }
cleanup_agent_files() { cd ${BOT_INSTALL_PATH} && sudo rm -rf node; }

cleanup_files() {
    msg_info "🧹 Финальная очистка..."
    sudo rm -f "${BOT_INSTALL_PATH}/fix_compat.py"
    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then sudo rm -rf "$BOT_INSTALL_PATH/assets"; fi
    sudo rm -f "$BOT_INSTALL_PATH/custom_module"* "$BOT_INSTALL_PATH/.gitignore" "$BOT_INSTALL_PATH/LICENSE" "$BOT_INSTALL_PATH/aerich.ini" "$BOT_INSTALL_PATH/README"* "$BOT_INSTALL_PATH/ARCHITECTURE"* "$BOT_INSTALL_PATH/CHANGELOG"* "$BOT_INSTALL_PATH/.env.example" "$BOT_INSTALL_PATH/migrate.py" "$BOT_INSTALL_PATH/requirements.txt"
    DEPLOY_MODE_VAL=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' 2>/dev/null)
    [ "$DEPLOY_MODE_VAL" != "docker" ] && sudo rm -f "$BOT_INSTALL_PATH/Dockerfile" "$BOT_INSTALL_PATH/docker-compose.yml"
    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    msg_success "Очистка завершена."
}

install_extras() {
    local I=""; local J=""
    if ! command -v fail2ban-client &>/dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " I
        [[ "$I" =~ ^[Yy]$ ]] && run_with_spinner "Установка Fail2ban" sudo apt-get install -y -q fail2ban
    else msg_success "Fail2Ban уже установлен."; fi
    
    if ! command -v iperf3 &>/dev/null; then
        msg_question "iperf3 не найден. Установить? (y/n): " J
        if [[ "$J" =~ ^[Yy]$ ]]; then
            echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections
            run_with_spinner "Установка iperf3" sudo apt-get install -y -q iperf3
        fi
    else msg_success "iperf3 уже установлен."; fi
}

ask_env_details() {
    msg_info "Ввод данных .env..."
    msg_question "Токен Ботa: " T; msg_question "ID Админа: " A
    msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Внутренний Web Port [8080]: " P
    if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN
    
    local W=""
    msg_question "Включить Web-UI (Дашборд)? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then ENABLE_WEB="false"; SETUP_HTTPS="false"; else
        ENABLE_WEB="true"; GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
    fi
    export T A U N WEB_PORT ENABLE_WEB GEN_PASS SENTRY_DSN
}

write_env_file() {
    local dm=$1; local im=$2; local cn=$3; local debug_setting="true"
    [ "$GIT_BRANCH" == "main" ] && debug_setting="false"
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
    if ! command -v docker &> /dev/null; then
        curl -sSL https://get.docker.com -o /tmp/get-docker.sh
        run_with_spinner "Установка Docker" sudo sh /tmp/get-docker.sh
    fi
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
FROM python:3.12-slim-bookworm
LABEL maintainer="Jatixs"
LABEL org.opencontainers.image.source="https://github.com/jatixs/tgbotvpscp"
LABEL org.opencontainers.image.description="VPS Manager Telegram Bot"
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
  labels: ["org.opencontainers.image.source=https://github.com/jatixs/tgbotvpscp"]
services:
  bot-secure:
    <<: *bot-base
    container_name: tg-bot-secure
    profiles: ["secure"]
    user: "tgbot"
    ports: ["${WEB_PORT}:${WEB_PORT}"]
    environment: [INSTALL_MODE=secure, DEPLOY_MODE=docker, TG_BOT_CONTAINER_NAME=tg-bot-secure]
    volumes: ["./config:/opt/tg-bot/config", "./logs/bot:/opt/tg-bot/logs/bot", "/var/run/docker.sock:/var/run/docker.sock:ro", "/proc/uptime:/proc_host/uptime:ro", "/proc/stat:/proc_host/stat:ro", "/proc/meminfo:/proc_host/meminfo:ro", "/proc/net/dev:/proc_host/net/dev:ro"]
    cap_drop: [ALL]
    cap_add: [NET_RAW]
    labels: ["role=bot", "mode=secure"]
  bot-root:
    <<: *bot-base
    container_name: tg-bot-root
    profiles: ["root"]
    user: "root"
    ports: ["${WEB_PORT}:${WEB_PORT}"]
    environment: [INSTALL_MODE=root, DEPLOY_MODE=docker, TG_BOT_CONTAINER_NAME=tg-bot-root]
    privileged: true
    network_mode: "host"
    volumes: ["./config:/opt/tg-bot/config", "./logs/bot:/opt/tg-bot/logs/bot", "/:/host", "/var/run/docker.sock:/var/run/docker.sock:ro"]
    labels: ["role=bot", "mode=root"]
  watchdog:
    <<: *bot-base
    container_name: tg-watchdog
    command: python watchdog.py
    user: "root"
    volumes: ["./config:/opt/tg-bot/config", "./logs/watchdog:/opt/tg-bot/logs/watchdog", "/var/run/docker.sock:/var/run/docker.sock:ro"]
    labels: ["role=watchdog"]
EOF
}

create_and_start_service() {
    local svc=$1; local script=$2; local mode=$3; local desc=$4; local user="root"
    [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ] && user=${SERVICE_USER}
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
    local exec_user=$1; msg_info "Проверка и миграция базы данных..."
    cd "${BOT_INSTALL_PATH}" || return 1; [ -f "${ENV_FILE}" ] && set -a && source "${ENV_FILE}" && set +a
    local cmd_prefix=""; [ -n "$exec_user" ] && cmd_prefix="sudo -E -u ${SERVICE_USER}"
    local h=$(get_file_hash "${BOT_INSTALL_PATH}/core/models.py"); local db_exists=false
    [ -f "${BOT_INSTALL_PATH}/config/nodes.db" ] && db_exists=true
    if $db_exists && check_hash_match "DB_HASH" "$h"; then msg_success "Структура БД не менялась."; return; fi
    [ -f "${BOT_INSTALL_PATH}/aerich.ini" ] && rm -f "${BOT_INSTALL_PATH}/aerich.ini"
    $cmd_prefix ${VENV_PATH}/bin/aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    if $db_exists; then
        msg_info "Обновление БД..."; $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1
    else
        msg_info "Создание БД..."; ! $cmd_prefix ${VENV_PATH}/bin/aerich init-db >/dev/null 2>&1 && $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1
    fi
    update_state_hash "DB_HASH" "$h"
    [ -f "${BOT_INSTALL_PATH}/migrate.py" ] && (msg_info "Миграция конфига..."; $cmd_prefix ${VENV_PATH}/bin/python "${BOT_INSTALL_PATH}/migrate.py")
}

configure_web_final() {
    if [ "$ENABLE_WEB" == "true" ]; then
        local H=""; echo ""
        msg_question "Настроить HTTPS (Nginx Proxy)? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            msg_question "Домен: " HTTPS_DOMAIN; msg_question "Email: " HTTPS_EMAIL; msg_question "Порт HTTPS [8443]: " HP
            if [ -z "$HP" ]; then HTTPS_PORT="8443"; else HTTPS_PORT="$HP"; fi
            export HTTPS_DOMAIN HTTPS_EMAIL HTTPS_PORT WEB_PORT
            if setup_nginx_proxy; then
                echo ""; msg_success "Установка завершена! https://${HTTPS_DOMAIN}:${HTTPS_PORT}/"
                echo -e "🔑 ВАШ ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"
            else
                local ip=$(curl -s ipinfo.io/ip); msg_error "Ошибка HTTPS."
                msg_success "Доступен через HTTP: http://${ip}:${WEB_PORT}/"
                echo -e "🔑 ВАШ ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"
            fi
        else
            local ip=$(curl -s ipinfo.io/ip); echo ""
            msg_success "Установка завершена! http://${ip}:${WEB_PORT}/"
            echo -e "🔑 ВАШ ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"
        fi
    else
        echo ""; msg_success "Установка завершена! Web-UI отключен."
    fi
}

install_systemd_logic() {
    local mode=$1; common_install_steps; install_extras; local exec_cmd=""
    local req_hash=$(get_file_hash "${BOT_INSTALL_PATH}/requirements.txt"); local install_pip=true
    if [ -d "${VENV_PATH}" ] && [ -f "${VENV_PATH}/bin/python" ]; then
        if check_hash_match "REQ_HASH" "$req_hash"; then install_pip=false; msg_success "Venv актуален."; fi
    fi
    if [ "$mode" == "secure" ]; then
        ! id "${SERVICE_USER}" &>/dev/null && sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}
        setup_repo_and_dirs "${SERVICE_USER}"; exec_cmd="sudo -u ${SERVICE_USER}"
        [ ! -d "${VENV_PATH}" ] && run_with_spinner "Создание venv (Python 3.12)" sudo -u ${SERVICE_USER} ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
        apply_python_compat_fixes
        if $install_pip; then
            run_with_spinner "Установка зависимостей" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install --no-cache-dir -r "${BOT_INSTALL_PATH}/requirements.txt"
            run_with_spinner "Установка tomlkit" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install --no-cache-dir tomlkit
            update_state_hash "REQ_HASH" "$req_hash"
        fi
    else
        setup_repo_and_dirs "root"; exec_cmd=""
        [ ! -d "${VENV_PATH}" ] && run_with_spinner "Создание venv (Python 3.12)" ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
        apply_python_compat_fixes
        if $install_pip; then
            run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install --no-cache-dir -r "${BOT_INSTALL_PATH}/requirements.txt"
            run_with_spinner "Установка tomlkit" "${VENV_PATH}/bin/pip" install --no-cache-dir tomlkit
            update_state_hash "REQ_HASH" "$req_hash"
        fi
    fi
    load_cached_env; ask_env_details; write_env_file "systemd" "$mode" ""
    run_db_migrations "$exec_cmd"
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель"
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}; [ -f .env ] && set -a && source .env && set +a
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot; save_current_version; cleanup_agent_files; cleanup_files
    configure_web_final
}

install_docker_logic() {
    local mode=$1; common_install_steps; install_extras; setup_repo_and_dirs "root"; check_docker_deps
    apply_python_compat_fixes; load_cached_env; ask_env_details; create_dockerfile; create_docker_compose_yml
    local container_name="tg-bot-${mode}"; write_env_file "docker" "$mode" "${container_name}"
    cd ${BOT_INSTALL_PATH}; local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
    run_with_spinner "Сборка Docker" sudo $dc_cmd build --no-cache
    msg_info "Настройка прав доступа для Docker..."
    sudo chown -R 1001:1001 "${BOT_INSTALL_PATH}"
    run_with_spinner "Запуск Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans
    msg_info "Настройка БД в контейнере..."
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich upgrade >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python migrate.py >/dev/null 2>&1
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"; sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot; save_current_version; cleanup_agent_files; cleanup_files
    configure_web_final
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Установка НОДЫ (Клиент) ===${C_RESET}"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi
    common_install_steps; if ! command -v iperf3 &>/dev/null; then echo "iperf3 true" | sudo debconf-set-selections; run_with_spinner "Установка iperf3" sudo apt-get install -y -q iperf3; fi
    setup_repo_and_dirs "root"; local h=$(echo "psutil requests" | sha256sum | awk '{print $1}')
    [ ! -d "${VENV_PATH}" ] && run_with_spinner "Создание venv" ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
    apply_python_compat_fixes
    if ! check_hash_match "NODE_REQ_HASH" "$h"; then run_with_spinner "Deps" "${VENV_PATH}/bin/pip" install --no-cache-dir psutil requests; update_state_hash "NODE_REQ_HASH" "$h"; fi
    load_cached_env; echo ""; msg_info "Подключение:"
    msg_question "Agent URL: " AGENT_URL; msg_question "Token: " NODE_TOKEN
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
EOF
    sudo chmod 600 "${ENV_FILE}"; create_and_start_service "${NODE_SERVICE_NAME}" "node/node.py" "root" "Node Client"
    save_current_version; cleanup_node_files; msg_success "Нода установлена!"
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Удаление ===${C_RESET}"
    sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    [ -f "${DOCKER_COMPOSE_FILE}" ] && (cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &> /dev/null)
    sudo rm -rf "${BOT_INSTALL_PATH}" /usr/local/bin/tgcp-bot; id "${SERVICE_USER}" &>/dev/null && sudo userdel -r "${SERVICE_USER}"
    msg_success "Удалено."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Обновление ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then msg_info "Обновление Ноды..."; install_node_logic; return; fi
    local exec_cmd=""; if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi
    cd "${BOT_INSTALL_PATH}"; run_with_spinner "Git fetch" $exec_cmd git fetch origin; run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"
    if [ -f "${ENV_FILE}" ] && grep -q "DEPLOY_MODE=docker" "${ENV_FILE}"; then
        local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
        apply_python_compat_fixes
        sudo chown -R 1001:1001 "${BOT_INSTALL_PATH}"
        run_with_spinner "Docker Up" sudo $dc_cmd up -d --build --no-cache
        local m=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        sudo $dc_cmd --profile "$m" exec -T "tg-bot-$m" aerich upgrade >/dev/null 2>&1
        sudo $dc_cmd --profile "$m" exec -T "tg-bot-$m" python migrate.py >/dev/null 2>&1
    else
        apply_python_compat_fixes
        local h=$(get_file_hash "${BOT_INSTALL_PATH}/requirements.txt")
        if ! check_hash_match "REQ_HASH" "$h"; then run_with_spinner "Pip" $exec_cmd "${VENV_PATH}/bin/pip" install --no-cache-dir -r requirements.txt --upgrade; update_state_hash "REQ_HASH" "$h"; fi
        run_db_migrations "$exec_cmd"; if systemctl list-unit-files | grep -q "^${SERVICE_NAME}"; then sudo systemctl restart ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME}; fi
    fi
    save_current_version; cleanup_agent_files; cleanup_files; msg_success "Обновлено."
}

main_menu() {
    while true; do
        clear; echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║      Установка VPS Manager Bot    ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        local l=$(get_local_version); local r=$(get_remote_version)
        echo -e "  Ветка: ${GIT_BRANCH}"; echo -e "  Тип: ${INSTALL_TYPE} | Статус: ${STATUS_MESSAGE}"
        if [ "$l" != "$r" ] && [ "$r" != "Не удалось получить" ] && [ "$l" != "Не определена" ] && [ "$INSTALL_TYPE" != "НЕТ" ]; then
             echo -e "  Версия: ${C_YELLOW}Локальная: $l (Доступна: $r)${C_RESET}"
        else echo -e "  Версия: ${C_GREEN}$l${C_RESET}"; fi
        echo "--------------------------------------------------------"
        if [ "$INSTALL_TYPE" == "НЕТ" ]; then
            echo -e "  Выберите режим установки:"
            echo "--------------------------------------------------------"
            echo "  1) АГЕНТ (Systemd - Secure)  [Рекомендуется]"
            echo "  2) АГЕНТ (Systemd - Root)    [Полный доступ]"
            echo "  3) АГЕНТ (Docker - Secure)   [Изоляция]"
            echo "  4) АГЕНТ (Docker - Root)     [Docker + Host]"
            echo -e "${C_GREEN}  8) НОДА (Клиент)${C_RESET}"
            echo "  0) Выход"
            echo "--------------------------------------------------------"
            read -p "$(echo -e "${C_BOLD}Ваш выбор: ${C_RESET}")" ch
            case $ch in
                1) uninstall_bot; install_systemd_logic "secure"; read -p "Enter..." ;; 2) uninstall_bot; install_systemd_logic "root"; read -p "Enter..." ;;
                3) uninstall_bot; install_docker_logic "secure"; read -p "Enter..." ;; 4) uninstall_bot; install_docker_logic "root"; read -p "Enter..." ;;
                8) uninstall_bot; install_node_logic; read -p "Enter..." ;; 0) break ;;
            esac
        else
            echo "  1) Обновить бота"
            echo "  2) Удалить бота"
            echo "  3) Переустановить (Systemd - Secure)"
            echo "  4) Переустановить (Systemd - Root)"
            echo "  5) Переустановить (Docker - Secure)"
            echo "  6) Переустановить (Docker - Root)"
            echo -e "${C_GREEN}  8) Установить НОДУ (Клиент)${C_RESET}"
            echo "  0) Выход"
            echo "--------------------------------------------------------"
            read -p "$(echo -e "${C_BOLD}Ваш выбор: ${C_RESET}")" ch
            case $ch in
                1) update_bot; read -p "Enter..." ;; 2) msg_question "Удалить? (y/n): " c; [[ "$c" =~ ^[Yy]$ ]] && uninstall_bot; return ;;
                3) uninstall_bot; install_systemd_logic "secure"; read -p "Enter..." ;; 4) uninstall_bot; install_systemd_logic "root"; read -p "Enter..." ;;
                5) uninstall_bot; install_docker_logic "secure"; read -p "Enter..." ;; 6) uninstall_bot; install_docker_logic "root"; read -p "Enter..." ;;
                8) uninstall_bot; install_node_logic; read -p "Enter..." ;; 0) break ;;
            esac
        fi
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Нужен root."; exit 1; fi
if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then install_node_logic; exit 0; fi
main_menu