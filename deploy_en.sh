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
README_FILE="${BOT_INSTALL_PATH}/README.md"

# --- GitHub Repository and Branch ---
GITHUB_REPO="jatixs/tgbotvpscp"
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

# --- Colors and output functions ---
C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }; msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }
spinner() { local pid=$1; local msg=$2; local spin='|/-\'; local i=0; while kill -0 $pid 2>/dev/null; do i=$(( (i+1) %4 )); printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"; sleep .1; done; printf "\r"; }
run_with_spinner() { local msg=$1; shift; ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) & local pid=$!; spinner "$pid" "$msg"; wait $pid; local exit_code=$?; echo -ne "\033[2K\r"; if [ $exit_code -ne 0 ]; then msg_error "Error during '$msg'. Exit code: $exit_code"; msg_error "See log for details: /tmp/${SERVICE_NAME}_install.log"; fi; return $exit_code; }

# --- Check downloader ---
if command -v wget &> /dev/null; then DOWNLOADER="wget -qO-"; elif command -v curl &> /dev/null; then DOWNLOADER="curl -sSLf"; else msg_error "Neither wget nor curl found."; exit 1; fi
if command -v curl &> /dev/null; then DOWNLOADER_PIPE="curl -s"; else DOWNLOADER_PIPE="wget -qO-"; fi

# --- Version functions ---
get_local_version() { local readme_path="$1"; local version="Not found"; if [ -f "$readme_path" ]; then version=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$readme_path" || true); if [ -z "$version" ]; then version=$(grep -oP '<b\s*>v\K[\d\.]+(?=</b>)' "$readme_path" || true); fi; if [ -z "$version" ]; then version="Not found"; else version="v$version"; fi; else version="Not installed"; fi; echo "$version"; }
get_latest_version() { local api_url="$1"; local latest_tag=$($DOWNLOADER_PIPE "$api_url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "API Error"); if [[ "$latest_tag" == *"API rate limit exceeded"* ]]; then latest_tag="API Limit"; elif [[ "$latest_tag" == "API Error" ]] || [ -z "$latest_tag" ]; then latest_tag="Unknown"; fi; echo "$latest_tag"; }

# --- Integrity Check ---
INSTALL_STATUS="NOT_FOUND"; STATUS_MESSAGE="Check not performed."
check_integrity() { if [ ! -d "${BOT_INSTALL_PATH}" ]; then INSTALL_STATUS="NOT_FOUND"; STATUS_MESSAGE="Bot not installed."; return; fi; INSTALL_STATUS="OK"; local errors=(); if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then errors+=("- Missing .git"); INSTALL_STATUS="PARTIAL"; fi; if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || [ ! -f "${BOT_INSTALL_PATH}/watchdog.py" ] || [ ! -d "${BOT_INSTALL_PATH}/core" ] || [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then errors+=("- Missing core files"); INSTALL_STATUS="PARTIAL"; fi; if [ ! -f "${VENV_PATH}/bin/python" ]; then errors+=("- Missing venv"); INSTALL_STATUS="PARTIAL"; fi; if [ ! -f "${BOT_INSTALL_PATH}/.env" ]; then errors+=("- (Warning) Missing .env"); fi; if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then errors+=("- Missing ${SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi; if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then errors+=("- Missing ${WATCHDOG_SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi; if [ "$INSTALL_STATUS" == "OK" ]; then local bot_status; local watchdog_status; if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Active${C_RESET}"; else bot_status="${C_RED}Inactive${C_RESET}"; fi; if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Active${C_RESET}"; else watchdog_status="${C_RED}Inactive${C_RESET}"; fi; STATUS_MESSAGE="Installation OK (Bot: ${bot_status} | Watchdog: ${watchdog_status})"; if [[ " ${errors[*]} " =~ " .env" ]]; then STATUS_MESSAGE+=" ${C_YELLOW}(No .env!)${C_RESET}"; fi; elif [ "$INSTALL_STATUS" == "PARTIAL" ]; then STATUS_MESSAGE="${C_RED}Installation corrupted.${C_RESET}\n  Issue: ${errors[0]}"; fi; }

# --- Installation functions ---
install_extras() {
    local packages_to_install=()
    # Fail2Ban Check
    if ! command -v fail2ban-client &> /dev/null; then msg_question "Fail2Ban not found. Install? (y/n): " INSTALL_F2B; if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then packages_to_install+=("fail2ban"); else msg_info "Skipping Fail2Ban."; fi; else msg_success "Fail2Ban already installed."; fi

    # iperf3 Check
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 not found. It is required for the 'Speed Test' module (iperf3). Install? (y/n): " INSTALL_IPERF3
        if [[ "$INSTALL_IPERF3" =~ ^[Yy]$ ]]; then
            packages_to_install+=("iperf3")
        else
            msg_info "Skipping iperf3. The 'Speed Test' module (iperf3) will not work."
        fi
    else
        msg_success "iperf3 is already installed."
    fi

    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Installing additional packages: ${packages_to_install[*]}"
        run_with_spinner "Updating package list" sudo apt-get update -y
        run_with_spinner "Installing packages" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages_to_install[@]}"; if [ $? -ne 0 ]; then msg_error "Error installing additional packages."; exit 1; fi
        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then sudo systemctl enable fail2ban &> /dev/null; sudo systemctl start fail2ban &> /dev/null; msg_success "Fail2Ban installed and started."; fi
        if [[ " ${packages_to_install[*]} " =~ " iperf3 " ]]; then msg_success "iperf3 installed."; fi
        msg_success "Additional packages installed."
    fi
}
common_install_steps() { echo "" > /tmp/${SERVICE_NAME}_install.log; msg_info "1. Updating packages and installing basic dependencies..."; run_with_spinner "Updating package list" sudo apt-get update -y || { msg_error "Failed to update packages"; exit 1; }; run_with_spinner "Installing dependencies (python3, pip, venv, git, curl, wget, sudo)" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo || { msg_error "Failed to install basic dependencies"; exit 1; }; install_extras; }
install_logic() { local mode=$1; local branch_to_use=$2; local exec_user_cmd=""; local owner="root:root"; local owner_user="root"; if [ "$mode" == "secure" ]; then msg_info "2. Creating user '${SERVICE_USER}'..."; if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || exit 1; fi; sudo mkdir -p ${BOT_INSTALL_PATH}; sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}; msg_info "3. Cloning repo (branch ${branch_to_use}) as ${SERVICE_USER}..."; run_with_spinner "Cloning repository" sudo -u ${SERVICE_USER} git clone --branch "${branch_to_use}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1; exec_user_cmd="sudo -u ${SERVICE_USER}"; owner="${SERVICE_USER}:${SERVICE_USER}"; owner_user=${SERVICE_USER}; else msg_info "2. Creating directory..."; sudo mkdir -p ${BOT_INSTALL_PATH}; msg_info "3. Cloning repo (branch ${branch_to_use}) as root..."; run_with_spinner "Cloning repository" sudo git clone --branch "${branch_to_use}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1; exec_user_cmd=""; owner="root:root"; owner_user="root"; fi; msg_info "4. Setting up venv..."; if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Creating venv" $exec_user_cmd ${PYTHON_BIN} -m venv "${VENV_PATH}" || exit 1; fi; run_with_spinner "Updating pip" $exec_user_cmd "${VENV_PATH}/bin/pip" install --upgrade pip || msg_warning "Failed to update pip..."; run_with_spinner "Installing Python dependencies" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" || exit 1; msg_info "5. Creating .gitignore, logs/, config/..."; sudo -u ${owner_user} bash -c "cat > ${BOT_INSTALL_PATH}/.gitignore" <<< $'/venv/\n/__pycache__/\n*.pyc\n/.env\n/config/\n/logs/\n*.log\n*_flag.txt'; sudo chmod 644 "${BOT_INSTALL_PATH}/.gitignore"; sudo -u ${owner_user} mkdir -p "${BOT_INSTALL_PATH}/logs" "${BOT_INSTALL_PATH}/config"; msg_info "6. Configuring .env..."; msg_question "Bot Token: " T; msg_question "Admin User ID: " A; msg_question "Admin Username (optional): " U; msg_question "Bot Name (optional): " N; sudo bash -c "cat > ${BOT_INSTALL_PATH}/.env" <<< $(printf "TG_BOT_TOKEN=\"%s\"\nTG_ADMIN_ID=\"%s\"\nTG_ADMIN_USERNAME=\"%s\"\nTG_BOT_NAME=\"%s\"\nINSTALL_MODE=\"%s\"" "$T" "$A" "$U" "$N" "$mode"); sudo chown ${owner} "${BOT_INSTALL_PATH}/.env"; sudo chmod 600 "${BOT_INSTALL_PATH}/.env"; if [ "$mode" == "root" ]; then msg_info "7. Configuring sudo (root)..."; F="/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo tee ${F} > /dev/null <<< $'root ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-bot.service\nroot ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-watchdog.service\nroot ALL=(ALL) NOPASSWD: /sbin/reboot'; sudo chmod 440 ${F}; elif [ "$mode" == "secure" ]; then F="/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo tee ${F} > /dev/null <<< $'Defaults:tgbot !requiretty\ntgbot ALL=(root) NOPASSWD: /bin/systemctl restart tg-bot.service'; sudo chmod 440 ${F}; msg_info "7. Configuring sudo (secure)..."; fi; create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "${mode}" "Telegram Bot"; create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog"; local ip=$(curl -s --connect-timeout 5 ipinfo.io/ip || echo "Could not determine"); echo ""; echo "---"; msg_success "Installation complete!"; msg_info "IP: ${ip}"; echo "---"; }
install_secure() { echo -e "\n${C_BOLD}=== Secure Installation (branch: ${GIT_BRANCH}) ===${C_RESET}"; common_install_steps; install_logic "secure" "${GIT_BRANCH}"; }
install_root() { echo -e "\n${C_BOLD}=== Root Installation (branch: ${GIT_BRANCH}) ===${C_RESET}"; common_install_steps; install_logic "root" "${GIT_BRANCH}"; }
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
; msg_info "Starting ${svc}..."; sudo systemctl daemon-reload; sudo systemctl enable ${svc}.service &> /dev/null; run_with_spinner "Starting ${svc}" sudo systemctl restart ${svc}; sleep 2; if sudo systemctl is-active --quiet ${svc}.service; then msg_success "${svc} started!"; msg_info "Status: sudo systemctl status ${svc}"; else msg_error "${svc} FAILED TO START. Logs: sudo journalctl -u ${svc} -n 50 --no-pager"; if [ "$svc" == "$SERVICE_NAME" ]; then exit 1; fi; fi; }
uninstall_bot() { echo -e "\n${C_BOLD}=== Uninstalling Bot ===${C_RESET}"; msg_info "1. Stopping services..."; if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then sudo systemctl stop ${SERVICE_NAME} &> /dev/null; sudo systemctl disable ${SERVICE_NAME} &> /dev/null; fi; if systemctl list-units --full -all | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl stop ${WATCHDOG_SERVICE_NAME} &> /dev/null; sudo systemctl disable ${WATCHDOG_SERVICE_NAME} &> /dev/null; fi; msg_info "2. Removing system files..."; sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"; sudo rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service"; sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo rm -f "/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo systemctl daemon-reload; msg_info "3. Removing bot directory..."; sudo rm -rf "${BOT_INSTALL_PATH}"; msg_info "4. Removing user '${SERVICE_USER}'..."; if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null || msg_warning "Could not completely remove user ${SERVICE_USER}."; fi; msg_success "Uninstallation complete."; }
update_bot() { echo -e "\n${C_BOLD}=== Updating Bot (branch: ${GIT_BRANCH}) ===${C_RESET}"; if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git repository not found. Cannot update."; return 1; fi; local exec_user=""; if [ -f "${BOT_INSTALL_PATH}/.env" ]; then MODE=$(grep '^INSTALL_MODE=' "${BOT_INSTALL_PATH}/.env" | cut -d'=' -f2 | tr -d '"'); if [ "$MODE" == "secure" ]; then exec_user="sudo -u ${SERVICE_USER}"; fi; fi; msg_warning "Update will overwrite local changes."; msg_warning ".env, config/, logs/ will be preserved."; msg_info "1. Fetching updates (branch ${GIT_BRANCH})..."; pushd "${BOT_INSTALL_PATH}" > /dev/null; run_with_spinner "Git fetch" $exec_user git fetch origin; run_with_spinner "Git reset --hard" $exec_user git reset --hard "origin/${GIT_BRANCH}"; local st=$?; popd > /dev/null; if [ $st -ne 0 ]; then msg_error "Git update failed."; return 1; fi; msg_success "Project files updated."; msg_info "2. Updating Python dependencies..."; run_with_spinner "Pip install" $exec_user "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade; if [ $? -ne 0 ]; then msg_error "Pip install failed."; return 1; fi; msg_info "3. Restarting services..."; if sudo systemctl restart ${SERVICE_NAME}; then msg_success "${SERVICE_NAME} restarted."; else msg_error "Failed to restart ${SERVICE_NAME}."; return 1; fi; sleep 1; if sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; then msg_success "${WATCHDOG_SERVICE_NAME} restarted."; else msg_error "Failed to restart ${WATCHDOG_SERVICE_NAME}."; fi; echo -e "\n${C_GREEN}${C_BOLD}🎉 Update complete!${C_RESET}\n"; }

# --- Management Menu ---
main_menu() { local local_version=$(get_local_version "$README_FILE"); local latest_version=$(get_latest_version "$GITHUB_API_URL"); while true; do clear; echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"; echo -e "${C_BLUE}${C_BOLD}║    VPS Telegram Bot Manager       ║${C_RESET}"; echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"; local current_branch=$(cd "$BOT_INSTALL_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Not installed"); echo -e "  Current branch (installed): ${C_YELLOW}${current_branch}${C_RESET}"; echo -e "  Target branch (for action): ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "  Local version: ${C_GREEN}${local_version}${C_RESET}"; echo -e "  Latest version: ${C_CYAN}${latest_version}${C_RESET}"; if [ -z "$orig_arg1" ] && [ "$GIT_BRANCH" == "main" ]; then echo -e "  ${C_YELLOW}(Hint: To act on a different branch, run:${C_RESET}"; echo -e "  ${C_YELLOW} sudo bash $0 <branch_name>)${C_RESET}"; fi; check_integrity; echo "--------------------------------------------------------"; echo -n -e "  Status: "; if [ "$INSTALL_STATUS" == "OK" ]; then echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"; else echo -e "${C_RED}${STATUS_MESSAGE}${C_RESET}"; msg_warning "  Reinstallation recommended."; fi; echo "--------------------------------------------------------"; echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Reinstall (Secure):${C_RESET}          ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Reinstall (Root):${C_RESET}           ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "${C_CYAN}  3)${C_RESET} ${C_BOLD}Update bot:${C_RESET}                   ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "${C_RED}  4)${C_RESET} ${C_BOLD}Uninstall bot${C_RESET}"; echo -e "  5) ${C_BOLD}Exit${C_RESET}"; echo "--------------------------------------------------------"; read -p "$(echo -e "${C_BOLD}Enter option number [1-5]: ${C_RESET}")" choice; case $choice in 1) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Reinstall (secure, ${GIT_BRANCH})? (y/n): " confirm; if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_secure; local_version=$(get_local_version "$README_FILE"); else msg_info "Cancelled."; fi ;; 2) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Reinstall (root, ${GIT_BRANCH})? (y/n): " confirm; if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_root; local_version=$(get_local_version "$README_FILE"); else msg_info "Cancelled."; fi ;; 3) rm -f /tmp/${SERVICE_NAME}_install.log; update_bot && local_version=$(get_local_version "$README_FILE") ;; 4) msg_question "Uninstall bot COMPLETELY? (y/n): " confirm_uninstall; if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then uninstall_bot; msg_info "Bot uninstalled. Exiting."; return; else msg_info "Uninstallation cancelled."; fi ;; 5) break ;; *) msg_error "Invalid choice." ;; esac; if [[ "$choice" != "4" || ! "$confirm_uninstall" =~ ^[Yy]$ ]]; then echo; read -n 1 -s -r -p "Press any key to return to the menu..."; fi; done; }

# --- Main "Router" ---
main() {
    clear
    msg_info "Starting bot management script (Target branch: ${GIT_BRANCH})..."
    check_integrity # First status check

    if [ "$INSTALL_STATUS" == "NOT_FOUND" ] || [ "$INSTALL_STATUS" == "PARTIAL" ]; then
        if [ "$INSTALL_STATUS" == "PARTIAL" ]; then
            msg_error "Corrupted installation detected."
            msg_warning "${STATUS_MESSAGE}" # Show problem details
            msg_question "Problems detected. Remove old files and reinstall? (y/n): " confirm_delete
            if [[ "$confirm_delete" =~ ^[Yy]$ ]]; then
                uninstall_bot # Uninstall only if user confirms
            else
                msg_error "Installation cancelled due to corrupted files. Run script again for management.";
                exit 1;
            fi
            # Check again after uninstall, status changed to NOT_FOUND
            check_integrity
        fi

        # Nice installation block
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║     VPS Telegram Bot Installer    ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        echo -e "  ${C_YELLOW}Bot not found or installation corrupted.${C_RESET}"
        echo -e "  Select installation mode for branch: ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo "--------------------------------------------------------"
        echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Secure Installation:${C_RESET}     Recommended"
        echo -e "     (Bot runs as user '${SERVICE_USER}')"
        echo ""
        echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Root Installation:${C_RESET}        For full access"
        echo -e "     (Bot runs as 'root', requires sudo privileges)"
        echo ""
        echo -e "  3) ${C_BOLD}Exit${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Enter option number [1-3]: ${C_RESET}")" install_choice

        local install_done=false # Internal flag
        rm -f /tmp/${SERVICE_NAME}_install.log # Clear log before install
        case $install_choice in
            1) install_secure; install_done=true ;;
            2) install_root; install_done=true ;;
            *) msg_info "Installation cancelled."; exit 0 ;;
        esac

        # Check after installation
        if [ "$install_done" = true ]; then
            msg_info "Verifying after installation...";
            check_integrity; # Check again
            if [ "$INSTALL_STATUS" == "OK" ]; then
                msg_success "Installation completed successfully!"
                echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"
                read -n 1 -s -r -p "Press Enter to proceed to the Main Menu..."
                # Go to main menu after successful installation
                main_menu
                echo -e "\n${C_CYAN}👋 Goodbye!${C_RESET}"
                exit 0 # Exit after main_menu
            else
                msg_error "Installation finished with errors!"
                msg_error "${C_RED}${STATUS_MESSAGE}${C_RESET}"
                msg_error "Log: /tmp/${SERVICE_NAME}_install.log";
                exit 1;
            fi
        fi
        # If installation was cancelled, we won't reach here
    else
        # If bot is already installed (INSTALL_STATUS == OK), show menu directly
        main_menu;
        echo -e "\n${C_CYAN}👋 Goodbye!${C_RESET}"
    fi
}

# --- Root Check ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Please run this script as root or with sudo."; exit 1; fi

# --- Start ---
main