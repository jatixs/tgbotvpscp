#!/bin/bash

# --- Remember the original argument ---
orig_arg1="$1"

# --- Configuration ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"
README_FILE="${BOT_INSTALL_PATH}/README.en.md" # <-- English README
# --- DOCKER VARS ADDED ---
DOCKER_COMPOSE_FILE="${BOT_INSTALL_PATH}/docker-compose.yml"
ENV_FILE="${BOT_INSTALL_PATH}/.env"

# --- GitHub Repository and Branch ---
GITHUB_REPO="jatixs/tgbotvpscp"
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

# --- Colors and output functions ---
C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }; msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }
spinner() { local pid=$1; local msg=$2; local spin='|/-\'; local i=0; while kill -0 $pid 2>/dev/null; do i=$(( (i+1) %4 )); printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"; sleep .1; done; printf "\r"; }
run_with_spinner() { local msg=$1; shift; ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) & local pid=$!; spinner "$pid" "$msg"; wait $pid; local exit_code=$?; echo -ne "\033[2K\r"; if [ $exit_code -ne 0 ]; then msg_error "Error during '$msg'. Code: $exit_code"; msg_error "Log: /tmp/${SERVICE_NAME}_install.log"; fi; return $exit_code; }

# --- Check downloader ---
if command -v wget &> /dev/null; then DOWNLOADER="wget -qO-"; elif command -v curl &> /dev/null; then DOWNLOADER="curl -sSLf"; else msg_error "Neither wget nor curl found."; exit 1; fi
if command -v curl &> /dev/null; then DOWNLOADER_PIPE="curl -s"; else DOWNLOADER_PIPE="wget -qO-"; fi

# --- Version functions ---
get_local_version() { local readme_path="$1"; local version="Not found"; if [ -f "$readme_path" ]; then version=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$readme_path" || true); if [ -z "$version" ]; then version=$(grep -oP '<b\s*>v\K[\d\.]+(?=</b>)' "$readme_path" || true); fi; if [ -z "$version" ]; then version="Not found"; else version="v$version"; fi; else version="Not installed"; fi; echo "$version"; }
get_latest_version() { local api_url="$1"; local latest_tag=$($DOWNLOADER_PIPE "$api_url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "API Error"); if [[ "$latest_tag" == *"API rate limit exceeded"* ]]; then latest_tag="API Limit"; elif [[ "$latest_tag" == "API Error" ]] || [ -z "$latest_tag" ]; then latest_tag="Unknown"; fi; echo "$latest_tag"; }

# --- [HEAVILY MODIFIED] Integrity Check ---
INSTALL_TYPE="NONE"; STATUS_MESSAGE="Check not performed."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="NONE"; STATUS_MESSAGE="Bot not installed."; return;
    fi

    # Determine installation type (Docker or Systemd)
    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "unknown")

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="DOCKER ($INSTALL_MODE_FROM_ENV)"
        # --- [FIXED] Check both docker-compose and docker compose ---
        if ! command -v docker &> /dev/null; then
            STATUS_MESSAGE="${C_RED}Docker installation corrupted (Docker not found).${C_RESET}"; return;
        fi
        if ! (command -v docker-compose &> /dev/null || docker compose version &> /dev/null); then
            STATUS_MESSAGE="${C_RED}Docker installation corrupted (Docker Compose not found).${C_RESET}"; return;
        fi
        if [ ! -f "${DOCKER_COMPOSE_FILE}" ]; then
            STATUS_MESSAGE="${C_RED}Docker installation corrupted (Missing docker-compose.yml).${C_RESET}"; return;
        fi
        
        local bot_container_name=$(grep '^TG_BOT_CONTAINER_NAME=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ -z "$bot_container_name" ]; then
            bot_container_name="tg-bot-${INSTALL_MODE_FROM_ENV}" # Fallback
        fi
        local watchdog_container_name="tg-watchdog"
        
        local bot_status; local watchdog_status;
        if docker ps -f "name=${bot_container_name}" --format '{{.Names}}' | grep -q "${bot_container_name}"; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi
        if docker ps -f "name=${watchdog_container_name}" --format '{{.Names}}' | grep -q "${watchdog_container_name}"; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi
        
        STATUS_MESSAGE="Docker installation OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"

    else # Systemd
        INSTALL_TYPE="SYSTEMD ($INSTALL_MODE_FROM_ENV)"
        INSTALL_STATUS="OK"; local errors=();
        if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || [ ! -d "${BOT_INSTALL_PATH}/core" ] || [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then errors+=("- Missing core files"); INSTALL_STATUS="PARTIAL"; fi;
        if [ ! -f "${VENV_PATH}/bin/python" ]; then errors+=("- Missing venv"); INSTALL_STATUS="PARTIAL"; fi;
        if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then errors+=("- Missing ${SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi;
        if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then errors+=("- Missing ${WATCHDOG_SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi;
        
        if [ "$INSTALL_STATUS" == "OK" ]; then
            local bot_status; local watchdog_status;
            if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi;
            if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi;
            STATUS_MESSAGE="Systemd installation OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"
        else
            STATUS_MESSAGE="${C_RED}Systemd installation corrupted.${C_RESET}\n  Issue: ${errors[0]}"
        fi
    fi
}


# --- Installation functions ---
install_extras() {
    local packages_to_install=()
    local packages_to_remove=()

    # Fail2Ban Check
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban not found. Install? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then
            packages_to_install+=("fail2ban")
        else
            msg_info "Skipping Fail2Ban."
        fi
    else
        msg_success "Fail2Ban already installed."
    fi

    # iperf3 Check
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 not found. It is required for the 'Speedtest' module. Install? (y/n): " INSTALL_IPERF3
        if [[ "$INSTALL_IPERF3" =~ ^[Yy]$ ]]; then
            packages_to_install+=("iperf3")
        else
            msg_info "Skipping iperf3. The 'Speedtest' module will not work."
        fi
    else
        msg_success "iperf3 is already installed."
    fi

    # Speedtest CLI Check for removal
    if command -v speedtest &> /dev/null || dpkg -s speedtest-cli &> /dev/null; then
        msg_warning "Detected old 'speedtest-cli' package."
        msg_question "Remove 'speedtest-cli'? (Recommended, as the bot now uses iperf3) (y/n): " REMOVE_SPEEDTEST
        if [[ "$REMOVE_SPEEDTEST" =~ ^[Yy]$ ]]; then
            packages_to_remove+=("speedtest-cli")
        else
            msg_info "Skipping removal of speedtest-cli."
        fi
    fi

    # Package Removal
    if [ ${#packages_to_remove[@]} -gt 0 ]; then
        msg_info "Removing packages: ${packages_to_remove[*]}"
        run_with_spinner "Removing packages" sudo apt-get remove --purge -y "${packages_to_remove[@]}"
        run_with_spinner "Cleaning up apt" sudo apt-get autoremove -y
        msg_success "Specified packages removed."
    fi

    # Package Installation
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Installing additional packages: ${packages_to_install[*]}"
        run_with_spinner "Updating package list" sudo apt-get update -y
        run_with_spinner "Installing packages" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages_to_install[@]}"
        if [ $? -ne 0 ]; then msg_error "Error installing additional packages."; exit 1; fi

        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then
             sudo systemctl enable fail2ban &> /dev/null
             sudo systemctl start fail2ban &> /dev/null
             msg_success "Fail2Ban installed and started."
        fi
        if [[ " ${packages_to_install[*]} " =~ " iperf3 " ]]; then
             msg_success "iperf3 installed."
        fi
        msg_success "Additional packages installed."
    fi
}
# --- [MODIFIED] common_install_steps ---
common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Updating packages and installing basic dependencies..."
    run_with_spinner "Updating package list" sudo apt-get update -y || { msg_error "Failed to update packages"; exit 1; }
    # Added python3-yaml to dependencies
    run_with_spinner "Installing dependencies (python3, pip, venv, git, curl, wget, sudo, yaml)" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo python3-yaml || { msg_error "Failed to install basic dependencies"; exit 1; }
    # --- [FIXED] install_extras is no longer called here ---
}
# --- [END MODIFIED] common_install_steps ---

# --- NEW FUNCTION: Ask .env details ---
ask_env_details() {
    msg_info "Please enter details for the .env file..."
    msg_question "Bot Token (TG_BOT_TOKEN): " T
    msg_question "Admin User ID (TG_ADMIN_ID): " A
    msg_question "Admin Username (TG_ADMIN_USERNAME, optional): " U
    msg_question "Bot Name (TG_BOT_NAME, optional, e.g., 'My VPS'): " N
    
    # Export them for use in calling functions
    export T A U N
}

# --- NEW FUNCTION: Write .env ---
write_env_file() {
    local deploy_mode=$1 # "systemd" or "docker"
    local install_mode=$2 # "secure" or "root"
    local container_name=$3 # "tg-bot-secure" / "tg-bot-root" / ""

    msg_info "Creating .env file..."
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
# --- Telegram Bot Settings ---
TG_BOT_TOKEN="${T}"
TG_ADMIN_ID="${A}"
TG_ADMIN_USERNAME="${U}"
TG_BOT_NAME="${N}"

# --- Deployment Settings (DO NOT EDIT MANUALLY) ---
INSTALL_MODE="${install_mode}"
DEPLOY_MODE="${deploy_mode}"
TG_BOT_CONTAINER_NAME="${container_name}"
EOF
    sudo chmod 600 "${ENV_FILE}"
    msg_success ".env file created."
}

# --- NEW FUNCTION: Clone repo and set up dirs ---
setup_repo_and_dirs() {
    local owner_user="root"
    if [ "$1" == "secure" ]; then
        msg_info "Creating user '${SERVICE_USER}'..."
        if ! id "${SERVICE_USER}" &>/dev/null; then
            sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || exit 1
        fi
        owner_user=${SERVICE_USER}
    fi
    
    sudo mkdir -p ${BOT_INSTALL_PATH}
    msg_info "Cloning repository (branch ${GIT_BRANCH})..."
    run_with_spinner "Cloning repository" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    
    msg_info "Creating .gitignore, logs/, config/..."
    # [FIXED] Do not ignore docker-compose.yml
    sudo -u ${owner_user} bash -c "cat > ${BOT_INSTALL_PATH}/.gitignore" <<< $'/venv/\n/__pycache__/\n*.pyc\n/.env\n/config/\n/logs/\n*.log\n*_flag.txt'
    sudo chmod 644 "${BOT_INSTALL_PATH}/.gitignore"
    sudo -u ${owner_user} mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/config"
    
    # Set owner for everything except .git
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
    sudo chown -R root:root ${BOT_INSTALL_PATH}/.git
    
    # Export owner for .env
    export OWNER_USER=${owner_user}
}

# --- [FIXED] NEW FUNCTION: Check Docker ---
check_docker_deps() {
    msg_info "Checking Docker dependencies..."
    if ! command -v docker &> /dev/null; then
        msg_warning "Docker not found. Attempting installation..."
        run_with_spinner "Installing Docker (docker.io)" sudo apt-get install -y docker.io || { msg_error "Failed to install docker.io."; exit 1; }
        sudo systemctl start docker
        sudo systemctl enable docker
    else
        msg_success "Docker found."
    fi
    
    # Check for v2 (docker compose) and v1 (docker-compose)
    if command -v docker-compose &> /dev/null; then
        msg_success "Docker Compose v1 (docker-compose) found."
    elif docker compose version &> /dev/null; then
        msg_success "Docker Compose v2 (docker compose) found."
    else
        msg_warning "Docker Compose not found. Attempting installation..."
        
        # Try 1: Install v2 plugin via apt
        msg_info "Attempt 1: Installing 'docker-compose-plugin' via apt..."
        sudo apt-get install -y docker-compose-plugin &> /tmp/${SERVICE_NAME}_install.log
        
        if docker compose version &> /dev/null; then
            msg_success "Successfully installed 'docker-compose-plugin' (v2) via apt."
        else
            msg_warning "Failed to install v2 via apt. Attempt 2: Installing v1 ('docker-compose') via apt..."
            # Try 2: Install v1 via apt
            sudo apt-get install -y docker-compose &> /tmp/${SERVICE_NAME}_install.log
            
            if command -v docker-compose &> /dev/null; then
                 msg_success "Successfully installed 'docker-compose' (v1) via apt."
            else
                msg_warning "Failed to install v1 via apt. Attempt 3: Downloading v2 binary..."
                # Try 3: Download v2 binary (most reliable)
                local DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
                if [ -z "$DOCKER_COMPOSE_VERSION" ] || [[ "$DOCKER_COMPOSE_VERSION" == *"API rate limit"* ]]; then
                    msg_error "Could not determine latest Docker Compose version from GitHub (API rate limit?)."
                    msg_error "Please install Docker Compose (v1 or v2) manually."
                    exit 1;
                fi
                
                local LATEST_COMPOSE_URL="https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)"
                local DOCKER_CLI_PLUGIN_DIR="/usr/libexec/docker/cli-plugins"
                local DOCKER_COMPOSE_PATH="${DOCKER_CLI_PLUGIN_DIR}/docker-compose"

                sudo mkdir -p ${DOCKER_CLI_PLUGIN_DIR}
                
                msg_info "Downloading Docker Compose ${DOCKER_COMPOSE_VERSION} to ${DOCKER_COMPOSE_PATH}..."
                run_with_spinner "Downloading docker-compose" sudo curl -SLf "${LATEST_COMPOSE_URL}" -o "${DOCKER_COMPOSE_PATH}"
                if [ $? -ne 0 ]; then
                    msg_error "Failed to download Docker Compose from ${LATEST_COMPOSE_URL}."
                    msg_error "Please install Docker Compose (v1 or v2) manually."
                    exit 1;
                fi
                
                sudo chmod +x "${DOCKER_COMPOSE_PATH}"
                
                # Check again
                if docker compose version &> /dev/null; then
                    msg_success "Successfully installed Docker Compose v2 (binary)."
                else
                    msg_error "Failed to install Docker Compose. Please install it manually."
                    exit 1;
                fi
            fi
        fi
    fi
}


# --- Old installation functions (Systemd) ---
create_and_start_service() { local svc=$1; local script=$2; local mode=$3; local desc=$4; local user="root"; local group="root"; local env=""; local suffix=""; local after="After=network.target"; local req=""; if [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ]; then user=${SERVICE_USER}; group=${SERVICE_USER}; suffix="(Secure)"; elif [ "$svc" == "$SERVICE_NAME" ]; then user="root"; group="root"; suffix="(Root)"; elif [ "$svc" == "$WATCHDOG_SERVICE_NAME" ]; then user="root"; group="root"; after="After=network.target ${SERVICE_NAME}.service"; fi; env="EnvironmentFile=${BOT_INSTALL_PATH}/.env"; msg_info "Creating systemd unit for ${svc}..."; FILE="/etc/systemd/system/${svc}.service"; sudo tee ${FILE} > /dev/null <<EOF
[Unit]
Description=${desc} Service ${suffix}
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
msg_info "Starting ${svc}..."; sudo systemctl daemon-reload; sudo systemctl enable ${svc}.service &> /dev/null; run_with_spinner "Starting ${svc}" sudo systemctl restart ${svc}; sleep 2; if sudo systemctl is-active --quiet ${svc}.service; then msg_success "${svc} started!"; msg_info "Status: sudo systemctl status ${svc}"; else msg_error "${svc} FAILED TO START. Logs: sudo journalctl -u ${svc} -n 50 --no-pager"; if [ "$svc" == "$SERVICE_NAME" ]; then exit 1; fi; fi; }

install_systemd_logic() { 
    local mode=$1 # "secure" or "root"
    local branch_to_use=$2
    
    common_install_steps
    # --- [FIXED] Call install_extras here for Systemd ---
    install_extras
    # -----------------------------------------------
    setup_repo_and_dirs "$mode" # Clones repo and creates user/dirs
    
    local exec_user_cmd=""
    if [ "$mode" == "secure" ]; then
        exec_user_cmd="sudo -u ${SERVICE_USER}"
    fi

    msg_info "Configuring venv for Systemd..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Creating venv" $exec_user_cmd ${PYTHON_BIN} -m venv "${VENV_PATH}" || exit 1; fi;
    run_with_spinner "Updating pip" $exec_user_cmd "${VENV_PATH}/bin/pip" install --upgrade pip || msg_warning "Failed to update pip...";
    run_with_spinner "Installing Python dependencies" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" || exit 1;
    
    ask_env_details # Asks for T, A, U, N
    write_env_file "systemd" "$mode" "" # Writes .env
    sudo chown ${OWNER_USER}:${OWNER_USER} "${ENV_FILE}" # Sets .env owner
    
    if [ "$mode" == "root" ]; then msg_info "Configuring sudo (root)..."; F="/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo tee ${F} > /dev/null <<< $'root ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-bot.service\nroot ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-watchdog.service\nroot ALL=(ALL) NOPASSWD: /sbin/reboot'; sudo chmod 440 ${F}; elif [ "$mode" == "secure" ]; then F="/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo tee ${F} > /dev/null <<< $'Defaults:tgbot !requiretty\ntgbot ALL=(root) NOPASSWD: /bin/systemctl restart tg-bot.service'; sudo chmod 440 ${F}; msg_info "Configuring sudo (secure)..."; fi;
    
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "${mode}" "Telegram Bot";
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog";
    
    local ip=$(curl -s --connect-timeout 5 ipinfo.io/ip || echo "Could not determine"); echo ""; echo "---"; msg_success "Installation (Systemd) complete!"; msg_info "IP: ${ip}"; echo "---";
}

install_systemd_secure() { echo -e "\n${C_BOLD}=== Install Systemd (Secure) (branch: ${GIT_BRANCH}) ===${C_RESET}"; install_systemd_logic "secure" "${GIT_BRANCH}"; }
install_systemd_root() { echo -e "\n${C_BOLD}=== Install Systemd (Root) (branch: ${GIT_BRANCH}) ===${C_RESET}"; install_systemd_logic "root" "${GIT_BRANCH}"; }

# --- [FIXED] NEW Installation functions (Docker) ---
create_dockerfile() {
    msg_info "Creating Dockerfile..."
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
# /opt/tg-bot/Dockerfile
FROM python:3.10-slim-bookworm
LABEL maintainer="Jatixs"
LABEL description="Telegram VPS Bot"
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
    docker.io \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir docker
RUN groupadd -g 1001 tgbot && \
    useradd -u 1001 -g 1001 -m -s /bin/bash tgbot && \
    echo "tgbot ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
WORKDIR /opt/tg-bot
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /opt/tg-bot/config /opt/tg-bot/logs/bot /opt/tg-bot/logs/watchdog && \
    chown -R tgbot:tgbot /opt/tg-bot
USER tgbot
CMD ["python", "bot.py"]
EOF
    sudo chown ${OWNER_USER}:${OWNER_USER} "${BOT_INSTALL_PATH}/Dockerfile"
    sudo chmod 644 "${BOT_INSTALL_PATH}/Dockerfile"
}

create_docker_compose_yml() {
    msg_info "Creating docker-compose.yml..."
    sudo tee "${BOT_INSTALL_PATH}/docker-compose.yml" > /dev/null <<'EOF'
# /opt/tg-bot/docker-compose.yml
version: '3.8'
services:
  bot-base: &bot-base
    build: .
    image: tg-vps-bot:latest
    restart: always
    env_file: .env
  bot-secure:
    <<: *bot-base
    container_name: tg-bot-secure
    profiles: ["secure"]
    user: "tgbot"
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
    sudo chmod 644 "${BOT_INSTALL_PATH}/docker-compose.yml"
}


install_docker_logic() {
    local mode=$1 # "secure" or "root"
    local branch_to_use=$2
    local container_name="tg-bot-${mode}"
    
    check_docker_deps # Checks/installs docker and compose
    # --- [FIXED] Call install_extras for Docker ---
    install_extras
    # -------------------------------------------
    setup_repo_and_dirs "$mode" # Clones repo and creates user/dirs
    
    # --- [FIXED] Create files BEFORE build ---
    create_dockerfile
    create_docker_compose_yml
    # ----------------------------------------

    ask_env_details # Asks for T, A, U, N
    write_env_file "docker" "$mode" "$container_name" # Writes .env
    sudo chown ${OWNER_USER}:${OWNER_USER} "${ENV_FILE}" # Sets .env owner

    # --- [FIXED] Determine compose command ---
    local COMPOSE_CMD=""
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="sudo docker-compose"
    elif docker compose version &> /dev/null; then
        COMPOSE_CMD="sudo docker compose"
    else
        msg_error "[Install] docker-compose command not found. Docker installation aborted."
        exit 1
    fi

    msg_info "Building Docker image..."
    (cd ${BOT_INSTALL_PATH} && run_with_spinner "Building image tg-vps-bot:latest" $COMPOSE_CMD build) || { msg_error "Docker build failed."; exit 1; }
    
    msg_info "Starting Docker Compose (Profile: ${mode})..."
    # --- [FIXED] Added --remove-orphans ---
    (cd ${BOT_INSTALL_PATH} && run_with_spinner "Starting containers" $COMPOSE_CMD --profile "${mode}" up -d --remove-orphans) || { msg_error "Docker Compose failed to start."; exit 1; }
    
    sleep 2
    msg_success "Installation (Docker) complete!"
    msg_info "Containers:"
    (cd ${BOT_INSTALL_PATH} && $COMPOSE_CMD ps)
    msg_info "Bot logs: $COMPOSE_CMD logs -f ${container_name}"
    msg_info "Watchdog logs: $COMPOSE_CMD logs -f tg-watchdog"
}

install_docker_secure() { echo -e "\n${C_BOLD}=== Install Docker (Secure) (branch: ${GIT_BRANCH}) ===${C_RESET}"; install_docker_logic "secure" "${GIT_BRANCH}"; }
install_docker_root() { echo -e "\n${C_BOLD}=== Install Docker (Root) (branch: ${GIT_BRANCH}) ===${C_RESET}"; install_docker_logic "root" "${GIT_BRANCH}"; }


# --- [HEAVILY MODIFIED] Uninstall function ---
uninstall_bot() {
    echo -e "\n${C_BOLD}=== Uninstalling Bot ===${C_RESET}";
    
    # 1. Stop Systemd
    msg_info "1. Stopping Systemd services (if any)...";
    if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then
        sudo systemctl stop ${SERVICE_NAME} &> /dev/null
        sudo systemctl disable ${SERVICE_NAME} &> /dev/null
    fi
    if systemctl list-units --full -all | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then
        sudo systemctl stop ${WATCHDOG_SERVICE_NAME} &> /dev/null
        sudo systemctl disable ${WATCHDOG_SERVICE_NAME} &> /dev/null
    fi
    
    # 2. Stop Docker
    if [ -f "${DOCKER_COMPOSE_FILE}" ]; then
        msg_info "2. Stopping Docker containers (if any)...";
        # --- [FIXED] Determine compose command ---
        local COMPOSE_CMD=""
        if command -v docker-compose &> /dev/null; then
            COMPOSE_CMD="sudo docker-compose"
        elif docker compose version &> /dev/null; then
            COMPOSE_CMD="sudo docker compose"
        fi
        
        if [ -n "$COMPOSE_CMD" ]; then
            (cd ${BOT_INSTALL_PATH} && $COMPOSE_CMD down -v --remove-orphans &> /tmp/${SERVICE_NAME}_install.log)
        else
            msg_warning "Could not find docker-compose/docker compose command to stop containers."
        fi
    fi
    
    # 3. Remove Systemd files
    msg_info "3. Removing system files (systemd, sudoers)...";
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service"
    sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"
    sudo rm -f "/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"
    sudo systemctl daemon-reload
    
    # 4. Remove bot directory
    msg_info "4. Removing bot directory (${BOT_INSTALL_PATH})...";
    sudo rm -rf "${BOT_INSTALL_PATH}"
    
    # 5. Remove user
    msg_info "5. Removing user '${SERVICE_USER}' (if any)...";
    if id "${SERVICE_USER}" &>/dev/null; then
        sudo userdel -r "${SERVICE_USER}" &> /dev/null || msg_warning "Could not completely remove user ${SERVICE_USER}."
    fi

    # 6. Remove Docker image (optional)
    if command -v docker &> /dev/null && docker image inspect tg-vps-bot:latest &> /dev/null; then
        msg_question "Remove Docker image 'tg-vps-bot:latest'? (y/n): " confirm_docker_rmi
        if [[ "$confirm_docker_rmi" =~ ^[Yy]$ ]]; then
            sudo docker rmi tg-vps-bot:latest &> /dev/null
        fi
    fi
    
    msg_success "Uninstallation complete.";
}

# --- [HEAVILY MODIFIED] Update function ---
update_bot() {
    echo -e "\n${C_BOLD}=== Updating Bot (branch: ${GIT_BRANCH}) ===${C_RESET}";
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git repository not found. Cannot update."; return 1; fi
    
    local exec_user="";
    if [ ! -f "${ENV_FILE}" ]; then msg_error ".env file not found. Cannot determine update mode."; return 1; fi
    
    local DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    local INSTALL_MODE_FROM_ENV=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    
    if [ "$INSTALL_MODE_FROM_ENV" == "secure" ]; then
        exec_user="sudo -u ${SERVICE_USER}"
    fi

    msg_warning "Update will overwrite local changes.";
    msg_warning ".env, config/, logs/ will be preserved.";
    
    msg_info "1. Fetching updates (branch ${GIT_BRANCH})...";
    pushd "${BOT_INSTALL_PATH}" > /dev/null;
    run_with_spinner "Git fetch" $exec_user git fetch origin;
    run_with_spinner "Git reset --hard" $exec_user git reset --hard "origin/${GIT_BRANCH}";
    local st=$?;
    popd > /dev/null;
    if [ $st -ne 0 ]; then msg_error "Git update failed."; return 1; fi;
    msg_success "Project files updated.";

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        # --- [FIXED] Determine compose command ---
        local COMPOSE_CMD=""
        if command -v docker-compose &> /dev/null; then
            COMPOSE_CMD="sudo docker-compose"
        elif docker compose version &> /dev/null; then
            COMPOSE_CMD="sudo docker compose"
        else
            msg_error "[Update] docker-compose command not found. Docker update aborted."
            return 1
        fi
        
        # --- [FIXED] Create files if missing ---
        if [ ! -f "${BOT_INSTALL_PATH}/Dockerfile" ]; then create_dockerfile; fi
        if [ ! -f "${BOT_INSTALL_PATH}/docker-compose.yml" ]; then create_docker_compose_yml; fi

        msg_info "2. [Docker] Rebuilding image...";
        (cd ${BOT_INSTALL_PATH} && run_with_spinner "Building Docker image" $COMPOSE_CMD build) || { msg_error "Docker build failed."; return 1; }
        msg_info "3. [Docker] Restarting containers (Profile: ${INSTALL_MODE_FROM_ENV})...";
        # --- [FIXED] Added --remove-orphans ---
        (cd ${BOT_INSTALL_PATH} && run_with_spinner "Restarting Docker Compose" $COMPOSE_CMD --profile "${INSTALL_MODE_FROM_ENV}" up -d --remove-orphans) || { msg_error "Docker Compose restart failed."; return 1; }
    
    else # Systemd
        msg_info "2. [Systemd] Updating Python dependencies...";
        run_with_spinner "Pip install" $exec_user "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade;
        if [ $? -ne 0 ]; then msg_error "Pip install failed."; return 1; fi;
        
        msg_info "3. [Systemd] Restarting services...";
        if sudo systemctl restart ${SERVICE_NAME}; then msg_success "${SERVICE_NAME} restarted."; else msg_error "Failed to restart ${SERVICE_NAME}."; return 1; fi;
        sleep 1;
        if sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; then msg_success "${WATCHDOG_SERVICE_NAME} restarted."; else msg_error "Failed to restart ${WATCHDOG_SERVICE_NAME}."; fi;
    fi

    echo -e "\n${C_GREEN}${C_BOLD}🎉 Update complete!${C_RESET}\n";
}


# --- [HEAVILY MODIFIED] Management Menu ---
main_menu() {
    local local_version=$(get_local_version "$README_FILE")
    local latest_version=$(get_latest_version "$GITHUB_API_URL")
    
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║    VPS Telegram Bot Manager       ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        
        local current_branch=$(cd "$BOT_INSTALL_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Not installed")
        echo -e "  Current branch (installed): ${C_YELLOW}${current_branch}${C_RESET}"
        echo -e "  Target branch (for action): ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "  Local version: ${C_GREEN}${local_version}${C_RESET}"
        echo -e "  Latest version: ${C_CYAN}${latest_version}${C_RESET}"
        if [ -z "$orig_arg1" ] && [ "$GIT_BRANCH" == "main" ]; then
            echo -e "  ${C_YELLOW}(Hint: To act on a different branch, run:${C_RESET}";
            echo -e "  ${C_YELLOW} sudo bash $0 <branch_name>)${C_RESET}";
        fi
        
        check_integrity # Check status
        echo "--------------------------------------------------------"
        echo -n -e "  Install Type: ${C_GREEN}${INSTALL_TYPE}${C_RESET}\n"
        echo -n -e "  Status: ";
        if [[ "$STATUS_MESSAGE" == *"OK"* ]]; then
            echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"
        else
            echo -e "${C_RED}${STATUS_MESSAGE}${C_RESET}"
            msg_warning "  Reinstallation recommended."
        fi
        echo "--------------------------------------------------------"
        echo -e "  ${C_BOLD}MANAGEMENT:${C_RESET}"
        echo -e "  1) ${C_CYAN}${C_BOLD}Update bot:${C_RESET}                 ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "  2) ${C_RED}${C_BOLD}Uninstall bot${C_RESET}"
        echo -e "\n  ${C_BOLD}REINSTALL (Branch: ${C_YELLOW}${GIT_BRANCH}${C_RESET}):"
        echo -e "  3) ${C_GREEN}Install (Systemd - Secure)${C_RESET}"
        echo -e "  4) ${C_YELLOW}Install (Systemd - Root)${C_RESET}"
        echo -e "  5) ${C_BLUE}Install (Docker - Secure)${C_RESET}"
        echo -e "  6) ${C_BLUE}Install (Docker - Root)${C_RESET}"
        echo -e "\n  7) ${C_BOLD}Exit${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Enter option number [1-7]: ${C_RESET}")" choice
        
        case $choice in
            1) rm -f /tmp/${SERVICE_NAME}_install.log; update_bot && local_version=$(get_local_version "$README_FILE") ;;
            2) msg_question "Uninstall bot COMPLETELY? (y/n): " confirm_uninstall;
               if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then uninstall_bot; msg_info "Bot uninstalled. Exiting."; return; else msg_info "Uninstallation cancelled."; fi ;;
            
            3) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Reinstall (Systemd - Secure, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_systemd_secure; local_version=$(get_local_version "$README_FILE"); else msg_info "Cancelled."; fi ;;
            4) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Reinstall (Systemd - Root, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_systemd_root; local_version=$(get_local_version "$README_FILE"); else msg_info "Cancelled."; fi ;;
            5) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Reinstall (Docker - Secure, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_docker_secure; local_version=$(get_local_version "$README_FILE"); else msg_info "Cancelled."; fi ;;
            6) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Reinstall (Docker - Root, ${GIT_BRANCH})? (y/n): " confirm;
               if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_docker_root; local_version=$(get_local_version "$README_FILE"); else msg_info "Cancelled."; fi ;;

            7) break ;;
            *) msg_error "Invalid choice." ;;
        esac
        if [[ "$choice" != "2" || ! "$confirm_uninstall" =~ ^[Yy]$ ]]; then
            echo; read -n 1 -s -r -p "Press any key to return to the menu...";
        fi
    done
}

# --- [HEAVILY MODIFIED] Main "Router" ---
main() {
    clear
    msg_info "Starting bot management script (Target branch: ${GIT_BRANCH})..."
    check_integrity # First status check

    if [ "$INSTALL_TYPE" == "NONE" ] || [[ "$STATUS_MESSAGE" == *"corrupted"* ]]; then
        if [[ "$STATUS_MESSAGE" == *"corrupted"* ]]; then
            msg_error "Corrupted installation detected."
            msg_warning "${STATUS_MESSAGE}" # Show problem details
            msg_question "Problems detected. Remove old files and reinstall? (y/n): " confirm_delete
            if [[ "$confirm_delete" =~ ^[Yy]$ ]]; then
                uninstall_bot # Uninstall only if user confirms
            else
                msg_error "Installation cancelled due to corrupted files. Run script again for management.";
                exit 1;
            fi
        fi

        # First Install Menu
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║     VPS Telegram Bot Installer    ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        echo -e "  ${C_YELLOW}Bot not found or installation corrupted.${C_RESET}"
        echo -e "  Select installation mode for branch: ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo "--------------------------------------------------------"
        echo -e "  ${C_BOLD}SYSTEMD MODE (Classic):${C_RESET}"
        echo -e "  1) ${C_GREEN}Secure:${C_RESET}   Recommended (Runs as 'tgbot' user)"
        echo -e "  2) ${C_YELLOW}Root:${C_RESET}     For full access (Runs as 'root')"
        echo ""
        echo -e "  ${C_BOLD}DOCKER MODE (Isolated):${C_RESET}"
        echo -e "  3) ${C_BLUE}Secure:${C_RESET}   Recommended (Limited host access)"
        echo -e "  4) ${C_BLUE}Root:${C_RESET}     For full access (Privileged container)"
        echo ""
        echo -e "  5) ${C_BOLD}Exit${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Enter option number [1-5]: ${C_RESET}")" install_choice

        local install_done=false
        rm -f /tmp/${SERVICE_NAME}_install.log
        
        # --- [FIXED] Added uninstall_bot; before each install ---
        case $install_choice in
            1) uninstall_bot; install_systemd_secure; install_done=true ;;
            2) uninstall_bot; install_systemd_root; install_done=true ;;
            3) uninstall_bot; install_docker_secure; install_done=true ;;
            4) uninstall_bot; install_docker_root; install_done=true ;;
            5) msg_info "Installation cancelled."; exit 0 ;;
            *) msg_error "Invalid choice."; exit 1 ;;
        esac
        # --- [END FIXED] ---

        # Check after installation
        if [ "$install_done" = true ]; then
            msg_info "Verifying after installation...";
            check_integrity; # Check again
            if [[ "$STATUS_MESSAGE" == *"OK"* ]]; then
                msg_success "Installation completed successfully!"
                echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"
                read -n 1 -s -r -p "Press Enter to proceed to the Main Menu..."
                main_menu
                echo -e "\n${C_CYAN}👋 Goodbye!${C_RESET}"
                exit 0
            else
                msg_error "Installation finished with errors!"
                msg_error "${C_RED}${STATUS_MESSAGE}${C_RESET}"
                msg_error "Log: /tmp/${SERVICE_NAME}_install.log";
                exit 1;
            fi
        fi
    else
        # If bot is already installed (INSTALL_TYPE != "NONE"), show management menu
        main_menu;
        echo -e "\n${C_CYAN}👋 Goodbye!${C_RESET}"
    fi
}

# --- Root Check ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Please run this script as root or with sudo."; exit 1; fi

# --- Start ---
main