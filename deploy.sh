#!/bin/bash

# --- Запоминаем исходный аргумент ---
orig_arg1="$1"

# --- Конфигурация ---
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

# --- GitHub Репозиторий ---
GITHUB_REPO="jatixs/tgbotvpscp"
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

# --- Цвета ---
C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }; msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }

spinner() { 
    local pid=$1; local msg=$2; local spin='|/-\'; local i=0
    while kill -0 $pid 2>/dev/null; do 
        i=$(( (i+1) % 4 )); printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"; sleep .1
    done
    printf "\r"
}

run_with_spinner() { 
    local msg=$1; shift
    # [FIX] Переходим в корень перед выполнением, чтобы не потерять контекст при удалении папки
    ( cd / && "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) & 
    local pid=$!; spinner "$pid" "$msg"; wait $pid; local exit_code=$?
    echo -ne "\033[2K\r"
    if [ $exit_code -ne 0 ]; then 
        msg_error "Ошибка во время '$msg'. Код: $exit_code"
        msg_error "Лог: /tmp/${SERVICE_NAME}_install.log"
    fi
    return $exit_code 
}

# --- Проверка ---
if command -v wget &> /dev/null; then DOWNLOADER="wget -qO-"; elif command -v curl &> /dev/null; then DOWNLOADER="curl -sSLf"; else msg_error "Нет wget/curl."; exit 1; fi
get_local_version() { if [ -f "$README_FILE" ]; then grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE" || echo "Не найдена"; else echo "Не установлен"; fi; }

# --- Проверка целостности ---
INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Проверка не проводилась."
check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Бот не установлен."; return;
    fi

    if grep -q "MODE=node" "${ENV_FILE}"; then
        INSTALL_TYPE="НОДА (Клиент)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}"; else STATUS_MESSAGE="${C_RED}Неактивен${C_RESET}"; fi
        return
    fi

    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="АГЕНТ (Docker)"
        if docker ps | grep -q "tg-bot"; then STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}"; else STATUS_MESSAGE="${C_RED}Остановлен${C_RESET}"; fi
    else
        INSTALL_TYPE="АГЕНТ (Systemd)"
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}"; else STATUS_MESSAGE="${C_RED}Остановлен${C_RESET}"; fi
    fi
}

# --- Установка ---
common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Обновление системы..."
    run_with_spinner "Обновление списка пакетов" sudo apt-get update -y
    run_with_spinner "Установка зависимостей" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo python3-yaml
}

# --- [FIX] Умная переустановка репо с сохранением данных ---
setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    cd / # Уходим из папки, чтобы не блокировать удаление
    
    msg_info "Подготовка файлов..."
    # Бэкап
    if [ -f "${ENV_FILE}" ]; then cp "${ENV_FILE}" /tmp/tgbot_env.bak; fi
    if [ -d "${VENV_PATH}" ]; then sudo mv "${VENV_PATH}" /tmp/tgbot_venv.bak; fi

    # Полная очистка папки перед клонированием
    if [ -d "${BOT_INSTALL_PATH}" ]; then
        run_with_spinner "Удаление старых файлов" sudo rm -rf "${BOT_INSTALL_PATH}"
    fi
    sudo mkdir -p ${BOT_INSTALL_PATH}

    # Клонирование
    run_with_spinner "Клонирование репозитория" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1
    
    # Восстановление
    if [ -f "/tmp/tgbot_env.bak" ]; then sudo mv /tmp/tgbot_env.bak "${ENV_FILE}"; fi
    if [ -d "/tmp/tgbot_venv.bak" ]; then 
        if [ -d "${VENV_PATH}" ]; then sudo rm -rf "${VENV_PATH}"; fi
        sudo mv /tmp/tgbot_venv.bak "${VENV_PATH}"
    fi
    
    # Создание папок логов
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/logs/node" "${BOT_INSTALL_PATH}/config"
    sudo chown -R ${owner_user}:${owner_user} ${BOT_INSTALL_PATH}
}

cleanup_node_files() {
    msg_info "Очистка лишних файлов (режим Ноды)..."
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf core modules bot.py watchdog.py Dockerfile docker-compose.yml .git .github config/users.json config/alerts_config.json deploy.sh deploy_en.sh requirements.txt README* LICENSE CHANGELOG* .gitignore
    msg_success "Нода оптимизирована."
}

cleanup_agent_files() {
    msg_info "Удаление файлов ноды (режим Агента)..."
    cd ${BOT_INSTALL_PATH}
    sudo rm -rf node
}

# --- Генерация скрипта Ноды (гарантия наличия) ---
create_node_script() {
    # Эта функция теперь не обязательна, если файл есть в репо, 
    # но оставим её пустой для совместимости структуры
    :
}

# --- Функции установки ---
install_extras() {
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Установка Fail2ban" sudo apt-get install -y fail2ban; fi
    fi
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 не найден. Установить? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Установка iperf3" sudo apt-get install -y iperf3; fi
    fi
}

ask_env_details() {
    msg_info "Ввод данных .env..."
    msg_question "Токен Бота: " T; msg_question "ID Админа: " A; msg_question "Username Админа (опц): " U; msg_question "Имя Бота (опц): " N
    msg_question "Порт веб-сервера [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    export T A U N WEB_PORT
}

write_env_file() {
    local dm=$1; local im=$2; local cn=$3
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
EOF
    sudo chmod 600 "${ENV_FILE}"
}

check_docker_deps() {
    if ! command -v docker &> /dev/null; then 
        curl -sSL https://get.docker.com -o /tmp/get-docker.sh
        run_with_spinner "Установка Docker" sudo sh /tmp/get-docker.sh
    fi
    if command -v docker-compose &> /dev/null; then sudo rm -f $(which docker-compose); fi
    # ... (здесь можно добавить очистку старых пакетов, как было раньше, если нужно)
}

create_dockerfile() {
    sudo tee "${BOT_INSTALL_PATH}/Dockerfile" > /dev/null <<'EOF'
FROM python:3.10-slim-bookworm
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
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Бот"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель"
    cleanup_agent_files
    local ip=$(curl -s ipinfo.io/ip); echo ""; msg_success "Установка завершена! Агент доступен: http://${ip}:${WEB_PORT}"
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
    cleanup_agent_files
    cd ${BOT_INSTALL_PATH}
    sudo docker-compose build
    sudo docker-compose --profile "${mode}" up -d --remove-orphans
    msg_success "Установка Docker завершена!"
}

install_node_logic() {
    echo -e "\n${C_BOLD}=== Установка НОДЫ (Клиент) ===${C_RESET}"
    common_install_steps
    
    # [FIX] Установка iperf3 в неинтерактивном режиме для предотвращения зависания
    run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iperf3
    
    setup_repo_and_dirs "root"
    create_node_script
    
    msg_info "Настройка venv..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install psutil requests
    
    if [ ! -f "${ENV_FILE}" ] || ! grep -q "AGENT_TOKEN" "${ENV_FILE}"; then
        echo ""; msg_info "Настройка подключения:"
        msg_question "URL Агента (http://IP:8080): " AGENT_URL
        msg_question "Токен Ноды: " NODE_TOKEN
        sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_UPDATE_INTERVAL=5
EOF
        sudo chmod 600 "${ENV_FILE}"
    fi

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
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Удалено."
}

update_bot() {
    echo -e "\n${C_BOLD}=== Обновление ===${C_RESET}"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then
        msg_info "Обновление Ноды..."
        install_node_logic
        return
    fi

    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git не найден."; return 1; fi
    local exec_user=""; if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_user="sudo -u ${SERVICE_USER}"; fi
    
    cd "${BOT_INSTALL_PATH}"
    if ! run_with_spinner "Получение изменений (fetch)" $exec_user git fetch origin; then return 1; fi
    if ! run_with_spinner "Применение изменений (reset)" $exec_user git reset --hard "origin/${GIT_BRANCH}"; then return 1; fi
    
    cleanup_agent_files

    if [ -f "docker-compose.yml" ]; then
        sudo docker compose up -d --build
    else
        run_with_spinner "Обновление Python-пакетов" $exec_user "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
        msg_info "Перезапуск служб..."
        if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then sudo systemctl restart ${SERVICE_NAME}; fi
        if systemctl list-unit-files | grep -q "^${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; fi
    fi
    msg_success "Обновлено."
}

main_menu() {
    while true; do
        clear
        check_integrity
        echo -e "${C_BLUE}VPS Bot Manager${C_RESET} | Статус: ${STATUS_MESSAGE}"
        echo "1) Обновить"
        echo "2) Удалить"
        echo "3-6) Переустановить АГЕНТА (Systemd/Docker)"
        echo "8) Установить/Переустановить НОДУ"
        echo "0) Выход"
        read -p "Выбор: " ch
        case $ch in
            1) update_bot; read -p "Нажмите Enter..." ;;
            2) uninstall_bot; return ;;
            3) uninstall_bot; install_systemd_logic "secure"; read -p "Нажмите Enter..." ;;
            4) uninstall_bot; install_systemd_logic "root"; read -p "Нажмите Enter..." ;;
            5) uninstall_bot; install_docker_logic "secure"; read -p "Нажмите Enter..." ;;
            6) uninstall_bot; install_docker_logic "root"; read -p "Нажмите Enter..." ;;
            8) uninstall_bot; install_node_logic; read -p "Нажмите Enter..." ;;
            0) break ;;
        esac
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Нужен root."; exit 1; fi

check_integrity
if [ "$INSTALL_TYPE" == "НЕТ" ]; then
    echo "1-4) Установить Агента, 8) Установить Ноду"
    read -p "> " ch
    case $ch in
        1) uninstall_bot; install_systemd_secure ;;
        2) uninstall_bot; install_systemd_root ;;
        3) uninstall_bot; install_docker_secure ;;
        4) uninstall_bot; install_docker_root ;;
        8) uninstall_bot; install_node_logic ;;
    esac
    main_menu
else
    main_menu
fi