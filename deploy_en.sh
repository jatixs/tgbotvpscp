#!/bin/bash

orig_arg1="$1"

# --- Configuration ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
# --- NEW: Node service name ---
NODE_SERVICE_NAME="tg-node"
# ------------------------------
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

    # --- CHECK NODE MODE ---
    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="NODE (Client)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then
             STATUS_MESSAGE="${C_GREEN}Active${C_RESET}"
        else
             STATUS_MESSAGE="${C_RED}Inactive${C_RESET}"
        fi
        return
    fi

    # Agent check (Docker/Systemd)
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "unknown")

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="AGENT (Docker - $INSTALL_MODE_FROM_ENV)"
        if ! command -v docker &> /dev/null; then STATUS_MESSAGE="${C_RED}Docker missing.${C_RESET}"; return; fi
        if [ ! -f "${DOCKER_COMPOSE_FILE}" ]; then STATUS_MESSAGE="${C_RED}Missing docker-compose.yml.${C_RESET}"; return; fi
        
        local bot_container_name=$(grep '^TG_BOT_CONTAINER_NAME=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ -z "$bot_container_name" ]; then bot_container_name="tg-bot-${INSTALL_MODE_FROM_ENV}"; fi
        local watchdog_container_name="tg-watchdog"
        
        local bot_status; local watchdog_status;
        if docker ps -f "name=${bot_container_name}" --format '{{.Names}}' | grep -q "${bot_container_name}"; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi
        if docker ps -f "name=${watchdog_container_name}" --format '{{.Names}}' | grep -q "${watchdog_container_name}"; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi
        
        STATUS_MESSAGE="Docker OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"

    else # Systemd
        INSTALL_TYPE="AGENT (Systemd - $INSTALL_MODE_FROM_ENV)"
        if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ]; then STATUS_MESSAGE="${C_RED}Files corrupted.${C_RESET}"; return; fi;
        
        local bot_status; local watchdog_status;
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi;
        if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi;
        STATUS_MESSAGE="Systemd OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"
    fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Updating packages and installing base dependencies..."
    run_with_spinner "Updating apt" sudo apt-get update -y || { msg_error "Failed to update packages"; exit 1; }
    run_with_spinner "Installing dependencies (python3, pip, venv, git, curl, wget, sudo, yaml)" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo python3-yaml || { msg_error "Failed to install dependencies"; exit 1; }
}

setup_repo_and_dirs() {
    local owner_user=$1
    if [ -z "$owner_user" ]; then owner_user="root"; fi

    sudo mkdir -p ${BOT_INSTALL_PATH}
    msg_info "Cloning repository (branch ${GIT_BRANCH})..."
    run_with_spinner "Cloning repo" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    
    msg_info "Creating directories..."
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    
    # Set owner
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

# --- Agent Installation Functions ---
install_extras() {
    local packages_to_install=()
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban not found. Install? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then packages_to_install+=("fail2ban"); fi
    fi
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 not found. Install? (y/n): " INSTALL_IPERF3
        if [[ "$INSTALL_IPERF3" =~ ^[Yy]$ ]]; then packages_to_install+=("iperf3"); fi
    fi
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        run_with_spinner "Installing extra packages" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages_to_install[@]}"
    fi
}

ask_env_details() {
    msg_info "Entering .env details..."
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
    if ! command -v docker &> /dev/null; then
        msg_info "Installing Docker..."
        curl -sSL https://get.docker.com -o /tmp/get-docker.sh
        run_with_spinner "Install Docker" sudo sh /tmp/get-docker.sh
    fi
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
FROM python:3.10-slim-bookworm
RUN apt-get update && apt-get install -y python3-yaml iperf3 git curl wget sudo procps iputils-ping net-tools gnupg docker.io coreutils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir docker
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
}

create_and_start_service() { 
    local svc=$1; local script=$2; local mode=$3; local desc=$4
    local user="root"; if [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ]; then user=${SERVICE_USER}; fi
    msg_info "Creating ${svc}.service..."
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
    sudo systemctl daemon-reload
    sudo systemctl enable ${svc} &> /dev/null
    sudo systemctl restart ${svc}
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
    msg_success "Systemd Installation Complete!"
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
    msg_success "Docker Installation Complete!"
}

# --- NEW LOGIC: NODE INSTALLATION ---
install_node_logic() {
    echo -e "\n${C_BOLD}=== Installing NODE (Client) ===${C_RESET}"
    common_install_steps
    setup_repo_and_dirs "root" # Node runs as root for system access
    
    msg_info "Setting up virtual environment..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Creating venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Installing psutil requests" "${VENV_PATH}/bin/pip" install psutil requests
    
    echo ""
    msg_info "Agent Connection Setup:"
    msg_question "Agent URL (e.g. http://1.2.3.4:8080): " AGENT_URL
    msg_question "Node Token (received from bot): " NODE_TOKEN
    
    msg_info "Creating .env..."
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=10
EOF
    sudo chmod 600 "${ENV_FILE}"

    msg_info "Creating service ${NODE_SERVICE_NAME}..."
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
    
    sudo systemctl daemon-reload
    sudo systemctl enable ${NODE_SERVICE_NAME}
    run_with_spinner "Starting Node" sudo systemctl restart ${NODE_SERVICE_NAME}
    
    msg_success "Node installed and running!"
    msg_info "Logs: sudo journalctl -u ${NODE_SERVICE_NAME} -f"
}

# --- Uninstall ---
uninstall_bot() {
    echo -e "\n${C_BOLD}=== Uninstalling ===${C_RESET}"
    sudo systemctl stop ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo systemctl disable ${SERVICE_NAME} ${WATCHDOG_SERVICE_NAME} ${NODE_SERVICE_NAME} &> /dev/null
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then
        cd ${BOT_INSTALL_PATH} && sudo docker-compose down -v --remove-orphans &> /dev/null
    fi
    
    sudo rm -rf "${BOT_INSTALL_PATH}"
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Uninstall complete."
}

# --- Menu ---
main_menu() {
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}   VPS Bot Manager${C_RESET}"
        check_integrity
        echo "   Type: ${INSTALL_TYPE} | Status: ${STATUS_MESSAGE}"
        echo "---------------------------------"
        echo "1) Update"
        echo "2) Uninstall"
        echo "---------------------------------"
        echo "3) Install AGENT (Systemd - Secure)"
        echo "4) Install AGENT (Systemd - Root)"
        echo "5) Install AGENT (Docker - Secure)"
        echo "6) Install AGENT (Docker - Root)"
        echo "---------------------------------"
        echo -e "${C_GREEN}8) Install NODE (Client)${C_RESET}"
        echo "---------------------------------"
        echo "0) Exit"
        read -p "Choice: " choice
        
        case $choice in
            1) # Update logic
               cd ${BOT_INSTALL_PATH} && git pull
               msg_success "Updated. Restart services."
               read -p "Enter..." ;;
            2) uninstall_bot; read -p "Enter..." ;;
            3) uninstall_bot; install_systemd_logic "secure"; read -p "Enter..." ;;
            4) uninstall_bot; install_systemd_logic "root"; read -p "Enter..." ;;
            5) uninstall_bot; install_docker_logic "secure"; read -p "Enter..." ;;
            6) uninstall_bot; install_docker_logic "root"; read -p "Enter..." ;;
            8) uninstall_bot; install_node_logic; read -p "Enter..." ;;
            0) exit 0 ;;
            *) ;;
        esac
    done
}

# --- Start ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Root required."; exit 1; fi

check_integrity
if [ "$INSTALL_TYPE" == "NONE" ]; then
    main_menu
else
    main_menu
fi