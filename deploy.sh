#!/bin/bash

GIT_BRANCH="main"
AUTO_AGENT_URL=""
AUTO_NODE_TOKEN=""
AUTO_MODE=false
MIGRATE_ARGS=""

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
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"
README_FILE="${BOT_INSTALL_PATH}/README.md"
DOCKER_COMPOSE_FILE="${BOT_INSTALL_PATH}/docker-compose.yml"
ENV_FILE="${BOT_INSTALL_PATH}/.env"

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
        echo -e "${C_YELLOW}Последние строки лога (/tmp/${SERVICE_NAME}_install.log):${C_RESET}"
        tail -n 10 /tmp/${SERVICE_NAME}_install.log
    fi
    return $exit_code
}

get_local_version() { 
    if [ -f "${ENV_FILE}" ]; then
        local ver_env=$(grep '^INSTALLED_VERSION=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ -n "$ver_env" ]; then
            echo "$ver_env"
            return
        fi
    fi
    if [ -f "$README_FILE" ]; then 
        grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE" || echo "Не найдена"
    else 
        echo "Не установлен"
    fi 
}

INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Проверка не проводилась."
INTEGRITY_STATUS=""

check_integrity() {
    INTEGRITY_STATUS=""
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Бот не установлен."; return;
    fi

    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    IS_NODE=$(grep -q "MODE=node" "${ENV_FILE}" && echo "yes" || echo "no")

    if [ "$IS_NODE" == "yes" ]; then
        INTEGRITY_STATUS="${C_GREEN}🛡️ Режим НОДЫ (Git не требуется)${C_RESET}"
    elif [ -d "${BOT_INSTALL_PATH}/.git" ]; then
        cd "${BOT_INSTALL_PATH}" || return
        git fetch origin "$GIT_BRANCH" >/dev/null 2>&1
        local FILES_TO_CHECK="core modules bot.py watchdog.py migrate.py manage.py"
        local EXISTING_FILES=""
        for f in $FILES_TO_CHECK; do
            if [ -e "${BOT_INSTALL_PATH}/$f" ]; then EXISTING_FILES="$EXISTING_FILES $f"; fi
        done
        if [ -z "$EXISTING_FILES" ]; then
            INTEGRITY_STATUS="${C_YELLOW}⚠️ Файлы не найдены${C_RESET}"
        else
            local DIFF=$(git diff --name-only HEAD -- $EXISTING_FILES 2>/dev/null)
            if [ -n "$DIFF" ]; then
                INTEGRITY_STATUS="${C_RED}⚠️ ЦЕЛОСТНОСТЬ НАРУШЕНА (Файлы изменены локально)${C_RESET}"
            else
                INTEGRITY_STATUS="${C_GREEN}🛡️ Код подтвержден${C_RESET}"
            fi
        fi
        cd - >/dev/null
    else
        INTEGRITY_STATUS="${C_YELLOW}⚠️ Git не найден${C_RESET}"
    fi

    if [ "$IS_NODE" == "yes" ]; then
        INSTALL_TYPE="НОДА (Клиент)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}"; else STATUS_MESSAGE="${C_RED}Неактивен${C_RESET}"; fi
        return
    fi

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="АГЕНТ (Docker)"
        if command -v docker &> /dev/null && docker ps | grep -q "tg-bot"; then STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"; fi
    else
        INSTALL_TYPE="АГЕНТ (Systemd)"
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"; fi
    fi
}

setup_nginx_proxy() {
    echo -e "\n${C_CYAN}🔒 Настройка HTTPS (Nginx + Certbot)${C_RESET}"
    run_with_spinner "Установка Nginx и Certbot" sudo apt-get install -y -q nginx certbot python3-certbot-nginx psmisc

    if command -v lsof &> /dev/null && lsof -Pi :80 -sTCP:LISTEN -t >/dev/null ; then
        sudo fuser -k 80/tcp 2>/dev/null
        sudo systemctl stop nginx 2>/dev/null
    elif command -v fuser &> /dev/null && sudo fuser 80/tcp >/dev/null; then
         sudo fuser -k 80/tcp
         sudo systemctl stop nginx 2>/dev/null
    fi

    if sudo certbot certonly --standalone --non-interactive --agree-tos --email "${HTTPS_EMAIL}" -d "${HTTPS_DOMAIN}"; then
        msg_success "Сертификат получен!"
    else
        msg_error "Ошибка получения сертификата."
        sudo systemctl start nginx
        return 1
    fi

    NGINX_CONF="/etc/nginx/sites-available/${HTTPS_DOMAIN}"
    NGINX_LINK="/etc/nginx/sites-enabled/${HTTPS_DOMAIN}"
    if [ -f "/etc/nginx/sites-enabled/default" ]; then sudo rm -f "/etc/nginx/sites-enabled/default"; fi

    sudo bash -c "cat > ${NGINX_CONF}" <<EOF
server {
    listen ${HTTPS_PORT} ssl http2;
    server_name ${HTTPS_DOMAIN};

    # SSL
    ssl_certificate /etc/letsencrypt/live/${HTTPS_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${HTTPS_DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5:!RC4;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    access_log /var/log/nginx/${HTTPS_DOMAIN}_access.log;
    error_log /var/log/nginx/${HTTPS_DOMAIN}_error.log;

    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
EOF
    sudo ln -sf "${NGINX_CONF}" "${NGINX_LINK}"
    if sudo nginx -t; then
        sudo systemctl restart nginx
        if command -v ufw &> /dev/null; then sudo ufw allow ${HTTPS_PORT}/tcp >/dev/null; fi
        echo -e "Веб-панель доступна: https://${HTTPS_DOMAIN}:${HTTPS_PORT}/"
    else
        msg_error "Ошибка в конфиге Nginx."
    fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Обновление системы..."
    
    # Удаляем битые симлинки Nginx (оставшиеся от удаленных сайтов), чтобы избежать ошибок apt-get dpkg
    if [ -d "/etc/nginx/sites-enabled" ]; then
        sudo find /etc/nginx/sites-enabled -xtype l -delete 2>/dev/null
    fi
    
    run_with_spinner "Apt update" sudo apt-get update -y -q
    run_with_spinner "Установка пакетов" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3 python3-pip python3-venv git curl wget sudo python3-yaml
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    cd /
    msg_info "Подготовка файлов (Ветка: ${GIT_BRANCH})..."
    if [ -f "${ENV_FILE}" ]; then cp "${ENV_FILE}" /tmp/tgbot_env.bak; fi
    if [ -d "${BOT_INSTALL_PATH}" ]; then run_with_spinner "Удаление старых файлов" sudo rm -rf "${BOT_INSTALL_PATH}"; fi
    sudo mkdir -p ${BOT_INSTALL_PATH}
    run_with_spinner "Клонирование репозитория" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    if [ -f "/tmp/tgbot_env.bak" ]; then sudo cp /tmp/tgbot_env.bak "${ENV_FILE}"; fi
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
            msg_info "Загружаю сохраненные данные..."
            get_env_val() { grep "^$1=" "$env_file" | cut -d'=' -f2- | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//"; }
            [ -z "$T" ] && T=$(get_env_val "TG_BOT_TOKEN")
            [ -z "$A" ] && A=$(get_env_val "TG_ADMIN_ID")
            [ -z "$U" ] && U=$(get_env_val "TG_ADMIN_USERNAME")
            [ -z "$N" ] && N=$(get_env_val "TG_BOT_NAME")
            [ -z "$P" ] && P=$(get_env_val "WEB_SERVER_PORT")
            [ -z "$SENTRY_DSN" ] && SENTRY_DSN=$(get_env_val "SENTRY_DSN")
            if [ -z "$W" ]; then
                local val=$(get_env_val "ENABLE_WEB_UI")
                if [[ "$val" == "false" ]]; then W="n"; else W="y"; fi
            fi
            [ -z "$AGENT_URL" ] && AGENT_URL=$(get_env_val "AGENT_BASE_URL")
            [ -z "$NODE_TOKEN" ] && NODE_TOKEN=$(get_env_val "AGENT_TOKEN")
        else
            msg_info "Восстановление пропущено."
        fi
    fi
}
cleanup_common_trash() {
    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then sudo rm -rf "$BOT_INSTALL_PATH/assets"; fi
    sudo find "$BOT_INSTALL_PATH" -maxdepth 1 -type f \( -name "*.txt" -o -name "*.md" -o -name "*.sh" -o -name ".gitignore" -o -name "LICENSE" \) -delete
    sudo find "$BOT_INSTALL_PATH" -maxdepth 1 -type f -name "*.ini" ! -name "aerich.ini" -delete
    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
}
cleanup_for_systemd() {
    local action_name=$1
    msg_info "Завершение ${action_name}..."
    cleanup_common_trash
    sudo rm -rf "${BOT_INSTALL_PATH}/node"
    sudo rm -f "${BOT_INSTALL_PATH}/Dockerfile" "${BOT_INSTALL_PATH}/docker-compose.yml"
}
cleanup_for_docker() {
    local action_name=$1
    msg_info "Завершение ${action_name}..."
    cleanup_common_trash
    cd "${BOT_INSTALL_PATH}"
    sudo rm -rf node
    sudo rm -rf core modules bot.py watchdog.py manage.py migrate.py aerich.ini
    sudo rm -f Dockerfile
}
cleanup_for_node() {
    local action_name=$1
    msg_info "Завершение ${action_name}..."
    cleanup_common_trash
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git config/users.json config/alerts_config.json
}

install_extras() {
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Установка Fail2ban" sudo apt-get install -y -q fail2ban; fi
    fi
    
    # Detect server location by external IP
    msg_info "Определение геолокации сервера..."
    SERVER_COUNTRY=""
    EXT_IP=$(curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null || curl -s --connect-timeout 5 https://ipinfo.io/ip 2>/dev/null || echo "")
    if [ -n "$EXT_IP" ]; then
        SERVER_COUNTRY=$(curl -s --connect-timeout 5 "http://ip-api.com/line/${EXT_IP}?fields=countryCode" 2>/dev/null || echo "")
    fi
    
    if [ "$SERVER_COUNTRY" == "RU" ]; then
        msg_info "Сервер находится в России - устанавливаем iperf3 для speedtest"
        if ! command -v iperf3 &> /dev/null; then
            run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
        else
            msg_success "iperf3 уже установлен"
        fi
        # Mark that we use iperf3 mode
        echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    else
        msg_info "Сервер не в России - устанавливаем Ookla Speedtest CLI"
        
        # Remove iperf3 if present (not needed outside Russia)
        if command -v iperf3 &> /dev/null; then
            run_with_spinner "Удаление iperf3" sudo apt-get remove -y -q iperf3
        fi
        
        if command -v speedtest &> /dev/null && speedtest --version 2>&1 | grep -q "Speedtest by Ookla"; then
            msg_success "Ookla Speedtest CLI уже установлен"
        else
            install_ookla_speedtest
        fi
        echo "OOKLA" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    fi
}

install_ookla_speedtest() {
    # Check if already installed and working
    if command -v speedtest &> /dev/null && speedtest --version 2>&1 | grep -q "Speedtest by Ookla"; then
        msg_success "Ookla Speedtest CLI уже установлен"
        return 0
    fi
    
    msg_info "Установка Ookla Speedtest CLI..."
    
    # Install curl if not present
    if ! command -v curl &> /dev/null; then
        run_with_spinner "Установка curl" sudo apt-get install -y -q curl
    fi
    
    # Get Ubuntu version
    UBUNTU_VERSION=""
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        UBUNTU_VERSION="$VERSION_ID"
    fi
    
    # Add Ookla repository
    run_with_spinner "Добавление репозитория Ookla" bash -c 'curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash'
    
    # Fix for Ubuntu 24+ (noble -> jammy)
    OOKLA_LIST="/etc/apt/sources.list.d/ookla_speedtest-cli.list"
    if [ -f "$OOKLA_LIST" ]; then
        if grep -q "noble" "$OOKLA_LIST" 2>/dev/null; then
            msg_info "Применяю исправление для Ubuntu 24+..."
            sudo sed -i 's/noble/jammy/g' "$OOKLA_LIST"
        fi
        # Also fix for other unsupported versions
        if grep -q "oracular\|mantic\|lunar" "$OOKLA_LIST" 2>/dev/null; then
            msg_info "Применяю исправление для неподдерживаемой версии Ubuntu..."
            sudo sed -i 's/oracular\|mantic\|lunar/jammy/g' "$OOKLA_LIST"
        fi
    fi
    
    run_with_spinner "Обновление пакетов" sudo apt-get update -y -q
    run_with_spinner "Установка speedtest" sudo apt-get install -y -q speedtest
    
    if command -v speedtest &> /dev/null; then
        msg_success "Ookla Speedtest CLI установлен успешно"
    else
        msg_warning "Не удалось установить Ookla Speedtest CLI, будет использован iperf3"
        if ! command -v iperf3 &> /dev/null; then
            run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
        fi
        echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    fi
}

ask_env_details() {
    msg_info "Ввод данных .env..."
    msg_question "Токен Ботa: " T; msg_question "ID Админа: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Внутренний Web Port [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN

    msg_question "Включить Web-UI? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then
        ENABLE_WEB="false"
        SETUP_HTTPS="false"
    else
        ENABLE_WEB="true"
        GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        msg_question "Настроить HTTPS? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"
            msg_question "Домен: " HTTPS_DOMAIN
            msg_question "Email: " HTTPS_EMAIL
            msg_question "Внешний HTTPS порт [8443]: " HP
            if [ -z "$HP" ]; then HTTPS_PORT="8443"; else HTTPS_PORT="$HP"; fi
        else
            SETUP_HTTPS="false"
        fi
    fi
    export T A U N WEB_PORT ENABLE_WEB SETUP_HTTPS HTTPS_DOMAIN HTTPS_EMAIL HTTPS_PORT GEN_PASS SENTRY_DSN
}

write_env_file() {
    local dm=$1; local im=$2; local cn=$3
    local ver=""
    if [ -f "$README_FILE" ]; then ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE"); fi
    if [ -z "$ver" ]; then ver="Unknown"; fi
    local debug_setting="true"
    if [ "$GIT_BRANCH" == "main" ]; then debug_setting="false"; fi

    local compose_profile=""
    if [ "$dm" == "docker" ]; then compose_profile="${im}"; fi
    local web_domain=""
    if [ -n "$HTTPS_DOMAIN" ]; then web_domain="${HTTPS_DOMAIN}"; fi

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
INSTALLED_VERSION="${ver}"
COMPOSE_PROFILES="${compose_profile}"
WEB_DOMAIN="${web_domain}"
EOF
    sudo chmod 600 "${ENV_FILE}"

    # Create installstate file
    local installstate_file="${BOT_INSTALL_PATH}/installstate"
    sudo bash -c "cat > ${installstate_file}" <<EOF
install_mode=${im}
deploy_mode=${dm}
installed_at=$(date -Iseconds)
version=${ver}
branch=${GIT_BRANCH}
EOF
    sudo chmod 644 "${installstate_file}"
}

ensure_env_variables() {
    # Check and add missing environment variables to .env file
    # This ensures compatibility between versions
    
    if [ ! -f "${ENV_FILE}" ]; then
        msg_warning ".env файл не найден, пропуск проверки переменных."
        return 0
    fi
    
    msg_info "Проверка переменных окружения..."
    local changes_made=false
    
    # List of variables with their default values
    # Format: "VAR_NAME|default_value|description"
    local ENV_VARS=(
        "WEB_SERVER_HOST|0.0.0.0|Хост веб-сервера"
        "WEB_SERVER_PORT|8080|Порт веб-сервера"
        "INSTALL_MODE|secure|Режим установки"
        "DEPLOY_MODE|systemd|Режим деплоя"
        "ENABLE_WEB_UI|true|Включить веб-интерфейс"
        "DEBUG|false|Режим отладки"
        "TG_BOT_NAME|VPS Bot|Имя бота"
    )
    
    for var_entry in "${ENV_VARS[@]}"; do
        local var_name=$(echo "$var_entry" | cut -d'|' -f1)
        local default_val=$(echo "$var_entry" | cut -d'|' -f2)
        local var_desc=$(echo "$var_entry" | cut -d'|' -f3)
        
        if ! grep -q "^${var_name}=" "${ENV_FILE}"; then
            echo -e "${C_YELLOW}  + Добавлена переменная ${var_name}=${default_val}${C_RESET}"
            sudo bash -c "echo '${var_name}=\"${default_val}\"' >> ${ENV_FILE}"
            changes_made=true
        fi
    done
    
    # Add optional variables if not present (with empty defaults)
    local OPTIONAL_VARS=(
        "SENTRY_DSN"
        "TG_ADMIN_USERNAME"
        "TG_BOT_CONTAINER_NAME"
        "COMPOSE_PROFILES"
        "WEB_DOMAIN"
    )
    
    for var_name in "${OPTIONAL_VARS[@]}"; do
        if ! grep -q "^${var_name}=" "${ENV_FILE}"; then
            sudo bash -c "echo '${var_name}=\"\"' >> ${ENV_FILE}"
            changes_made=true
        fi
    done
    
    if [ "$changes_made" = true ]; then
        msg_success "Переменные окружения обновлены."
    else
        msg_success "Все переменные актуальны."
    fi
}

check_docker_deps() {
    if ! command -v docker &> /dev/null; then curl -sSL https://get.docker.com -o /tmp/get-docker.sh; run_with_spinner "Установка Docker" sudo sh /tmp/get-docker.sh; fi
    if command -v docker-compose &> /dev/null; then sudo rm -f $(which docker-compose); fi
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
FROM python:3.10-slim-bookworm
RUN apt-get update && apt-get install -y python3-yaml iperf3 git curl wget sudo procps iputils-ping net-tools gnupg docker.io coreutils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && pip install --no-cache-dir docker aiohttp aiosqlite argon2-cffi sentry-sdk tortoise-orm aerich cryptography tomlkit
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
version: '3.8'
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
    msg_info "Миграция базы данных и настроек..."
    cd "${BOT_INSTALL_PATH}" || return 1

    # Build env sourcing prefix for all commands
    local env_source=""
    if [ -f "${ENV_FILE}" ]; then
        set -a; source "${ENV_FILE}"; set +a
        env_source="set -a; source ${ENV_FILE}; set +a;"
    fi

    # For secure mode, run as service user with env vars
    local run_cmd=""
    if [ -n "$exec_user" ]; then
        run_cmd="sudo -u ${SERVICE_USER} bash -c"
    fi

    local aerich_bin="${VENV_PATH}/bin/aerich"
    local aerich_cfg="${BOT_INSTALL_PATH}/aerich.ini"

    # Always recreate aerich.ini with correct TOML format (quoted values)
    sudo bash -c "cat > '${aerich_cfg}'" <<'EOF'
[aerich]
tortoise_orm = "core.config.TORTOISE_ORM"
location = "./migrations"
src_folder = "."
EOF

    if [ -n "$exec_user" ]; then sudo chown ${SERVICE_USER} "${aerich_cfg}" 2>/dev/null; fi

    # Helper to run commands with proper env
    _run() {
        if [ -n "$run_cmd" ]; then
            $run_cmd "${env_source} cd ${BOT_INSTALL_PATH} && $*"
        else
            eval "$*"
        fi
    }

    if [ ! -x "$aerich_bin" ]; then
        msg_info "Aerich CLI не найден, пропуск миграций БД."
    elif [ ! -d "${BOT_INSTALL_PATH}/migrations" ]; then
        _run "'$aerich_bin' -c '$aerich_cfg' init-db" >/dev/null 2>&1 || true
    else
        _run "'$aerich_bin' -c '$aerich_cfg' upgrade" >/dev/null 2>&1 || true
    fi

    if [ -f "${BOT_INSTALL_PATH}/migrate.py" ]; then
        _run "'${VENV_PATH}/bin/python' '${BOT_INSTALL_PATH}/migrate.py' $MIGRATE_ARGS"
    fi
}

install_systemd_logic() {
    local mode=$1
    common_install_steps
    install_extras
    local exec_cmd=""
    if [ "$mode" == "secure" ]; then
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}; fi
        setup_repo_and_dirs "${SERVICE_USER}"
        sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv "${VENV_PATH}"
        run_with_spinner "Обновление pip" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install --upgrade pip setuptools wheel
        run_with_spinner "Установка зависимостей" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        run_with_spinner "Установка tomlkit" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install tomlkit
        exec_cmd="sudo -u ${SERVICE_USER}"
    else
        setup_repo_and_dirs "root"
        ${PYTHON_BIN} -m venv "${VENV_PATH}"
        run_with_spinner "Обновление pip" "${VENV_PATH}/bin/pip" install --upgrade pip setuptools wheel
        run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        run_with_spinner "Установка tomlkit" "${VENV_PATH}/bin/pip" install tomlkit
        exec_cmd=""
    fi

    load_cached_env
    ask_env_details
    write_env_file "systemd" "$mode" ""
    run_db_migrations "$exec_cmd"
    cleanup_for_systemd "установки"
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель"

    msg_info "Создание команды 'tgcp-bot'..."
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then set -a; source .env; set +a; fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    local ip=$(curl -s ipinfo.io/ip)
    echo ""; msg_success "Установка завершена! Панель: http://${ip}:${WEB_PORT}"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy; fi
}

install_docker_logic() {
    local mode=$1
    common_install_steps
    install_extras
    setup_repo_and_dirs "root"
    check_docker_deps
    load_cached_env
    ask_env_details
    create_dockerfile
    create_docker_compose_yml
    local container_name="tg-bot-${mode}"
    write_env_file "docker" "$mode" "${container_name}"
    cd ${BOT_INSTALL_PATH}
    local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
    run_with_spinner "Сборка Docker" sudo $dc_cmd build
    run_with_spinner "Запуск Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans

    msg_info "Миграция в контейнере..."
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init-db >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich upgrade >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python migrate.py $MIGRATE_ARGS >/dev/null 2>&1
    cleanup_for_docker "установки"

    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    msg_success "Установка Docker завершена!"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy; fi
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Установка НОДЫ ===${C_RESET}"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi
    common_install_steps
    
    # Detect node location and install appropriate speedtest tool
    msg_info "Определение геолокации ноды..."
    NODE_COUNTRY=""
    EXT_IP=$(curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null || curl -s --connect-timeout 5 https://ipinfo.io/ip 2>/dev/null || echo "")
    if [ -n "$EXT_IP" ]; then
        NODE_COUNTRY=$(curl -s --connect-timeout 5 "http://ip-api.com/line/${EXT_IP}?fields=countryCode" 2>/dev/null || echo "")
    fi
    
    if [ "$NODE_COUNTRY" == "RU" ]; then
        msg_info "Нода в России - используем iperf3"
        run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
    else
        msg_info "Нода не в России - устанавливаем Ookla Speedtest CLI"
        install_ookla_speedtest
        # Also install iperf3 as fallback
        run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
    fi
    
    setup_repo_and_dirs "root"
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Обновление pip" "${VENV_PATH}/bin/pip" install --upgrade pip setuptools wheel
    run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install psutil requests pyyaml
    load_cached_env
    msg_question "Agent URL (http://IP:8080): " AGENT_URL
    msg_question "Token: " NODE_TOKEN
    local ver="Unknown"; if [ -f "$README_FILE" ]; then ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE"); fi
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
INSTALLED_VERSION="${ver}"
EOF
    
    # Check and restore/configure agent monitoring variables if settings were restored
    if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]] && [ -f "/tmp/tgbot_env.bak" ]; then
        local saved_bot_token=$(grep "^BOT_TOKEN=" "/tmp/tgbot_env.bak" | cut -d'=' -f2- | tr -d '"' | xargs)
        local saved_chat_ids=$(grep "^CRITICAL_ALERT_CHAT_IDS=" "/tmp/tgbot_env.bak" | cut -d'=' -f2- | tr -d '"' | xargs)
        local saved_node_name=$(grep "^NODE_NAME=" "/tmp/tgbot_env.bak" | cut -d'=' -f2- | tr -d '"')
        local saved_delay=$(grep "^AGENT_ALERT_DELAY_SECONDS=" "/tmp/tgbot_env.bak" | cut -d'=' -f2- | tr -d '"')
        
        # Ask user if monitoring variables are missing or empty
        local need_bot_token=""
        local need_chat_ids=""
        local need_node_name=""
        
        if [ -z "$saved_bot_token" ]; then
            need_bot_token="yes"
        fi
        if [ -z "$saved_chat_ids" ]; then
            need_chat_ids="yes"
        fi
        if [ -z "$saved_node_name" ]; then
            need_node_name="yes"
        fi
        
        # If any monitoring variable is missing, ask if user wants to configure them
        if [ -n "$need_bot_token" ] || [ -n "$need_chat_ids" ]; then
            echo ""
            echo -e "${C_YELLOW}⚠️  Обнаружены пустые переменные для мониторинга агента:${C_RESET}"
            [ -n "$need_bot_token" ] && echo -e "  • BOT_TOKEN (токен бота)"
            [ -n "$need_chat_ids" ] && echo -e "  • CRITICAL_ALERT_CHAT_IDS (ID чатов для алертов)"
            [ -n "$need_node_name" ] && echo -e "  • NODE_NAME (имя ноды)"
            echo ""
            read -p "$(echo -e "${C_CYAN}❓ Настроить мониторинг агента сейчас? (y/n) [n]: ${C_RESET}")" setup_monitoring
            setup_monitoring=${setup_monitoring:-n}
            
            if [[ "$setup_monitoring" =~ ^[Yy]$ ]]; then
                echo ""
                echo -e "${C_CYAN}Настройка мониторинга агента:${C_RESET}"
                echo -e "${C_YELLOW}Важно:${C_RESET} не используйте chat_id другого бота (Telegram блокирует отправку боту от бота)."
                echo ""
                echo -e "${C_YELLOW}Как получить Chat ID:${C_RESET}"
                echo -e "  • Напишите боту @userinfobot команду /start"
                echo -e "  • Или добавьте бота в группу и используйте /start"
                echo ""
                
                if [ -n "$need_bot_token" ]; then
                    read -p "Введите BOT_TOKEN: " saved_bot_token
                fi
                
                if [ -n "$need_chat_ids" ]; then
                    read -p "Введите CRITICAL_ALERT_CHAT_IDS (через запятую): " saved_chat_ids
                fi
                
                if [ -n "$need_node_name" ]; then
                    read -p "Введите NODE_NAME (имя этой ноды): " saved_node_name
                fi
            fi
        fi
        
        # Add monitoring variables to .env if monitoring was configured (has BOT_TOKEN and CHAT_IDS)
        if [ -n "$saved_bot_token" ] && [ -n "$saved_chat_ids" ]; then
            echo "" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "# Agent Monitoring Configuration" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "BOT_TOKEN=\"${saved_bot_token}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "CRITICAL_ALERT_CHAT_IDS=\"${saved_chat_ids}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "NODE_NAME=\"${saved_node_name}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            [ -n "$saved_delay" ] && echo "AGENT_ALERT_DELAY_SECONDS=\"${saved_delay}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            msg_info "✓ Переменные мониторинга добавлены в .env"
        fi
    fi
    
    sudo chmod 600 "${ENV_FILE}"
    sudo tee "/etc/systemd/system/${NODE_SERVICE_NAME}.service" > /dev/null <<EOF
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
    sudo systemctl daemon-reload; sudo systemctl enable ${NODE_SERVICE_NAME}
    cleanup_for_node "установки"  
    run_with_spinner "Запуск Ноды" sudo systemctl restart ${NODE_SERVICE_NAME}
    msg_success "Нода установлена!"
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Удаление ===${C_RESET}"
    cd /
    sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &> /dev/null; fi
    sudo rm -rf "${BOT_INSTALL_PATH}"
    sudo rm -f /usr/local/bin/tgcp-bot
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Удалено."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Обновление ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then install_node_logic; return; fi
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git не найден."; return 1; fi
    echo "" > /tmp/${SERVICE_NAME}_install.log
    local exec_cmd=""
    if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi

    cd "${BOT_INSTALL_PATH}"
    if ! run_with_spinner "Git fetch" $exec_cmd git fetch origin; then return 1; fi
    if ! run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"; then return 1; fi
    
    local new_ver=""
    
    # 1. Пробуем получить версию из названия ветки (например, release/1.19.0 -> 1.19.0)
    if echo "$GIT_BRANCH" | grep -q "release/"; then
        new_ver=$(echo "$GIT_BRANCH" | grep -oP 'release/\K[\d\.]+')
    fi
    
    # 2. Если не вышло, ищем последнюю версию в CHANGELOG.md (по формату ## [1.19.0])
    if [ -z "$new_ver" ] && [ -f "${BOT_INSTALL_PATH}/CHANGELOG.md" ]; then
        new_ver=$(grep -oP '^## \[\K[\d\.]+' "${BOT_INSTALL_PATH}/CHANGELOG.md" | head -n 1)
    fi
    
    # 3. Если и там нет, берем из README.md (как было изначально)
    if [ -z "$new_ver" ] && [ -f "$README_FILE" ]; then
        new_ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
    fi

    # Обновляем .env
    if [ -n "$new_ver" ] && [ -f "${ENV_FILE}" ]; then
         if grep -q "^INSTALLED_VERSION=" "${ENV_FILE}"; then
             sudo sed -i "s/^INSTALLED_VERSION=.*/INSTALLED_VERSION=\"${new_ver}\"/" "${ENV_FILE}"
         else
             sudo bash -c "echo 'INSTALLED_VERSION=\"${new_ver}\"' >> ${ENV_FILE}"
         fi
    fi

    # Check and add missing environment variables
    ensure_env_variables

    local current_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    
    if [ "$current_mode" == "docker" ]; then
        if [ -f "docker-compose.yml" ]; then
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            if ! run_with_spinner "Docker Up" sudo $dc_cmd up -d --build; then msg_error "Ошибка Docker."; return 1; fi
            sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
            sudo chmod +x /usr/local/bin/tgcp-bot
        else msg_error "Нет docker-compose.yml"; return 1; fi
    else
        run_with_spinner "Обновление pip" $exec_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
        run_with_spinner "Обновление tomlkit" $exec_cmd "${VENV_PATH}/bin/pip" install tomlkit
        sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then set -a; source .env; set +a; fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
        sudo chmod +x /usr/local/bin/tgcp-bot
        if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then sudo systemctl restart ${SERVICE_NAME}; fi
        if systemctl list-unit-files | grep -q "^${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; fi
    fi
	
    MIGRATE_ARGS=""
    if [ -f "${BOT_INSTALL_PATH}/config/system_config.json" ]; then
        echo ""
        echo -e "${C_CYAN}🔍 Проверка конфигурации...${C_RESET}"
        echo "❓ Хотите сбросить мета-данные WebUI (заголовок, фавикон, SEO) до стандартных?"
        read -p "Сбросить? (y/N): " reset_meta_answer
        if [[ "$reset_meta_answer" =~ ^[Yy]$ ]]; then
            MIGRATE_ARGS="--reset-meta"
            echo -e "${C_YELLOW}⚠️  Будет выполнен сброс мета-данных.${C_RESET}"
        fi
    fi

    if [ "$current_mode" == "docker" ]; then
         local mode=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
         local cn="tg-bot-${mode}"
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} aerich upgrade >/dev/null 2>&1
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} python migrate.py $MIGRATE_ARGS >/dev/null 2>&1
         
         cleanup_for_docker "обновления"
    else
         run_db_migrations "$exec_cmd"
         cleanup_for_systemd "обновления"
    fi

    msg_success "Обновлено."
}

check_agent_monitoring_status() {
    if [ ! -f "${ENV_FILE}" ]; then
        echo "выкл"
        return
    fi

    local bot_token_value=$(grep '^BOT_TOKEN=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local chat_ids_value=$(grep '^CRITICAL_ALERT_CHAT_IDS=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)

    if [ -n "$bot_token_value" ] && [ -n "$chat_ids_value" ]; then
        echo "вкл"
    else
        echo "выкл"
    fi
}

toggle_agent_monitoring() {
    if [ ! -f "${ENV_FILE}" ]; then
        msg_error "Файл .env не найден!"
        return
    fi

    local current_bot_token=$(grep '^BOT_TOKEN=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_chat_ids=$(grep '^CRITICAL_ALERT_CHAT_IDS=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_node_name=$(grep '^NODE_NAME=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"')
    local current_delay=$(grep '^AGENT_ALERT_DELAY_SECONDS=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local status=$(check_agent_monitoring_status)

    if [ "$status" == "вкл" ]; then
        # Отключаем мониторинг - удаляем переменные
        msg_warning "Отключение мониторинга агента..."
        sed -i '/^# Agent Monitoring Configuration$/d' "${ENV_FILE}"
        sed -i '/^DEBUG=/d' "${ENV_FILE}"
        sed -i '/^BOT_TOKEN=/d' "${ENV_FILE}"
        sed -i '/^CRITICAL_ALERT_CHAT_IDS=/d' "${ENV_FILE}"
        sed -i '/^AGENT_ALERT_DELAY_SECONDS=/d' "${ENV_FILE}"
        sed -i '/^NODE_NAME=/d' "${ENV_FILE}"
        msg_success "Мониторинг агента отключен. Переменные удалены из .env"
        local deploy_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ "$deploy_mode" == "docker" ]; then
            msg_info "Перезапуск Docker контейнера..."
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            cd "${BOT_INSTALL_PATH}" && sudo $dc_cmd restart
            msg_success "Docker контейнер перезапущен"
        else
            msg_info "Перезапуск ноды..."
            sudo systemctl restart ${NODE_SERVICE_NAME}
            msg_success "Нода перезапущена"
        fi
    else
        # Включаем/чинить мониторинг - запрашиваем данные и обновляем переменные
        msg_info "Настройка мониторинга агента..."
        if [ -z "$current_bot_token" ]; then
            msg_warning "BOT_TOKEN отсутствует или пустой в .env"
        fi
        if [ -z "$current_chat_ids" ]; then
            msg_warning "CRITICAL_ALERT_CHAT_IDS отсутствует или пустой в .env"
        fi
        if [ -z "$current_node_name" ]; then
            msg_warning "NODE_NAME отсутствует или пустой в .env"
        fi
        if [ -z "$current_delay" ]; then
            msg_warning "AGENT_ALERT_DELAY_SECONDS отсутствует или пустой в .env"
        fi

        echo ""
        echo -e "${C_CYAN}Для работы мониторинга агента нужны:${C_RESET}"
        echo -e "  1. BOT_TOKEN - токен вашего Telegram бота"
        echo -e "  2. CRITICAL_ALERT_CHAT_IDS - ID чатов для критических алертов (через запятую)"
        echo -e "  3. AGENT_ALERT_DELAY_SECONDS - задержка перед отправкой алерта (в секундах)"
        echo -e "  4. NODE_NAME - имя этой ноды"
        echo ""
        echo -e "${C_YELLOW}Важно:${C_RESET} не используйте chat_id другого бота (Telegram блокирует отправку боту от бота)."
        echo ""
        echo -e "${C_YELLOW}Как получить Chat ID:${C_RESET}"
        echo -e "  • Напишите боту @userinfobot команду /start"
        echo -e "  • Или добавьте бота в группу и используйте /start"
        echo ""

        read -p "Введите BOT_TOKEN [текущее: ${current_bot_token:-пусто}]: " bot_token
        if [ -z "$bot_token" ]; then
            bot_token="$current_bot_token"
        fi
        if [ -z "$bot_token" ]; then
            msg_error "BOT_TOKEN не может быть пустым!"
            return
        fi

        read -p "Введите CRITICAL_ALERT_CHAT_IDS (через запятую) [текущее: ${current_chat_ids:-пусто}]: " chat_ids
        if [ -z "$chat_ids" ]; then
            chat_ids="$current_chat_ids"
        fi
        if [ -z "$chat_ids" ]; then
            msg_error "CRITICAL_ALERT_CHAT_IDS не может быть пустым!"
            return
        fi

        read -p "Введите NODE_NAME [текущее: ${current_node_name:-Node}]: " node_name
        if [ -z "$node_name" ]; then
            node_name="${current_node_name:-Node}"
        fi

        read -p "Введите AGENT_ALERT_DELAY_SECONDS [текущее: ${current_delay:-15}]: " alert_delay
        if [ -z "$alert_delay" ]; then
            alert_delay="${current_delay:-15}"
        fi

        # Обновляем переменные в .env
        sed -i '/^# Agent Monitoring Configuration$/d' "${ENV_FILE}"
        sed -i '/^DEBUG=/d' "${ENV_FILE}"
        sed -i '/^BOT_TOKEN=/d' "${ENV_FILE}"
        sed -i '/^CRITICAL_ALERT_CHAT_IDS=/d' "${ENV_FILE}"
        sed -i '/^AGENT_ALERT_DELAY_SECONDS=/d' "${ENV_FILE}"
        sed -i '/^NODE_NAME=/d' "${ENV_FILE}"
        echo "" >> "${ENV_FILE}"
        echo "DEBUG=\"false\"" >> "${ENV_FILE}"
        echo "BOT_TOKEN=\"${bot_token}\"" >> "${ENV_FILE}"
        echo "CRITICAL_ALERT_CHAT_IDS=\"${chat_ids}\"" >> "${ENV_FILE}"
        echo "AGENT_ALERT_DELAY_SECONDS=\"${alert_delay}\"" >> "${ENV_FILE}"
        echo "NODE_NAME=\"${node_name}\"" >> "${ENV_FILE}"

        msg_success "Мониторинг агента включен/обновлен!"
        local deploy_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ "$deploy_mode" == "docker" ]; then
            msg_info "Перезапуск Docker контейнера..."
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            cd "${BOT_INSTALL_PATH}" && sudo $dc_cmd restart
            msg_success "Docker контейнер перезапущен"
        else
            msg_info "Перезапуск ноды..."
            sudo systemctl restart ${NODE_SERVICE_NAME}
            msg_success "Нода перезапущена"
        fi
    fi
}

main_menu() {
    local local_version=$(get_local_version)
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║    Менеджер VPS Telegram Бот      ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        local item_type="агента"
        if [ "$IS_NODE" == "yes" ]; then
            item_type="ноду"
        fi
        echo -e "  Ветка: ${GIT_BRANCH} | Версия: ${local_version}"
        echo -e "  Тип: ${INSTALL_TYPE} | Статус: ${STATUS_MESSAGE}"
        if [ -n "$INTEGRITY_STATUS" ]; then echo -e "  Интегритет: ${INTEGRITY_STATUS}"; fi
        echo "--------------------------------------------------------"
        echo "  1) Обновить ${item_type}"
        echo "  2) Удалить ${item_type}"
        echo "  3) Переустановить (Systemd - Secure)"
        echo "  4) Переустановить (Systemd - Root)"
        echo "  5) Переустановить (Docker - Secure)"
        echo "  6) Переустановить (Docker - Root)"
        if [ "$IS_NODE" == "yes" ]; then
            echo -e "${C_GREEN}  7) Установить НОДУ (Клиент)${C_RESET}"
        fi
        
        # Показываем пункт мониторинга агента только для нод
        if [ "$IS_NODE" == "yes" ]; then
            local monitoring_status=$(check_agent_monitoring_status)
            echo -e "${C_YELLOW}  8) Мониторинг агента (${monitoring_status})${C_RESET}"
        fi
        
        echo "  0) Выход"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Ваш выбор: ${C_RESET}")" choice
        case $choice in
            1) update_bot; read -p "Нажмите Enter..." ;;
            2) msg_question "Удалить ${item_type}? (y/n): " c; if [[ "$c" =~ ^[Yy]$ ]]; then uninstall_bot; return; fi ;;
            3) uninstall_bot; install_systemd_logic "secure"; read -p "Нажмите Enter..." ;;
            4) uninstall_bot; install_systemd_logic "root"; read -p "Нажмите Enter..." ;;
            5) uninstall_bot; install_docker_logic "secure"; read -p "Нажмите Enter..." ;;
            6) uninstall_bot; install_docker_logic "root"; read -p "Нажмите Enter..." ;;
            7) if [ "$IS_NODE" == "yes" ]; then uninstall_bot; install_node_logic; read -p "Нажмите Enter..."; else msg_error "Пункт доступен только в режиме НОДЫ."; sleep 2; fi ;;
            8) if [ "$IS_NODE" == "yes" ]; then toggle_agent_monitoring; read -p "Нажмите Enter..."; fi ;;
            0) break ;;
        esac
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Нужен root."; exit 1; fi
if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then install_node_logic; exit 0; fi

check_integrity
if [ "$INSTALL_TYPE" == "НЕТ" ]; then
    clear
    echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║      Установка VPS Manager Bot    ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    echo -e "  Выберите режим установки:"
    echo "--------------------------------------------------------"
    echo "  1) АГЕНТ (Systemd - Secure)  [Рекомендуется]"
    echo "  2) АГЕНТ (Systemd - Root)    [Полный доступ]"
    echo "  3) АГЕНТ (Docker - Secure)   [Изоляция]"
    echo "  4) АГЕНТ (Docker - Root)     [Docker + Host]"
    echo -e "${C_GREEN}  7) НОДА (Клиент)${C_RESET}"
    echo "  0) Выход"
    echo "--------------------------------------------------------"
    read -p "$(echo -e "${C_BOLD}Ваш выбор: ${C_RESET}")" ch
    case $ch in
        1) uninstall_bot; install_systemd_logic "secure"; read -p "Нажмите Enter..." ;;
        2) uninstall_bot; install_systemd_logic "root"; read -p "Нажмите Enter..." ;;
        3) uninstall_bot; install_docker_logic "secure"; read -p "Нажмите Enter..." ;;
        4) uninstall_bot; install_docker_logic "root"; read -p "Нажмите Enter..." ;;
        7) uninstall_bot; install_node_logic; read -p "Нажмите Enter..." ;;
        0) exit 0 ;;
        *) msg_error "Неверный выбор."; sleep 2 ;;
    esac
    main_menu
else
    main_menu
fi
