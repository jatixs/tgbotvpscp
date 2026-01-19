#!/bin/bash

cd ~
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
PYTHON_BIN="python3"
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
        msg_error "Error during '$msg'. Code: $exit_code"
        msg_error "Details in log: /tmp/${SERVICE_NAME}_install.log"
    fi
    return $exit_code
}

get_local_version() { if [ -f "$README_FILE" ]; then grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE" || echo "Not found"; else echo "Not installed"; fi; }

INSTALL_TYPE="NONE"; STATUS_MESSAGE="Not checked."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Bot not installed."; return;
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

cleanup_files_silent() {
    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then sudo rm -rf "$BOT_INSTALL_PATH/assets"; fi
    sudo rm -f "$BOT_INSTALL_PATH/custom_module.md"
    sudo rm -f "$BOT_INSTALL_PATH/custom_module_en.md"
    sudo rm -f "$BOT_INSTALL_PATH/.gitignore"
    sudo rm -f "$BOT_INSTALL_PATH/LICENSE"
    sudo rm -f "$BOT_INSTALL_PATH/README.md"
    sudo rm -f "$BOT_INSTALL_PATH/README.en.md"
    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
}

ask_for_version() {
    echo ""
    msg_info "Select installation version..."
    echo "  1) Latest version from branch '${GIT_BRANCH}' (default)"
    echo "  2) Select specific version (from tags)"
    read -p "$(echo -e "${C_BOLD}Your choice [1]: ${C_RESET}")" v_mode
    v_mode=${v_mode:-1}

    if [ "$v_mode" == "2" ]; then
        msg_info "Fetching version list from GitHub..."
        if ! command -v git &> /dev/null; then sudo apt-get install -y git; fi
        
        local tags=$(git ls-remote --tags --refs "${GITHUB_REPO_URL}" | cut -d/ -f3 | sort -V -r)
        
        if [ -z "$tags" ]; then
            msg_warning "No tags found. Using branch ${GIT_BRANCH}."
            return
        fi

        echo -e "${C_BLUE}Available versions:${C_RESET}"
        local i=1
        declare -A version_map
        
        while read -r tag; do
            echo "  $i) $tag"
            version_map[$i]="$tag"
            ((i++))
        done <<< "$tags"

        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Enter version number: ${C_RESET}")" tag_num
        if [ -n "${version_map[$tag_num]}" ]; then
            GIT_BRANCH="${version_map[$tag_num]}"
            msg_success "Selected version: ${GIT_BRANCH}"
        else
            msg_error "Invalid number. Staying on ${GIT_BRANCH}."
        fi
    else
        msg_info "Using branch: ${GIT_BRANCH}"
    fi
}

ensure_latest_python() {
    msg_info "Checking Python version..."
    local TARGET_VERSION="3.12"
    local TARGET_BIN="python${TARGET_VERSION}" 
    
    if command -v $TARGET_BIN &>/dev/null; then
        PYTHON_BIN=$(which $TARGET_BIN)
        msg_success "Found target Python: $PYTHON_BIN"
        return
    fi

    msg_info "$TARGET_BIN not found. Installing SIDE-BY-SIDE..."
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [ "$ID" == "ubuntu" ]; then
            if ! grep -q "^deb .*deadsnakes/ppa" /etc/apt/sources.list /etc/apt/sources.list.d/*; then
                msg_info "Adding deadsnakes PPA..."
                if ! command -v add-apt-repository &>/dev/null; then
                    sudo apt-get install -y -q software-properties-common
                fi
                sudo add-apt-repository -y ppa:deadsnakes/ppa
                sudo apt-get update -y -q
            fi
        fi
    fi

    run_with_spinner "Installing $TARGET_BIN" sudo apt-get install -y ${TARGET_BIN} ${TARGET_BIN}-venv ${TARGET_BIN}-dev
    if command -v $TARGET_BIN &>/dev/null; then
        PYTHON_BIN=$(which $TARGET_BIN)
        msg_success "$TARGET_BIN successfully installed ($PYTHON_BIN)"
    else
        msg_warning "Failed to install $TARGET_BIN. Using system default."
        PYTHON_BIN="/usr/bin/python3"
    fi
}

check_and_recreate_venv() {
    if [ -d "${VENV_PATH}" ]; then
        local venv_ver=$("${VENV_PATH}/bin/python" --version 2>/dev/null | awk '{print $2}' | cut -d. -f1,2)
        local sys_ver=$("${PYTHON_BIN}" --version 2>/dev/null | awk '{print $2}' | cut -d. -f1,2)
        if [ "$venv_ver" != "$sys_ver" ]; then
            msg_warning "Python version changed ($venv_ver -> $sys_ver). Recreating venv..."
            sudo rm -rf "${VENV_PATH}"
        fi
    fi
}

setup_nginx_proxy() {
    echo -e "\n${C_CYAN}🔒 HTTPS Setup (Nginx + Certbot)${C_RESET}"
    run_with_spinner "Installing Nginx and Certbot" sudo apt-get install -y -q nginx certbot python3-certbot-nginx psmisc

    if command -v lsof &> /dev/null && lsof -Pi :80 -sTCP:LISTEN -t >/dev/null ; then
        msg_warning "Port 80 is busy. Attempting to free..."
        sudo fuser -k 80/tcp 2>/dev/null; sudo systemctl stop nginx 2>/dev/null
    elif command -v fuser &> /dev/null && sudo fuser 80/tcp >/dev/null; then
         msg_warning "Port 80 is busy. Attempting to free..."
         sudo fuser -k 80/tcp; sudo systemctl stop nginx 2>/dev/null
    fi

    msg_info "Obtaining SSL certificate for ${HTTPS_DOMAIN}..."
    if sudo certbot certonly --standalone --non-interactive --agree-tos --email "${HTTPS_EMAIL}" -d "${HTTPS_DOMAIN}"; then
        msg_success "Certificate obtained!"
    else
        msg_error "Error obtaining certificate."
        sudo systemctl start nginx; return 1
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
        echo ""; msg_success "HTTPS configured successfully!"
    else
        msg_error "Nginx config error."
    fi
}

create_fix_script() {
    cat > "${BOT_INSTALL_PATH}/fix_db_auto.py" <<'EOF'
import sqlite3, os, hashlib
DB = "config/nodes.db"
if os.path.exists(DB):
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        try: c.execute("ALTER TABLE nodes ADD COLUMN token_safe TEXT")
        except: pass
        try: c.execute("ALTER TABLE nodes ADD COLUMN token_hash VARCHAR(64)")
        except: pass
        try: c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uid_nodes_token_h_a1b2c3 ON nodes (token_hash)")
        except: pass
        
        try:
            c.execute("PRAGMA table_info(nodes)")
            cols = [row['name'] for row in c.fetchall()]
            src_col = 'token' if 'token' in cols else 'token_safe'
            if 'token_hash' in cols:
                c.execute(f"SELECT id, {src_col}, token_hash FROM nodes")
                rows = c.fetchall()
                for row in rows:
                    uid = row['id']
                    val = row[src_col]
                    curr_hash = row['token_hash']
                    if val and not curr_hash:
                        new_hash = hashlib.sha256(val.encode()).hexdigest()
                        c.execute("UPDATE nodes SET token_hash = ?, token_safe = ? WHERE id = ?", (new_hash, val, uid))
                        print(f"Fixed hash for node {uid}")
        except Exception as e:
            print(f"Hash fix warn: {e}")

        try: c.execute("DELETE FROM aerich")
        except: pass
        
        conn.commit()
        conn.close()
        print("DB Schema patched.")
    except Exception as e:
        print(f"DB Patch error: {e}")
EOF
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    
    cleanup_files_silent
    
    msg_info "1. Updating system..."
    run_with_spinner "Apt update" sudo apt-get update -y -q
    ensure_latest_python
    run_with_spinner "Installing system packages" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3 python3-pip git curl wget sudo python3-yaml
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    cd /
    msg_info "Preparing files (Version: ${GIT_BRANCH})..."
    if [ -f "${ENV_FILE}" ]; then cp "${ENV_FILE}" /tmp/tgbot_env.bak; fi
    if [ -d "${BOT_INSTALL_PATH}" ]; then run_with_spinner "Removing old files" sudo rm -rf "${BOT_INSTALL_PATH}"; fi
    sudo mkdir -p ${BOT_INSTALL_PATH}
    run_with_spinner "Cloning repository" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    if [ -f "/tmp/tgbot_env.bak" ]; then sudo mv /tmp/tgbot_env.bak "${ENV_FILE}"; fi
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

load_cached_env() {
    local env_file="${ENV_FILE}"
    if [ ! -f "$env_file" ] && [ -f "/tmp/tgbot_env.bak" ]; then env_file="/tmp/tgbot_env.bak"; fi
    if [ -f "$env_file" ]; then
        echo -e "${C_YELLOW}⚠️  Found saved configuration.${C_RESET}"
        read -p "$(echo -e "${C_CYAN}❓ Restore settings? (y/n) [y]: ${C_RESET}")" RESTORE_CHOICE
        RESTORE_CHOICE=${RESTORE_CHOICE:-y}
        if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]]; then
            msg_info "Loading saved data..."
            get_env_val() { grep "^$1=" "$env_file" | cut -d'=' -f2- | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//"; }
            [ -z "$T" ] && T=$(get_env_val "TG_BOT_TOKEN")
            [ -z "$A" ] && A=$(get_env_val "TG_ADMIN_ID")
            [ -z "$U" ] && U=$(get_env_val "TG_ADMIN_USERNAME")
            [ -z "$N" ] && N=$(get_env_val "TG_BOT_NAME")
            [ -z "$P" ] && P=$(get_env_val "WEB_SERVER_PORT")
            [ -z "$SENTRY_DSN" ] && SENTRY_DSN=$(get_env_val "SENTRY_DSN")
            if [ -z "$W" ]; then local val=$(get_env_val "ENABLE_WEB_UI"); if [[ "$val" == "false" ]]; then W="n"; else W="y"; fi; fi
            [ -z "$AGENT_URL" ] && AGENT_URL=$(get_env_val "AGENT_BASE_URL")
            [ -z "$NODE_TOKEN" ] && NODE_TOKEN=$(get_env_val "AGENT_TOKEN")
        else
            msg_info "Restore skipped."
        fi
    fi
}

cleanup_node_files() {
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git .github config/users.json config/alerts_config.json deploy.sh deploy_en.sh requirements.txt README* LICENSE CHANGELOG* .gitignore aerich.ini
}

cleanup_agent_files() {
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf node
}

install_extras() {
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban not found. Install? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Installing Fail2ban" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" fail2ban; fi
    fi
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 not found. Install? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Installing iperf3" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" iperf3; fi
    fi
}

ask_env_details() {
    msg_info "Entering .env data..."
    msg_question "Bot Token: " T; msg_question "Admin ID: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Internal Web Port [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN
    msg_question "Enable Web-UI (Dashboard)? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then
        ENABLE_WEB="false"; SETUP_HTTPS="false"
    else
        ENABLE_WEB="true"; GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        msg_question "Setup HTTPS (Nginx Proxy)? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"
            msg_question "Domain (e.g. bot.site.com): " HTTPS_DOMAIN
            msg_question "Email for SSL: " HTTPS_EMAIL
            msg_question "External HTTPS Port [8443]: " HP
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
    if [ "$GIT_BRANCH" == "main" ]; then debug_setting="false"; fi
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
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y python3-yaml iperf3 git curl wget sudo procps iputils-ping net-tools gnupg docker.io coreutils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir docker aiohttp aiosqlite argon2-cffi sentry-sdk tortoise-orm aerich cryptography
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
    ports: ["${WEB_PORT}:${WEB_PORT}"]
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
    ports: ["${WEB_PORT}:${WEB_PORT}"]
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
    msg_info "Checking and migrating database..."
    cd "${BOT_INSTALL_PATH}" || return 1
    if [ -f "${ENV_FILE}" ]; then set -a; source "${ENV_FILE}"; set +a; fi
    
    create_fix_script
    msg_info "Running DB patch..."
    if [ -n "$exec_user" ]; then 
        $exec_user "${VENV_PATH}/bin/python" fix_db_auto.py >/dev/null 2>&1
    else
        "${VENV_PATH}/bin/python" fix_db_auto.py >/dev/null 2>&1
    fi
    rm -f fix_db_auto.py

    local cmd_prefix=""; if [ -n "$exec_user" ]; then cmd_prefix="sudo -E -u ${SERVICE_USER}"; fi

    # Force creation of aerich.ini to avoid missing file issues
    msg_info "Configuring Aerich..."
    cat > "${BOT_INSTALL_PATH}/aerich.ini" <<EOF
[aerich]
tortoise_orm = core.config.TORTOISE_ORM
location = ./migrations
src_folder = .
EOF

    if [ -n "$exec_user" ]; then
        chown ${SERVICE_USER}:${SERVICE_USER} "${BOT_INSTALL_PATH}/aerich.ini"
    fi
    if [ ! -d "${BOT_INSTALL_PATH}/migrations" ]; then
        if ! $cmd_prefix ${VENV_PATH}/bin/aerich init-db; then msg_warning "init-db skipped (DB might exist)."; fi
    else
        $cmd_prefix ${VENV_PATH}/bin/aerich upgrade >/dev/null 2>&1
    fi
    msg_info "Safe config migration..."
    if [ -f "${BOT_INSTALL_PATH}/migrate.py" ]; then $cmd_prefix ${VENV_PATH}/bin/python "${BOT_INSTALL_PATH}/migrate.py"; else msg_warning "migrate.py not found."; fi
}

install_systemd_logic() {
    local mode=$1
    common_install_steps
    install_extras

    ask_for_version

    local exec_cmd=""
    if [ "$mode" == "secure" ]; then
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}; fi
        setup_repo_and_dirs "${SERVICE_USER}"
        check_and_recreate_venv
        if [ ! -d "${VENV_PATH}" ]; then sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
        run_with_spinner "Installing dependencies" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        exec_cmd="sudo -u ${SERVICE_USER}"
    else
        setup_repo_and_dirs "root"
        check_and_recreate_venv
        if [ ! -d "${VENV_PATH}" ]; then ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
        run_with_spinner "Installing dependencies" "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        exec_cmd=""
    fi

    load_cached_env
    ask_env_details
    write_env_file "systemd" "$mode" ""

    run_with_spinner "Database setup and migration" run_db_migrations "$exec_cmd"

    cleanup_files_silent
    cleanup_agent_files

    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog"

    msg_info "Creating 'tgcp-bot' command..."
    if [ ! -f "${BOT_INSTALL_PATH}/manage.py" ]; then true; else chmod +x "${BOT_INSTALL_PATH}/manage.py"; fi
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then set -a; source .env; set +a; fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    local ip=$(curl -s ipinfo.io/ip)
    echo ""; msg_success "Installation complete! Agent available at: http://${ip}:${WEB_PORT}"
    echo -e "💡 Use command ${C_BOLD}tgcp-bot${C_RESET} to manage."
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 YOUR WEB-UI PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy; fi
}

install_docker_logic() {
    local mode=$1
    common_install_steps
    install_extras
    
    ask_for_version

    setup_repo_and_dirs "root"
    check_docker_deps
    load_cached_env
    ask_env_details

    create_dockerfile
    create_docker_compose_yml
    local container_name="tg-bot-${mode}"
    write_env_file "docker" "$mode" "${container_name}"
    
    cleanup_files_silent
    cleanup_agent_files
    
    cd ${BOT_INSTALL_PATH}
    local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; elif command -v docker-compose &>/dev/null; then dc_cmd="docker-compose"; else msg_error "Docker Compose not found."; return 1; fi
    run_with_spinner "Building Docker" sudo $dc_cmd build
    run_with_spinner "Starting Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans

    msg_info "Attempting DB setup in container..."
    
    # AUTO FIX FOR DOCKER
    create_fix_script
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python fix_db_auto.py >/dev/null 2>&1
    rm -f fix_db_auto.py
    
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
    msg_success "Docker Installation Complete!"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 YOUR WEB-UI PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy; fi
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Installing NODE (Client) ===${C_RESET}"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi
    common_install_steps
    run_with_spinner "Installing iperf3" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" iperf3
    setup_repo_and_dirs "root"
    msg_info "Configuring venv..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Creating venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Installing dependencies" "${VENV_PATH}/bin/pip" install psutil requests
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
    cleanup_node_files
    run_with_spinner "Starting Node" sudo systemctl restart ${NODE_SERVICE_NAME}
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
    sudo rm -f /usr/local/bin/tgcp-bot
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Uninstalled."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Updating ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then msg_info "Updating Node..."; install_node_logic; return; fi
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git not found. Reinstall."; return 1; fi
    
    ask_for_version

    local exec_cmd=""
    if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi

    cd "${BOT_INSTALL_PATH}"
    if ! run_with_spinner "Git fetch" $exec_cmd git fetch origin --tags; then return 1; fi
    
    if $exec_cmd git rev-parse --verify "origin/${GIT_BRANCH}" &>/dev/null; then
         if ! run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"; then return 1; fi
    else
         if ! run_with_spinner "Git checkout" $exec_cmd git checkout --force "${GIT_BRANCH}"; then return 1; fi
    fi
    
    cleanup_agent_files
    cleanup_files_silent

    if [ -f "${ENV_FILE}" ] && grep -q "DEPLOY_MODE=docker" "${ENV_FILE}"; then
        if [ -f "docker-compose.yml" ]; then
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            if ! run_with_spinner "Docker Up" sudo $dc_cmd up -d --build; then msg_error "Docker Error."; return 1; fi
            local mode=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
            local cn="tg-bot-${mode}"
            
            # AUTO FIX FOR DOCKER UPDATE
            create_fix_script
            sudo $dc_cmd --profile "${mode}" exec -T ${cn} python fix_db_auto.py >/dev/null 2>&1
            rm -f fix_db_auto.py
            
            sudo $dc_cmd --profile "${mode}" exec -T ${cn} aerich upgrade >/dev/null 2>&1
            sudo $dc_cmd --profile "${mode}" exec -T ${cn} python migrate.py >/dev/null 2>&1
        else msg_error "No docker-compose.yml"; return 1; fi
    else
        ensure_latest_python
        check_and_recreate_venv
        if [ ! -d "${VENV_PATH}" ]; then
             if [ -n "$exec_cmd" ]; then sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv "${VENV_PATH}"; else ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
        fi
        run_with_spinner "Updating pip" $exec_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
        run_with_spinner "DB setup and migration" run_db_migrations "$exec_cmd"
        if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then sudo systemctl restart ${SERVICE_NAME}; fi
        if systemctl list-unit-files | grep -q "^${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; fi
    fi
    msg_success "Updated to ${GIT_BRANCH}."
}

main_menu() {
    local local_version=$(get_local_version "$README_FILE")
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║      VPS Manager Bot Setup        ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        echo -e "  Branch/Tag: ${GIT_BRANCH} | Version: ${local_version}"
        echo -e "  Type: ${INSTALL_TYPE} | Status: ${STATUS_MESSAGE}"
        echo "--------------------------------------------------------"
        echo "  1) Update Bot / Change Version"
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
    echo -e "${C_BLUE}${C_BOLD}║      VPS Manager Bot Setup        ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    echo -e "  Select installation mode:"
    echo "--------------------------------------------------------"
    echo "  1) AGENT (Systemd - Secure)  [Recommended]"
    echo "  2) AGENT (Systemd - Root)    [Full Access]"
    echo "  3) AGENT (Docker - Secure)   [Isolated]"
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