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

# --- ISOLATION: Use Python 3.12 for venv only ---
PYTHON_FOR_VENV="/usr/bin/python3.12"
VENV_PATH="${BOT_INSTALL_PATH}/venv"
README_FILE="${BOT_INSTALL_PATH}/README.en.md"
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
        msg_error "Error during '$msg'. Code: $exit_code"
        msg_error "Details in log: /tmp/${SERVICE_NAME}_install.log"
    fi
    return $exit_code
}

# --- COMPATIBILITY FIXER (f-strings patch) ---
apply_python_compat_fixes() {
    msg_info "Applying Python < 3.12 compatibility patches..."
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
    python3 "$fix_script" > /dev/null 2>&1
}

get_file_hash() { [ -f "$1" ] && sha256sum "$1" | awk '{print $1}' || echo "none"; }
update_state_hash() { [ ! -f "$STATE_FILE" ] && touch "$STATE_FILE"; sed -i "/^$1=/d" "$STATE_FILE"; echo "$1=$2" >> "$STATE_FILE"; }
check_hash_match() { [ -f "$STATE_FILE" ] && [ "$(grep "^$1=" "$STATE_FILE" | cut -d'=' -f2)" == "$2" ] && return 0 || return 1; }

get_remote_version() {
    local v=$(curl -s "https://raw.githubusercontent.com/${GITHUB_REPO}/${GIT_BRANCH}/README.md" | grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+')
    [ -z "$v" ] && echo "Failed to get" || echo "$v"
}

save_current_version() {
    if [ -f "$README_FILE" ]; then
        local v=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
        if [ -n "$v" ] && [ -f "${ENV_FILE}" ]; then
            grep -q "^INSTALLED_VERSION=" "${ENV_FILE}" && sudo sed -i "s/^INSTALLED_VERSION=.*/INSTALLED_VERSION=$v/" "${ENV_FILE}" || echo "INSTALLED_VERSION=$v" | sudo tee -a "${ENV_FILE}" > /dev/null
        fi
    fi
}

get_local_version() { 
    local v=""; [ -f "${ENV_FILE}" ] && v=$(grep '^INSTALLED_VERSION=' "${ENV_FILE}" | cut -d'=' -f2)
    [ -z "$v" ] && [ -f "$README_FILE" ] && v=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
    [ -z "$v" ] && echo "Undefined" || echo "$v"
}

check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Bot is not installed."; return;
    fi
    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="NODE (Client)"; systemctl is-active --quiet ${NODE_SERVICE_NAME}.service && STATUS_MESSAGE="${C_GREEN}Active${C_RESET}" || STATUS_MESSAGE="${C_RED}Inactive${C_RESET}"; return
    fi
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="AGENT (Docker)"; docker ps | grep -q "tg-bot" && STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}" || STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"
    else
        INSTALL_TYPE="AGENT (Systemd)"; systemctl is-active --quiet ${SERVICE_NAME}.service && STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}" || STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"
    fi
}

setup_nginx_proxy() {
    echo -e "\n${C_CYAN}🔒 Setting up HTTPS (Nginx + Certbot)${C_RESET}"
    run_with_spinner "Installing Nginx and Certbot" sudo apt-get install -y -q nginx certbot python3-certbot-nginx psmisc
    sudo fuser -k 80/tcp 2>/dev/null; sudo systemctl stop nginx 2>/dev/null
    if sudo certbot certonly --standalone --non-interactive --agree-tos --email "${HTTPS_EMAIL}" -d "${HTTPS_DOMAIN}"; then
        msg_success "Certificate obtained!"
    else
        msg_error "Error obtaining certificate."; sudo systemctl start nginx; return 1
    fi
    NGINX_CONF="/etc/nginx/sites-available/${HTTPS_DOMAIN}"
    sudo bash -c "cat > ${NGINX_CONF}" <<EOF
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
    sudo ln -sf "${NGINX_CONF}" "/etc/nginx/sites-enabled/${HTTPS_DOMAIN}"
    sudo rm -f /etc/nginx/sites-enabled/default
    if sudo nginx -t; then sudo systemctl restart nginx; msg_success "HTTPS setup successfully!"; else msg_error "Nginx config error."; fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Preparing system (Python 3.12)..."
    run_with_spinner "Apt update" sudo apt-get update -y -q
    # Installing Python 3.12 without changing system default python3
    run_with_spinner "Installing Python 3.12" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3.12 python3.12-venv python3.12-dev git curl wget sudo python3-pip python3-yaml
}

setup_repo_and_dirs() {
    local owner_user=${1:-root}; cd /
    [ -f "${ENV_FILE}" ] && cp "${ENV_FILE}" /tmp/tgbot_env.bak; [ -f "${STATE_FILE}" ] && cp "${STATE_FILE}" /tmp/tgbot_state.bak
    [ -d "${VENV_PATH}" ] && sudo mv "${VENV_PATH}" /tmp/tgbot_venv.bak
    [ -d "${BOT_INSTALL_PATH}" ] && sudo rm -rf "${BOT_INSTALL_PATH}"
    sudo mkdir -p "${BOT_INSTALL_PATH}"
    run_with_spinner "Cloning repository" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}"
    [ -f "/tmp/tgbot_env.bak" ] && sudo mv /tmp/tgbot_env.bak "${ENV_FILE}"; [ -f "/tmp/tgbot_state.bak" ] && sudo mv /tmp/tgbot_state.bak "${STATE_FILE}"
    [ -d "/tmp/tgbot_venv.bak" ] && sudo mv /tmp/tgbot_venv.bak "${VENV_PATH}"
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

load_cached_env() {
    local env_file="${ENV_FILE}"; [ ! -f "$env_file" ] && [ -f "/tmp/tgbot_env.bak" ] && env_file="/tmp/tgbot_env.bak"
    if [ -f "$env_file" ]; then
        echo -e "${C_YELLOW}⚠️  Found saved configuration.${C_RESET}"
        read -p "$(echo -e "${C_CYAN}❓ Restore settings? (y/n) [y]: ${C_RESET}")" RESTORE_CHOICE; RESTORE_CHOICE=${RESTORE_CHOICE:-y}
        if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]]; then
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
    msg_info "🧹 Final cleanup..."
    sudo rm -f "${BOT_INSTALL_PATH}/fix_compat.py"
    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then sudo rm -rf "$BOT_INSTALL_PATH/assets"; fi
    sudo rm -f "$BOT_INSTALL_PATH/custom_module"* "$BOT_INSTALL_PATH/.gitignore" "$BOT_INSTALL_PATH/LICENSE" "$BOT_INSTALL_PATH/aerich.ini" "$BOT_INSTALL_PATH/README"* "$BOT_INSTALL_PATH/ARCHITECTURE"* "$BOT_INSTALL_PATH/CHANGELOG"* "$BOT_INSTALL_PATH/.env.example" "$BOT_INSTALL_PATH/migrate.py" "$BOT_INSTALL_PATH/requirements.txt"
    DEPLOY_MODE_VAL=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' 2>/dev/null)
    [ "$DEPLOY_MODE_VAL" != "docker" ] && sudo rm -f "$BOT_INSTALL_PATH/Dockerfile" "$BOT_INSTALL_PATH/docker-compose.yml"
    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    msg_success "Cleanup completed."
}

install_extras() {
    if ! command -v fail2ban-client &>/dev/null; then
        msg_question "Fail2Ban not found. Install? (y/n): " I
        [[ "$I" =~ ^[Yy]$ ]] && run_with_spinner "Installing Fail2ban" sudo apt-get install -y -q fail2ban
    fi
    if ! command -v iperf3 &>/dev/null; then
        msg_question "iperf3 not found. Install? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then
            # iperf3 automation
            echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections
            run_with_spinner "Installing iperf3" sudo apt-get install -y -q iperf3
        fi
    fi
}

ask_env_details() {
    msg_info "Entering .env data..."
    msg_question "Bot Token: " T; msg_question "Admin ID: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Internal Web Port [8080]: " P; WEB_PORT=${P:-8080}; msg_question "Sentry DSN (opt): " SENTRY_DSN
    msg_question "Enable Web-UI? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then ENABLE_WEB="false"; SETUP_HTTPS="false"; else
        ENABLE_WEB="true"; GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        msg_question "Setup HTTPS (Nginx Proxy)? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"; msg_question "Domain: " HTTPS_DOMAIN; msg_question "Email: " HTTPS_EMAIL; msg_question "External Port [8443]: " HP
            HTTPS_PORT=${HP:-8443}
        else SETUP_HTTPS="false"; fi
    fi
    export T A U N WEB_PORT ENABLE_WEB SETUP_HTTPS HTTPS_DOMAIN HTTPS_EMAIL HTTPS_PORT GEN_PASS SENTRY_DSN
}

write_env_file() {
    local debug="true"; [ "$GIT_BRANCH" == "main" ] && debug="false"
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
TG_BOT_TOKEN="${T}"
TG_ADMIN_ID="${A}"
TG_ADMIN_USERNAME="${U}"
TG_BOT_NAME="${N}"
WEB_SERVER_HOST="0.0.0.0"
WEB_SERVER_PORT="${WEB_PORT}"
INSTALL_MODE="$2"
DEPLOY_MODE="$1"
TG_BOT_CONTAINER_NAME="$3"
ENABLE_WEB_UI="${ENABLE_WEB}"
TG_WEB_INITIAL_PASSWORD="${GEN_PASS}"
DEBUG="${debug}"
SENTRY_DSN="${SENTRY_DSN}"
EOF
    sudo chmod 600 "${ENV_FILE}"
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
# Docker isolated: using 3.12
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
    ports: ["${WEB_PORT}:${WEB_PORT}"]
    environment: [INSTALL_MODE=secure, DEPLOY_MODE=docker, TG_BOT_CONTAINER_NAME=tg-bot-secure]
    volumes: ["./config:/opt/tg-bot/config", "./logs/bot:/opt/tg-bot/logs/bot", "/var/run/docker.sock:/var/run/docker.sock:ro", "/proc/uptime:/proc_host/uptime:ro", "/proc/stat:/proc_host/stat:ro", "/proc/meminfo:/proc_host/meminfo:ro", "/proc/net/dev:/proc_host/net/dev:ro"]
    cap_drop: [ALL]
    cap_add: [NET_RAW]
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
  watchdog:
    <<: *bot-base
    container_name: tg-watchdog
    command: python watchdog.py
    user: "root"
    volumes: ["./config:/opt/tg-bot/config", "./logs/watchdog:/opt/tg-bot/logs/watchdog", "/var/run/docker.sock:/var/run/docker.sock:ro"]
EOF
}

create_and_start_service() {
    local u="root"; [ "$3" == "secure" ] && [ "$1" == "$SERVICE_NAME" ] && u=${SERVICE_USER}
    sudo tee "/etc/systemd/system/$1.service" > /dev/null <<EOF
[Unit]
Description=$4
After=network.target
[Service]
Type=simple
User=$u
WorkingDirectory=${BOT_INSTALL_PATH}
EnvironmentFile=${BOT_INSTALL_PATH}/.env
ExecStart=${VENV_PATH}/bin/python $2
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload; sudo systemctl enable $1 &>/dev/null; sudo systemctl restart $1
}

run_db_migrations() {
    msg_info "Database check..."
    cd "${BOT_INSTALL_PATH}"
    [ -f "${ENV_FILE}" ] && set -a && source "${ENV_FILE}" && set +a
    local cmd=""; [ -n "$1" ] && cmd="sudo -E -u ${SERVICE_USER}"
    local h=$(get_file_hash "core/models.py")
    if check_hash_match "DB_HASH" "$h" && [ -f "config/nodes.db" ]; then msg_success "DB is up to date."; return; fi
    sudo rm -f aerich.ini
    $cmd ${VENV_PATH}/bin/aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    if [ -f "config/nodes.db" ]; then $cmd ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1
    else $cmd ${VENV_PATH}/bin/aerich init-db >/dev/null 2>&1 || $cmd ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1; fi
    update_state_hash "DB_HASH" "$h"
    [ -f "migrate.py" ] && $cmd ${VENV_PATH}/bin/python migrate.py
}

install_systemd_logic() {
    local mode=$1; common_install_steps; install_extras; local exec=""
    if [ "$mode" == "secure" ]; then
        ! id "${SERVICE_USER}" &>/dev/null && sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}
        setup_repo_and_dirs "${SERVICE_USER}"; exec="sudo -u ${SERVICE_USER}"
        [ ! -d "${VENV_PATH}" ] && run_with_spinner "Creating venv (Python 3.12)" sudo -u ${SERVICE_USER} ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
    else
        setup_repo_and_dirs "root"
        [ ! -d "${VENV_PATH}" ] && run_with_spinner "Creating venv (Python 3.12)" ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
    fi
    
    apply_python_compat_fixes
    
    local rh=$(get_file_hash "requirements.txt")
    if ! check_hash_match "REQ_HASH" "$rh"; then
        run_with_spinner "Dependencies" $exec "${VENV_PATH}/bin/pip" install -r requirements.txt tomlkit; update_state_hash "REQ_HASH" "$rh"
    fi
    load_cached_env; ask_env_details; write_env_file "systemd" "$mode" ""
    run_db_migrations "$exec"; create_and_start_service "${SERVICE_NAME}" "bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "watchdog.py" "root" "Watchdog"
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
[ -f .env ] && set -a && source .env && set +a
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot; save_current_version; cleanup_agent_files; cleanup_files
    local ip=$(curl -s ipinfo.io/ip); msg_success "Done! http://${ip}:${WEB_PORT}"; [ "$ENABLE_WEB" == "true" ] && msg_info "Password: ${GEN_PASS}"
    [ "$SETUP_HTTPS" == "true" ] && setup_nginx_proxy
}

install_docker_logic() {
    local mode=$1; common_install_steps; install_extras; setup_repo_and_dirs root; ! command -v docker &>/dev/null && (curl -sSL https://get.docker.com | sudo sh)
    
    apply_python_compat_fixes
    
    load_cached_env; ask_env_details; create_dockerfile; create_docker_compose_yml
    local cn="tg-bot-${mode}"; write_env_file "docker" "$mode" "$cn"
    local dc="docker compose"; ! sudo $dc version &>/dev/null && dc="docker-compose"
    run_with_spinner "Docker Build" sudo $dc build --no-cache; run_with_spinner "Docker Up" sudo $dc --profile "$1" up -d --remove-orphans
    sudo $dc --profile "$mode" exec -T $cn aerich upgrade >/dev/null 2>&1; sudo $dc --profile "$mode" exec -T $cn python migrate.py >/dev/null 2>&1
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot
    save_current_version; cleanup_agent_files; cleanup_files; msg_success "Docker is running!"; if [ "${ENABLE_WEB}" == "true" ]; then echo -e "🔑 PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Installing NODE ===${C_RESET}"
    [ -n "$AUTO_AGENT_URL" ] && AGENT_URL="$AUTO_AGENT_URL"; [ -n "$AUTO_NODE_TOKEN" ] && NODE_TOKEN="$AUTO_NODE_TOKEN"
    common_install_steps
    if ! command -v iperf3 &>/dev/null; then echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections; run_with_spinner "iperf3" sudo apt-get install -y -q iperf3; fi
    setup_repo_and_dirs root; local h=$(echo "psutil requests" | sha256sum | awk '{print $1}')
    [ ! -d "${VENV_PATH}" ] && run_with_spinner "Venv 3.12" ${PYTHON_FOR_VENV} -m venv "${VENV_PATH}"
    
    apply_python_compat_fixes
    
    if ! check_hash_match "NODE_REQ_HASH" "$h"; then run_with_spinner "Deps" "${VENV_PATH}/bin/pip" install psutil requests; update_state_hash "NODE_REQ_HASH" "$h"; fi
    load_cached_env; msg_question "Agent URL: " AGENT_URL; msg_question "Token: " NODE_TOKEN
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
EOF
    sudo chmod 600 "${ENV_FILE}"; create_and_start_service "${NODE_SERVICE_NAME}" "node/node.py" "root" "Node Client"
    save_current_version; cleanup_node_files; msg_success "Node installed!"
}

uninstall_bot() {
    msg_info "Uninstalling..."; sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &>/dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service; sudo systemctl daemon-reload
    [ -f "${DOCKER_COMPOSE_FILE}" ] && (cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &>/dev/null)
    sudo rm -rf "${BOT_INSTALL_PATH}" /usr/local/bin/tgcp-bot; id "${SERVICE_USER}" &>/dev/null && sudo userdel -r "${SERVICE_USER}"
    msg_success "Uninstalled."
}

update_bot() {
    msg_info "Updating..."; [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}" && (install_node_logic; return)
    local exec=""; [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}" && exec="sudo -u ${SERVICE_USER}"
    cd "${BOT_INSTALL_PATH}"; run_with_spinner "Fetch" $exec git fetch origin; run_with_spinner "Reset" $exec git reset --hard "origin/${GIT_BRANCH}"
    if [ -f "${ENV_FILE}" ] && grep -q "DEPLOY_MODE=docker" "${ENV_FILE}"; then
        local dc="docker compose"; ! sudo $dc version &>/dev/null && dc="docker-compose"
        apply_python_compat_fixes
        run_with_spinner "Docker Build" sudo $dc build --no-cache; run_with_spinner "Docker Up" sudo $dc up -d --build
    else
        apply_python_compat_fixes
        local rh=$(get_file_hash "requirements.txt")
        if ! check_hash_match "REQ_HASH" "$rh"; then run_with_spinner "Pip update" $exec "${VENV_PATH}/bin/pip" install -r requirements.txt --upgrade; update_state_hash "REQ_HASH" "$rh"; fi
        run_db_migrations "$exec"; sudo systemctl restart ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME}
    fi
    save_current_version; cleanup_agent_files; cleanup_files; msg_success "Updated."
}

# --- MENU ---
[ "$(id -u)" -ne 0 ] && (msg_error "Root required."; exit 1)
if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then install_node_logic; exit 0; fi

while true; do
    clear; echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║     VPS Manager Telegram Bot      ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    check_integrity; echo -e "  Type: $INSTALL_TYPE | Status: $STATUS_MESSAGE | Version: $(get_local_version)"
    echo "--------------------------------------------------------"
    if [ "$INSTALL_TYPE" == "NONE" ]; then
        echo -e "  1) AGENT (Systemd - Secure)  [Recommended]\n  2) AGENT (Systemd - Root)    [Full Access]\n  3) AGENT (Docker - Secure)   [Isolation]\n  4) AGENT (Docker - Root)     [Docker + Host]\n  8) NODE (Client)\n  0) Exit"
        read -p "Your choice: " ch
        case $ch in
            1) uninstall_bot; install_systemd_logic "secure" ;; 2) uninstall_bot; install_systemd_logic "root" ;; 3) uninstall_bot; install_docker_logic "secure" ;;
            4) uninstall_bot; install_docker_logic "root" ;; 8) uninstall_bot; install_node_logic ;; 0) break ;;
        esac
    else
        echo -e "  1) Update Bot\n  2) Uninstall Bot\n  0) Exit"
        read -p "Your choice: " ch
        case $ch in 1) update_bot ;; 2) uninstall_bot ;; 0) break ;; esac
    fi
    [ "$ch" != "0" ] && read -p "Press Enter..."
done