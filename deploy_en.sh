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
PYTHON_BIN="/usr/bin/python3"
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

# --- HASH HELPERS ---
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
    # Remove old entry and append new one
    sed -i "/^$key=/d" "$STATE_FILE"
    echo "$key=$hash" >> "$STATE_FILE"
}

check_hash_match() {
    local key=$1
    local current_hash=$2
    if [ -f "$STATE_FILE" ]; then
        local stored_hash=$(grep "^$key=" "$STATE_FILE" | cut -d'=' -f2)
        if [ "$stored_hash" == "$current_hash" ]; then
            return 0 # True (match)
        fi
    fi
    return 1 # False (no match or no record)
}

# --- VERSION HANDLING ---

# 1. Get Remote Version
get_remote_version() {
    local remote_ver=$(curl -s "https://raw.githubusercontent.com/${GITHUB_REPO}/${GIT_BRANCH}/README.md" | grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+')
    if [ -z "$remote_ver" ]; then echo "Failed to get"; else echo "$remote_ver"; fi
}

# 2. Save Current Version to .env (before cleanup)
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

# 3. Read Local Version
get_local_version() { 
    local ver=""
    if [ -f "${ENV_FILE}" ]; then
        ver=$(grep '^INSTALLED_VERSION=' "${ENV_FILE}" | cut -d'=' -f2)
    fi
    if [ -z "$ver" ] && [ -f "$README_FILE" ]; then
        ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
    fi
    if [ -z "$ver" ]; then echo "Undefined"; else echo "$ver"; fi
}

INSTALL_TYPE="NONE"; STATUS_MESSAGE="Check was not performed."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Bot is not installed."; return;
    fi
    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="NODE (Client)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Active${C_RESET}"; else STATUS_MESSAGE="${C_RED}Inactive${C_RESET}"; fi
        return
    fi
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="AGENT (Docker)"
        if command -v docker &> /dev/null && docker ps | grep -q "tg-bot"; then STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"; fi
    else
        INSTALL_TYPE="AGENT (Systemd)"
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"; fi
    fi
}

# --- HTTPS Setup ---
setup_nginx_proxy() {
    echo -e "\n${C_CYAN}🔒 Setting up HTTPS (Nginx + Certbot)${C_RESET}"
    run_with_spinner "Installing Nginx and Certbot" sudo apt-get install -y -q nginx certbot python3-certbot-nginx psmisc

    if command -v lsof &> /dev/null && lsof -Pi :80 -sTCP:LISTEN -t >/dev/null ; then
        msg_warning "Port 80 is busy. Trying to free it..."
        sudo fuser -k 80/tcp 2>/dev/null
        sudo systemctl stop nginx 2>/dev/null
    elif command -v fuser &> /dev/null && sudo fuser 80/tcp >/dev/null; then
         msg_warning "Port 80 is busy. Trying to free it..."
         sudo fuser -k 80/tcp
         sudo systemctl stop nginx 2>/dev/null
    fi

    msg_info "Obtaining SSL certificate for ${HTTPS_DOMAIN}..."
    if sudo certbot certonly --standalone --non-interactive --agree-tos --email "${HTTPS_EMAIL}" -d "${HTTPS_DOMAIN}"; then
        msg_success "Certificate obtained!"
    else
        msg_error "Error obtaining certificate. Check DNS A-record and port 80."
        sudo systemctl start nginx
        return 1
    fi

    msg_info "Creating Nginx configuration..."
    NGINX_CONF="/etc/nginx/sites-available/${HTTPS_DOMAIN}"
    NGINX_LINK="/etc/nginx/sites-enabled/${HTTPS_DOMAIN}"
    if [ -f "/etc/nginx/sites-enabled/default" ]; then sudo rm -f "/etc/nginx/sites-enabled/default"; fi

    sudo bash -c "cat > ${NGINX_CONF}" <<EOF
server {
    listen ${HTTPS_PORT} ssl;
    server_name ${HTTPS_DOMAIN};
    ssl_certificate /etc/letsencrypt/live/${HTTPS_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${HTTPS_DOMAIN}/privkey.pem;
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
    }
}
EOF
    sudo ln -sf "${NGINX_CONF}" "${NGINX_LINK}"
    if sudo nginx -t; then
        sudo systemctl restart nginx
        if command -v ufw &> /dev/null; then sudo ufw allow ${HTTPS_PORT}/tcp >/dev/null; fi
        echo ""; msg_success "HTTPS setup successfully!"
        echo -e "Web panel available: https://${HTTPS_DOMAIN}:${HTTPS_PORT}/"
    else
        msg_error "Nginx config error."
    fi
}

# --- INSTALLATION FUNCTIONS ---
common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    # Check: if base packages exist, skip apt update for speed
    if command -v python3 >/dev/null && command -v git >/dev/null && command -v pip3 >/dev/null; then
        msg_success "Base packages (Python/Git) are already installed. Skipping apt update."
    else
        msg_info "1. Updating system..."
        run_with_spinner "Apt update" sudo apt-get update -y -q
        run_with_spinner "Installing system packages" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3 python3-pip python3-venv git curl wget sudo python3-yaml
    fi
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    cd /
    msg_info "Preparing files (Branch: ${GIT_BRANCH})..."
    
    # Save important files before cleanup
    if [ -f "${ENV_FILE}" ]; then cp "${ENV_FILE}" /tmp/tgbot_env.bak; fi
    if [ -f "${STATE_FILE}" ]; then cp "${STATE_FILE}" /tmp/tgbot_state.bak; fi
    # IMPORTANT: Save venv to avoid reinstalling dependencies on re-run
    if [ -d "${VENV_PATH}" ]; then 
        msg_info "Saving venv..."
        sudo mv "${VENV_PATH}" /tmp/tgbot_venv.bak
    fi

    if [ -d "${BOT_INSTALL_PATH}" ]; then run_with_spinner "Removing old files" sudo rm -rf "${BOT_INSTALL_PATH}"; fi
    sudo mkdir -p ${BOT_INSTALL_PATH}
    run_with_spinner "Cloning repository" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    
    # Restore files
    if [ -f "/tmp/tgbot_env.bak" ]; then sudo mv /tmp/tgbot_env.bak "${ENV_FILE}"; fi
    if [ -f "/tmp/tgbot_state.bak" ]; then sudo mv /tmp/tgbot_state.bak "${STATE_FILE}"; fi
    # Restore venv
    if [ -d "/tmp/tgbot_venv.bak" ]; then 
        sudo mv /tmp/tgbot_venv.bak "${VENV_PATH}"
        msg_success "Venv restored."
    fi

    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

# --- Load variables from .env ---
load_cached_env() {
    local env_file="${ENV_FILE}"

    if [ ! -f "$env_file" ] && [ -f "/tmp/tgbot_env.bak" ]; then
        env_file="/tmp/tgbot_env.bak"
    fi

    if [ -f "$env_file" ]; then
        echo -e "${C_YELLOW}⚠️  Found saved configuration from previous installation.${C_RESET}"
        read -p "$(echo -e "${C_CYAN}❓ Restore settings (Token, ID, Port, Sentry)? (y/n) [y]: ${C_RESET}")" RESTORE_CHOICE
        RESTORE_CHOICE=${RESTORE_CHOICE:-y}

        if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]]; then
            msg_info "Loading saved data..."

            get_env_val() {
                grep "^$1=" "$env_file" | cut -d'=' -f2- | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//"
            }

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
            msg_info "Restoration skipped. Enter data again."
            # RESET VARIABLES to ensure prompt
            T=""; A=""; U=""; N=""; P=""; SENTRY_DSN=""
            ENABLE_WEB=""; SETUP_HTTPS=""; HTTPS_DOMAIN=""; HTTPS_EMAIL=""; HTTPS_PORT=""
            AGENT_URL=""; NODE_TOKEN=""
        fi
    fi
}

cleanup_node_files() {
    cd ${BOT_INSTALL_PATH}
    # Remove everything unnecessary for Node mode
    sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git .github config/users.json config/alerts_config.json deploy.sh deploy_en.sh requirements.txt LICENSE CHANGELOG* .gitignore aerich.ini
    sudo rm -f .env.example migrate.py manage.py ARCHITECTURE* custom_module*
    sudo rm -f README*
}

cleanup_agent_files() {
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf node
}

# --- CLEANUP TRASH AFTER INSTALL ---
cleanup_files() {
    msg_info "🧹 Starting final cleanup..."

    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then sudo rm -rf "$BOT_INSTALL_PATH/assets"; fi

    sudo rm -f "$BOT_INSTALL_PATH/custom_module.md" "$BOT_INSTALL_PATH/custom_module_en.md"
    sudo rm -f "$BOT_INSTALL_PATH/.gitignore" "$BOT_INSTALL_PATH/LICENSE"
    sudo rm -f "$BOT_INSTALL_PATH/aerich.ini"
    sudo rm -f "$BOT_INSTALL_PATH/README.md" "$BOT_INSTALL_PATH/README.en.md"
    sudo rm -f "$BOT_INSTALL_PATH/ARCHITECTURE.md" "$BOT_INSTALL_PATH/ARCHITECTURE.en.md"
    sudo rm -f "$BOT_INSTALL_PATH/CHANGELOG.md" "$BOT_INSTALL_PATH/CHANGELOG.en.md"
    sudo rm -f "$BOT_INSTALL_PATH/.env.example"
    sudo rm -f "$BOT_INSTALL_PATH/migrate.py"
    sudo rm -f "$BOT_INSTALL_PATH/requirements.txt"

    if [ -f "${ENV_FILE}" ]; then
        DEPLOY_MODE_VAL=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ "$DEPLOY_MODE_VAL" != "docker" ]; then
             sudo rm -f "$BOT_INSTALL_PATH/Dockerfile"
             sudo rm -f "$BOT_INSTALL_PATH/docker-compose.yml"
        fi
    fi

    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    msg_success "Cleanup completed."
}

install_extras() {
    # Check fail2ban
    if command -v fail2ban-client &> /dev/null; then
        msg_success "Fail2Ban is already installed."
    else
        msg_question "Fail2Ban not found. Install? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Installing Fail2ban" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" fail2ban; fi
    fi
    
    # Check iperf3
    if command -v iperf3 &> /dev/null; then
        msg_success "iperf3 is already installed."
    else
        msg_question "iperf3 not found. Install? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then 
            echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections
            run_with_spinner "Installing iperf3" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" iperf3
        fi
    fi
}

ask_env_details() {
    msg_info "Entering .env data..."
    msg_question "Bot Token: " T; msg_question "Admin ID: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Internal Web Port [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN

    msg_question "Enable Web-UI (Dashboard)? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then
        ENABLE_WEB="false"
        SETUP_HTTPS="false"
    else
        ENABLE_WEB="true"
        GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        msg_question "Setup HTTPS (Nginx Proxy)? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"
            msg_question "Domain (e.g. bot.site.com): " HTTPS_DOMAIN
            msg_question "Email for SSL: " HTTPS_EMAIL
            msg_question "External HTTPS port [8443]: " HP
            if [ -z "$HP" ]; then HTTPS_PORT="8443"; else HTTPS_PORT="$HP"; fi
        else
            SETUP_HTTPS="false"
        fi
    fi
    export T A U N WEB_PORT ENABLE_WEB SETUP_HTTPS HTTPS_DOMAIN HTTPS_EMAIL HTTPS_PORT GEN_PASS SENTRY_DSN
}

write_env_file() {
    local dm=$1; local im=$2; local cn=$3

    local debug_setting="true"
    if [ "$GIT_BRANCH" == "main" ]; then
        debug_setting="false"
    fi

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
    if ! command -v docker &> /dev/null; then curl -sSL https://get.docker.com -o /tmp/get-docker.sh; run_with_spinner "Installing Docker" sudo sh /tmp/get-docker.sh; fi
    if command -v docker-compose &> /dev/null; then sudo rm -f $(which docker-compose); fi
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
FROM python:3.10-slim-bookworm
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

# --- Database Migration (Aerich) & JSON ---
run_db_migrations() {
    local exec_user=$1 # "sudo -u tgbot" or empty for root

    msg_info "Checking and migrating database..."
    cd "${BOT_INSTALL_PATH}" || return 1

    # Export vars
    if [ -f "${ENV_FILE}" ]; then
        set -a
        source "${ENV_FILE}"
        set +a
    fi

    local cmd_prefix=""
    if [ -n "$exec_user" ]; then
        cmd_prefix="sudo -E -u ${SERVICE_USER}"
    fi

    # --- CHECK FOR SKIP MIGRATION ---
    local db_models_hash=$(get_file_hash "${BOT_INSTALL_PATH}/core/models.py")
    local db_exists=false
    if [ -f "${BOT_INSTALL_PATH}/config/nodes.db" ]; then db_exists=true; fi

    if $db_exists && check_hash_match "DB_HASH" "$db_models_hash"; then
        msg_success "DB structure unchanged. Skipping migrations."
        return
    fi
    # ------------------------------------

    # Generate aerich.ini
    if [ -f "${BOT_INSTALL_PATH}/aerich.ini" ]; then rm -f "${BOT_INSTALL_PATH}/aerich.ini"; fi
    $cmd_prefix ${VENV_PATH}/bin/aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1

    # Run migrations
    if $db_exists; then
        if [ -d "${BOT_INSTALL_PATH}/migrations" ]; then
            msg_info "Applying database updates..."
            $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1
        else
            msg_info "Database found, migrations folder missing (skipping)."
        fi
    else
        # No DB
        if [ ! -d "${BOT_INSTALL_PATH}/migrations" ]; then
            msg_info "Creating database..."
            if ! $cmd_prefix ${VENV_PATH}/bin/aerich init-db >/dev/null 2>&1; then
                 msg_warning "Error creating DB (init-db)."
            fi
        else
            msg_info "Applying migrations (creating DB)..."
            $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1
        fi
    fi

    # Update hash after success
    update_state_hash "DB_HASH" "$db_models_hash"

    # 6. Secure Migration JSON -> Encrypted
    msg_info "Secure configuration migration..."
    if [ -f "${BOT_INSTALL_PATH}/migrate.py" ]; then
        $cmd_prefix ${VENV_PATH}/bin/python "${BOT_INSTALL_PATH}/migrate.py"
    else
        msg_warning "Script migrate.py not found, skipping JSON encryption."
    fi
}

install_systemd_logic() {
    local mode=$1
    common_install_steps
    install_extras

    local exec_cmd=""
    local req_hash=$(get_file_hash "${BOT_INSTALL_PATH}/requirements.txt")
    local install_pip=true

    # Check if we need to install deps
    if [ -d "${VENV_PATH}" ] && [ -f "${VENV_PATH}/bin/python" ]; then
        if check_hash_match "REQ_HASH" "$req_hash"; then
            install_pip=false
            msg_success "Dependencies (Venv) are up to date. Skipping installation."
        fi
    fi

    if [ "$mode" == "secure" ]; then
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}; fi
        setup_repo_and_dirs "${SERVICE_USER}"
        
        # Create venv if not exists
        if [ ! -d "${VENV_PATH}" ]; then sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
        
        if $install_pip; then
            run_with_spinner "Installing dependencies" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
            run_with_spinner "Installing extra packages (tomlkit)" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install tomlkit
            update_state_hash "REQ_HASH" "$req_hash"
        fi
        exec_cmd="sudo -u ${SERVICE_USER}"
    else
        setup_repo_and_dirs "root"
        
        if [ ! -d "${VENV_PATH}" ]; then ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi

        if $install_pip; then
            run_with_spinner "Installing dependencies" "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
            run_with_spinner "Installing extra packages (tomlkit)" "${VENV_PATH}/bin/pip" install tomlkit
            update_state_hash "REQ_HASH" "$req_hash"
        fi
        exec_cmd=""
    fi

    load_cached_env
    ask_env_details
    write_env_file "systemd" "$mode" ""

    # Run migrations (with hash checks)
    run_db_migrations "$exec_cmd"

    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog"

    # --- CLI UTILS ---
    msg_info "Creating 'tgcp-bot' command..."
    if [ ! -f "${BOT_INSTALL_PATH}/manage.py" ]; then
       true
    else
       chmod +x "${BOT_INSTALL_PATH}/manage.py"
    fi
    
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    if [ -f "/usr/local/bin/tgcp-bot" ] && [ -x "/usr/local/bin/tgcp-bot" ]; then
        msg_success "Command 'tgcp-bot' created successfully!"
    else
        msg_error "Failed to create 'tgcp-bot' command."
    fi

    # === FINAL CLEANUP ===
    save_current_version
    cleanup_agent_files
    cleanup_files
    # =========================

    local ip=$(curl -s ipinfo.io/ip)
    echo ""; msg_success "Installation completed! Agent available: http://${ip}:${WEB_PORT}"
    echo -e "💡 Use command ${C_BOLD}tgcp-bot${C_RESET} to manage (reset password, etc)."

    if [ "${ENABLE_WEB}" == "true" ]; then
        echo -e "${C_CYAN}🔑 YOUR WEB PANEL PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"
        echo -e "Save it! You need it to login."
    fi

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
    local dc_cmd=""
    if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; elif command -v docker-compose &>/dev/null; then dc_cmd="docker-compose"; else msg_error "Docker Compose not found."; return 1; fi
    run_with_spinner "Building Docker" sudo $dc_cmd build
    run_with_spinner "Starting Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans

    # Attempt migrations inside container
    msg_info "Attempting to setup DB in container..."
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init-db >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich upgrade >/dev/null 2>&1

    # Migrate JSON
    msg_info "Migrating JSON files in container..."
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python migrate.py >/dev/null 2>&1
    
    # --- CLI UTILS ---
    msg_info "Creating 'tgcp-bot' command (Docker Wrapper)..."
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    if [ -f "/usr/local/bin/tgcp-bot" ] && [ -x "/usr/local/bin/tgcp-bot" ]; then
        msg_success "Command 'tgcp-bot' (Docker) created successfully!"
    else
        msg_error "Failed to create 'tgcp-bot' command."
    fi

    # === FINAL CLEANUP ===
    save_current_version
    cleanup_agent_files
    cleanup_files
    # =========================

    msg_success "Docker installation completed!"
    echo -e "💡 Use command ${C_BOLD}tgcp-bot${C_RESET} to manage."

    if [ "${ENABLE_WEB}" == "true" ]; then
        echo -e "${C_CYAN}🔑 YOUR WEB PANEL PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"
        echo -e "Save it! You need it to login."
    fi

    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy; fi
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Installing NODE (Client) ===${C_RESET}"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi

    common_install_steps
    # install_extras NOT called here to avoid fail2ban check
    
    # Check iperf3 only
    if command -v iperf3 &> /dev/null; then
        msg_success "iperf3 is already installed."
    else
        msg_question "iperf3 not found. Install? (y/n): " I
        if [[ "$I" =~ ^[Yy]$ ]]; then 
            echo "iperf3 iperf3/start_daemon boolean true" | sudo debconf-set-selections
            run_with_spinner "Installing iperf3" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" iperf3
        fi
    fi

    setup_repo_and_dirs "root"
    
    # Calc node deps hash
    local node_deps_hash=$(echo "psutil requests" | sha256sum | awk '{print $1}')
    local install_pip=true

    msg_info "Setting up venv..."
    if [ ! -d "${VENV_PATH}" ]; then 
        run_with_spinner "Creating venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"
    else
        # If venv exists, check hash
        if check_hash_match "NODE_REQ_HASH" "$node_deps_hash"; then
            install_pip=false
            msg_success "Dependencies (Venv) are up to date. Skipping installation."
        fi
    fi

    if $install_pip; then
        run_with_spinner "Installing dependencies" "${VENV_PATH}/bin/pip" install psutil requests
        update_state_hash "NODE_REQ_HASH" "$node_deps_hash"
    fi

    load_cached_env
    echo ""; msg_info "Connection:"
    msg_question "Agent URL (http://IP:8080): " AGENT_URL
    msg_question "Token: " NODE_TOKEN

    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
EOF
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
    run_with_spinner "Starting Node" sudo systemctl restart ${NODE_SERVICE_NAME}
    
    # === FINAL CLEANUP ===
    save_current_version
    cleanup_node_files
    # =========================
    
    msg_success "Node installed!"
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Uninstalling ===${C_RESET}"
    cd /
    sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &> /dev/null; fi
    sudo rm -rf "${BOT_INSTALL_PATH}"
    # Remove CLI util
    sudo rm -f /usr/local/bin/tgcp-bot
    
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Uninstalled."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Updating ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then msg_info "Updating Node..."; install_node_logic; return; fi
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git not found. Reinstall."; return 1; fi

    local exec_cmd=""
    if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi

    cd "${BOT_INSTALL_PATH}"
    if ! run_with_spinner "Git fetch" $exec_cmd git fetch origin; then return 1; fi
    if ! run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"; then return 1; fi
    
    if [ -f "${ENV_FILE}" ] && grep -q "DEPLOY_MODE=docker" "${ENV_FILE}"; then
        if [ -f "docker-compose.yml" ]; then
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            if ! run_with_spinner "Docker Up" sudo $dc_cmd up -d --build; then msg_error "Docker Error."; return 1; fi
            
            local mode=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
            local cn="tg-bot-${mode}"
            sudo $dc_cmd --profile "${mode}" exec -T ${cn} aerich upgrade >/dev/null 2>&1
            sudo $dc_cmd --profile "${mode}" exec -T ${cn} python migrate.py >/dev/null 2>&1
            
            # Update CLI wrapper
            msg_info "Updating CLI 'tgcp-bot'..."
            sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
            sudo chmod +x /usr/local/bin/tgcp-bot
            
            if [ -f "/usr/local/bin/tgcp-bot" ] && [ -x "/usr/local/bin/tgcp-bot" ]; then
                msg_success "CLI 'tgcp-bot' updated."
            fi

        else msg_error "No docker-compose.yml"; return 1; fi
    else
        # Update PIP only if requirements.txt changed
        local req_hash=$(get_file_hash "${BOT_INSTALL_PATH}/requirements.txt")
        if check_hash_match "REQ_HASH" "$req_hash"; then
             msg_success "Dependencies have not changed. Skipping PIP update."
        else
             run_with_spinner "Updating pip" $exec_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
             run_with_spinner "Updating tomlkit" $exec_cmd "${VENV_PATH}/bin/pip" install tomlkit
             update_state_hash "REQ_HASH" "$req_hash"
        fi

        run_db_migrations "$exec_cmd"
        
        msg_info "Updating CLI 'tgcp-bot'..."
        sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
        sudo chmod +x /usr/local/bin/tgcp-bot
        
        if [ -f "/usr/local/bin/tgcp-bot" ] && [ -x "/usr/local/bin/tgcp-bot" ]; then
            msg_success "CLI 'tgcp-bot' updated."
        fi

        if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then sudo systemctl restart ${SERVICE_NAME}; fi
        if systemctl list-unit-files | grep -q "^${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; fi
    fi

    # === FINAL CLEANUP ===
    save_current_version
    cleanup_agent_files
    cleanup_files
    # =========================

    msg_success "Updated."
}

main_menu() {
    local remote_version=""
    
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║     VPS Manager Telegram Bot      ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        
        local local_version=$(get_local_version)

        # Get remote version only if not yet fetched
        if [ -z "$remote_version" ]; then
            remote_version=$(get_remote_version)
        fi

        echo -e "  Branch: ${GIT_BRANCH}"
        echo -e "  Type: ${INSTALL_TYPE} | Status: ${STATUS_MESSAGE}"
        
        # Version compare
        if [ "$local_version" != "$remote_version" ] && [ "$remote_version" != "Failed to get" ] && [ "$local_version" != "Not installed" ] && [ "$local_version" != "Undefined" ]; then
             echo -e "  Version: ${C_YELLOW}Local: $local_version (Available: $remote_version)${C_RESET}"
        else
             echo -e "  Version: ${C_GREEN}$local_version${C_RESET}"
        fi

        echo "--------------------------------------------------------"
        echo "  1) Update Bot"
        echo "  2) Uninstall Bot"
        echo "  3) Reinstall (Systemd - Secure)"
        echo "  4) Reinstall (Systemd - Root)"
        echo "  5) Reinstall (Docker - Secure)"
        echo "  6) Reinstall (Docker - Root)"
        echo -e "${C_GREEN}  8) Install NODE (Client)${C_RESET}"
        echo "  0) Exit"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Your choice: ${C_RESET}")" choice
        case $choice in
            1) update_bot; read -p "Press Enter..." ;;
            2) msg_question "Uninstall? (y/n): " c; if [[ "$c" =~ ^[Yy]$ ]]; then uninstall_bot; return; fi ;;
            3) uninstall_bot; install_systemd_logic "secure"; read -p "Press Enter..." ;;
            4) uninstall_bot; install_systemd_logic "root"; read -p "Press Enter..." ;;
            5) uninstall_bot; install_docker_logic "secure"; read -p "Press Enter..." ;;
            6) uninstall_bot; install_docker_logic "root"; read -p "Press Enter..." ;;
            8) uninstall_bot; install_node_logic; read -p "Press Enter..." ;;
            0) break ;;
        esac
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Root required."; exit 1; fi

if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then
    install_node_logic
    exit 0
fi

check_integrity
if [ "$INSTALL_TYPE" == "NONE" ]; then
    clear
    echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║    VPS Manager Bot Installation   ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    echo -e "  Select installation mode:"
    echo "--------------------------------------------------------"
    echo "  1) AGENT (Systemd - Secure)  [Recommended]"
    echo "  2) AGENT (Systemd - Root)    [Full Access]"
    echo "  3) AGENT (Docker - Secure)   [Isolation]"
    echo "  4) AGENT (Docker - Root)     [Docker + Host]"
    echo -e "${C_GREEN}  8) NODE (Client)${C_RESET}"
    echo "  0) Exit"
    echo "--------------------------------------------------------"
    read -p "$(echo -e "${C_BOLD}Your choice: ${C_RESET}")" ch
    case $ch in
        1) uninstall_bot; install_systemd_logic "secure"; read -p "Press Enter..." ;;
        2) uninstall_bot; install_systemd_logic "root"; read -p "Press Enter..." ;;
        3) uninstall_bot; install_docker_logic "secure"; read -p "Press Enter..." ;;
        4) uninstall_bot; install_docker_logic "root"; read -p "Press Enter..." ;;
        8) uninstall_bot; install_node_logic; read -p "Press Enter..." ;;
        0) exit 0 ;;
        *) msg_error "Invalid choice."; sleep 2 ;;
    esac
    main_menu
else
    main_menu
fi