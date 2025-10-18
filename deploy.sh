#!/bin/bash

# --- Конфигурация ---
BOT_INSTALL_PATH="/opt/tg-bot"
SERVICE_NAME="tg-bot"
WATCHDOG_SERVICE_NAME="tg-watchdog" # Имя сервиса для watchdog
SERVICE_USER="tgbot"
PYTHON_BIN="/usr/bin/python3"
VENV_PATH="${BOT_INSTALL_PATH}/venv"

# URLы файлов
BOT_PY_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/bot.py"
REQUIREMENTS_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/requirements.txt"
WATCHDOG_PY_URL="https://raw.githubusercontent.com/jatixs/tgbotvpscp/main/watchdog.py" # URL для watchdog.py

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

# --- Спиннер ---
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
    printf "\r" # Очистить строку спиннера
}

run_with_spinner() {
    local msg=$1
    shift
    "$@" > /dev/null 2>&1 &
    local pid=$!
    spinner "$msg" "$@" # Передаем команду для возможного вывода ошибки
    wait $pid
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        msg_error "Ошибка во время '$msg'. Код выхода: $exit_code"
        # Можно добавить вывод логов при ошибке
        # echo "Command output:"
        # cat command_output.log # Если перенаправляли вывод в файл
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

# --- Установка доп. пакетов ---
install_extras() {
    local packages_to_install=()
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " INSTALL_F2B
        if [[ "$INSTALL_F2B" =~ ^[Yy]$ ]]; then
            packages_to_install+=("fail2ban")
        else msg_info "Пропуск Fail2Ban."; fi
    else msg_success "Fail2Ban уже установлен."; fi

    if ! command -v speedtest &> /dev/null; then
        msg_question "Speedtest CLI не найден. Установить? (y/n): " INSTALL_SPEEDTEST
        if [[ "$INSTALL_SPEEDTEST" =~ ^[Yy]$ ]]; then
            packages_to_install+=("speedtest") # Используем метапакет ookla
        else msg_info "Пропуск Speedtest CLI."; fi
    else msg_success "Speedtest CLI уже установлен."; fi

    if [ ${#packages_to_install[@]} -gt 0 ]; then
        msg_info "Установка дополнительных пакетов: ${packages_to_install[*]}"
        # Добавляем репозиторий speedtest если нужно
        if [[ " ${packages_to_install[*]} " =~ " speedtest " ]]; then
             run_with_spinner "Добавление репозитория Speedtest" bash -c "${DOWNLOADER_PIPE} https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash"
             # Фикс для Ubuntu Noble
             if [ -f /etc/os-release ]; then . /etc/os-release; if [ "$VERSION_CODENAME" == "noble" ]; then sudo sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list; fi; fi
        fi
        run_with_spinner "Обновление списка пакетов после добавления репо" sudo apt-get update -y
        run_with_spinner "Установка пакетов" sudo apt-get install -y "${packages_to_install[@]}"
        if [ $? -ne 0 ]; then msg_error "Ошибка при установке доп. пакетов."; exit 1; fi

        # Включаем fail2ban если ставили
        if [[ " ${packages_to_install[*]} " =~ " fail2ban " ]]; then
            sudo systemctl enable fail2ban &> /dev/null
            sudo systemctl start fail2ban &> /dev/null
            msg_success "Fail2Ban установлен и запущен."
        fi
        msg_success "Дополнительные пакеты установлены."
    fi
}

# --- Общие шаги установки ---
common_install_steps() {
    msg_info "1. Обновление пакетов и установка базовых зависимостей..."
    run_with_spinner "Обновление списка пакетов" sudo apt-get update -y || { msg_error "Не удалось обновить пакеты"; exit 1; }
    run_with_spinner "Установка зависимостей (python3, pip, venv, git, curl, sudo)" sudo apt-get install -y python3 python3-pip python3-venv git curl wget sudo || { msg_error "Не удалось установить базовые зависимости"; exit 1; }

    install_extras # Установка fail2ban, speedtest

    msg_info "2. Создание директории для бота..."
    sudo mkdir -p "${BOT_INSTALL_PATH}/logs" "${BOT_INSTALL_PATH}/config" || { msg_error "Не удалось создать директории бота"; exit 1; }

    msg_info "3. Скачивание файлов проекта из GitHub..."
    if ! ${DOWNLOADER} "${BOT_PY_URL}" | sudo tee "${BOT_INSTALL_PATH}/bot.py" > /dev/null; then msg_error "Не удалось скачать bot.py."; exit 1; fi
    if ! ${DOWNLOADER} "${REQUIREMENTS_URL}" | sudo tee "${BOT_INSTALL_PATH}/requirements.txt" > /dev/null; then msg_error "Не удалось скачать requirements.txt."; exit 1; fi
    if ! ${DOWNLOADER} "${WATCHDOG_PY_URL}" | sudo tee "${BOT_INSTALL_PATH}/watchdog.py" > /dev/null; then msg_error "Не удалось скачать watchdog.py."; exit 1; fi
}

# --- Логика установки (Secure/Root) ---
install_logic() {
    local mode=$1
    local exec_user_cmd=""
    local owner="root:root"

    if [ "$mode" == "secure" ]; then
        msg_info "Создание системного пользователя '${SERVICE_USER}'..."
        if ! id "${SERVICE_USER}" &>/dev/null; then
            sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER} || { msg_error "Не удалось создать пользователя ${SERVICE_USER}"; exit 1; }
        fi
        sudo chown -R ${SERVICE_USER}:${SERVICE_USER} ${BOT_INSTALL_PATH}
        sudo chmod -R 750 ${BOT_INSTALL_PATH} # Даем права группе (для watchdog?)
        exec_user_cmd="sudo -u ${SERVICE_USER}"
        owner="${SERVICE_USER}:${SERVICE_USER}"
    else # Root mode
        sudo chown -R root:root ${BOT_INSTALL_PATH}
        sudo chmod -R 750 ${BOT_INSTALL_PATH} # 755 не нужно, если запускается от root
    fi

    msg_info "4. Настройка виртуального окружения Python..."
    # Создаем venv от имени нужного пользователя
    if [ ! -d "${VENV_PATH}" ]; then
        run_with_spinner "Создание venv" $exec_user_cmd ${PYTHON_BIN} -m venv "${VENV_PATH}" || { msg_error "Не удалось создать venv"; exit 1; }
    fi

    # Устанавливаем зависимости от имени нужного пользователя
    run_with_spinner "Обновление pip" $exec_user_cmd "${VENV_PATH}/bin/pip" install --upgrade pip || msg_warning "Не удалось обновить pip, но продолжаем..."
    run_with_spinner "Установка зависимостей Python" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" || { msg_error "Не удалось установить зависимости Python."; exit 1; }

    msg_info "5. Настройка переменных окружения..."
    msg_question "Введите ваш Telegram Bot Token: " TG_BOT_TOKEN_USER
    msg_question "Введите ваш Telegram User ID (только цифры): " TG_ADMIN_ID_USER
    msg_question "Введите ваш Telegram Username (без @, необязательно): " TG_ADMIN_USERNAME_USER

    # Создаем .env файл
    sudo bash -c "cat > ${BOT_INSTALL_PATH}/.env" <<EOF
TG_BOT_TOKEN="${TG_BOT_TOKEN_USER}"
TG_ADMIN_ID="${TG_ADMIN_ID_USER}"
TG_ADMIN_USERNAME="${TG_ADMIN_USERNAME_USER}"
INSTALL_MODE="${mode}"
EOF

    sudo chown ${owner} "${BOT_INSTALL_PATH}/.env"
    sudo chmod 600 "${BOT_INSTALL_PATH}/.env" # Только владелец может читать/писать

    if [ "$mode" == "root" ]; then
      msg_info "6. Настройка прав sudo для перезапуска/перезагрузки (только для root)..."
      SUDOERS_FILE="/etc/sudoers.d/98-${SERVICE_NAME}-root"
      sudo tee ${SUDOERS_FILE} > /dev/null <<EOF
root ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}.service
root ALL=(ALL) NOPASSWD: /bin/systemctl restart ${WATCHDOG_SERVICE_NAME}.service
root ALL=(ALL) NOPASSWD: /sbin/reboot
EOF
      sudo chmod 440 ${SUDOERS_FILE}
    elif [ "$mode" == "secure" ]; then
      # Даем пользователю root право перезапускать watchdog от имени tgbot
      SUDOERS_WATCHDOG="/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"
      sudo tee ${SUDOERS_WATCHDOG} > /dev/null <<EOF
Defaults:${SERVICE_USER} !requiretty
${SERVICE_USER} ALL=(root) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}.service
EOF
       sudo chmod 440 ${SUDOERS_WATCHDOG}
       msg_info "Настроены права sudo для перезапуска бота из watchdog."
    fi

    # Создаем и запускаем сервисы
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "${mode}" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Watchdog" # Watchdog всегда от root

    # Напоминание про внешний мониторинг
    local server_ip=$(curl -s 4.ipinfo.io/ip || echo "YOUR_SERVER_IP")
    echo ""
    echo "-----------------------------------------------------"
    echo "🔔 REMINDER: Don't forget to set up or check external monitoring"
    echo "   for this server (e.g., using UptimeRobot)!"
    echo "   Monitor IP: ${server_ip}"
    echo "-----------------------------------------------------"
}

# --- Функции установки режимов ---
install_secure() {
    echo -e "\n${C_BOLD}=== Начало безопасной установки (отдельный пользователь) ===${C_RESET}"
    common_install_steps
    install_logic "secure"
}

install_root() {
    echo -e "\n${C_BOLD}=== Начало установки от имени Root ===${C_RESET}"
    if [ "$(id -u)" -ne 0 ]; then
        msg_error "Для установки от имени root, запустите скрипт с 'sudo'."
        exit 1
    fi
    common_install_steps
    install_logic "root"
}

# --- Функция создания systemd-сервиса ---
create_and_start_service() {
    local svc_name=$1
    local script_path=$2
    local install_mode=$3 # 'secure', 'root', или режим watchdog'а
    local description=$4

    local user="root"
    local group="root"
    local env_file_line=""
    local desc_mode_suffix=""

    if [ "$install_mode" == "secure" ] && [ "$svc_name" == "$SERVICE_NAME" ]; then
        user=${SERVICE_USER}
        group=${SERVICE_USER}
        env_file_line="EnvironmentFile=${BOT_INSTALL_PATH}/.env"
        desc_mode_suffix="(Secure Mode)"
    elif [ "$svc_name" == "$SERVICE_NAME" ]; then # Root mode for bot
        env_file_line="EnvironmentFile=${BOT_INSTALL_PATH}/.env"
        desc_mode_suffix="(Root Mode)"
    # Для watchdog user/group остаются root, env_file не нужен ему явно (он сам читает)
    elif [ "$svc_name" == "$WATCHDOG_SERVICE_NAME" ]; then
         # Watchdog требует sudo для перезапуска сервиса бота
         # Добавим зависимость от сети и основного бота
         after_line="After=network.target ${SERVICE_NAME}.service"
         # requires_line="Requires=${SERVICE_NAME}.service" # Может вызвать цикл остановки?
    fi

    msg_info "Создание systemd сервиса для ${svc_name}..."
    SERVICE_FILE="/etc/systemd/system/${svc_name}.service"
    sudo tee ${SERVICE_FILE} > /dev/null <<EOF
[Unit]
Description=${description} Service ${desc_mode_suffix}
${after_line:-After=network.target}
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

    msg_info "Запуск и активация сервиса ${svc_name}..."
    sudo systemctl daemon-reload
    sudo systemctl enable ${svc_name}.service &> /dev/null
    run_with_spinner "Запуск ${svc_name}" sudo systemctl start ${svc_name}

    sleep 2 # Даем время сервису запуститься

    if sudo systemctl is-active --quiet ${svc_name}.service; then
        msg_success "Сервис ${svc_name} успешно запущен!"
        msg_info "Для проверки статуса: sudo systemctl status ${svc_name}"
    else
        msg_error "Сервис ${svc_name} не запустился. Проверьте логи: sudo journalctl -u ${svc_name} -n 50 --no-pager"
        # Не выходим из скрипта, если watchdog не запустился, но бот запустился
        if [ "$svc_name" == "$SERVICE_NAME" ]; then exit 1; fi
    fi
}

# --- Удаление бота ---
uninstall_bot() {
    echo -e "\n${C_BOLD}=== Начало удаления Telegram-бота и Watchdog ===${C_RESET}"

    msg_info "1. Остановка и отключение сервисов..."
    if systemctl list-units --full -all | grep -q "${SERVICE_NAME}.service"; then
        sudo systemctl stop ${SERVICE_NAME} &> /dev/null
        sudo systemctl disable ${SERVICE_NAME} &> /dev/null
    fi
    if systemctl list-units --full -all | grep -q "${WATCHDOG_SERVICE_NAME}.service"; then
        sudo systemctl stop ${WATCHDOG_SERVICE_NAME} &> /dev/null
        sudo systemctl disable ${WATCHDOG_SERVICE_NAME} &> /dev/null
    fi

    msg_info "2. Удаление системных файлов..."
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    sudo rm -f "/etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service"
    sudo rm -f "/etc/sudoers.d/98-${SERVICE_NAME}-root"
    sudo rm -f "/etc/sudoers.d/99-${WATCHDOG_SERVICE_NAME}-restart"
    sudo systemctl daemon-reload

    msg_info "3. Удаление директории с ботом..."
    sudo rm -rf "${BOT_INSTALL_PATH}"

    msg_info "4. Удаление пользователя '${SERVICE_USER}' (если существует)..."
    if id "${SERVICE_USER}" &>/dev/null; then
        sudo userdel -r "${SERVICE_USER}" &> /dev/null || msg_warning "Не удалось полностью удалить пользователя ${SERVICE_USER} (возможно, остались файлы)."
    fi

    msg_success "Удаление полностью завершено."
}

# --- Обновление бота ---
update_bot() {
    echo -e "\n${C_BOLD}=== Начало обновления бота и watchdog ===${C_RESET}"
    if [ ! -f "${BOT_INSTALL_PATH}/bot.py" ]; then msg_error "Установка бота не найдена в ${BOT_INSTALL_PATH}."; return 1; fi

    msg_info "1. Скачивание последних версий файлов..."
    if ! ${DOWNLOADER} "${BOT_PY_URL}" | sudo tee "${BOT_INSTALL_PATH}/bot.py" > /dev/null; then msg_error "Не удалось скачать bot.py."; return 1; fi
    msg_success "Файл bot.py успешно обновлен."
    if ! ${DOWNLOADER} "${WATCHDOG_PY_URL}" | sudo tee "${BOT_INSTALL_PATH}/watchdog.py" > /dev/null; then msg_error "Не удалось скачать watchdog.py."; return 1; fi
    msg_success "Файл watchdog.py успешно обновлен."
    if ! ${DOWNLOADER} "${REQUIREMENTS_URL}" | sudo tee "${BOT_INSTALL_PATH}/requirements.txt" > /dev/null; then msg_warning "Не удалось скачать requirements.txt. Используется старая версия."; else msg_success "Файл requirements.txt успешно обновлен."; fi

    msg_info "2. Обновление зависимостей Python..."
    local exec_user_cmd=""
    local owner="root:root"
    if [ -f "${BOT_INSTALL_PATH}/.env" ]; then
        # Читаем .env, чтобы определить режим установки
        INSTALL_MODE_DETECTED=$(grep '^INSTALL_MODE=' "${BOT_INSTALL_PATH}/.env" | cut -d'=' -f2 | tr -d '"')
        if [ "$INSTALL_MODE_DETECTED" == "secure" ]; then
             exec_user_cmd="sudo -u ${SERVICE_USER}"
             owner="${SERVICE_USER}:${SERVICE_USER}"
        fi
    fi
    # Обновляем права на скачанные файлы
    sudo chown ${owner} "${BOT_INSTALL_PATH}/bot.py" "${BOT_INSTALL_PATH}/watchdog.py" "${BOT_INSTALL_PATH}/requirements.txt"
    sudo chmod 640 "${BOT_INSTALL_PATH}/bot.py" "${BOT_INSTALL_PATH}/watchdog.py" "${BOT_INSTALL_PATH}/requirements.txt" # Права на чтение владельцу и группе

    # Установка зависимостей от нужного пользователя
    run_with_spinner "Установка/обновление зависимостей" $exec_user_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade || { msg_error "Ошибка при обновлении зависимостей Python."; return 1; }

    msg_info "3. Перезапуск сервисов..."
    # Перезапускаем watchdog сначала, затем бота
    if sudo systemctl restart ${WATCHDOG_SERVICE_NAME}; then msg_success "Сервис ${WATCHDOG_SERVICE_NAME} успешно перезапущен."; else msg_error "Ошибка при перезапуске ${WATCHDOG_SERVICE_NAME}. Логи: sudo journalctl -u ${WATCHDOG_SERVICE_NAME} -n 50 --no-pager"; fi
    sleep 1 # Небольшая пауза
    if sudo systemctl restart ${SERVICE_NAME}; then msg_success "Сервис ${SERVICE_NAME} успешно перезапущен."; else msg_error "Ошибка при перезапуске ${SERVICE_NAME}. Логи: sudo journalctl -u ${SERVICE_NAME} -n 50 --no-pager"; return 1; fi

    echo -e "\n${C_GREEN}${C_BOLD}🎉 Обновление завершено!${C_RESET}\n"
}

# --- Главное меню ---
main_menu() {
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}"
        echo "╔══════════════════════════════════════════════════════╗"
        echo "║                                                      ║"
        echo "║             VPS Manager Telegram Bot                 ║"
        echo "║                   by Jatix                           ║"
        echo "╚══════════════════════════════════════════════════════╝"
        echo -e "${C_RESET}"
        echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Установить (Secure):${C_RESET} Рекомендуемый, безопасный режим"
        echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Установить (Root):${C_RESET}   Менее безопасный, полный доступ"
        echo -e "${C_CYAN}  3)${C_RESET} ${C_BOLD}Обновить бота:${C_RESET}         Обновление бота и watchdog"
        echo -e "${C_RED}  4)${C_RESET} ${C_BOLD}Удалить бота:${C_RESET}          Полное удаление с сервера"
        echo -e "  5) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-5]: ${C_RESET}")" choice

        case $choice in
            1) install_secure ;;
            2) install_root ;;
            3) update_bot ;;
            4)
                msg_question "ВЫ УВЕРЕНЫ, что хотите ПОЛНОСТЬЮ удалить бота и watchdog? (y/n): " confirm_uninstall
                if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then
                    uninstall_bot
                else
                    msg_info "Удаление отменено."
                fi
                ;;
            5) break ;;
            *) msg_error "Неверный выбор." ;;
        esac
        echo
        read -n 1 -s -r -p "Нажмите любую клавишу для возврата в меню..."
    done
    echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
}

# --- Запуск ---
main_menu