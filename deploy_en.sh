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
        msg_error "Error during '$msg'. Code: $exit_code"
        msg_error "Details in log: /tmp/${SERVICE_NAME}_install.log"
        echo -e "${C_YELLOW}Last lines of log (/tmp/${SERVICE_NAME}_install.log):${C_RESET}"
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
        grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE" || echo "Not found"
    else 
        echo "Not installed"
    fi 
}

INSTALL_TYPE="NONE"; STATUS_MESSAGE="Check not performed."
INTEGRITY_STATUS=""

check_integrity() {
    INTEGRITY_STATUS=""
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Bot not installed."; return;
    fi

    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    IS_NODE=$(grep -q "MODE=node" "${ENV_FILE}" && echo "yes" || echo "no")

    if [ "$IS_NODE" == "yes" ]; then
        INTEGRITY_STATUS="${C_GREEN}🛡️ NODE Mode (Git not required)${C_RESET}"
    elif [ -d "${BOT_INSTALL_PATH}/.git" ]; then
        cd "${BOT_INSTALL_PATH}" || return
        git fetch origin "$GIT_BRANCH" >/dev/null 2>&1
        local FILES_TO_CHECK="core modules bot.py watchdog.py migrate.py manage.py"
        local EXISTING_FILES=""
        for f in $FILES_TO_CHECK; do
            if [ -e "${BOT_INSTALL_PATH}/$f" ]; then EXISTING_FILES="$EXISTING_FILES $f"; fi
        done
        if [ -z "$EXISTING_FILES" ]; then
            INTEGRITY_STATUS="${C_YELLOW}⚠️ Files not found${C_RESET}"
        else
            local DIFF=$(git diff --name-only HEAD -- $EXISTING_FILES 2>/dev/null)
            if [ -n "$DIFF" ]; then
                INTEGRITY_STATUS="${C_RED}⚠️ INTEGRITY VIOLATED (Files modified locally)${C_RESET}"
            else
                INTEGRITY_STATUS="${C_GREEN}🛡️ Code verified${C_RESET}"
            fi
        fi
        cd - >/dev/null
    else
        INTEGRITY_STATUS="${C_YELLOW}⚠️ Git not found${C_RESET}"
    fi

    if [ "$IS_NODE" == "yes" ]; then
        INSTALL_TYPE="NODE (Client)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Active${C_RESET}"; else STATUS_MESSAGE="${C_RED}Inactive${C_RESET}"; fi
        return
    fi

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="AGENT (Docker)"
        if command -v docker &> /dev/null && docker ps | grep -q "tg-bot"; then STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"; fi
    else
        INSTALL_TYPE="AGENT (Systemd)"
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"; fi
    fi
}

setup_nginx_proxy() {
    echo -e "\n${C_CYAN}🔒 Setting up HTTPS (Nginx + Certbot)${C_RESET}"
    run_with_spinner "Installing Nginx and Certbot" sudo apt-get install -y -q nginx certbot python3-certbot-nginx psmisc

    if command -v lsof &> /dev/null && lsof -Pi :80 -sTCP:LISTEN -t >/dev/null ; then
        sudo fuser -k 80/tcp 2>/dev/null
        sudo systemctl stop nginx 2>/dev/null
    elif command -v fuser &> /dev/null && sudo fuser 80/tcp >/dev/null; then
         sudo fuser -k 80/tcp
         sudo systemctl stop nginx 2>/dev/null
    fi

    if sudo certbot certonly --standalone --non-interactive --agree-tos --email "${HTTPS_EMAIL}" -d "${HTTPS_DOMAIN}"; then
        msg_success "Certificate obtained!"
    else
        msg_error "Error obtaining certificate."
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
        echo -e "Web panel available at: https://${HTTPS_DOMAIN}:${HTTPS_PORT}/"
    else
        msg_error "Error in Nginx config."
    fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Updating system..."
    
    # Removing broken Nginx symlinks to avoid apt-get dpkg errors
    if [ -d "/etc/nginx/sites-enabled" ]; then
        sudo find /etc/nginx/sites-enabled -xtype l -delete 2>/dev/null
    fi
    
    run_with_spinner "Apt update" sudo apt-get update -y -q
    run_with_spinner "Installing packages" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3 python3-pip python3-venv git curl wget sudo python3-yaml
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    cd /
    msg_info "Preparing files (Branch: ${GIT_BRANCH})..."
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
        echo -e "${C_YELLOW}⚠️  Saved configuration detected.${C_RESET}"
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
            if [ -z "$W" ]; then
                local val=$(get_env_val "ENABLE_WEB_UI")
                if [[ "$val" == "false" ]]; then W="n"; else W="y"; fi
            fi
            [ -z "$AGENT_URL" ] && AGENT_URL=$(get_env_val "AGENT_BASE_URL")
            [ -z "$NODE_TOKEN" ] && NODE_TOKEN=$(get_env_val "AGENT_TOKEN")
        else
            msg_info "Restore skipped."
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
    msg_info "Finishing ${action_name}..."
    cleanup_common_trash
    sudo rm -rf "${BOT_INSTALL_PATH}/node"
    sudo rm -f "${BOT_INSTALL_PATH}/Dockerfile" "${BOT_INSTALL_PATH}/docker-compose.yml"
}
cleanup_for_docker() {
    local action_name=$1
    msg_info "Finishing ${action_name}..."
    cleanup_common_trash
    cd "${BOT_INSTALL_PATH}"
    sudo rm -rf node
    sudo rm -rf core modules bot.py watchdog.py manage.py migrate.py aerich.ini
    sudo rm -f Dockerfile
}
cleanup_for_node() {
    local action_name=$1
    msg_info "Finishing ${action_name}..."
    cleanup_common_trash
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git config/users.json config/alerts_config.json
}

install_extras() {
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban not found. Install? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Installing Fail2ban" sudo apt-get install -y -q fail2ban; fi
    fi
    
    # Detect server location by external IP
    msg_info "Detecting server geolocation..."
    SERVER_COUNTRY=""
    EXT_IP=$(curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null || curl -s --connect-timeout 5 https://ipinfo.io/ip 2>/dev/null || echo "")
    if [ -n "$EXT_IP" ]; then
        SERVER_COUNTRY=$(curl -s --connect-timeout 5 "http://ip-api.com/line/${EXT_IP}?fields=countryCode" 2>/dev/null || echo "")
    fi
    
    if [ "$SERVER_COUNTRY" == "RU" ]; then
        msg_info "Server is located in Russia - using iperf3 for speedtest"
        if ! command -v iperf3 &> /dev/null; then
            msg_question "iperf3 not found. Install? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Installing iperf3" sudo apt-get install -y -q iperf3; fi
        fi
        # Mark that we use iperf3 mode
        echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    else
        msg_info "Server is not in Russia - Ookla Speedtest CLI is recommended"
        
        HAS_IPERF3=false
        HAS_OOKLA=false
        
        if command -v iperf3 &> /dev/null; then
            HAS_IPERF3=true
        fi
        
        if command -v speedtest &> /dev/null && speedtest --version 2>&1 | grep -q "Speedtest by Ookla"; then
            HAS_OOKLA=true
        fi
        
        # If iperf3 is installed but Ookla is not - offer to switch
        if [ "$HAS_IPERF3" = true ] && [ "$HAS_OOKLA" = false ]; then
            echo -e "${C_YELLOW}⚠️  iperf3 detected. For servers outside Russia, Ookla Speedtest CLI is recommended.${C_RESET}"
            msg_question "Remove iperf3 and install Ookla Speedtest CLI? (y/n) [y]: " SWITCH_CHOICE
            SWITCH_CHOICE=${SWITCH_CHOICE:-y}
            
            if [[ "$SWITCH_CHOICE" =~ ^[Yy]$ ]]; then
                run_with_spinner "Removing iperf3" sudo apt-get remove -y -q iperf3
                install_ookla_speedtest
                echo "OOKLA" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
            else
                msg_info "iperf3 kept. It will be used for speedtest."
                echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
            fi
        # If Ookla already installed
        elif [ "$HAS_OOKLA" = true ]; then
            msg_success "Ookla Speedtest CLI is already installed"
            echo "OOKLA" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
        # If neither is installed
        else
            echo -e "${C_CYAN}Speedtest is not installed. Which tool to install?${C_RESET}"
            echo "  1) Ookla Speedtest CLI (recommended for servers outside Russia)"
            echo "  2) iperf3"
            echo "  3) Skip"
            msg_question "Choose (1/2/3) [1]: " ST_CHOICE
            ST_CHOICE=${ST_CHOICE:-1}
            
            case "$ST_CHOICE" in
                1)
                    install_ookla_speedtest
                    echo "OOKLA" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
                    ;;
                2)
                    run_with_spinner "Installing iperf3" sudo apt-get install -y -q iperf3
                    echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
                    ;;
                3)
                    msg_warning "Speedtest will not be available"
                    ;;
            esac
        fi
    fi
}

install_ookla_speedtest() {
    # Check if already installed and working
    if command -v speedtest &> /dev/null && speedtest --version 2>&1 | grep -q "Speedtest by Ookla"; then
        msg_success "Ookla Speedtest CLI is already installed"
        return 0
    fi
    
    msg_info "Installing Ookla Speedtest CLI..."
    
    # Install curl if not present
    if ! command -v curl &> /dev/null; then
        run_with_spinner "Installing curl" sudo apt-get install -y -q curl
    fi
    
    # Get Ubuntu version
    UBUNTU_VERSION=""
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        UBUNTU_VERSION="$VERSION_ID"
    fi
    
    # Add Ookla repository
    run_with_spinner "Adding Ookla repository" bash -c 'curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash'
    
    # Fix for Ubuntu 24+ (noble -> jammy)
    OOKLA_LIST="/etc/apt/sources.list.d/ookla_speedtest-cli.list"
    if [ -f "$OOKLA_LIST" ]; then
        if grep -q "noble" "$OOKLA_LIST" 2>/dev/null; then
            msg_info "Applying fix for Ubuntu 24+..."
            sudo sed -i 's/noble/jammy/g' "$OOKLA_LIST"
        fi
        # Also fix for other unsupported versions
        if grep -q "oracular\|mantic\|lunar" "$OOKLA_LIST" 2>/dev/null; then
            msg_info "Applying fix for unsupported Ubuntu version..."
            sudo sed -i 's/oracular\|mantic\|lunar/jammy/g' "$OOKLA_LIST"
        fi
    fi
    
    run_with_spinner "Updating packages" sudo apt-get update -y -q
    run_with_spinner "Installing speedtest" sudo apt-get install -y -q speedtest
    
    if command -v speedtest &> /dev/null; then
        msg_success "Ookla Speedtest CLI installed successfully"
    else
        msg_warning "Failed to install Ookla Speedtest CLI, will use iperf3"
        if ! command -v iperf3 &> /dev/null; then
            run_with_spinner "Installing iperf3" sudo apt-get install -y -q iperf3
        fi
        echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    fi
}

ask_env_details() {
    msg_info "Entering .env data..."
    msg_question "Bot Token: " T; msg_question "Admin ID: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Internal Web Port [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN

    msg_question "Enable Web-UI? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then
        ENABLE_WEB="false"
        SETUP_HTTPS="false"
    else
        ENABLE_WEB="true"
        GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        msg_question "Setup HTTPS? (y/n): " H
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"
            msg_question "Domain: " HTTPS_DOMAIN
            msg_question "Email: " HTTPS_EMAIL
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
        msg_warning ".env file not found, skipping variable check."
        return 0
    fi
    
    msg_info "Checking environment variables..."
    local changes_made=false
    
    # List of variables with their default values
    # Format: "VAR_NAME|default_value|description"
    local ENV_VARS=(
        "WEB_SERVER_HOST|0.0.0.0|Web server host"
        "WEB_SERVER_PORT|8080|Web server port"
        "INSTALL_MODE|secure|Installation mode"
        "DEPLOY_MODE|systemd|Deploy mode"
        "ENABLE_WEB_UI|true|Enable web interface"
        "DEBUG|false|Debug mode"
        "TG_BOT_NAME|VPS Bot|Bot name"
    )
    
    for var_entry in "${ENV_VARS[@]}"; do
        local var_name=$(echo "$var_entry" | cut -d'|' -f1)
        local default_val=$(echo "$var_entry" | cut -d'|' -f2)
        local var_desc=$(echo "$var_entry" | cut -d'|' -f3)
        
        if ! grep -q "^${var_name}=" "${ENV_FILE}"; then
            echo -e "${C_YELLOW}  + Added variable ${var_name}=${default_val}${C_RESET}"
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
        msg_success "Environment variables updated."
    else
        msg_success "All variables are up to date."
    fi
}

check_docker_deps() {
    if ! command -v docker &> /dev/null; then curl -sSL https://get.docker.com -o /tmp/get-docker.sh; run_with_spinner "Installing Docker" sudo sh /tmp/get-docker.sh; fi
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
    msg_info "Database and settings migration..."
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
        msg_info "Aerich CLI not found, skipping DB migrations."
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
        run_with_spinner "Updating pip" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install --upgrade pip setuptools wheel
        run_with_spinner "Installing dependencies" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        run_with_spinner "Installing tomlkit" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install tomlkit
        exec_cmd="sudo -u ${SERVICE_USER}"
    else
        setup_repo_and_dirs "root"
        ${PYTHON_BIN} -m venv "${VENV_PATH}"
        run_with_spinner "Updating pip" "${VENV_PATH}/bin/pip" install --upgrade pip setuptools wheel
        run_with_spinner "Installing dependencies" "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        run_with_spinner "Installing tomlkit" "${VENV_PATH}/bin/pip" install tomlkit
        exec_cmd=""
    fi

    load_cached_env
    ask_env_details
    write_env_file "systemd" "$mode" ""
    run_db_migrations "$exec_cmd"
    cleanup_for_systemd "installation"
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog"

    msg_info "Creating 'tgcp-bot' command..."
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then set -a; source .env; set +a; fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    local ip=$(curl -s ipinfo.io/ip)
    echo ""; msg_success "Installation complete! Panel: http://${ip}:${WEB_PORT}"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
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
    run_with_spinner "Building Docker" sudo $dc_cmd build
    run_with_spinner "Starting Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans

    msg_info "Migration in container..."
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init-db >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich upgrade >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python migrate.py $MIGRATE_ARGS >/dev/null 2>&1
    cleanup_for_docker "installation"

    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    msg_success "Docker installation complete!"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 PASSWORD: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy; fi
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== NODE Installation ===${C_RESET}"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi
    common_install_steps
    run_with_spinner "Installing iperf3" sudo apt-get install -y -q iperf3
    setup_repo_and_dirs "root"
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Creating venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Updating pip" "${VENV_PATH}/bin/pip" install --upgrade pip setuptools wheel
    run_with_spinner "Installing dependencies" "${VENV_PATH}/bin/pip" install psutil requests
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
    cleanup_for_node "installation"  
    run_with_spinner "Starting Node" sudo systemctl restart ${NODE_SERVICE_NAME}
    msg_success "Node installed!"
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Uninstall ===${C_RESET}"
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
    echo -e "\n${C_BOLD}=== Update ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then install_node_logic; return; fi
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git not found."; return 1; fi
    echo "" > /tmp/${SERVICE_NAME}_install.log
    local exec_cmd=""
    if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi

    cd "${BOT_INSTALL_PATH}"
    if ! run_with_spinner "Git fetch" $exec_cmd git fetch origin; then return 1; fi
    if ! run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"; then return 1; fi
    
    if [ -f "$README_FILE" ]; then
        local new_ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
        if [ -n "$new_ver" ] && [ -f "${ENV_FILE}" ]; then
             if grep -q "^INSTALLED_VERSION=" "${ENV_FILE}"; then
                 sudo sed -i "s/^INSTALLED_VERSION=.*/INSTALLED_VERSION=\"${new_ver}\"/" "${ENV_FILE}"
             else
                 sudo bash -c "echo 'INSTALLED_VERSION=\"${new_ver}\"' >> ${ENV_FILE}"
             fi
        fi
    fi

    # Check and add missing environment variables
    ensure_env_variables

    local current_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    
    if [ "$current_mode" == "docker" ]; then
        if [ -f "docker-compose.yml" ]; then
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            if ! run_with_spinner "Docker Up" sudo $dc_cmd up -d --build; then msg_error "Docker error."; return 1; fi
            sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
            sudo chmod +x /usr/local/bin/tgcp-bot
        else msg_error "No docker-compose.yml"; return 1; fi
    else
        run_with_spinner "Updating pip" $exec_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
        run_with_spinner "Updating tomlkit" $exec_cmd "${VENV_PATH}/bin/pip" install tomlkit
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
        echo -e "${C_CYAN}🔍 Checking configuration...${C_RESET}"
        echo "❓ Do you want to reset WebUI meta-data (title, favicon, SEO) to defaults?"
        read -p "Reset? (y/N): " reset_meta_answer
        if [[ "$reset_meta_answer" =~ ^[Yy]$ ]]; then
            MIGRATE_ARGS="--reset-meta"
            echo -e "${C_YELLOW}⚠️  Meta-data will be reset.${C_RESET}"
        fi
    fi

    if [ "$current_mode" == "docker" ]; then
         local mode=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
         local cn="tg-bot-${mode}"
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} aerich upgrade >/dev/null 2>&1
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} python migrate.py $MIGRATE_ARGS >/dev/null 2>&1
         
         cleanup_for_docker "update"
    else
         run_db_migrations "$exec_cmd"
         cleanup_for_systemd "update"
    fi

    msg_success "Updated."
}

main_menu() {
    local local_version=$(get_local_version)
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║    VPS Telegram Bot Manager       ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        echo -e "  Branch: ${GIT_BRANCH} | Version: ${local_version}"
        echo -e "  Type: ${INSTALL_TYPE} | Status: ${STATUS_MESSAGE}"
        if [ -n "$INTEGRITY_STATUS" ]; then echo -e "  Integrity: ${INTEGRITY_STATUS}"; fi
        echo "--------------------------------------------------------"
        echo "  1) Update bot"
        echo "  2) Uninstall bot"
        echo "  3) Reinstall (Systemd - Secure)"
        echo "  4) Reinstall (Systemd - Root)"
        echo "  5) Reinstall (Docker - Secure)"
        echo "  6) Reinstall (Docker - Root)"
        echo -e "${C_GREEN}  7) Install NODE (Client)${C_RESET}"
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
            7) uninstall_bot; install_node_logic; read -p "Press Enter..." ;;
            0) break ;;
        esac
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Root required."; exit 1; fi
if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then install_node_logic; exit 0; fi

check_integrity
if [ "$INSTALL_TYPE" == "NONE" ]; then
    clear
    echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║      VPS Manager Bot Install      ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    echo -e "  Select installation mode:"
    echo "--------------------------------------------------------"
    echo "  1) AGENT (Systemd - Secure)  [Recommended]"
    echo "  2) AGENT (Systemd - Root)    [Full access]"
    echo "  3) AGENT (Docker - Secure)   [Isolation]"
    echo "  4) AGENT (Docker - Root)     [Docker + Host]"
    echo -e "${C_GREEN}  7) NODE (Client)${C_RESET}"
    echo "  0) Exit"
    echo "--------------------------------------------------------"
    read -p "$(echo -e "${C_BOLD}Your choice: ${C_RESET}")" ch
    case $ch in
        1) uninstall_bot; install_systemd_logic "secure"; read -p "Press Enter..." ;;
        2) uninstall_bot; install_systemd_logic "root"; read -p "Press Enter..." ;;
        3) uninstall_bot; install_docker_logic "secure"; read -p "Press Enter..." ;;
        4) uninstall_bot; install_docker_logic "root"; read -p "Press Enter..." ;;
        7) uninstall_bot; install_node_logic; read -p "Press Enter..." ;;
        0) exit 0 ;;
        *) msg_error "Invalid choice."; sleep 2 ;;
    esac
    main_menu
else
    main_menu
fi
