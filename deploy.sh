#!/bin/bash

# --- Запоминаем исходный аргумент ---
orig_arg1="$1"

# --- Конфигурация ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"
README_FILE="${BOT_INSTALL_PATH}/README.md"

# --- GitHub Репозиторий и Ветка ---
GITHUB_REPO="jatixs/tgbotvpscp"
GIT_BRANCH="${orig_arg1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"
GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"

# --- Цвета и функции вывода ---
C_RESET='\033[0m'; C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_BLUE='\033[0;34m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'
msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }; msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }; msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }; msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }; msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }
spinner() { local pid=$1; local msg=$2; local spin='|/-\'; local i=0; while kill -0 $pid 2>/dev/null; do i=$(( (i+1) %4 )); printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"; sleep .1; done; printf "\r"; }
run_with_spinner() { local msg=$1; shift; ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) & local pid=$!; spinner "$pid" "$msg"; wait $pid; local exit_code=$?; echo -ne "\033[2K\r"; if [ $exit_code -ne 0 ]; then msg_error "Ошибка во время '$msg'. Код: $exit_code"; msg_error "Лог: /tmp/${SERVICE_NAME}_install.log"; fi; return $exit_code; }

# --- Проверка загрузчика ---
if command -v wget &> /dev/null; then DOWNLOADER="wget -qO-"; elif command -v curl &> /dev/null; then DOWNLOADER="curl -sSLf"; else msg_error "Ни wget, ни curl не найдены."; exit 1; fi
if command -v curl &> /dev/null; then DOWNLOADER_PIPE="curl -s"; else DOWNLOADER_PIPE="wget -qO-"; fi

# --- Функции версий ---
get_local_version() { local readme_path="$1"; local version="Не найдена"; if [ -f "$readme_path" ]; then version=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$readme_path" || true); if [ -z "$version" ]; then version=$(grep -oP '<b\s*>v\K[\d\.]+(?=</b>)' "$readme_path" || true); fi; if [ -z "$version" ]; then version="Не найдена"; else version="v$version"; fi; else version="Не установлен"; fi; echo "$version"; }
get_latest_version() { local api_url="$1"; local latest_tag=$($DOWNLOADER_PIPE "$api_url" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "Ошибка API"); if [[ "$latest_tag" == *"API rate limit exceeded"* ]]; then latest_tag="Лимит API"; elif [[ "$latest_tag" == "Ошибка API" ]] || [ -z "$latest_tag" ]; then latest_tag="Неизвестно"; fi; echo "$latest_tag"; }

# --- Проверка целостности ---
INSTALL_STATUS="NOT_FOUND"; STATUS_MESSAGE="Проверка не проводилась."
check_integrity() { if [ ! -d "${BOT_INSTALL_PATH}" ]; then INSTALL_STATUS="NOT_FOUND"; STATUS_MESSAGE="Бот не установлен."; return; fi; INSTALL_STATUS="OK"; local errors=(); if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then errors+=("- Отсутствует .git"); INSTALL_STATUS="PARTIAL"; fi; if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || [ ! -f "${BOT_INSTALL_PATH}/watchdog.py" ] || [ ! -d "${BOT_INSTALL_PATH}/core" ] || [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then errors+=("- Отсутствуют основные файлы"); INSTALL_STATUS="PARTIAL"; fi; if [ ! -f "${VENV_PATH}/bin/python" ]; then errors+=("- Отсутствует venv"); INSTALL_STATUS="PARTIAL"; fi; if [ ! -f "${BOT_INSTALL_PATH}/.env" ]; then errors+=("- (Предупреждение) Отсутствует .env"); fi; if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then errors+=("- Отсутствует ${SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi; if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then errors+=("- Отсутствует ${WATCHDOG_SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi; if [ "$INSTALL_STATUS" == "OK" ]; then local bot_status; local watchdog_status; if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Активен${C_RESET}"; else bot_status="${C_RED}Неактивен${C_RESET}"; fi; if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Активен${C_RESET}"; else watchdog_status="${C_RED}Неактивен${C_RESET}"; fi; STATUS_MESSAGE="Установка OK (Бот: ${bot_status} | Наблюдатель: ${watchdog_status})"; if [[ " ${errors[*]} " =~ " .env" ]]; then STATUS_MESSAGE+=" ${C_YELLOW}(Нет .env!)${C_RESET}"; fi; elif [ "$INSTALL_STATUS" == "PARTIAL" ]; then STATUS_MESSAGE="${C_RED}Установка повреждена.${C_RESET}\n  Проблема: ${errors[0]}"; fi; }

# --- Функции установки ---
install_extras() {
    local packages_to_install=()
    local packages_to_remove=()

    # Fail2Ban Check
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then
            packages_to_install+=("fail2ban")
        else
            msg_info "Пропуск Fail2Ban."
        fi
    else
        msg_success "Fail2Ban уже установлен."
    fi

    # iperf3 Check
    if ! command -v iperf3 &> /dev/null; then
        msg_question "iperf3 не найден. Он необходим для модуля 'Скорость сети'. Установить? (y/n): " INSTALL_IPERF3
        if [[ "$INSTALL_IPERF3" =~ ^[Yy]$ ]]; then
            packages_to_install+=("iperf3")
        else
            msg_info "Пропуск iperf3. Модуль 'Скорость сети' не будет работать."
        fi
    else
        msg_success "iperf3 уже установлен."
    fi

    # Speedtest CLI Check for removal
    if command -v speedtest &> /dev/null || dpkg -s speedtest-cli &> /dev/null; then
        msg_warning "Обнаружен старый пакет 'speedtest-cli'."
        msg_question "Удалить 'speedtest-cli'? (Рекомендуется, т.к. бот теперь использует iperf3) (y/n): " REMOVE_SPEEDTEST
        if [[ "$REMOVE_SPEEDTEST" =~ ^[Yy]$ ]]; then
            packages_to_remove+=("speedtest-cli")
        else
            msg_info "Пропуск удаления speedtest-cli."
        fi
    fi

    # Package Removal
    if [ ${#packages_to_remove[@]} -gt 0 ]; then
        msg_info "Удаление пакетов: ${packages_to_remove[*]}"
        run_with_spinner "Удаление пакетов" sudo apt-get remove --purge -y "${packages_to_remove[@]}"
        run_with_spinner "Очистка apt" sudo apt-get autoremove -y
        msg_success "Указанные пакеты удалены."
    fi

    # Package Installation
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Установка дополнительных пакетов: ${packages_to_install[*]}"
        run_with_spinner "Обновление списка пакетов" sudo apt-get update -y
        run_with_spinner "Установка пакетов" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages_to_install[@]}"
        if [ $? -ne 0 ]; then msg_error "Ошибка при установке доп. пакетов."; exit 1; fi

        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then
             sudo systemctl enable fail2ban &> /dev/null
             sudo systemctl start fail2ban &> /dev/null
             msg_success "Fail2Ban установлен и запущен."
        fi
        if [[ " ${packages_to_install[*]} " =~ " iperf3 " ]]; then
             msg_success "iperf3 установлен."
        fi
        msg_success "Дополнительные пакеты установлены."
    fi
}
# --- [ИЗМЕНЕНО] common_install_steps ---
common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Обновление пакетов и установка базовых зависимостей..."
    run_with_spinner "Обновление списка пакетов" sudo apt-get update -y || { msg_error "Не удалось обновить пакеты"; exit 1; }
    # Добавляем python3-yaml к основным зависимостям
    run_with_spinner "Установка зависимостей (python3, pip, venv, git, curl, wget, sudo, yaml)" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv git curl wget sudo python3-yaml || { msg_error "Не удалось установить базовые зависимости"; exit 1; }
    install_extras
}
# --- [КОНЕЦ ИЗМЕНЕНИЙ] common_install_steps ---
install_logic() { local mode=$1; local branch_to_use=$2; local exec_user_cmd=""; local owner="root:root"; local owner_user="root"; if [ "$mode" == "secure" ]; then msg_info "2. Создание пользователя '${SERVICE_USER}'..."; if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || exit 1; fi; sudo mkdir -p ${BOT_INSTALL_PATH}; sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}; msg_info "3. Клонирование репо (ветка ${branch_to_use}) от ${SERVICE_USER}..."; run_with_spinner "Клонирование репозитория" sudo -u ${SERVICE_USER} git clone --branch "${branch_to_use}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1; exec_user_cmd="sudo -u ${SERVICE_USER}"; owner="${SERVICE_USER}:${SERVICE_USER}"; owner_user=${SERVICE_USER}; else msg_info "2. Создание директории..."; sudo mkdir -p ${BOT_INSTALL_PATH}; msg_info "3. Клонирование репо (ветка ${branch_to_use}) от root..."; run_with_spinner "Клонирование репозитория" sudo git clone --branch "${branch_to_use}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}" || exit 1; exec_user_cmd=""; owner="root:root"; owner_user="root"; fi; msg_info "4. Настройка venv..."; if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" $exec_user_cmd ${PYTHON_BIN} -m venv "${VENV_PATH}" || exit 1; fi; run_with_spinner "Обновление pip" $exec_user_cmd "${VENV_PATH}/bin/pip" install --upgrade pip || msg_warning "Не удалось обновить pip..."; run_with_spinner "Установка зависимостей Python" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" || exit 1; msg_info "5. Создание .gitignore, logs/, config/..."; sudo -u ${owner_user} bash -c "cat > ${BOT_INSTALL_PATH}/.gitignore" <<< $'/venv/\n/__pycache__/\n*.pyc\n/.env\n/config/\n/logs/\n*.log\n*_flag.txt'; sudo chmod 644 "${BOT_INSTALL_PATH}/.gitignore"; sudo -u ${owner_user} mkdir -p "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" "${BOT_INSTALL_PATH}/config"; msg_info "6. Настройка .env..."; msg_question "Токен: " T; msg_question "ID Администратора: " A; msg_question "Имя (Username) Админа (опц): " U; msg_question "Имя Бота (опц): " N; sudo bash -c "cat > ${BOT_INSTALL_PATH}/.env" <<< $(printf "TG_BOT_TOKEN=\"%s\"\nTG_ADMIN_ID=\"%s\"\nTG_ADMIN_USERNAME=\"%s\"\nTG_BOT_NAME=\"%s\"\nINSTALL_MODE=\"%s\"" "$T" "$A" "$U" "$N" "$mode"); sudo chown ${owner} "${BOT_INSTALL_PATH}/.env"; sudo chmod 600 "${BOT_INSTALL_PATH}/.env"; if [ "$mode" == "root" ]; then msg_info "7. Настройка sudo (root)..."; F="/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo tee ${F} > /dev/null <<< $'root ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-bot.service\nroot ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-watchdog.service\nroot ALL=(ALL) NOPASSWD: /sbin/reboot'; sudo chmod 440 ${F}; elif [ "$mode" == "secure" ]; then F="/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo tee ${F} > /dev/null <<< $'Defaults:tgbot !requiretty\ntgbot ALL=(root) NOPASSWD: /bin/systemctl restart tg-bot.service'; sudo chmod 440 ${F}; msg_info "7. Настройка sudo (secure)..."; fi; create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "${mode}" "Telegram Бот"; create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель"; local ip=$(curl -s --connect-timeout 5 ipinfo.io/ip || echo "Не удалось определить"); echo ""; echo "---"; msg_success "Установка завершена!"; msg_info "IP: ${ip}"; echo "---"; }
install_secure() { echo -e "\n${C_BOLD}=== Безопасная Установка (ветка: ${GIT_BRANCH}) ===${C_RESET}"; common_install_steps; install_logic "secure" "${GIT_BRANCH}"; }
install_root() { echo -e "\n${C_BOLD}=== Установка от Root (ветка: ${GIT_BRANCH}) ===${C_RESET}"; common_install_steps; install_logic "root" "${GIT_BRANCH}"; }
create_and_start_service() { local svc=$1; local script=$2; local mode=$3; local desc=$4; local user="root"; local group="root"; local env=""; local suffix=""; local after="After=network.target"; local req=""; if [ "$mode" == "secure" ] && [ "$svc" == "$SERVICE_NAME" ]; then user=${SERVICE_USER}; group=${SERVICE_USER}; suffix="(Безопасно)"; elif [ "$svc" == "$SERVICE_NAME" ]; then user="root"; group="root"; suffix="(Root)"; elif [ "$svc" == "$WATCHDOG_SERVICE_NAME" ]; then user="root"; group="root"; after="After=network.target ${SERVICE_NAME}.service"; fi; env="EnvironmentFile=${BOT_INSTALL_PATH}/.env"; msg_info "Создание systemd для ${svc}..."; FILE="/etc/systemd/system/${svc}.service"; sudo tee ${FILE} > /dev/null <<EOF
[Unit]
Description=${desc} Служба ${suffix}
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
msg_info "Запуск ${svc}..."; sudo systemctl daemon-reload; sudo systemctl enable ${svc}.service &> /dev/null; run_with_spinner "Запуск ${svc}" sudo systemctl restart ${svc}; sleep 2; if sudo systemctl is-active --quiet ${svc}.service; then msg_success "${svc} запущен!"; msg_info "Статус: sudo systemctl status ${svc}"; else msg_error "${svc} НЕ ЗАПУСТИЛСЯ. Логи: sudo journalctl -u ${svc} -n 50 --no-pager"; if [ "$svc" == "$SERVICE_NAME" ]; then exit 1; fi; fi; }
uninstall_bot() { echo -e "\n${C_BOLD}=== Удаление Бота ===${C_RESET}"; msg_info "1. Остановка служб..."; if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then sudo systemctl stop ${SERVICE_NAME} &> /dev/null; sudo systemctl disable ${SERVICE_NAME} &> /dev/null; fi; if systemctl list-units --full -all | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl stop ${WATCHDOG_SERVICE_NAME} &> /dev/null; sudo systemctl disable ${WATCHDOG_SERVICE_NAME} &> /dev/null; fi; msg_info "2. Удаление системных файлов..."; sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"; sudo rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service"; sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo rm -f "/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo systemctl daemon-reload; msg_info "3. Удаление директории бота..."; sudo rm -rf "${BOT_INSTALL_PATH}"; msg_info "4. Удаление пользователя '${SERVICE_USER}'..."; if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null || msg_warning "Не удалось полностью удалить пользователя ${SERVICE_USER}."; fi; msg_success "Удаление завершено."; }
update_bot() { echo -e "\n${C_BOLD}=== Обновление Бота (ветка: ${GIT_BRANCH}) ===${C_RESET}"; if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Репозиторий Git не найден. Невозможно обновить."; return 1; fi; local exec_user=""; if [ -f "${BOT_INSTALL_PATH}/.env" ]; then MODE=$(grep '^INSTALL_MODE=' "${BOT_INSTALL_PATH}/.env" | cut -d'=' -f2 | tr -d '"'); if [ "$MODE" == "secure" ]; then exec_user="sudo -u ${SERVICE_USER}"; fi; fi; msg_warning "Обновление перезапишет локальные изменения."; msg_warning ".env, config/, logs/ будут сохранены."; msg_info "1. Получение обновлений (ветка ${GIT_BRANCH})..."; pushd "${BOT_INSTALL_PATH}" > /dev/null; run_with_spinner "Git fetch (загрузка)" $exec_user git fetch origin; run_with_spinner "Git reset --hard (сброс)" $exec_user git reset --hard "origin/${GIT_BRANCH}"; local st=$?; popd > /dev/null; if [ $st -ne 0 ]; then msg_error "Обновление Git не удалось."; return 1; fi; msg_success "Файлы проекта обновлены."; msg_info "2. Обновление зависимостей Python..."; run_with_spinner "Установка Pip" $exec_user "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade; if [ $? -ne 0 ]; then msg_error "Установка Pip не удалась."; return 1; fi; msg_info "3. Перезапуск служб..."; if sudo systemctl restart ${SERVICE_NAME}; then msg_success "${SERVICE_NAME} перезапущен."; else msg_error "Не удалось перезапустить ${SERVICE_NAME}."; return 1; fi; sleep 1; if sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; then msg_success "${WATCHDOG_SERVICE_NAME} перезапущен."; else msg_error "Не удалось перезапустить ${WATCHDOG_SERVICE_NAME}."; fi; echo -e "\n${C_GREEN}${C_BOLD}🎉 Обновление завершено!${C_RESET}\n"; }

# --- Меню управления ---
main_menu() { local local_version=$(get_local_version "$README_FILE"); local latest_version=$(get_latest_version "$GITHUB_API_URL"); while true; do clear; echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"; echo -e "${C_BLUE}${C_BOLD}║    Менеджер VPS Telegram Бот      ║${C_RESET}"; echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"; local current_branch=$(cd "$BOT_INSTALL_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Не установлено"); echo -e "  Текущая ветка (установлена): ${C_YELLOW}${current_branch}${C_RESET}"; echo -e "  Целевая ветка (для действия): ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "  Локальная версия: ${C_GREEN}${local_version}${C_RESET}"; echo -e "  Последняя версия: ${C_CYAN}${latest_version}${C_RESET}"; if [ -z "$orig_arg1" ] && [ "$GIT_BRANCH" == "main" ]; then echo -e "  ${C_YELLOW}(Подсказка: Для действия с другой веткой, запустите:${C_RESET}"; echo -e "  ${C_YELLOW} sudo bash $0 <имя_ветки>)${C_RESET}"; fi; check_integrity; echo "--------------------------------------------------------"; echo -n -e "  Статус: "; if [ "$INSTALL_STATUS" == "OK" ]; then echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"; else echo -e "${C_RED}${STATUS_MESSAGE}${C_RESET}"; msg_warning "  Рекомендуется переустановка."; fi; echo "--------------------------------------------------------"; echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Переустановить (Безопасно):${C_RESET}  ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Переустановить (Root):${C_RESET}       ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "${C_CYAN}  3)${C_RESET} ${C_BOLD}Обновить бота:${C_RESET}               ${C_YELLOW}${GIT_BRANCH}${C_RESET}"; echo -e "${C_RED}  4)${C_RESET} ${C_BOLD}Удалить бота${C_RESET}"; echo -e "  5) ${C_BOLD}Выход${C_RESET}"; echo "--------------------------------------------------------"; read -p "$(echo -e "${C_BOLD}Введите номер опции [1-5]: ${C_RESET}")" choice; case $choice in 1) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (безопасно, ${GIT_BRANCH})? (y/n): " confirm; if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_secure; local_version=$(get_local_version "$README_FILE"); else msg_info "Отменено."; fi ;; 2) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (root, ${GIT_BRANCH})? (y/n): " confirm; if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_root; local_version=$(get_local_version "$README_FILE"); else msg_info "Отменено."; fi ;; 3) rm -f /tmp/${SERVICE_NAME}_install.log; update_bot && local_version=$(get_local_version "$README_FILE") ;; 4) msg_question "Удалить бота ПОЛНОСТЬЮ? (y/n): " confirm_uninstall; if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then uninstall_bot; msg_info "Бот удален. Выход."; return; else msg_info "Удаление отменено."; fi ;; 5) break ;; *) msg_error "Неверный выбор." ;; esac; if [[ "$choice" != "4" || ! "$confirm_uninstall" =~ ^[Yy]$ ]]; then echo; read -n 1 -s -r -p "Нажмите любую клавишу для возврата в меню..."; fi; done; }

# --- Главный "Роутер" ---
main() {
    clear
    msg_info "Запуск скрипта управления ботом (Целевая ветка: ${GIT_BRANCH})..."
    check_integrity # Первая проверка статуса

    if [ "$INSTALL_STATUS" == "NOT_FOUND" ] || [ "$INSTALL_STATUS" == "PARTIAL" ]; then
        if [ "$INSTALL_STATUS" == "PARTIAL" ]; then
            msg_error "Обнаружена поврежденная установка."
            msg_warning "${STATUS_MESSAGE}" # Показываем детали проблемы
            msg_question "Обнаружены проблемы. Удалить старые файлы и переустановить? (y/n): " confirm_delete
            if [[ "$confirm_delete" =~ ^[Yy]$ ]]; then
                uninstall_bot # Удаляем только если пользователь согласился
            else
                msg_error "Установка отменена из-за поврежденных файлов. Запустите скрипт снова для управления.";
                exit 1;
            fi
            # После удаления снова проверяем, т.к. статус изменился на NOT_FOUND
            check_integrity
        fi

        # Красивый блок установки
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║      Установка VPS Telegram Бот     ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        echo -e "  ${C_YELLOW}Бот не найден или установка повреждена.${C_RESET}"
        echo -e "  Выберите режим установки для ветки: ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo "--------------------------------------------------------"
        echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Безопасная установка:${C_RESET}   Рекомендуется"
        echo -e "     (Бот работает от пользователя '${SERVICE_USER}')"
        echo ""
        echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Установка от Root:${C_RESET}      Для полного доступа"
        echo -e "     (Бот работает от 'root', нужны права sudo)"
        echo ""
        echo -e "  3) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-3]: ${C_RESET}")" install_choice

        local install_done=false # Внутренний флаг
        rm -f /tmp/${SERVICE_NAME}_install.log # Очищаем лог перед установкой
        case $install_choice in
            1) install_secure; install_done=true ;;
            2) install_root; install_done=true ;;
            *) msg_info "Установка отменена."; exit 0 ;;
        esac

        # Проверка после установки
        if [ "$install_done" = true ]; then
            msg_info "Проверка после установки...";
            check_integrity; # Проверяем снова
            if [ "$INSTALL_STATUS" == "OK" ]; then
                msg_success "Установка завершена успешно!"
                echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"
                read -n 1 -s -r -p "Нажмите Enter для перехода в Главное Меню..."
                # Переходим в главное меню после успешной установки
                main_menu
                echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
                exit 0 # Выходим после main_menu
            else
                msg_error "Установка завершилась с ошибками!"
                msg_error "${C_RED}${STATUS_MESSAGE}${C_RESET}"
                msg_error "Лог: /tmp/${SERVICE_NAME}_install.log";
                exit 1;
            fi
        fi
        # Если установка была отменена, мы сюда не дойдем
    else
        # Если бот уже установлен (INSTALL_STATUS == OK), сразу показываем меню
        main_menu;
        echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
    fi
}

# --- Проверка Root ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Запустите скрипт от имени root или с правами sudo."; exit 1; fi

# --- Запуск ---
main
