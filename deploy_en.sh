#!/bin/bash

orig_arg1="$1"

# --- Configuration ---
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
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }; msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }
spinner() { local pid=$1; local msg=$2; local spin='|/-\'; local i=0; while kill -0 $pid 2>/dev/null; do i=$(( (i+1) %4 )); printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"; sleep .1; done; printf "\r"; }
run_with_spinner() { local msg=$1; shift; ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) & local pid=$!; spinner "$pid" "$msg"; wait $pid; local exit_code=$?; echo -ne "\033[2K\r"; if [ $exit_code -ne 0 ]; then msg_error "Error during '$msg'. Code: $exit_code"; msg_error "Log: /tmp/${SERVICE_NAME}_install.log"; fi; return $exit_code; }

if command -v wget &> /dev/null; then DOWNLOADER="wget -qO-"; elif command -v curl &> /dev/null; then DOWNLOADER="curl -sSLf"; else msg_error "Neither wget nor curl found."; exit 1; fi
if command -v curl &> /dev/null; then DOWNLOADER_PIPE="curl -s"; else DOWNLOADER_PIPE="wget -qO-"; fi

get_local_version() { local readme_path="$1"; local version="Not found"; if [ -f "$readme_path" ]; then version=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$readme_path" || true); if [ -z "$version" ]; then version=$(grep -oP '<b\s*>v\K[\d\.]+(?=</b>)' "$readme_path" || true); fi; if [ -z "$version" ]; then version="Not found"; else version="v$version"; fi; else version="Not installed"; fi; echo "$version"; }
get_latest_version() { local api_url="$1"; local latest_tag=$($DOWNLOADER_PIPE "$api_url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "API Error"); if [[ "$latest_tag" == *"API rate limit exceeded"* ]]; then latest_tag="API Limit"; elif [[ "$latest_tag" == "API Error" ]] || [ -z "$latest_tag" ]; then latest_tag="Unknown"; fi; echo "$latest_tag"; }

# --- Integrity Check ---
INSTALL_TYPE="NONE"; STATUS_MESSAGE="Check not performed."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Not installed."; return;
    fi

    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="NODE (Client)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Active${C_RESET}"; else STATUS_MESSAGE="${C_RED}Inactive${C_RESET}"; fi
        return
    fi

    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "unknown")

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="AGENT (Docker - $INSTALL_MODE_FROM_ENV)"
        if ! command -v docker &> /dev/null; then STATUS_MESSAGE="${C_RED}Docker missing.${C_RESET}"; return; fi
        if ! (command -v docker-compose &> /dev/null || docker compose version &> /dev/null); then STATUS_MESSAGE="${C_RED}Docker Compose missing.${C_RESET}"; return; fi
        if [ ! -f "${DOCKER_COMPOSE_FILE}" ]; then STATUS_MESSAGE="${C_RED}Missing docker-compose.yml.${C_RESET}"; return; fi
        
        local bot_container_name=$(grep '^TG_BOT_CONTAINER_NAME=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ -z "$bot_container_name" ]; then bot_container_name="tg-bot-${INSTALL_MODE_FROM_ENV}"; fi
        local watchdog_container_name="tg-watchdog"
        
        local bot_status; local watchdog_status;
        if docker ps -f "name=${bot_container_name}" --format '{{.Names}}' | grep -q "${bot_container_name}"; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi
        if docker ps -f "name=${watchdog_container_name}" --format '{{.Names}}' | grep -q "${watchdog_container_name}"; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi
        STATUS_MESSAGE="Docker: OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"
    else
        INSTALL_TYPE="AGENT (Systemd - $INSTALL_MODE_FROM_ENV)"
        if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ]; then STATUS_MESSAGE="${C_RED}Files corrupted.${C_RESET}"; return; fi;
        local bot_status; local watchdog_status;
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi;
        if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi;
        STATUS_MESSAGE="Systemd: OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"
    fi
}

install_extras() {
    local packages_to_install=()
    local packages_to_remove=()
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban not found. Install? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then packages_to_install+=("fail2ban"); else msg_info "Skipping Fail2Ban."; fi
    else msg_success "Fail2Ban installed."; fi
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 not found. Install? (y/n): " INSTALL_IPERF3
        if [[ "$INSTALL_IPERF3" =~ ^[Yy]$ ]]; then packages_to_install+=("iperf3"); else msg_info "Skipping iperf3."; fi
    else msg_success "iperf3 installed."; fi
    if command -v speedtest &> /dev/null || dpkg -s speedtest-cli &> /dev/null; then
        msg_warning "Old 'speedtest-cli' detected."
        msg_question "Remove 'speedtest-cli'? (y/n): " REMOVE_SPEEDTEST
        if [[ "$REMOVE_SPEEDTEST" =~ ^[Yy]$ ]]; then packages_to_remove+=("speedtest-cli"); else msg_info "Skipping removal."; fi
    fi
    if [ ${#packages_to_remove[@]} -gt 0 ]; then
        run_with_spinner "Removing packages" sudo apt-get remove --purge -y "${packages_to_remove[@]}"
        run_with_spinner "Cleaning apt" sudo apt-get autoremove -y
    fi
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        run_with_spinner "Updating apt" sudo apt-get update -y
        run_with_spinner "Installing packages" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages_to_install[@]}"
        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then sudo systemctl enable fail2ban &> /dev/null; sudo systemctl start fail2ban &> /dev/null; fi
    fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Updating packages and dependencies..."
    run_with_spinner "Updating apt" sudo apt-get update -y
    run_with_spinner "Installing dependencies" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo python3-yaml
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    sudo mkdir -p ${BOT_INSTALL_PATH}
    msg_info "Cloning repo (branch ${GIT_BRANCH})..."
    run_with_spinner "Cloning" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    msg_info "Creating directories..."
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

ask_env_details() {
    msg_info "Enter .env details..."
    msg_question "Bot Token: " T
    msg_question "Admin ID: " A
    msg_question "Admin Username (opt): " U
    msg_question "Bot Name (opt): " N
    msg_question "Web Server Port (WEB_SERVER_PORT) [8080]: " PORT_INPUT
    if [ -z "$PORT_INPUT" ]; then WEB_PORT="8080"; else WEB_PORT="$PORT_INPUT"; fi
    export T A U N WEB_PORT
}

write_env_file() {
    local deploy_mode=$1; local install_mode=$2; local container_name=$3
    msg_info "Creating .env..."
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
TG_BOT_TOKEN="${T}"
TG_ADMIN_ID="${A}"
TG_ADMIN_USERNAME="${U}"
TG_BOT_NAME="${N}"
WEB_SERVER_HOST="0.0.0.0"
WEB_SERVER_PORT="${WEB_PORT}"
INSTALL_MODE="${install_mode}"
DEPLOY_MODE="${deploy_mode}"
TG_BOT_CONTAINER_NAME="${container_name}"
EOF
    sudo chmod 600 "${ENV_FILE}"
}

check_docker_deps() {
    msg_info "Checking Docker..."
    if ! command -v docker &> /dev/null; then
        curl -sSL https://get.docker.com -o /tmp/get-docker.sh
        run_with_spinner "Installing Docker" sudo sh /tmp/get-docker.sh
    fi
    if command -v docker-compose &> /dev/null; then sudo rm -f $(which docker-compose); fi
    (sudo apt-get purge -y docker.io docker-compose docker-compose-plugin docker-ce docker-ce-cli containerd.io docker-buildx-plugin &> /tmp/${SERVICE_NAME}_install.log)
    (sudo apt-get autoremove -y &> /tmp/${SERVICE_NAME}_install.log)
    sudo systemctl enable docker &> /tmp/${SERVICE_NAME}_install.log
    run_with_spinner "Starting Docker" sudo systemctl restart docker
    
    msg_info "Installing Docker Compose v2..."
    local DOCKER_CLI_PLUGIN_DIR="/usr/libexec/docker/cli-plugins"
    if [ ! -d "$DOCKER_CLI_PLUGIN_DIR" ]; then DOCKER_CLI_PLUGIN_DIR="/usr/local/lib/docker/cli-plugins"; fi
    local DOCKER_COMPOSE_PATH="${DOCKER_CLI_PLUGIN_DIR}/docker-compose"
    sudo mkdir -p ${DOCKER_CLI_PLUGIN_DIR}
    local DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
    local LATEST_COMPOSE_URL="https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)"
    run_with_spinner "Downloading compose" sudo curl -SLf "${LATEST_COMPOSE_URL}" -o "${DOCKER_COMPOSE_PATH}"
    sudo chmod +x "${DOCKER_COMPOSE_PATH}"
}

create_dockerfile() {
    msg_info "Creating Dockerfile..."
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
FROM python:3.10-slim-bookworm
LABEL maintainer="Jatixs"
RUN apt-get update && apt-get install -y python3-yaml iperf3 git curl wget sudo procps iputils-ping net-tools gnupg docker.io coreutils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir docker aiohttp
RUN groupadd -g 1001 tgbot && useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
WORKDIR /opt/tg-bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && chown -R tgbot:tgbot /opt/tg-bot
USER tgbot
CMD ["python", "bot.py"]
EOF
    sudo chown ${OWNER_USER}:${OWNER_USER} "${BOT_INSTALL_PATH}/Dockerfile"
}

create_docker_compose_yml() {
    msg_info "Creating docker-compose.yml..."
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
      - /proc/uptime:/proc/uptime:ro
      - /proc/stat:/proc/stat:ro
      - /proc/meminfo:/proc/meminfo:ro
      - /proc/net/dev:/proc/net/dev:ro
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
    sudo chown ${OWNER_USER}:${OWNER_USER} "${BOT_INSTALL_PATH}/docker-compose.yml"
}

create_and_start_service() { 
    local svc=$1; local script=$2; local mode=$3; local desc=$4
    local user="root"; if [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ]; then user=${SERVICE_USER}; fi
    msg_info "Creating ${svc}.service..."; sudo tee "/etc/systemd/system/${svc}.service" > /dev/null <<EOF
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
    if sudo systemctl is-active --quiet ${svc}; then msg_success "Started!"; else msg_error "Failed."; fi
}

install_systemd_logic() {
    local mode=$1
    common_install_steps
    install_extras
    if [ "$mode" == "secure" ]; then
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}; fi
        setup_repo_and_dirs "${SERVICE_USER}"
        sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv "${VENV_PATH}"
        sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
    else
        setup_repo_and_dirs "root"
        ${PYTHON_BIN} -m venv "${VENV_PATH}"
        "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
    fi
    ask_env_details
    write_env_file "systemd" "$mode" ""
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog"
    msg_success "Systemd Install Complete!"
}

install_docker_logic() {
    local mode=$1
    common_install_steps
    install_extras
    setup_repo_and_dirs "root" 
    check_docker_deps
    ask_env_details
    create_dockerfile
    create_docker_compose_yml
    write_env_file "docker" "$mode" "tg-bot-${mode}"
    cd ${BOT_INSTALL_PATH}
    sudo docker-compose build
    sudo docker-compose --profile "${mode}" up -d --remove-orphans
    msg_success "Docker Install Complete!"
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Installing NODE (Client) ===${C_RESET}"
    common_install_steps
    setup_repo_and_dirs "root"
    
    msg_info "Setting up venv..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Creating venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Installing deps" "${VENV_PATH}/bin/pip" install psutil requests
    
    echo ""; msg_info "Agent Setup:"
    msg_question "Agent URL (http://IP:PORT): " AGENT_URL
    msg_question "Node Token: " NODE_TOKEN
    
    msg_info "Creating .env..."
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
EOF
    sudo chmod 600 "${ENV_FILE}"

    msg_info "Creating ${NODE_SERVICE_NAME}.service..."
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
    msg_success "Node installed! Logs: sudo journalctl -u ${NODE_SERVICE_NAME} -f"
}

install_systemd_secure() { echo -e "\n${C_BOLD}=== Install Systemd (Secure) ===${C_RESET}"; install_systemd_logic "secure"; }
install_systemd_root() { echo -e "\n${C_BOLD}=== Install Systemd (Root) ===${C_RESET}"; install_systemd_logic "root"; }
install_docker_secure() { echo -e "\n${C_BOLD}=== Install Docker (Secure) ===${C_RESET}"; install_docker_logic "secure"; }
install_docker_root() { echo -e "\n${C_BOLD}=== Install Docker (Root) ===${C_RESET}"; install_docker_logic "root"; }

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Uninstalling ===${C_RESET}"
    sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &> /dev/null; fi
    sudo rm -rf "${BOT_INSTALL_PATH}"
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    if command -v docker &> /dev/null; then sudo docker rmi tg-vps-bot:latest &> /dev/null; fi
    msg_success "Uninstall complete."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Updating (branch: ${GIT_BRANCH}) ===${C_RESET}";
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git repo not found. Cannot update."; return 1; fi
    
    local exec_user="";
    if [ ! -f "${ENV_FILE}" ]; then msg_error ".env not found. Cannot determine update mode."; return 1; fi
    
    # Read vars
    local DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    local INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    local WEB_PORT=$(grep '^WEB_SERVER_PORT=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    if [ -z "$WEB_PORT" ]; then WEB_PORT="8080"; fi
    export WEB_PORT

    if [ "$INSTALL_MODE_FROM_ENV" == "secure" ]; then
        exec_user="sudo -u ${SERVICE_USER}"
    fi

    msg_warning "Update overwrites local changes."
    msg_warning ".env, config/, logs/ preserved."
    
    msg_info "1. Fetching updates..."
    pushd "${BOT_INSTALL_PATH}" > /dev/null
    run_with_spinner "Git fetch" $exec_user git fetch origin
    run_with_spinner "Git reset" $exec_user git reset --hard "origin/${GIT_BRANCH}"
    popd > /dev/null
    msg_success "Files updated."

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        # Docker update logic
        local COMPOSE_CMD="sudo docker compose"
        if ! docker compose version &> /dev/null; then COMPOSE_CMD="sudo docker-compose"; fi

        # Re-create files in case they changed (e.g. port)
        if [ ! -f "${BOT_INSTALL_PATH}/Dockerfile" ]; then create_dockerfile; fi
        create_docker_compose_yml 

        msg_info "2. Rebuilding and restarting containers..."
        (cd ${BOT_INSTALL_PATH} && run_with_spinner "Build" $COMPOSE_CMD build)
        (cd ${BOT_INSTALL_PATH} && run_with_spinner "Up" $COMPOSE_CMD --profile "${INSTALL_MODE_FROM_ENV}" up -d --remove-orphans)
        msg_success "Docker updated."
    else
        # Systemd update logic
        msg_info "2. Updating dependencies..."
        run_with_spinner "Pip install" $exec_user "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
        
        msg_info "3. Restarting services..."
        sudo systemctl restart ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME}
        msg_success "Services restarted."
    fi
}

main_menu() {
    local local_version=$(get_local_version "$README_FILE")
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║    VPS Telegram Bot Manager       ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        echo -e "  Branch: ${GIT_BRANCH} | Version: ${local_version}"
        echo -e "  Type: ${INSTALL_TYPE} | Status: ${STATUS_MESSAGE}"
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
        read -p "Your choice: " choice
        case $choice in
            1) update_bot; read -p "Enter..." ;;
            2) msg_question "Uninstall completely? (y/n): " c; if [[ "$c" =~ ^[Yy]$ ]]; then uninstall_bot; return; fi ;;
            3) uninstall_bot; install_systemd_secure; read -p "Enter..." ;;
            4) uninstall_bot; install_systemd_root; read -p "Enter..." ;;
            5) uninstall_bot; install_docker_secure; read -p "Enter..." ;;
            6) uninstall_bot; install_docker_root; read -p "Enter..." ;;
            8) uninstall_bot; install_node_logic; read -p "Enter..." ;;
            0) break ;;
            *) ;;
        esac
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Root required."; exit 1; fi

check_integrity
if [ "$INSTALL_TYPE" == "NONE" ] || [[ "$STATUS_MESSAGE" == *"corrupted"* ]]; then
    echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║      Install VPS Telegram Bot     ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    echo -e "  ${C_YELLOW}Bot not found or corrupted.${C_RESET}"
    echo "--------------------------------------------------------"
    echo "  1) AGENT (Systemd - Secure)"
    echo "  2) AGENT (Systemd - Root)"
    echo "  3) AGENT (Docker - Secure)"
    echo "  4) AGENT (Docker - Root)"
    echo -e "${C_GREEN}  8) NODE (Client)${C_RESET}"
    echo "  0) Exit"
    echo "--------------------------------------------------------"
    read -p "$(echo -e "${C_BOLD}Choice: ${C_RESET}")" install_choice
    rm -f /tmp/${SERVICE_NAME}_install.log
    case $install_choice in
        1) uninstall_bot; install_systemd_secure; main_menu ;;
        2) uninstall_bot; install_systemd_root; main_menu ;;
        3) uninstall_bot; install_docker_secure; main_menu ;;
        4) uninstall_bot; install_docker_root; main_menu ;;
        8) uninstall_bot; install_node_logic; main_menu ;;
        0) exit 0 ;;
        *) msg_error "Invalid choice."; exit 1 ;;
    esac
else
    main_menu
fi