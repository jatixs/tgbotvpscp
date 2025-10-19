#!/bin/bash

# --- Конфигурация ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog"
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"

# --- GitHub Репозиторий и Ветка ---
GITHUB_REPO="jatixs/tgbotvpscp"
# (ИЗМЕНЕНИЕ) Используем $1 если он есть, иначе 'main'.
GIT_BRANCH="${1:-main}"
GITHUB_REPO_URL="https://github.com/${GITHUB_REPO}.git"

# --- Цвета и функции вывода ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_CYAN='\033[0;36m'
C_BOLD='\033[1m'

msg_info() { echo -e "${C_CYAN}🔵 $1${C_RESET}"; }
msg_success() { echo -e "${C_GREEN}✅ $1${C_RESET}"; }
msg_warning() { echo -e "${C_YELLOW}⚠️  $1${C_RESET}"; }
msg_error() { echo -e "${C_RED}❌ $1${C_RESET}"; }
msg_question() { read -p "$(echo -e "${C_YELLOW}❓ $1${C_RESET}")" $2; }

spinner() {
    local pid=$1
    local msg=$2
    local spin='|/-\'
    local i=0
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) %4 ))
        printf "\r${C_BLUE}⏳ ${spin:$i:1} ${msg}...${C_RESET}"
        sleep .1
    done
    printf "\r"
}

run_with_spinner() {
    local msg=$1
    shift
    "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 &
    local pid=$!
    spinner "$msg" "$@"
    wait $pid
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        msg_error "Ошибка во время '$msg'. Код выхода: $exit_code"
        msg_error "Смотрите лог для деталей: /tmp/${SERVICE_NAME}_install.log"
    fi
    return $exit_code
}

# --- Проверка загрузчика ---
if command -v curl &> /dev/null; then
    DOWNLOADER="curl -sSLf"
    DOWNLOADER_PIPE="curl -s"
else
    msg_error "Curl не найден. Пожалуйста, установите curl (sudo apt install curl) и запустите скрипт снова."
    exit 1
fi

# --- Проверка целостности ---
INSTALL_STATUS="NOT_FOUND"
STATUS_MESSAGE="Проверка не проводилась."

check_integrity() {
    if [ ! -d "${BOT_INSTALL_PATH}" ]; then
        INSTALL_STATUS="NOT_FOUND"
        STATUS_MESSAGE="Бот не установлен."
        return
    fi
    INSTALL_STATUS="OK" # Предполагаем, что все хорошо
    local errors=()
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then errors+=("- Отсутствует .git (обновление будет невозможно)"); INSTALL_STATUS="PARTIAL"; fi
    if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ] || \
       [ ! -f "${BOT_INSTALL_PATH}/watchdog.py" ] || \
       [ ! -d "${BOT_INSTALL_PATH}/core" ] || \
       [ ! -d "${BOT_INSTALL_PATH}/modules" ]; then
         errors+=("- Отсутствуют основные файлы (bot.py, core/, modules/)")
         INSTALL_STATUS="PARTIAL"
    fi
    if [ ! -f "${VENV_PATH}/bin/python" ]; then errors+=("- Отсутствует venv (${VENV_PATH}/bin/python)"); INSTALL_STATUS="PARTIAL"; fi
    if [ ! -f "${BOT_INSTALL_PATH}/.env" ]; then errors+=("- (Предупреждение) Отсутствует файл .env"); fi
    if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}.service"; then errors+=("- Отсутствует файл ${SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi
    if ! systemctl list-unit-files | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then errors+=("- Отсутствует файл ${WATCHDOG_SERVICE_NAME}.service"); INSTALL_STATUS="PARTIAL"; fi

    if [ "$INSTALL_STATUS" == "OK" ]; then
        local bot_status; local watchdog_status
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then bot_status="${C_GREEN}Активен${C_RESET}"; else bot_status="${C_RED}Неактивен${C_RESET}"; fi
        if systemctl is-active --quiet ${WATCHDOG_SERVICE_NAME}.service; then watchdog_status="${C_GREEN}Активен${C_RESET}"; else watchdog_status="${C_RED}Неактивен${C_RESET}"; fi
        STATUS_MESSAGE="Установка OK (Бот: ${bot_status} | Watchdog: ${watchdog_status})"
        if [[ " ${errors[*]} " =~ " .env" ]]; then STATUS_MESSAGE+=" ${C_YELLOW}(Нет .env!)${C_RESET}"; fi
    elif [ "$INSTALL_STATUS" == "PARTIAL" ]; then
        STATUS_MESSAGE="${C_RED}Установка повреждена.${C_RESET}\n  Проблема: ${errors[0]}"
    fi
}

# --- Функции установки ---
install_extras() {
    local packages_to_install=()
    if ! command -v fail2ban-client &> /dev/null; then msg_question "Fail2Ban не найден. Установить? (y/n): " INSTALL_F2B; if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then packages_to_install+=("fail2ban"); else msg_info "Пропуск Fail2Ban."; fi; else msg_success "Fail2Ban уже установлен."; fi
    if ! command -v speedtest &> /dev/null; then msg_question "Speedtest CLI не найден. Установить? (y/n): " INSTALL_SPEEDTEST; if [[ "$INSTALL_SPEEDTEST" =~ ^[Yy]$ ]]; then packages_to_install+=("speedtest"); else msg_info "Пропуск Speedtest CLI."; fi; else msg_success "Speedtest CLI уже установлен."; fi
    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Установка дополнительных пакетов: ${packages_to_install[*]}"
        if [[ " ${packages_to_install[*]} " =~ " speedtest " ]]; then run_with_spinner "Добавление репозитория Speedtest" bash -c "${DOWNLOADER_PIPE} https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash"; if [ -f /etc/os-release ]; then . /etc/os-release; if [ "$VERSION_CODENAME" == "noble" ]; then sudo sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list; fi; fi; fi
        run_with_spinner "Обновление списка пакетов после добавления репо" sudo apt-get update -y
        run_with_spinner "Установка пакетов" sudo apt-get install -y "${packages_to_install[@]}"; if [ $? -ne 0 ]; then msg_error "Ошибка при установке доп. пакетов."; exit 1; fi
        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then sudo systemctl enable fail2ban &> /dev/null; sudo systemctl start fail2ban &> /dev/null; msg_success "Fail2Ban установлен и запущен."; fi
        msg_success "Дополнительные пакеты установлены."
    fi
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Обновление пакетов и установка базовых зависимостей..."
    run_with_spinner "Обновление списка пакетов" sudo apt-get update -y || { msg_error "Не удалось обновить пакеты"; exit 1; }
    run_with_spinner "Установка зависимостей (python3, pip, venv, git, curl, sudo)" sudo apt-get install -y python3 python3-pip python3-venv git curl wget sudo || { msg_error "Не удалось установить базовые зависимости"; exit 1; }
    install_extras
}

install_logic() {
    local mode=$1
    local branch_to_use=$2 # Принимаем ветку как аргумент
    local exec_user_cmd=""; local owner="root:root"; local owner_user="root"

    if [ "$mode" == "secure" ]; then
        msg_info "2. Создание системного пользователя '${SERVICE_USER}'..."
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || { msg_error "Не удалось создать пользователя ${SERVICE_USER}"; exit 1; }; fi
        sudo mkdir -p ${BOT_INSTALL_PATH}; sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
        msg_info "3. Клонирование репозитория (ветка ${branch_to_use}) от имени ${SERVICE_USER}..."
        run_with_spinner "Клонирование репозитория" sudo -u ${SERVICE_USER} git clone --branch "${branch_to_use}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}"; if [ $? -ne 0 ]; then msg_error "Не удалось клонировать репозиторий."; exit 1; fi
        exec_user_cmd="sudo -u ${SERVICE_USER}"; owner="${SERVICE_USER}:${SERVICE_USER}"; owner_user=${SERVICE_USER}
    else # Root mode
        msg_info "2. Создание директории для бота..."; sudo mkdir -p ${BOT_INSTALL_PATH}
        msg_info "3. Клонирование репозитория (ветка ${branch_to_use}) от имени root..."
        run_with_spinner "Клонирование репозитория" sudo git clone --branch "${branch_to_use}" "${GITHUB_REPO_URL}" "${BOT_INSTALL_PATH}"; if [ $? -ne 0 ]; then msg_error "Не удалось клонировать репозиторий."; exit 1; fi
        exec_user_cmd=""; owner="root:root"; owner_user="root"
    fi

    msg_info "4. Настройка виртуального окружения Python..."
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" $exec_user_cmd ${PYTHON_BIN} -m venv "${VENV_PATH}" || { msg_error "Не удалось создать venv"; exit 1; }; fi
    run_with_spinner "Обновление pip" $exec_user_cmd "${VENV_PATH}/bin/pip" install --upgrade pip || msg_warning "Не удалось обновить pip..."
    run_with_spinner "Установка зависимостей Python" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" || { msg_error "Не удалось установить зависимости Python."; exit 1; }

    msg_info "5. Создание .gitignore, logs/ и config/..."
    sudo -u ${owner_user} bash -c "cat > ${BOT_INSTALL_PATH}/.gitignore" <<< $'/venv/\n/__pycache__/\n*.pyc\n/.env\n/config/\n/logs/\n*.log'; sudo chmod 644 "${BOT_INSTALL_PATH}/.gitignore"
    sudo -u ${owner_user} mkdir -p "${BOT_INSTALL_PATH}/logs" "${BOT_INSTALL_PATH}/config"

    msg_info "6. Настройка переменных окружения..."
    msg_question "Введите ваш Telegram Bot Token: " TG_BOT_TOKEN_USER; msg_question "Введите ваш Telegram User ID (только цифры): " TG_ADMIN_ID_USER; msg_question "Введите ваш Telegram Username (без @, необязательно): " TG_ADMIN_USERNAME_USER
    sudo bash -c "cat > ${BOT_INSTALL_PATH}/.env" <<< $(printf "TG_BOT_TOKEN=\"%s\"\nTG_ADMIN_ID=\"%s\"\nTG_ADMIN_USERNAME=\"%s\"\nINSTALL_MODE=\"%s\"" "$TG_BOT_TOKEN_USER" "$TG_ADMIN_ID_USER" "$TG_ADMIN_USERNAME_USER" "$mode"); sudo chown ${owner} "${BOT_INSTALL_PATH}/.env"; sudo chmod 600 "${BOT_INSTALL_PATH}/.env"

    if [ "$mode" == "root" ]; then
      msg_info "7. Настройка прав sudo для перезапуска/перезагрузки (только для root)..."
      SUDOERS_FILE="/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo tee ${SUDOERS_FILE} > /dev/null <<< $'root ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-bot.service\nroot ALL=(ALL) NOPASSWD: /bin/systemctl restart tg-watchdog.service\nroot ALL=(ALL) NOPASSWD: /sbin/reboot'; sudo chmod 440 ${SUDOERS_FILE}
    elif [ "$mode" == "secure" ]; then
      SUDOERS_WATCHDOG="/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo tee ${SUDOERS_WATCHDOG} > /dev/null <<< $'Defaults:tgbot !requiretty\ntgbot ALL=(root) NOPASSWD: /bin/systemctl restart tg-bot.service'; sudo chmod 440 ${SUDOERS_WATCHDOG}; msg_info "7. Настроены права sudo для перезапуска бота из watchdog."
    fi

    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "${mode}" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog"

    local server_ip=$(curl -s 4.ipinfo.io/ip || echo "YOUR_SERVER_IP"); echo ""; echo "-----------------------------------------------------"; msg_success "Установка завершена!"; msg_info "   Не забудьте настроить внешний мониторинг (UptimeRobot)"; msg_info "   на IP: ${server_ip}"; echo "-----------------------------------------------------"
}

# (ИЗМЕНЕНИЕ) Теперь install_* принимают только ветку GIT_BRANCH, определенную в начале
install_secure() { echo -e "\n${C_BOLD}=== Начало безопасной установки (ветка: ${GIT_BRANCH}) ===${C_RESET}"; common_install_steps; install_logic "secure" "${GIT_BRANCH}"; }
install_root() { echo -e "\n${C_BOLD}=== Начало установки от имени Root (ветка: ${GIT_BRANCH}) ===${C_RESET}"; common_install_steps; install_logic "root" "${GIT_BRANCH}"; }

create_and_start_service() {
    local svc_name=$1; local script_path=$2; local install_mode=$3; local description=$4
    local user="root"; local group="root"; local env_file_line=""; local desc_mode_suffix=""; local after_line="After=network.target"; local requires_line=""

    if [ "$install_mode" == "secure" ] && [ "$svc_name" == "$SERVICE_NAME" ]; then
        user=${SERVICE_USER}; group=${SERVICE_USER}; env_file_line="EnvironmentFile=${BOT_INSTALL_PATH}/.env"; desc_mode_suffix="(Secure Mode)"
    elif [ "$svc_name" == "$SERVICE_NAME" ]; then # Root mode for bot
        env_file_line="EnvironmentFile=${BOT_INSTALL_PATH}/.env"; desc_mode_suffix="(Root Mode)"
    elif [ "$svc_name" == "$WATCHDOG_SERVICE_NAME" ]; then
         after_line="After=network.target ${SERVICE_NAME}.service"
    fi

    msg_info "Создание systemd сервиса для ${svc_name}..."
    SERVICE_FILE="/etc/systemd/system/${svc_name}.service"
    sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${description} Service ${desc_mode_suffix}
${after_line}
${requires_line}

[Service]
Type=simple
User=${user}
Group=${group}
WorkingDirectory=${BOT_INSTALL_PATH}
${env_file_line}
ExecStart=${VENV_PATH}/bin/python ${script_path}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    msg_info "Запуск и активация сервиса ${svc_name}..."; sudo systemctl daemon-reload; sudo systemctl enable ${svc_name}.service &> /dev/null; run_with_spinner "Запуск ${svc_name}" sudo systemctl start ${svc_name}; sleep 2
    if sudo systemctl is-active --quiet ${svc_name}.service; then msg_success "Сервис ${svc_name} успешно запущен!"; msg_info "Для проверки статуса: sudo systemctl status ${svc_name}"; else msg_error "Сервис ${svc_name} не запустился. Логи: sudo journalctl -u ${svc_name} -n 50 --no-pager"; if [ "$svc_name" == "$SERVICE_NAME" ]; then exit 1; fi; fi
}

uninstall_bot() {
    echo -e "\n${C_BOLD}=== Начало удаления Telegram-бота и Watchdog ===${C_RESET}"; msg_info "1. Остановка и отключение сервисов..."
    if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then sudo systemctl stop ${SERVICE_NAME} &> /dev/null; sudo systemctl disable ${SERVICE_NAME} &> /dev/null; fi
    if systemctl list-units --full -all | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then sudo systemctl stop ${WATCHDOG_SERVICE_NAME} &> /dev/null; sudo systemctl disable ${WATCHDOG_SERVICE_NAME} &> /dev/null; fi
    msg_info "2. Удаление системных файлов..."; sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"; sudo rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service"; sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"; sudo rm -f "/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"; sudo systemctl daemon-reload
    msg_info "3. Удаление директории с ботом..."; sudo rm -rf "${BOT_INSTALL_PATH}"; msg_info "4. Удаление пользователя '${SERVICE_USER}' (если существует)..."; if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null || msg_warning "Не удалось полностью удалить пользователя ${SERVICE_USER}."; fi; msg_success "Удаление полностью завершено."
}

# (ИЗМЕНЕНИЕ) update_bot теперь использует только GIT_BRANCH
update_bot() {
    echo -e "\n${C_BOLD}=== Начало обновления бота (ветка: ${GIT_BRANCH}) ===${C_RESET}"
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Установка (git) не найдена."; msg_error "Невозможно обновиться. Пожалуйста, переустановите бота."; return 1; fi
    local exec_user_cmd=""; if [ -f "${BOT_INSTALL_PATH}/.env" ]; then INSTALL_MODE_DETECTED=$(grep '^INSTALL_MODE=' "${BOT_INSTALL_PATH}/.env" | cut -d'=' -f2 | tr -d '"'); if [ "$INSTALL_MODE_DETECTED" == "secure" ]; then exec_user_cmd="sudo -u ${SERVICE_USER}"; fi; fi
    msg_warning "ВНИМАНИЕ: Обновление принудительно перезапишет локальные изменения."; msg_warning "Файлы .env, config/, logs/ будут сохранены."; msg_info "1. Получение обновлений из Git (ветка ${GIT_BRANCH})..."
    pushd "${BOT_INSTALL_PATH}" > /dev/null; run_with_spinner "Получение (fetch) изменений" $exec_user_cmd git fetch origin; run_with_spinner "Принудительный сброс (reset) до origin/${GIT_BRANCH}" $exec_user_cmd git reset --hard "origin/${GIT_BRANCH}"; local update_status=$?; popd > /dev/null
    if [ $update_status -ne 0 ]; then msg_error "Ошибка во время git fetch/reset."; return 1; fi; msg_success "Файлы проекта успешно обновлены."
    msg_info "2. Обновление зависимостей Python..."; run_with_spinner "Установка/обновление зависимостей" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade; if [ $? -ne 0 ]; then msg_error "Ошибка при обновлении зависимостей Python."; return 1; fi
    msg_info "3. Перезапуск сервисов..."; if sudo systemctl restart ${SERVICE_NAME}; then msg_success "Сервис ${SERVICE_NAME} успешно перезапущен."; else msg_error "Ошибка при перезапуске ${SERVICE_NAME}."; return 1; fi; sleep 1
    if sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; then msg_success "Сервис ${WATCHDOG_SERVICE_NAME} успешно перезапущен."; else msg_error "Ошибка при перезапуске ${WATCHDOG_SERVICE_NAME}."; fi
    echo -e "\n${C_GREEN}${C_BOLD}🎉 Обновление завершено!${C_RESET}\n"
}

# --- Меню управления ---
main_menu() {
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║     VPS Manager Telegram Bot      ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        local current_branch=$(cd "$BOT_INSTALL_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "Неизвестно")
        echo -e "  Текущая ветка: ${C_YELLOW}${current_branch}${C_RESET}"
        # (ИЗМЕНЕНИЕ) Используем GIT_BRANCH как единственную целевую ветку
        echo -e "  Целевая ветка (для уст./обн.): ${C_YELLOW}${GIT_BRANCH}${C_RESET}"

        check_integrity
        echo "--------------------------------------------------------"
        echo -n -e "  Статус: "; if [ "$INSTALL_STATUS" == "OK" ]; then echo -e "${C_GREEN}${STATUS_MESSAGE}${C_RESET}"; else echo -e "${C_RED}${STATUS_MESSAGE}${C_RESET}"; msg_warning "  Рекомендуется переустановка."; fi
        echo "--------------------------------------------------------"
        # (ИЗМЕНЕНИЕ) Убраны опции тестовой ветки (T1, T2, T3)
        echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Переустановить (Secure):${C_RESET}     ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Переустановить (Root):${C_RESET}       ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "${C_CYAN}  3)${C_RESET} ${C_BOLD}Обновить бота:${C_RESET}               ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "${C_RED}  4)${C_RESET} ${C_BOLD}Удалить бота${C_RESET}"
        echo -e "  5) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-5]: ${C_RESET}")" choice

        case $choice in
            1) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (secure, ветка ${GIT_BRANCH})? (y/n): " confirm; if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_secure; else msg_info "Отменено."; fi ;;
            2) rm -f /tmp/${SERVICE_NAME}_install.log; msg_question "Переустановить (root, ветка ${GIT_BRANCH})? (y/n): " confirm; if [[ "$confirm" =~ ^[Yy]$ ]]; then uninstall_bot; install_root; else msg_info "Отменено."; fi ;;
            3) rm -f /tmp/${SERVICE_NAME}_install.log; update_bot ;; # update_bot теперь использует GIT_BRANCH
            4) msg_question "Удалить бота ПОЛНОСТЬЮ? (y/n): " confirm_uninstall; if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then uninstall_bot; msg_info "Бот удален. Выход."; return; else msg_info "Удаление отменено."; fi ;;
            5) break ;;
            *) msg_error "Неверный выбор." ;;
        esac

        if [[ "$choice" != "4" || ! "$confirm_uninstall" =~ ^[Yy]$ ]]; then
            echo; read -n 1 -s -r -p "Нажмите любую клавишу для возврата в меню..."
        fi
    done
}

# --- Главный "Роутер" ---
main() {
    clear
    msg_info "Запуск скрипта управления ботом (Целевая ветка: ${GIT_BRANCH})..."
    check_integrity

    if [ "$INSTALL_STATUS" == "NOT_FOUND" ] || [ "$INSTALL_STATUS" == "PARTIAL" ]; then
        if [ "$INSTALL_STATUS" == "PARTIAL" ]; then
            msg_error "Обнаружена поврежденная установка."; msg_warning "${STATUS_MESSAGE}"
            msg_question "Рекомендуется полная переустановка. Удалить существующие файлы и начать заново? (y/n): " confirm_delete
            if [[ "$confirm_delete" =~ ^[Yy]$ ]]; then uninstall_bot; else msg_error "Выход."; exit 1; fi
        fi

        msg_info "Бот не установлен. Запуск мастера установки..."
        echo "--------------------------------------------------------"
        # (ИЗМЕНЕНИЕ) Убраны опции тестовой ветки
        echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Установить (Secure):${C_RESET}     ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Установить (Root):${C_RESET}       ${C_YELLOW}${GIT_BRANCH}${C_RESET}"
        echo -e "  3) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-3]: ${C_RESET}")" install_choice

        local install_done=false
        rm -f /tmp/${SERVICE_NAME}_install.log

        case $install_choice in
            1) install_secure; install_done=true ;; # install_secure теперь использует GIT_BRANCH
            2) install_root; install_done=true ;;   # install_root теперь использует GIT_BRANCH
            *) msg_info "Установка отменена. Выход."; exit 0 ;;
        esac

        if [ "$install_done" = true ]; then
            msg_info "Повторная проверка целостности после установки из ветки '${GIT_BRANCH}'..."
            check_integrity
            if [ "$INSTALL_STATUS" == "OK" ]; then
                msg_success "Установка завершена и проверена. Запуск меню управления..."
                read -n 1 -s -r -p "Нажмите любую клавишу для продолжения..."
            else
                msg_error "Установка завершилась, но проверка не пройдена."; msg_error "Лог: /tmp/${SERVICE_NAME}_install.log"; exit 1
            fi
        fi
    fi

    # Запускаем главное меню управления
    main_menu
    echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
}

# --- Проверка Root ---
if [ "$(id -u)" -ne 0 ]; then msg_error "Запустите скрипт от имени root или с правами sudo."; exit 1; fi

# --- Запуск ---
main