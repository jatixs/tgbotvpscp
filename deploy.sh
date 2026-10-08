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
LEGACY_SECURITY_KEY_FILE="${BOT_INSTALL_PATH}/config/security.key"
ENV_BACKUP_FILE="/root/.tgbot_env.bak"
LEGACY_ENV_BACKUP_FILE="/tmp/tgbot_env.bak"

if [ -f "${LEGACY_ENV_BACKUP_FILE}" ] && [ ! -f "${ENV_BACKUP_FILE}" ]; then
    sudo install -m 600 "${LEGACY_ENV_BACKUP_FILE}" "${ENV_BACKUP_FILE}"
    sudo rm -f "${LEGACY_ENV_BACKUP_FILE}"
fi

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

generate_fernet_key() {
    "${PYTHON_BIN}" - <<'PY'
import base64
import os

print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
}

is_node_context() {
    if [ "${FORCE_NODE_MODE:-no}" = "yes" ]; then
        return 0
    fi
    if [ "${IS_NODE:-no}" = "yes" ]; then
        return 0
    fi
    if [ -f "${ENV_FILE}" ] && grep -q '^MODE=node' "${ENV_FILE}"; then
        return 0
    fi
    if [ -f "${ENV_BACKUP_FILE}" ] && grep -q '^MODE=node' "${ENV_BACKUP_FILE}"; then
        return 0
    fi
    return 1
}

ensure_data_encryption_key() {
    if is_node_context; then
        return 0
    fi

    if [ -n "$DATA_ENCRYPTION_KEY" ]; then
        export DATA_ENCRYPTION_KEY
        return 0
    fi

    DATA_ENCRYPTION_KEY=$(generate_fernet_key)
    export DATA_ENCRYPTION_KEY
    msg_warning "DATA_ENCRYPTION_KEY отсутствовал. Сгенерирован новый ключ шифрования."
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

APT_LOCK_FILES="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/lib/apt/lists/lock /var/cache/apt/archives/lock"
APT_LOCK_WAIT_MAX=600

apt_lock_busy() {
    if command -v fuser >/dev/null 2>&1; then
        sudo fuser $APT_LOCK_FILES >/dev/null 2>&1
    else
        pgrep -x apt-get >/dev/null 2>&1 || pgrep -x apt >/dev/null 2>&1 || pgrep -x dpkg >/dev/null 2>&1 || pgrep -f unattended-upgrade >/dev/null 2>&1
    fi
}

# Unattended-upgrades or a parallel apt run holds the dpkg lock; wait instead of failing with code 100.
wait_for_apt_lock() {
    local waited=0
    while apt_lock_busy; do
        if [ $waited -eq 0 ]; then
            msg_warning "Менеджер пакетов занят другим процессом (apt/dpkg), ожидаю освобождения блокировки..."
        fi
        if [ $waited -ge $APT_LOCK_WAIT_MAX ]; then
            msg_error "Блокировка apt/dpkg не освободилась за $((APT_LOCK_WAIT_MAX / 60)) мин. Продолжаю, но установка пакетов может не удаться."
            return 1
        fi
        sleep 5
        waited=$((waited + 5))
    done
    if [ $waited -gt 0 ]; then
        msg_success "Блокировка apt/dpkg освобождена (ожидание ${waited} с)."
    fi
    return 0
}

run_with_spinner() {
    local msg=$1
    shift
    local is_apt=0
    case " $* " in *" apt-get "*) is_apt=1 ;; esac
    if [ $is_apt -eq 1 ]; then wait_for_apt_lock; fi

    local attempt=1
    local exit_code=0
    while true; do
        ( "$@" >> /tmp/${SERVICE_NAME}_install.log 2>&1 ) &
        local pid=$!
        spinner "$pid" "$msg"
        wait $pid
        exit_code=$?
        echo -ne "\033[2K\r"
        if [ $exit_code -ne 0 ] && [ $is_apt -eq 1 ] && [ $attempt -lt 3 ] \
            && tail -n 20 /tmp/${SERVICE_NAME}_install.log | grep -q "Could not get lock\|Unable to acquire the dpkg"; then
            attempt=$((attempt + 1))
            msg_warning "apt не смог получить блокировку, повторная попытка ${attempt}/3: '$msg'"
            sleep 5
            wait_for_apt_lock
            continue
        fi
        break
    done
    if [ $exit_code -ne 0 ]; then
        msg_error "Ошибка во время '$msg'. Код: $exit_code"
        msg_error "Подробности в логе: /tmp/${SERVICE_NAME}_install.log"
        echo -e "${C_YELLOW}Последние строки лога (/tmp/${SERVICE_NAME}_install.log):${C_RESET}"
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
        grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE" || echo "Не найдена"
    else 
        echo "Не установлен"
    fi 
}

INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Проверка не проводилась."
INTEGRITY_STATUS=""
# Set by update_bot so install_node_logic prints "update" wording instead of "install".
NODE_OP_UPDATE=""

op_header() { echo -e "\n${C_BOLD}=== $1 ===${C_RESET}"; }

# "НОДЫ" / "АГЕНТА" — genitive label of what is currently installed.
target_label() {
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then echo "НОДЫ"; else echo "АГЕНТА"; fi
}

mode_label() {
    local runtime=$1 mode=$2
    local m="Secure"; if [ "$mode" == "root" ]; then m="Root"; fi
    echo "${runtime} - ${m}"
}

# "Установка АГЕНТА (Systemd - Secure)" on a clean host, "Переустановка …" over an existing install.
agent_install_header() {
    local verb="Установка"
    if [ -d "${BOT_INSTALL_PATH}" ] && [ -f "${ENV_FILE}" ]; then verb="Переустановка"; fi
    op_header "${verb} АГЕНТА ($(mode_label "$1" "$2"))"
}

check_integrity() {
    INTEGRITY_STATUS=""
    if [ ! -d "${BOT_INSTALL_PATH}" ] || [ ! -f "${ENV_FILE}" ]; then
        INSTALL_TYPE="НЕТ"; STATUS_MESSAGE="Бот не установлен."; return;
    fi

    DEPLOY_MODE_FROM_ENV=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"' || echo "systemd")
    IS_NODE=$(grep -q "MODE=node" "${ENV_FILE}" && echo "yes" || echo "no")

    if [ "$IS_NODE" == "yes" ]; then
        INTEGRITY_STATUS="${C_GREEN}🛡️ Режим НОДЫ (Git не требуется)${C_RESET}"
    elif [ -d "${BOT_INSTALL_PATH}/.git" ]; then
        cd "${BOT_INSTALL_PATH}" || return
        git fetch origin "$GIT_BRANCH" >/dev/null 2>&1
        local FILES_TO_CHECK="core modules bot.py watchdog.py migrate.py manage.py"
        local EXISTING_FILES=""
        for f in $FILES_TO_CHECK; do
            if [ -e "${BOT_INSTALL_PATH}/$f" ]; then EXISTING_FILES="$EXISTING_FILES $f"; fi
        done
        if [ -z "$EXISTING_FILES" ]; then
            INTEGRITY_STATUS="${C_YELLOW}⚠️ Файлы не найдены${C_RESET}"
        else
            local DIFF=$(git diff --name-only HEAD -- $EXISTING_FILES 2>/dev/null | grep -v '^core/static/vendor/')
            if [ -n "$DIFF" ]; then
                INTEGRITY_STATUS="${C_RED}⚠️ ЦЕЛОСТНОСТЬ НАРУШЕНА (Файлы изменены локально)${C_RESET}"
            else
                INTEGRITY_STATUS="${C_GREEN}🛡️ Код подтвержден${C_RESET}"
            fi
        fi
        cd - >/dev/null
    else
        INTEGRITY_STATUS="${C_YELLOW}⚠️ Git не найден${C_RESET}"
    fi

    if [ "$IS_NODE" == "yes" ]; then
        INSTALL_TYPE="НОДА (Клиент)"
        if systemctl is-active --quiet ${NODE_SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Активен${C_RESET}"; else STATUS_MESSAGE="${C_RED}Неактивен${C_RESET}"; fi
        return
    fi

    if [ "$DEPLOY_MODE_FROM_ENV" == "docker" ]; then
        INSTALL_TYPE="АГЕНТ (Docker)"
        if command -v docker &> /dev/null && docker ps | grep -q "tg-bot"; then STATUS_MESSAGE="${C_GREEN}Docker OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Docker Stop${C_RESET}"; fi
    else
        INSTALL_TYPE="АГЕНТ (Systemd)"
        if systemctl is-active --quiet ${SERVICE_NAME}.service; then STATUS_MESSAGE="${C_GREEN}Systemd OK${C_RESET}"; else STATUS_MESSAGE="${C_RED}Systemd Stop${C_RESET}"; fi
    fi
}

nginx_check() {
    local output
    output=$(sudo nginx -t 2>&1) || { printf '%s\n' "${output}" >&2; return 1; }
}

# Проверяет хост, срок действия и соответствие ключа сертификату.
tls_pair_valid() {
    local cert="$1" key="$2" seconds="$3" check_flag="-checkhost" cert_hash key_hash
    command -v openssl >/dev/null 2>&1 || return 1
    sudo test -s "${cert}" && sudo test -s "${key}" || return 1
    sudo openssl x509 -noout -checkend "${seconds}" -in "${cert}" >/dev/null 2>&1 || return 1
    if [ "${TLS_KIND}" == "ip" ]; then check_flag="-checkip"; fi
    sudo openssl x509 -noout "${check_flag}" "${TLS_HOST}" -in "${cert}" 2>/dev/null | grep -q "does match" || return 1
    cert_hash=$(sudo openssl x509 -noout -pubkey -in "${cert}" 2>/dev/null | openssl sha256) || return 1
    key_hash=$(sudo openssl pkey -pubout -in "${key}" 2>/dev/null | openssl sha256) || return 1
    [ -n "${cert_hash}" ] && [ "${cert_hash}" == "${key_hash}" ]
}

# Ищет готовую пару в конфигурации Nginx (включая свои и Cloudflare-сертификаты) и в Certbot.
tls_find_certificate() {
    local min_seconds="$1" pair cert key
    local candidates=()
    mapfile -t candidates < <(
        sudo nginx -T 2>/dev/null | "${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" find-nginx-cert "${TLS_HOST}" 2>/dev/null
        printf '/etc/letsencrypt/live/%s/fullchain.pem\t/etc/letsencrypt/live/%s/privkey.pem\n' "${TLS_CERT_NAME}" "${TLS_CERT_NAME}"
    )
    for pair in "${candidates[@]}"; do
        cert="${pair%%$'\t'*}"
        key="${pair#*$'\t'}"
        if tls_pair_valid "${cert}" "${key}" "${min_seconds}"; then
            TLS_CERT_FILE="${cert}"
            TLS_KEY_FILE="${key}"
            return 0
        fi
    done
    return 1
}

setup_nginx_proxy() {
    local helper="${BOT_INSTALL_PATH}/core/tls_config.py"
    local parsed=()
    local tls_info=""
    local min_valid=86400

    echo -e "\n${C_CYAN}🔒 Настройка HTTPS${C_RESET}"
    tls_info=$("${PYTHON_BIN}" "${helper}" parse-url "${WEB_PUBLIC_URL}") || {
        msg_error "Некорректный HTTPS-адрес: ${WEB_PUBLIC_URL}"
        return 1
    }
    mapfile -t parsed <<< "${tls_info}"
    TLS_KIND="${parsed[0]}"
    TLS_HOST="${parsed[1]}"
    HTTPS_PORT="${parsed[2]}"
    TLS_CERT_NAME="${parsed[3]}"
    TLS_SITE_NAME="${parsed[3]}"
    HTTPS_DOMAIN="${TLS_HOST}"
    TLS_CERT_FILE=""
    TLS_KEY_FILE=""
    if [ "${TLS_KIND}" == "ip" ]; then min_valid=21600; fi

    run_with_spinner "Установка Nginx" sudo apt-get install -y -q nginx || return 1
    if tls_find_certificate "${min_valid}"; then
        msg_info "Использую уже установленный сертификат: ${TLS_CERT_FILE}"
    else
        issue_certbot_certificate || return 1
    fi
    write_nginx_site
}

issue_certbot_certificate() {
    local helper="${BOT_INSTALL_PATH}/core/tls_config.py"
    local webroot="/var/www/tgbot-acme"
    local certbot_cmd="$(command -v certbot 2>/dev/null || true)"
    local acme_conf="/etc/nginx/sites-available/tgbot-acme.conf"
    local acme_link="/etc/nginx/sites-enabled/tgbot-acme.conf"

    if [ -z "${certbot_cmd}" ]; then
        run_with_spinner "Установка Certbot" sudo apt-get install -y -q certbot || return 1
        certbot_cmd="$(command -v certbot 2>/dev/null || true)"
    fi

    if [ "${TLS_KIND}" == "ip" ] && ! "${certbot_cmd}" --help all 2>/dev/null | grep -q -- "--ip-address"; then
        run_with_spinner "Установка Certbot для сертификата по IP" sudo apt-get install -y -q snapd || return 1
        sudo systemctl enable --now snapd.socket || return 1
        if ! sudo snap list certbot >/dev/null 2>&1; then
            run_with_spinner "Установка актуального Certbot" sudo snap install certbot --classic
        fi
        certbot_cmd="/snap/bin/certbot"
        if ! "${certbot_cmd}" --help all 2>/dev/null | grep -q -- "--ip-address"; then
            msg_error "Нужен Certbot с поддержкой --ip-address (версия 5.8 или новее)."
            return 1
        fi
    fi

    if [ -z "${certbot_cmd}" ]; then
        msg_error "Certbot не найден."
        return 1
    fi

    sudo mkdir -p "${webroot}/.well-known/acme-challenge" /etc/nginx/sites-available /etc/nginx/sites-enabled
    sudo tee "${acme_conf}" >/dev/null <<EOF
server {
    listen 80;
    server_name ${TLS_HOST};
    location ^~ /.well-known/acme-challenge/ {
        root ${webroot};
        default_type text/plain;
        add_header Cache-Control "no-store" always;
    }
    location ~ ^/api/(agent/https|node/bootstrap|heartbeat)$ {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_set_header Host ${TLS_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location / { return 404; }
}
EOF
    sudo ln -sfn "${acme_conf}" "${acme_link}"
    if ! nginx_check; then
        sudo rm -f "${acme_link}" "${acme_conf}"
        return 1
    fi
    if systemctl is-active --quiet nginx; then sudo systemctl reload nginx; else sudo systemctl start nginx; fi
    if command -v ufw >/dev/null 2>&1; then sudo ufw allow 80/tcp >/dev/null; fi

    local probe_name="tgbot-acme-probe-$$-${RANDOM}"
    local probe_file="${webroot}/.well-known/acme-challenge/${probe_name}"
    local local_probe=""
    printf '%s' "${probe_name}" | sudo tee "${probe_file}" >/dev/null
    local_probe=$(curl -fsS --connect-timeout 3 --max-time 8 \
        --resolve "${TLS_HOST}:80:127.0.0.1" \
        "http://${TLS_HOST}/.well-known/acme-challenge/${probe_name}" 2>/dev/null) || true
    sudo rm -f "${probe_file}"
    if [ "${local_probe}" != "${probe_name}" ]; then
        sudo rm -f "${acme_link}" "${acme_conf}"
        nginx_check && sudo systemctl reload nginx
        msg_error "Nginx не отдает проверочный файл Let's Encrypt для ${TLS_HOST}: возможно, порт 80 обслуживает другой сайт."
        return 1
    fi

    local certbot_args=()
    local certbot_log="/tmp/${SERVICE_NAME}_certbot.log"
    local certbot_pid=0
    local certbot_rc=0
    mapfile -d '' -t certbot_args < <(
        "${PYTHON_BIN}" "${helper}" certbot-args "${TLS_HOST}" "${HTTPS_EMAIL}" "${certbot_cmd}" "${webroot}"
    )
    ( sudo "${certbot_args[@]}" > "${certbot_log}" 2>&1 ) &
    certbot_pid=$!
    spinner "${certbot_pid}" "Получение сертификата Let's Encrypt"
    wait "${certbot_pid}" || certbot_rc=$?
    echo -ne "\033[2K\r"
    cat "${certbot_log}" >> "/tmp/${SERVICE_NAME}_install.log"
    if [ "${certbot_rc}" -ne 0 ]; then
        sudo rm -f "${acme_link}" "${acme_conf}"
        nginx_check && sudo systemctl reload nginx
        if grep -q "too many certificates" "${certbot_log}"; then
            msg_warning "Let's Encrypt временно ограничил выпуск сертификатов для ${TLS_HOST}; повтор возможен после $(grep -o 'retry after [0-9-]* [0-9:]* UTC' "${certbot_log}" | head -n 1 | cut -d' ' -f3-)."
        elif grep -qiE "unauthorized|timeout|connection|rejected|NXDOMAIN" "${certbot_log}"; then
            msg_warning "Let's Encrypt не смог проверить ${TLS_HOST}: проверьте DNS, доступность порта 80 и чтобы CDN (например Cloudflare) не блокировал путь /.well-known/acme-challenge/."
        else
            msg_warning "Не удалось выпустить сертификат. Подробности: /var/log/letsencrypt/letsencrypt.log"
        fi
        if tls_find_certificate 3600; then
            msg_info "Использую уже установленный сертификат: ${TLS_CERT_FILE}"
            return 0
        fi
        msg_error "Сертификат не получен. Текущая HTTPS-настройка не изменена."
        return 1
    fi
    CERTBOT_CMD="${certbot_cmd}"

    local cert_dir="/etc/letsencrypt/live/${TLS_CERT_NAME}"
    if [ ! -s "${cert_dir}/fullchain.pem" ] || [ ! -s "${cert_dir}/privkey.pem" ]; then
        local certbot_report=""
        local lineage_name=""
        local lineage_domains=""
        local lineage_cert=""
        local lineage_key=""
        local fallback_cert_dir=""
        local fallback_lineage=""
        certbot_report=$("${certbot_cmd}" certificates 2>&1 || true)
        while IFS= read -r line; do
            case "$line" in
                *"Certificate Name:"*)
                    lineage_name="${line#*: }"
                    lineage_domains=""
                    lineage_cert=""
                    lineage_key=""
                    ;;
                *"Domains:"*) lineage_domains="${line#*: }" ;;
                *"Certificate Path:"*) lineage_cert="${line#*: }" ;;
                *"Private Key Path:"*)
                    lineage_key="${line#*: }"
                    if [[ " ${lineage_domains} " == *" ${TLS_HOST} "* ]] && \
                        [ -s "${lineage_cert}" ] && [ -s "${lineage_key}" ]; then
                        if [ "${lineage_name}" == "${TLS_CERT_NAME}" ]; then
                            fallback_cert_dir="$(dirname "${lineage_cert}")"
                            fallback_lineage="${lineage_name}"
                            break
                        elif [ -z "${fallback_cert_dir}" ]; then
                            fallback_cert_dir="$(dirname "${lineage_cert}")"
                            fallback_lineage="${lineage_name}"
                        fi
                    fi
                    ;;
            esac
        done <<< "${certbot_report}"

        if [ -n "${fallback_cert_dir}" ]; then
            cert_dir="${fallback_cert_dir}"
            TLS_CERT_NAME="${fallback_lineage}"
        else
            msg_error "Сертификат выпущен, но файлы для ${TLS_HOST} не найдены (см. ${certbot_cmd} certificates)."
            return 1
        fi
    fi
    TLS_CERT_FILE="${cert_dir}/fullchain.pem"
    TLS_KEY_FILE="${cert_dir}/privkey.pem"
}

write_nginx_site() {
    local webroot="/var/www/tgbot-acme"
    local acme_conf="/etc/nginx/sites-available/tgbot-acme.conf"
    local acme_link="/etc/nginx/sites-enabled/tgbot-acme.conf"
    local final_conf=""
    local final_link=""
    local old_conf=""
    local old_backup=""
    local stale=""

    final_conf="/etc/nginx/sites-available/tgbot-panel-${TLS_SITE_NAME}.conf"
    final_link="/etc/nginx/sites-enabled/tgbot-panel-${TLS_SITE_NAME}.conf"
    old_conf="/etc/nginx/sites-available/${TLS_HOST}"
    old_backup="${old_conf}.tgbot-migration-backup"
    if [ "${old_conf}" != "${final_conf}" ] && [ -f "${old_conf}" ] && grep -q "proxy_pass http://127.0.0.1:" "${old_conf}"; then
        if [ -L "/etc/nginx/sites-enabled/${TLS_HOST}" ]; then sudo rm -f "/etc/nginx/sites-enabled/${TLS_HOST}"; fi
        sudo mv "${old_conf}" "${old_backup}"
    fi

    sudo tee "${final_conf}" >/dev/null <<EOF
server {
    listen 80;
    server_name ${TLS_HOST};
    location ^~ /.well-known/acme-challenge/ {
        root ${webroot};
        default_type text/plain;
    }
    location ~ ^/api/(agent/https|node/bootstrap|heartbeat)$ {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_set_header Host ${TLS_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location / { return 301 ${WEB_PUBLIC_URL}\$request_uri; }
}

server {
    listen ${HTTPS_PORT} ssl http2;
    server_name ${TLS_HOST};
    client_max_body_size 50m;
    ssl_certificate ${TLS_CERT_FILE};
    ssl_certificate_key ${TLS_KEY_FILE};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5:!RC4;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    access_log /var/log/nginx/tgbot-panel_access.log;
    error_log /var/log/nginx/tgbot-panel_error.log;
    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host ${TLS_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
EOF
    sudo ln -sfn "${final_conf}" "${final_link}"
    if ! nginx_check; then
        sudo rm -f "${final_link}" "${final_conf}"
        if [ -f "${old_backup}" ]; then sudo mv "${old_backup}" "${old_conf}"; sudo ln -sfn "${old_conf}" "/etc/nginx/sites-enabled/${TLS_HOST}"; fi
        sudo rm -f "${acme_link}" "${acme_conf}"
        nginx_check && sudo systemctl reload nginx
        msg_error "Новая настройка Nginx не прошла проверку; восстановлена предыдущая."
        return 1
    fi

    sudo rm -f "${acme_link}" "${acme_conf}"
    for stale in /etc/nginx/sites-available/tgbot-panel-*.conf; do
        if [ -f "${stale}" ] && [ "${stale}" != "${final_conf}" ] && grep -q "server_name ${TLS_HOST};" "${stale}"; then
            sudo rm -f "${stale}" "/etc/nginx/sites-enabled/$(basename "${stale}")"
        fi
    done
    if [ -n "${WEB_DOMAIN}" ] && [ "${WEB_DOMAIN}" != "${TLS_HOST}" ]; then
        local previous_domain_conf="/etc/nginx/sites-available/${WEB_DOMAIN}"
        if [ -f "${previous_domain_conf}" ] && grep -q "proxy_pass http://127.0.0.1:" "${previous_domain_conf}"; then
            sudo rm -f "/etc/nginx/sites-enabled/${WEB_DOMAIN}" "${previous_domain_conf}"
        fi
    fi
    sudo systemctl reload nginx
    if [ -f "${old_backup}" ]; then sudo rm -f "${old_backup}"; fi
    if command -v ufw >/dev/null 2>&1; then sudo ufw allow "${HTTPS_PORT}/tcp" >/dev/null; fi

    local certbot_cmd="${CERTBOT_CMD:-$(command -v certbot 2>/dev/null || true)}"
    if [ "${TLS_KIND}" == "ip" ] && [ -x /snap/bin/certbot ]; then certbot_cmd="/snap/bin/certbot"; fi
    # Внешние сертификаты (не из /etc/letsencrypt) продлеваются их владельцем.
    if [[ "${TLS_CERT_FILE}" == /etc/letsencrypt/live/* ]] && [ -n "${certbot_cmd}" ]; then
        sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
        sudo tee /etc/letsencrypt/renewal-hooks/deploy/50-tgbot-nginx-reload >/dev/null <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
        sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/50-tgbot-nginx-reload
        sudo tee /etc/systemd/system/tgbot-certbot-renew.service >/dev/null <<EOF
[Unit]
Description=Renew tgbot HTTPS certificates

[Service]
Type=oneshot
ExecStart=${certbot_cmd} renew --cert-name $(basename "$(dirname "${TLS_CERT_FILE}")") --quiet
EOF
        sudo tee /etc/systemd/system/tgbot-certbot-renew.timer >/dev/null <<'EOF'
[Unit]
Description=Check tgbot certificates for renewal hourly

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF
        sudo systemctl daemon-reload
        sudo systemctl enable --now tgbot-certbot-renew.timer
    fi
    echo -e "Веб-панель доступна: ${WEB_PUBLIC_URL}/"
}

common_install_steps() {
    echo "" > /tmp/${SERVICE_NAME}_install.log
    msg_info "1. Обновление системы..."
    
    run_with_spinner "Apt update" sudo apt-get update -y -q
    run_with_spinner "Установка пакетов" sudo apt-get install -y -q -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3 python3-pip python3-venv git curl wget sudo
}

setup_repo_and_dirs() {
    local owner_user=$1; if [ -z "$owner_user" ]; then owner_user="root"; fi
    local staging_path="${BOT_INSTALL_PATH}.staging.$$"
    local previous_path="${BOT_INSTALL_PATH}.previous.$$"
    msg_info "Подготовка файлов (Ветка: ${GIT_BRANCH})..."
    if [ -f "${ENV_FILE}" ]; then
        sudo install -m 600 "${ENV_FILE}" "${ENV_BACKUP_FILE}" || return 1
    fi
    if [ -z "$DATA_ENCRYPTION_KEY" ] && [ -f "${LEGACY_SECURITY_KEY_FILE}" ]; then
        DATA_ENCRYPTION_KEY=$(tr -d '\r\n' < "${LEGACY_SECURITY_KEY_FILE}")
        export DATA_ENCRYPTION_KEY
        msg_info "Найден legacy security.key. Ключ будет перенесен в .env."
    fi
    sudo rm -rf "${staging_path}" "${previous_path}"
    if ! run_with_spinner "Клонирование репозитория" sudo git clone --branch "${GIT_BRANCH}" "${GITHUB_REPO_URL}" "${staging_path}"; then
        sudo rm -rf "${staging_path}"
        return 1
    fi

    sudo mkdir -p "${staging_path}/logs/bot" "${staging_path}/logs/watchdog" "${staging_path}/logs/node" "${staging_path}/config"
    if [ -d "${BOT_INSTALL_PATH}" ]; then
        local state_dir
        for state_dir in config logs scripts certbot-venv; do
            if [ -d "${BOT_INSTALL_PATH}/${state_dir}" ]; then
                sudo mkdir -p "${staging_path}/${state_dir}"
                if ! sudo cp -a "${BOT_INSTALL_PATH}/${state_dir}/." "${staging_path}/${state_dir}/"; then
                    sudo rm -rf "${staging_path}"
                    return 1
                fi
            fi
        done
        if [ -f "${BOT_INSTALL_PATH}/installstate" ]; then
            sudo cp -a "${BOT_INSTALL_PATH}/installstate" "${staging_path}/installstate"
        fi
    fi
    if [ -f "${ENV_BACKUP_FILE}" ]; then
        sudo install -m 600 "${ENV_BACKUP_FILE}" "${staging_path}/.env"
    fi

    local live_path="${BOT_INSTALL_PATH}"
    BOT_INSTALL_PATH="${staging_path}"
    if ! download_vendor_assets; then
        BOT_INSTALL_PATH="${live_path}"
        sudo rm -rf "${staging_path}"
        return 1
    fi
    BOT_INSTALL_PATH="${live_path}"
    sudo chown -R "${owner_user}:${owner_user}" "${staging_path}"

    if [ -d "${BOT_INSTALL_PATH}" ]; then
        if ! sudo mv "${BOT_INSTALL_PATH}" "${previous_path}"; then
            sudo rm -rf "${staging_path}"
            return 1
        fi
    fi
    if ! sudo mv "${staging_path}" "${BOT_INSTALL_PATH}"; then
        if [ -d "${previous_path}" ]; then sudo mv "${previous_path}" "${BOT_INSTALL_PATH}"; fi
        sudo rm -rf "${staging_path}"
        return 1
    fi
    sudo rm -rf "${previous_path}"
}

download_vendor_assets() {
    msg_info "Загрузка локальных JS/CSS зависимостей..."
    local vendor_dir="${BOT_INSTALL_PATH}/core/static/vendor"
    sudo mkdir -p "${vendor_dir}"
    
    run_with_spinner "Загрузка Twemoji" sudo curl -sSLo "${vendor_dir}/twemoji.min.js" "https://unpkg.com/@twemoji/api@15.1.0/dist/twemoji.min.js"
    run_with_spinner "Загрузка Chart.js" sudo curl -sSLo "${vendor_dir}/chart.umd.min.js" "https://cdn.jsdelivr.net/npm/chart.js"
    run_with_spinner "Загрузка xterm.js" sudo curl -sSLo "${vendor_dir}/xterm.js" "https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"
    run_with_spinner "Загрузка xterm.css" sudo curl -sSLo "${vendor_dir}/xterm.css" "https://cdn.jsdelivr.net/npm/xterm/css/xterm.css"
    run_with_spinner "Загрузка xterm-addon-fit" sudo curl -sSLo "${vendor_dir}/xterm-addon-fit.js" "https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"
    run_with_spinner "Загрузка SortableJS" sudo curl -sSLo "${vendor_dir}/sortable.min.js" "https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js"
    run_with_spinner "Загрузка DOMPurify" sudo curl -sSLo "${vendor_dir}/dompurify.min.js" "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.6/purify.min.js"
    run_with_spinner "Загрузка CryptoJS" sudo curl -sSLo "${vendor_dir}/crypto-js.min.js" "https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.1.1/crypto-js.min.js"
}

load_cached_env() {
    local env_file="${ENV_FILE}"
    if [ ! -f "$env_file" ] && [ -f "${ENV_BACKUP_FILE}" ]; then env_file="${ENV_BACKUP_FILE}"; fi

    if [ -f "$env_file" ]; then
        get_env_val() { grep -m 1 "^$1=" "$env_file" | cut -d'=' -f2- | sed 's/^"//;s/"$//' | sed "s/^'//;s/'$//"; }
        if [ -z "$DATA_ENCRYPTION_KEY" ] && ! is_node_context; then
            DATA_ENCRYPTION_KEY=$(get_env_val "DATA_ENCRYPTION_KEY")
        fi
        echo -e "${C_YELLOW}⚠️  Обнаружена сохраненная конфигурация.${C_RESET}"
        read -p "$(echo -e "${C_CYAN}❓ Восстановить настройки? (y/n) [y]: ${C_RESET}")" RESTORE_CHOICE
        RESTORE_CHOICE=${RESTORE_CHOICE:-y}

        if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]]; then
            msg_info "Загружаю сохраненные данные..."
            [ -z "$T" ] && T=$(get_env_val "TG_BOT_TOKEN")
            [ -z "$A" ] && A=$(get_env_val "TG_ADMIN_ID")
            [ -z "$U" ] && U=$(get_env_val "TG_ADMIN_USERNAME")
            [ -z "$N" ] && N=$(get_env_val "TG_BOT_NAME")
            [ -z "$P" ] && P=$(get_env_val "WEB_SERVER_PORT")
            [ -z "$WEB_PUBLIC_URL" ] && WEB_PUBLIC_URL=$(get_env_val "WEB_PUBLIC_URL")
            [ -z "$WEB_DOMAIN" ] && WEB_DOMAIN=$(get_env_val "WEB_DOMAIN")
            [ -z "$HTTPS_PORT" ] && HTTPS_PORT=$(get_env_val "HTTPS_PORT")
            [ -z "$HTTPS_EMAIL" ] && HTTPS_EMAIL=$(get_env_val "HTTPS_EMAIL")
            [ -z "$WEB_TLS_MODE" ] && WEB_TLS_MODE=$(get_env_val "WEB_TLS_MODE")
            [ -z "$LEGACY_NODE_BRIDGE" ] && LEGACY_NODE_BRIDGE=$(get_env_val "LEGACY_NODE_BRIDGE")
            if [ -z "$LEGACY_NODE_BRIDGE" ]; then
                local old_host="$(get_env_val WEB_SERVER_HOST)"
                local old_deploy="$(get_env_val DEPLOY_MODE)"
                if [ "$old_deploy" != "docker" ] && [ "$old_host" == "0.0.0.0" ]; then
                    LEGACY_NODE_BRIDGE="true"
                else
                    LEGACY_NODE_BRIDGE="false"
                fi
            fi
            [ -z "$SENTRY_DSN" ] && SENTRY_DSN=$(get_env_val "SENTRY_DSN")
            [ -z "$DATA_ENCRYPTION_KEY" ] && DATA_ENCRYPTION_KEY=$(get_env_val "DATA_ENCRYPTION_KEY")
            if [ -z "$W" ]; then
                local val=$(get_env_val "ENABLE_WEB_UI")
                if [[ "$val" == "false" ]]; then W="n"; else W="y"; fi
            fi
            [ -z "$AGENT_URL" ] && AGENT_URL=$(get_env_val "AGENT_BASE_URL")
            [ -z "$NODE_TOKEN" ] && NODE_TOKEN=$(get_env_val "AGENT_TOKEN")

            if [ -z "$WEB_PUBLIC_URL" ] && [ -n "$WEB_DOMAIN" ]; then
                local legacy_port="${HTTPS_PORT:-}"
                local legacy_nginx="/etc/nginx/sites-available/${WEB_DOMAIN}"
                if [ -z "$legacy_port" ] && [ -f "$legacy_nginx" ]; then
                    legacy_port=$(grep -Eo 'listen[[:space:]]+[0-9]+[[:space:]]+ssl' "$legacy_nginx" | head -n 1 | grep -Eo '[0-9]+')
                fi
                HTTPS_PORT="${legacy_port:-8443}"
                WEB_PUBLIC_URL=$("${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" build-url "$WEB_DOMAIN" "$HTTPS_PORT" 2>/dev/null || true)
            fi
        else
            msg_info "Восстановление пропущено."
        fi
    fi

    ensure_data_encryption_key
}

parse_tls_url() {
    local url="$1"
    local parsed=""
    parsed=$("${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" parse-url "$url") || return 1
    mapfile -t TLS_URL_PARTS <<< "$parsed"
    [ "${#TLS_URL_PARTS[@]}" -eq 4 ] || return 1
    TLS_KIND="${TLS_URL_PARTS[0]}"
    HTTPS_DOMAIN="${TLS_URL_PARTS[1]}"
    HTTPS_PORT="${TLS_URL_PARTS[2]}"
    TLS_CERT_NAME="${TLS_URL_PARTS[3]}"
}

detect_public_ipv4() {
    curl -4fsS --connect-timeout 3 --max-time 8 https://api.ipify.org 2>/dev/null \
        || curl -4fsS --connect-timeout 3 --max-time 8 https://ipinfo.io/ip 2>/dev/null \
        || true
}

read_env_value() {
    local key="$1"
    local file="${2:-${ENV_FILE}}"
    if [ ! -f "$file" ]; then return 0; fi
    grep -m 1 "^${key}=" "$file" | cut -d'=' -f2- | sed 's/^"//;s/"$//;s/^'"'"'//;s/'"'"'$//'
}

write_env_value() {
    "${PYTHON_BIN}" - "${ENV_FILE}" "$1" "$2" <<'PY'
import os
import sys
import tempfile

path, key, value = sys.argv[1:]
value = value.replace("\r", "").replace("\n", "")
with open(path, "r", encoding="utf-8") as source:
    lines = source.readlines()
replacement = f'{key}="{value}"\n'
updated = False
result = []
for line in lines:
    if line.startswith(f"{key}="):
        if not updated:
            result.append(replacement)
            updated = True
    else:
        result.append(line)
if not updated:
    if result and not result[-1].endswith("\n"):
        result[-1] += "\n"
    result.append(replacement)
fd, temporary = tempfile.mkstemp(prefix=".env.", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as destination:
        destination.writelines(result)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

migrate_web_https() {
    local web_enabled="$(read_env_value ENABLE_WEB_UI)"
    [ "$web_enabled" == "false" ] && return 0

    WEB_PUBLIC_URL="$(read_env_value WEB_PUBLIC_URL)"
    WEB_TLS_MODE="$(read_env_value WEB_TLS_MODE)"
    HTTPS_EMAIL="$(read_env_value HTTPS_EMAIL)"
    HTTPS_PORT="$(read_env_value HTTPS_PORT)"
    WEB_DOMAIN="$(read_env_value WEB_DOMAIN)"
    WEB_PORT="$(read_env_value WEB_SERVER_PORT)"
    WEB_PORT="${WEB_PORT:-8080}"
    local deploy_mode="$(read_env_value DEPLOY_MODE)"
    local legacy_host="$(read_env_value WEB_SERVER_HOST)"
    SETUP_HTTPS="false"

    if [ -z "$WEB_PUBLIC_URL" ] && [ -n "$WEB_DOMAIN" ]; then
        local previous_site="/etc/nginx/sites-available/${WEB_DOMAIN}"
        if [ -z "$HTTPS_PORT" ] && [ -f "$previous_site" ]; then
            HTTPS_PORT=$(grep -Eo 'listen[[:space:]]+[0-9]+[[:space:]]+ssl' "$previous_site" | head -n 1 | grep -Eo '[0-9]+')
        fi
        HTTPS_PORT="${HTTPS_PORT:-8443}"
        WEB_PUBLIC_URL=$("${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" build-url "$WEB_DOMAIN" "$HTTPS_PORT") || return 1
        WEB_TLS_MODE="managed"
    fi

    if [ -n "$WEB_PUBLIC_URL" ] && parse_tls_url "$WEB_PUBLIC_URL"; then
        if [ "$WEB_TLS_MODE" == "managed" ] || \
            [ -f "/etc/nginx/sites-available/tgbot-panel-${TLS_CERT_NAME}.conf" ] || \
            { [ -n "$WEB_DOMAIN" ] && [ -f "/etc/nginx/sites-available/${WEB_DOMAIN}" ]; }; then
            SETUP_HTTPS="true"
            WEB_TLS_MODE="managed"
        else
            WEB_TLS_MODE="external"
        fi
    else
        local detected_ip="$(detect_public_ipv4)"
        read -p "Публичный домен или IPv4 для HTTPS [${detected_ip:-обязателен}]: " TLS_IDENTIFIER
        TLS_IDENTIFIER="${TLS_IDENTIFIER:-$detected_ip}"
        if [ -z "$TLS_IDENTIFIER" ]; then
            msg_error "Не удалось определить публичный IPv4; задайте домен или IPv4 вручную."
            return 1
        fi
        HTTPS_PORT="${HTTPS_PORT:-443}"
        read -p "Внешний HTTPS порт [${HTTPS_PORT}]: " HP
        HTTPS_PORT="${HP:-$HTTPS_PORT}"
        WEB_PUBLIC_URL=$("${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" build-url "$TLS_IDENTIFIER" "$HTTPS_PORT") || return 1
        parse_tls_url "$WEB_PUBLIC_URL" || return 1
        read -p "Управлять локальным Nginx/Certbot? (y/n) [y]: " H
        H="${H:-y}"
        if [[ "$H" =~ ^[Yy]$ ]]; then
            SETUP_HTTPS="true"
            WEB_TLS_MODE="managed"
        else
            WEB_TLS_MODE="external"
        fi
    fi

    write_env_value WEB_PUBLIC_URL "$WEB_PUBLIC_URL" || return 1
    write_env_value WEB_DOMAIN "$HTTPS_DOMAIN" || return 1
    write_env_value HTTPS_PORT "$HTTPS_PORT" || return 1
    write_env_value HTTPS_EMAIL "$HTTPS_EMAIL" || return 1
    write_env_value WEB_TLS_MODE "$WEB_TLS_MODE" || return 1

    if [ "$deploy_mode" != "docker" ] && [ "$legacy_host" == "0.0.0.0" ]; then
        write_env_value LEGACY_NODE_BRIDGE true || return 1
        msg_warning "Старые ноды временно остаются на HMAC-защищенном heartbeat bridge; обновите агенты и завершите миграцию через tgcp-bot tls finalize."
    else
        write_env_value LEGACY_NODE_BRIDGE false || return 1
    fi

    if [ "$SETUP_HTTPS" == "true" ]; then setup_nginx_proxy || return 1; fi
}

fetch_node_name_from_agent() {
    local agent_url="${1%/}"
    local node_token="$2"
    local response=""

    if [ -z "$agent_url" ] || [ -z "$node_token" ]; then
        return 0
    fi

    response=$(curl -fsS --connect-timeout 5 --max-time 10 -H "X-Node-Token: ${node_token}" "${agent_url}/api/node/bootstrap" 2>/dev/null) || return 0
    printf '%s' "$response" | "${PYTHON_BIN}" -c 'import json, sys; data = json.load(sys.stdin); print((data.get("node_name") or "").strip())' 2>/dev/null || true
}

resolve_node_name_defaults() {
    local current_name="$1"
    local current_mode="$2"
    local agent_url="$3"
    local node_token="$4"
    local resolved_name="$current_name"
    local resolved_mode="$current_mode"

    if [ -z "$resolved_name" ]; then
        resolved_name=$(fetch_node_name_from_agent "$agent_url" "$node_token")
        resolved_mode="agent"
    elif [ -z "$resolved_mode" ]; then
        resolved_mode="manual"
    fi

    printf '%s\n%s\n' "$resolved_name" "$resolved_mode"
}
cleanup_common_trash() {
    if [ -d "$BOT_INSTALL_PATH/.github" ]; then sudo rm -rf "$BOT_INSTALL_PATH/.github"; fi
    if [ -d "$BOT_INSTALL_PATH/docs" ]; then sudo rm -rf "$BOT_INSTALL_PATH/docs"; fi
    if [ -d "$BOT_INSTALL_PATH/tests" ]; then sudo rm -rf "$BOT_INSTALL_PATH/tests"; fi
    if [ -d "$BOT_INSTALL_PATH/assets" ]; then
        sudo find "$BOT_INSTALL_PATH/assets" -type f ! -name "web_1.png" ! -name "bot_1.png" -delete
        sudo find "$BOT_INSTALL_PATH/assets" -mindepth 1 -type d -empty -delete
    fi
    sudo find "$BOT_INSTALL_PATH" -maxdepth 1 -type f \( -name "*.txt" ! -name "requirements.txt" -o -name "*.md" -o -name "*.sh" -o -name ".gitignore" -o -name "LICENSE" \) -delete
    sudo find "$BOT_INSTALL_PATH" -maxdepth 1 -type f -name "*.ini" ! -name "aerich.ini" -delete
    sudo find "$BOT_INSTALL_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
}
cleanup_for_systemd() {
    local action_name=$1
    msg_info "Завершение ${action_name}..."
    cleanup_common_trash
    sudo rm -rf "${BOT_INSTALL_PATH}/node"
    sudo rm -f "${BOT_INSTALL_PATH}/Dockerfile" "${BOT_INSTALL_PATH}/docker-compose.yml"
}
cleanup_for_docker() {
    local action_name=$1
    msg_info "Завершение ${action_name}..."
    cleanup_common_trash
    cd "${BOT_INSTALL_PATH}"
    sudo rm -rf node
    sudo rm -rf core modules bot.py watchdog.py manage.py migrate.py aerich.ini
    sudo rm -rf assets
}
cleanup_for_node() {
    local action_name=$1
    msg_info "Завершение ${action_name}..."
    cleanup_common_trash
    sudo rm -rf "${BOT_INSTALL_PATH}/core" "${BOT_INSTALL_PATH}/modules" "${BOT_INSTALL_PATH}/bot.py" \
        "${BOT_INSTALL_PATH}/watchdog.py" "${BOT_INSTALL_PATH}/Dockerfile" \
        "${BOT_INSTALL_PATH}/docker-compose.yml" "${BOT_INSTALL_PATH}/.git" "${BOT_INSTALL_PATH}/assets" \
        "${BOT_INSTALL_PATH}/scripts" "${BOT_INSTALL_PATH}/requirements.txt"
    sudo rm -rf "${BOT_INSTALL_PATH}/logs/bot" "${BOT_INSTALL_PATH}/logs/watchdog" \
        "${BOT_INSTALL_PATH}/logs/traffic_backups" "${BOT_INSTALL_PATH}/logs/config_backups" \
        "${BOT_INSTALL_PATH}/logs/logs_backups" "${BOT_INSTALL_PATH}/logs/nodes_backups"
    if [ -d "${BOT_INSTALL_PATH}/config" ]; then
        sudo find "${BOT_INSTALL_PATH}/config" -mindepth 1 -maxdepth 1 \
            ! -name ".speedtest_mode" ! -name ".agent_alert_state.json" ! -name ".agent_alert_meta.json" \
            -exec rm -rf {} +
    fi
}

stop_existing_runtime() {
    sudo systemctl stop "${SERVICE_NAME}" "${WATCHDOG_SERVICE_NAME}" "${NODE_SERVICE_NAME}" >/dev/null 2>&1 || true
    sudo systemctl disable "${SERVICE_NAME}" "${WATCHDOG_SERVICE_NAME}" "${NODE_SERVICE_NAME}" >/dev/null 2>&1 || true
    if [ -f "${DOCKER_COMPOSE_FILE}" ] && command -v docker >/dev/null 2>&1; then
        if sudo docker compose version >/dev/null 2>&1; then
            (cd "${BOT_INSTALL_PATH}" && sudo docker compose down --remove-orphans) || return 1
        elif command -v docker-compose >/dev/null 2>&1; then
            (cd "${BOT_INSTALL_PATH}" && sudo docker-compose down --remove-orphans) || return 1
        fi
    fi
}

get_country_code_by_ip() {
    local ext_ip=""
    local country=""
    local sypex_country=""
    local ipgeobase_country=""

    # Use strict overall timeout to avoid hanging on slow or blocked providers.
    ext_ip=$(curl -4fsS --connect-timeout 3 --max-time 8 https://api.ipify.org 2>/dev/null \
        || curl -4fsS --connect-timeout 3 --max-time 8 https://ipinfo.io/ip 2>/dev/null \
        || echo "")

    if [ -n "$ext_ip" ]; then
        country=$(curl -4fsS --connect-timeout 3 --max-time 8 "https://ipapi.co/${ext_ip}/country/" 2>/dev/null \
            || curl -4fsS --connect-timeout 3 --max-time 8 "http://ip-api.com/line/${ext_ip}?fields=countryCode" 2>/dev/null \
            || echo "")

        if [ -z "$country" ]; then
            # Russian geolocation providers as extra fallback.
            sypex_country=$(curl -4fsS --connect-timeout 3 --max-time 8 "https://api.sypexgeo.net/json/${ext_ip}" 2>/dev/null \
                | tr -d '\n' \
                | sed -n 's/.*"country"[^{]*{[^}]*"iso"[[:space:]]*:[[:space:]]*"\([A-Za-z][A-Za-z]\)".*/\1/p')

            if [ -n "$sypex_country" ]; then
                country="$sypex_country"
            else
                ipgeobase_country=$(curl -4fsS --connect-timeout 3 --max-time 8 "https://ipgeobase.ru:7020/geo?ip=${ext_ip}" 2>/dev/null \
                    | tr -d '\n' \
                    | sed -n 's:.*<country>\([A-Za-z][A-Za-z]\)</country>.*:\1:p')
                country="$ipgeobase_country"
            fi
        fi
    fi

    country=$(echo "$country" | tr -d '\r\n[:space:]' | tr '[:lower:]' '[:upper:]')
    echo "${country:0:2}"
}

install_extras() {
    if ! command -v fail2ban-client &> /dev/null; then
        msg_question "Fail2Ban не найден. Установить? (y/n): " I; if [[ "$I" =~ ^[Yy]$ ]]; then run_with_spinner "Установка Fail2ban" sudo apt-get install -y -q fail2ban; fi
    fi
    
    # Detect server location by external IP
    msg_info "Определение геолокации сервера..."
    SERVER_COUNTRY=$(get_country_code_by_ip)
    
    if [ "$SERVER_COUNTRY" == "RU" ]; then
        msg_info "Сервер находится в России - устанавливаем iperf3 для speedtest"
        if ! command -v iperf3 &> /dev/null; then
            run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
        else
            msg_success "iperf3 уже установлен"
        fi
        # Mark that we use iperf3 mode
        echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    else
        msg_info "Сервер не в России - устанавливаем Ookla Speedtest CLI"
        
        if command -v speedtest &> /dev/null && speedtest --version 2>&1 | grep -q "Speedtest by Ookla"; then
            msg_success "Ookla Speedtest CLI уже установлен"
        else
            install_ookla_speedtest
        fi
        echo "OOKLA" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    fi
}

install_ookla_speedtest() {
    # Check if already installed and working
    if command -v speedtest &> /dev/null && speedtest --version 2>&1 | grep -q "Speedtest by Ookla"; then
        msg_success "Ookla Speedtest CLI уже установлен"
        return 0
    fi
    
    msg_info "Установка Ookla Speedtest CLI..."
    
    # Install curl if not present
    if ! command -v curl &> /dev/null; then
        run_with_spinner "Установка curl" sudo apt-get install -y -q curl
    fi
    
    # Get Ubuntu version
    UBUNTU_VERSION=""
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        UBUNTU_VERSION="$VERSION_ID"
    fi
    
    # Add Ookla repository
    run_with_spinner "Добавление репозитория Ookla" bash -c 'curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash'
    
    # Fix for Ubuntu 24+ (noble -> jammy)
    OOKLA_LIST="/etc/apt/sources.list.d/ookla_speedtest-cli.list"
    if [ -f "$OOKLA_LIST" ]; then
        if grep -q "noble" "$OOKLA_LIST" 2>/dev/null; then
            msg_info "Применяю исправление для Ubuntu 24+..."
            sudo sed -i 's/noble/jammy/g' "$OOKLA_LIST"
        fi
        # Also fix for other unsupported versions
        if grep -q "oracular\|mantic\|lunar" "$OOKLA_LIST" 2>/dev/null; then
            msg_info "Применяю исправление для неподдерживаемой версии Ubuntu..."
            sudo sed -i 's/oracular\|mantic\|lunar/jammy/g' "$OOKLA_LIST"
        fi
    fi
    
    run_with_spinner "Обновление пакетов" sudo apt-get update -y -q
    run_with_spinner "Установка speedtest" sudo apt-get install -y -q speedtest
    
    if command -v speedtest &> /dev/null; then
        msg_success "Ookla Speedtest CLI установлен успешно"
    else
        msg_warning "Не удалось установить Ookla Speedtest CLI, будет использован iperf3"
        if ! command -v iperf3 &> /dev/null; then
            run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
        fi
        echo "RU" | sudo tee "${BOT_INSTALL_PATH}/config/.speedtest_mode" > /dev/null
    fi
}

ask_env_details() {
    msg_info "Ввод данных .env..."
    msg_question "Токен Ботa: " T; msg_question "ID Админа: " A; msg_question "Username (opt): " U; msg_question "Bot Name (opt): " N
    msg_question "Внутренний Web Port [8080]: " P; if [ -z "$P" ]; then WEB_PORT="8080"; else WEB_PORT="$P"; fi
    msg_question "Sentry DSN (opt): " SENTRY_DSN

    msg_question "Включить Web-UI? (y/n) [y]: " W
    if [[ "$W" =~ ^[Nn]$ ]]; then
        ENABLE_WEB="false"
        SETUP_HTTPS="false"
        WEB_PUBLIC_URL=""
        WEB_TLS_MODE="disabled"
    else
        ENABLE_WEB="true"
        GEN_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
        local managed_site="false"
        if [ -n "$WEB_PUBLIC_URL" ] && parse_tls_url "$WEB_PUBLIC_URL"; then
            local previous_site="/etc/nginx/sites-available/${WEB_DOMAIN}"
            if [ -f "/etc/nginx/sites-available/tgbot-panel-${TLS_CERT_NAME}.conf" ] || \
                { [ -n "$WEB_DOMAIN" ] && [ -f "$previous_site" ] && \
                  grep -q "proxy_pass http://127.0.0.1:" "$previous_site" && \
                  grep -q "access_log /var/log/nginx/${WEB_DOMAIN}_access.log" "$previous_site"; }; then
                managed_site="true"
            fi
        else
            WEB_PUBLIC_URL=""
        fi

        if [ "$managed_site" == "true" ]; then
            SETUP_HTTPS="true"
            WEB_TLS_MODE="managed"
        elif [ -n "$WEB_PUBLIC_URL" ]; then
            SETUP_HTTPS="false"
            WEB_TLS_MODE="external"
        else
            local detected_ip="$(detect_public_ipv4)"
            read -p "Публичный домен или IPv4 [${detected_ip:-обязателен}]: " TLS_IDENTIFIER
            TLS_IDENTIFIER="${TLS_IDENTIFIER:-$detected_ip}"
            if [ -z "$TLS_IDENTIFIER" ]; then
                msg_error "Не удалось определить публичный IPv4; задайте домен или IPv4 вручную."
                return 1
            fi
            read -p "Управлять локальным Nginx/Certbot? (y/n) [y]: " H
            H="${H:-y}"
            if [[ "$H" =~ ^[Yy]$ ]]; then
                SETUP_HTTPS="true"
                WEB_TLS_MODE="managed"
                HTTPS_PORT="${HTTPS_PORT:-443}"
                read -p "Внешний HTTPS порт [${HTTPS_PORT}]: " HP
                HTTPS_PORT="${HP:-$HTTPS_PORT}"
                read -p "Email для уведомлений Certbot (необязательно): " HTTPS_EMAIL_INPUT
                HTTPS_EMAIL="${HTTPS_EMAIL_INPUT:-$HTTPS_EMAIL}"
                WEB_PUBLIC_URL=$("${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" build-url "$TLS_IDENTIFIER" "$HTTPS_PORT") || return 1
            else
                SETUP_HTTPS="false"
                WEB_TLS_MODE="external"
                local detected_url="$("${PYTHON_BIN}" "${BOT_INSTALL_PATH}/core/tls_config.py" build-url "$TLS_IDENTIFIER" 443)" || return 1
                read -p "Публичный HTTPS URL reverse proxy [${detected_url}]: " WEB_PUBLIC_URL_INPUT
                WEB_PUBLIC_URL="${WEB_PUBLIC_URL_INPUT:-$detected_url}"
            fi
        fi
        parse_tls_url "$WEB_PUBLIC_URL" || {
            msg_error "WEB_PUBLIC_URL должен быть корректным HTTPS origin."
            return 1
        }
    fi
    ensure_data_encryption_key
    export T A U N WEB_PORT ENABLE_WEB SETUP_HTTPS HTTPS_DOMAIN HTTPS_EMAIL HTTPS_PORT WEB_PUBLIC_URL WEB_TLS_MODE GEN_PASS SENTRY_DSN
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
    local web_server_host="127.0.0.1"
    if [ "$dm" == "docker" ]; then web_server_host="0.0.0.0"; fi
    local legacy_node_bridge="false"
    if [ "$dm" != "docker" ] && [ "${LEGACY_NODE_BRIDGE:-false}" == "true" ]; then
        web_server_host="0.0.0.0"
        legacy_node_bridge="true"
    fi
    local web_domain=""
    if [ -n "$HTTPS_DOMAIN" ]; then web_domain="${HTTPS_DOMAIN}"; fi
    local web_tls_mode="${WEB_TLS_MODE:-external}"

    ensure_data_encryption_key

    sudo bash -c "cat > ${ENV_FILE}" <<EOF
TG_BOT_TOKEN="${T}"
TG_ADMIN_ID="${A}"
TG_ADMIN_USERNAME="${U}"
TG_BOT_NAME="${N}"
DATA_ENCRYPTION_KEY="${DATA_ENCRYPTION_KEY}"
WEB_SERVER_HOST="${web_server_host}"
WEB_SERVER_PORT="${WEB_PORT}"
WEB_PUBLIC_URL="${WEB_PUBLIC_URL}"
WEB_DOMAIN="${web_domain}"
HTTPS_PORT="${HTTPS_PORT}"
HTTPS_EMAIL="${HTTPS_EMAIL}"
WEB_TLS_MODE="${web_tls_mode}"
LEGACY_NODE_BRIDGE="${legacy_node_bridge}"
INSTALL_MODE="${im}"
DEPLOY_MODE="${dm}"
TG_BOT_CONTAINER_NAME="${cn}"
ENABLE_WEB_UI="${ENABLE_WEB}"
TG_WEB_INITIAL_PASSWORD="${GEN_PASS}"
DEBUG="${debug_setting}"
SENTRY_DSN="${SENTRY_DSN}"
INSTALLED_VERSION="${ver}"
COMPOSE_PROFILES="${compose_profile}"
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
        msg_warning ".env файл не найден, пропуск проверки переменных."
        return 0
    fi
    
    msg_info "Проверка переменных окружения..."
    local changes_made=false
    
    # List of variables with their default values
    # Format: "VAR_NAME|default_value|description"
    local deploy_mode_from_env=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    local default_web_host="127.0.0.1"
    if [ "$deploy_mode_from_env" == "docker" ]; then default_web_host="0.0.0.0"; fi
    local ENV_VARS=(
        "WEB_SERVER_HOST|${default_web_host}|Хост веб-сервера"
        "WEB_SERVER_PORT|8080|Порт веб-сервера"
        "INSTALL_MODE|secure|Режим установки"
        "DEPLOY_MODE|systemd|Режим деплоя"
        "ENABLE_WEB_UI|true|Включить веб-интерфейс"
        "DEBUG|false|Режим отладки"
        "TG_BOT_NAME|VPS Bot|Имя бота"
    )

    if ! is_node_context; then
        ENV_VARS=("DATA_ENCRYPTION_KEY||Ключ шифрования данных" "${ENV_VARS[@]}")
    fi

    for var_entry in "${ENV_VARS[@]}"; do
        local var_name=$(echo "$var_entry" | cut -d'|' -f1)
        local default_val=$(echo "$var_entry" | cut -d'|' -f2)
        local var_desc=$(echo "$var_entry" | cut -d'|' -f3)
        
        if ! grep -q "^${var_name}=" "${ENV_FILE}"; then
            if [ "$var_name" == "DATA_ENCRYPTION_KEY" ]; then
                if [ -z "$DATA_ENCRYPTION_KEY" ] && [ -f "${LEGACY_SECURITY_KEY_FILE}" ]; then
                    DATA_ENCRYPTION_KEY=$(tr -d '\r\n' < "${LEGACY_SECURITY_KEY_FILE}")
                fi
                ensure_data_encryption_key
                echo -e "${C_YELLOW}  + Добавлена переменная ${var_name}=[REDACTED]${C_RESET}"
                sudo bash -c "echo '${var_name}=\"${DATA_ENCRYPTION_KEY}\"' >> ${ENV_FILE}"
            else
                echo -e "${C_YELLOW}  + Добавлена переменная ${var_name}=${default_val}${C_RESET}"
                sudo bash -c "echo '${var_name}=\"${default_val}\"' >> ${ENV_FILE}"
            fi
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
        "WEB_PUBLIC_URL"
        "HTTPS_PORT"
        "HTTPS_EMAIL"
        "WEB_TLS_MODE"
        "LEGACY_NODE_BRIDGE"
    )
    
    for var_name in "${OPTIONAL_VARS[@]}"; do
        if ! grep -q "^${var_name}=" "${ENV_FILE}"; then
            sudo bash -c "echo '${var_name}=\"\"' >> ${ENV_FILE}"
            changes_made=true
        fi
    done
    
    if [ "$changes_made" = true ]; then
        msg_success "Переменные окружения обновлены."
    else
        msg_success "Все переменные актуальны."
    fi
}

check_docker_deps() {
    if ! command -v docker &> /dev/null; then curl -sSL https://get.docker.com -o /tmp/get-docker.sh; run_with_spinner "Установка Docker" sudo sh /tmp/get-docker.sh; fi
    if command -v docker-compose &> /dev/null; then sudo rm -f $(which docker-compose); fi
}

create_dockerfile() {
    if [ ! -f "${BOT_INSTALL_PATH}/Dockerfile" ]; then
        msg_error "Dockerfile is missing from the cloned repository."
        return 1
    fi
}

create_docker_compose_yml() {
        if [ ! -f "${DOCKER_COMPOSE_FILE}" ]; then
                msg_error "docker-compose.yml is missing from the cloned repository."
                return 1
        fi
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
TimeoutStopSec=20
[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload; sudo systemctl enable ${svc} &> /dev/null; sudo systemctl restart ${svc}
}

run_db_migrations() {
    local exec_user=$1
    msg_info "Миграция базы данных и настроек..."
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
        msg_info "Aerich CLI не найден, пропуск миграций БД."
    elif [ ! -d "${BOT_INSTALL_PATH}/migrations" ]; then
        _run "'$aerich_bin' -c '$aerich_cfg' init-db" >/dev/null 2>&1 || true
    else
        _run "'$aerich_bin' -c '$aerich_cfg' migrate --name update" >/dev/null 2>&1 || true
        _run "'$aerich_bin' -c '$aerich_cfg' upgrade" >/dev/null 2>&1 || true
    fi

    if [ -f "${BOT_INSTALL_PATH}/migrate.py" ]; then
        _run "'${VENV_PATH}/bin/python' '${BOT_INSTALL_PATH}/migrate.py' $MIGRATE_ARGS"
    fi
}

install_systemd_logic() {
    local mode=$1
    agent_install_header "Systemd" "$mode"
    stop_existing_runtime || return 1
    common_install_steps
    install_extras
    local exec_cmd=""
    if [ "$mode" == "secure" ]; then
        if ! id "${SERVICE_USER}" &>/dev/null; then sudo useradd -r -s /bin/false -d ${BOT_INSTALL_PATH} ${SERVICE_USER}; fi
        setup_repo_and_dirs "${SERVICE_USER}"
        sudo -u ${SERVICE_USER} ${PYTHON_BIN} -m venv "${VENV_PATH}"
        run_with_spinner "Обновление pip" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install --upgrade pip 'setuptools>=83.0.0' wheel
        run_with_spinner "Установка зависимостей" sudo -u ${SERVICE_USER} "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        exec_cmd="sudo -u ${SERVICE_USER}"
    else
        setup_repo_and_dirs "root"
        ${PYTHON_BIN} -m venv "${VENV_PATH}"
        run_with_spinner "Обновление pip" "${VENV_PATH}/bin/pip" install --upgrade pip 'setuptools>=83.0.0' wheel
        run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt"
        exec_cmd=""
    fi

    load_cached_env
    ask_env_details || return 1
    write_env_file "systemd" "$mode" ""
    run_db_migrations "$exec_cmd"
    cleanup_for_systemd "установки"
    create_and_start_service "${SERVICE_NAME}" "${BOT_INSTALL_PATH}/bot.py" "$mode" "Telegram Bot"
    create_and_start_service "${WATCHDOG_SERVICE_NAME}" "${BOT_INSTALL_PATH}/watchdog.py" "root" "Наблюдатель"

    msg_info "Создание команды 'tgcp-bot'..."
    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
if [ -f .env ]; then set -a; source .env; set +a; fi
${VENV_PATH}/bin/python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    local ip=$(curl -s ipinfo.io/ip)
    echo ""; msg_success "Установка завершена! Панель: http://${ip}:${WEB_PORT}"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ] && ! setup_nginx_proxy; then return 1; fi
}

install_docker_logic() {
    local mode=$1
    agent_install_header "Docker" "$mode"
    stop_existing_runtime || return 1
    common_install_steps
    install_extras
    setup_repo_and_dirs "root"
    check_docker_deps
    load_cached_env
    ask_env_details || return 1
    create_dockerfile
    create_docker_compose_yml
    local container_name="tg-bot-${mode}"
    write_env_file "docker" "$mode" "${container_name}"
    cd ${BOT_INSTALL_PATH}
    local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
    run_with_spinner "Сборка Docker" sudo $dc_cmd build
    run_with_spinner "Запуск Docker" sudo $dc_cmd --profile "${mode}" up -d --remove-orphans

    msg_info "Миграция в контейнере..."
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init -t core.config.TORTOISE_ORM >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich init-db >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} aerich upgrade >/dev/null 2>&1
    sudo $dc_cmd --profile "${mode}" exec -T ${container_name} python migrate.py $MIGRATE_ARGS >/dev/null 2>&1
    cleanup_for_docker "установки"

    sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
if [ "\$1" = "tls" ] && [ "\$2" = "finalize" ]; then
    sudo /usr/bin/python3 "${BOT_INSTALL_PATH}/scripts/tls_finalize.py"
    exit \$?
fi
if [ "\$1" = "restart" ]; then
    sudo $dc_cmd --profile "\$MODE" restart "\$CONTAINER"
    exit \$?
fi
if [ "\$1" = "status" ]; then
    sudo $dc_cmd --profile "\$MODE" ps
    exit \$?
fi
if [ "\$1" = "webpass" ]; then
    sudo $dc_cmd --profile "\$MODE" exec "\$CONTAINER" python manage.py "\$@"
    result=\$?
    if [ \$result -ne 0 ]; then exit \$result; fi
    sudo /usr/bin/python3 "${BOT_INSTALL_PATH}/scripts/tls_finalize.py" clear-initial-password
    exit \$?
fi
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
    sudo chmod +x /usr/local/bin/tgcp-bot

    msg_success "Установка Docker завершена!"
    if [ "${ENABLE_WEB}" == "true" ]; then echo -e "${C_CYAN}🔑 ПАРОЛЬ: ${C_BOLD}${GEN_PASS}${C_RESET}"; fi
    if [ "$SETUP_HTTPS" == "true" ] && ! setup_nginx_proxy; then return 1; fi
}

install_node_logic() {
    if [ -z "$NODE_OP_UPDATE" ]; then
        if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then op_header "Переустановка НОДЫ"; else op_header "Установка НОДЫ"; fi
    fi
    stop_existing_runtime || return 1
    FORCE_NODE_MODE="yes"
    if [ -n "$AUTO_AGENT_URL" ]; then AGENT_URL="$AUTO_AGENT_URL"; fi
    if [ -n "$AUTO_NODE_TOKEN" ]; then NODE_TOKEN="$AUTO_NODE_TOKEN"; fi
    common_install_steps
    
    # Detect node location and install appropriate speedtest tool
    msg_info "Определение геолокации ноды..."
    NODE_COUNTRY=$(get_country_code_by_ip)
    
    if [ "$NODE_COUNTRY" == "RU" ]; then
        msg_info "Нода в России - используем iperf3"
        run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
    else
        msg_info "Нода не в России - устанавливаем Ookla Speedtest CLI"
        install_ookla_speedtest
        # Also install iperf3 as fallback
        run_with_spinner "Установка iperf3" sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iperf3
    fi
    
    setup_repo_and_dirs "root"
    if [ ! -d "${VENV_PATH}" ]; then run_with_spinner "Создание venv" ${PYTHON_BIN} -m venv "${VENV_PATH}"; fi
    run_with_spinner "Обновление pip" "${VENV_PATH}/bin/pip" install --upgrade pip 'setuptools>=83.0.0' wheel
    run_with_spinner "Установка зависимостей" "${VENV_PATH}/bin/pip" install psutil requests pyyaml
    load_cached_env
    msg_question "Agent URL (http://IP:8080): " AGENT_URL
    msg_question "Token: " NODE_TOKEN
    local saved_node_name=""
    local saved_node_name_sync_mode=""
    if [ -f "${ENV_BACKUP_FILE}" ]; then
        saved_node_name=$(grep "^NODE_NAME=" "${ENV_BACKUP_FILE}" | cut -d'=' -f2- | tr -d '"')
        saved_node_name_sync_mode=$(grep "^NODE_NAME_SYNC_MODE=" "${ENV_BACKUP_FILE}" | cut -d'=' -f2- | tr -d '"' | xargs)
    fi
    mapfile -t node_name_defaults < <(resolve_node_name_defaults "$saved_node_name" "$saved_node_name_sync_mode" "$AGENT_URL" "$NODE_TOKEN")
    local initial_node_name="${node_name_defaults[0]}"
    local initial_node_name_sync_mode="${node_name_defaults[1]}"
    local ver="Unknown"; if [ -f "$README_FILE" ]; then ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE"); fi
    sudo bash -c "cat > ${ENV_FILE}" <<EOF
MODE=node
AGENT_BASE_URL="${AGENT_URL}"
AGENT_TOKEN="${NODE_TOKEN}"
NODE_NAME="${initial_node_name}"
NODE_NAME_SYNC_MODE="${initial_node_name_sync_mode:-agent}"
NODE_UPDATE_INTERVAL=5
INSTALLED_VERSION="${ver}"
EOF
    
    # Check and restore/configure agent monitoring variables if settings were restored
    if [[ "$RESTORE_CHOICE" =~ ^[Yy]$ ]] && [ -f "${ENV_BACKUP_FILE}" ]; then
        local saved_bot_token=$(grep "^BOT_TOKEN=" "${ENV_BACKUP_FILE}" | cut -d'=' -f2- | tr -d '"' | xargs)
        local saved_chat_ids=$(grep "^CRITICAL_ALERT_CHAT_IDS=" "${ENV_BACKUP_FILE}" | cut -d'=' -f2- | tr -d '"' | xargs)
        local saved_delay=$(grep "^AGENT_ALERT_DELAY_SECONDS=" "${ENV_BACKUP_FILE}" | cut -d'=' -f2- | tr -d '"')
        
        # Ask user if monitoring variables are missing or empty
        local need_bot_token=""
        local need_chat_ids=""
        
        if [ -z "$saved_bot_token" ]; then
            need_bot_token="yes"
        fi
        if [ -z "$saved_chat_ids" ]; then
            need_chat_ids="yes"
        fi
        
        # If any monitoring variable is missing, ask if user wants to configure them
        if [ -n "$need_bot_token" ] || [ -n "$need_chat_ids" ]; then
            echo ""
            echo -e "${C_YELLOW}⚠️  Обнаружены пустые переменные для мониторинга агента:${C_RESET}"
            [ -n "$need_bot_token" ] && echo -e "  • BOT_TOKEN (токен бота)"
            [ -n "$need_chat_ids" ] && echo -e "  • CRITICAL_ALERT_CHAT_IDS (ID чатов для алертов)"
            echo ""
            read -p "$(echo -e "${C_CYAN}❓ Настроить мониторинг агента сейчас? (y/n) [n]: ${C_RESET}")" setup_monitoring
            setup_monitoring=${setup_monitoring:-n}
            
            if [[ "$setup_monitoring" =~ ^[Yy]$ ]]; then
                echo ""
                echo -e "${C_CYAN}Настройка мониторинга агента:${C_RESET}"
                echo -e "${C_YELLOW}Важно:${C_RESET} не используйте chat_id другого бота (Telegram блокирует отправку боту от бота)."
                echo ""
                echo -e "${C_YELLOW}Как получить Chat ID:${C_RESET}"
                echo -e "  • Напишите боту @userinfobot команду /start"
                echo -e "  • Или добавьте бота в группу и используйте /start"
                echo ""
                
                if [ -n "$need_bot_token" ]; then
                    read -p "Введите BOT_TOKEN: " saved_bot_token
                fi
                
                if [ -n "$need_chat_ids" ]; then
                    read -p "Введите CRITICAL_ALERT_CHAT_IDS (через запятую): " saved_chat_ids
                fi
            fi
        fi
        
        # Add monitoring variables to .env if monitoring was configured (has BOT_TOKEN and CHAT_IDS)
        if [ -n "$saved_bot_token" ] && [ -n "$saved_chat_ids" ]; then
            echo "" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "# Agent Monitoring Configuration" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "BOT_TOKEN=\"${saved_bot_token}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            echo "CRITICAL_ALERT_CHAT_IDS=\"${saved_chat_ids}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            [ -n "$saved_delay" ] && echo "AGENT_ALERT_DELAY_SECONDS=\"${saved_delay}\"" | sudo tee -a "${ENV_FILE}" > /dev/null
            msg_info "✓ Переменные мониторинга добавлены в .env"
        fi
    fi
    
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
    if [ -n "$NODE_OP_UPDATE" ]; then cleanup_for_node "обновления"; else cleanup_for_node "установки"; fi
    run_with_spinner "Запуск Ноды" sudo systemctl restart ${NODE_SERVICE_NAME}
    FORCE_NODE_MODE="no"
    if [ -n "$NODE_OP_UPDATE" ]; then msg_success "Нода обновлена!"; else msg_success "Нода установлена!"; fi
}

uninstall_bot() {
    op_header "Удаление $(target_label)"
    cd /
    stop_existing_runtime
    sudo rm -f /etc/systemd/system/${SERVICE_NAME}.service /etc/systemd/system/${WATCHDOG_SERVICE_NAME}.service /etc/systemd/system/${NODE_SERVICE_NAME}.service
    sudo systemctl daemon-reload
    sudo rm -rf "${BOT_INSTALL_PATH}"
    sudo rm -f /usr/local/bin/tgcp-bot
    if id "${SERVICE_USER}" &>/dev/null; then sudo userdel -r "${SERVICE_USER}" &> /dev/null; fi
    msg_success "Удалено."
}

update_bot() {
    op_header "Обновление $(target_label)"
    if [ -f "${ENV_FILE}" ] && grep -q "MODE=node" "${ENV_FILE}"; then
        NODE_OP_UPDATE="yes"; install_node_logic; local rc=$?; NODE_OP_UPDATE=""; return $rc
    fi
    if [ ! -d "${BOT_INSTALL_PATH}/.git" ]; then msg_error "Git не найден."; return 1; fi
    echo "" > /tmp/${SERVICE_NAME}_install.log
    local exec_cmd=""
    if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then exec_cmd="sudo -u ${SERVICE_USER}"; fi

    cd "${BOT_INSTALL_PATH}"
    if ! run_with_spinner "Git fetch" $exec_cmd git fetch origin; then return 1; fi
    if ! run_with_spinner "Git reset" $exec_cmd git reset --hard "origin/${GIT_BRANCH}"; then return 1; fi
    
    local new_ver=""
    
    if echo "$GIT_BRANCH" | grep -q "release/"; then
        new_ver=$(echo "$GIT_BRANCH" | grep -oP 'release/\K[\d\.]+')
    fi
    
    if [ -z "$new_ver" ] && [ -f "${BOT_INSTALL_PATH}/CHANGELOG.md" ]; then
        new_ver=$(grep -oP '^## \[\K[\d\.]+' "${BOT_INSTALL_PATH}/CHANGELOG.md" | head -n 1)
    fi
    
    if [ -z "$new_ver" ] && [ -f "$README_FILE" ]; then
        new_ver=$(grep -oP 'img\.shields\.io/badge/version-v\K[\d\.]+' "$README_FILE")
    fi

    if [ -n "$new_ver" ] && [ -f "${ENV_FILE}" ]; then
         if grep -q "^INSTALLED_VERSION=" "${ENV_FILE}"; then
             sudo sed -i "s/^INSTALLED_VERSION=.*/INSTALLED_VERSION=\"${new_ver}\"/" "${ENV_FILE}"
         else
             sudo bash -c "echo 'INSTALLED_VERSION=\"${new_ver}\"' >> ${ENV_FILE}"
         fi
    fi

    # Check and add missing environment variables
    ensure_env_variables
    if ! migrate_web_https; then
        msg_error "HTTPS migration failed; the current service has not been switched."
        return 1
    fi

    download_vendor_assets
    if [ -f "${ENV_FILE}" ] && grep -q "INSTALL_MODE=secure" "${ENV_FILE}"; then
        sudo chown -R ${SERVICE_USER}:${SERVICE_USER} "${BOT_INSTALL_PATH}/core/static/vendor" 2>/dev/null || true
    fi

    local current_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
    
    if [ "$current_mode" == "docker" ]; then
        if [ -f "docker-compose.yml" ]; then
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            if ! run_with_spinner "Docker Up" sudo $dc_cmd up -d --build; then msg_error "Ошибка Docker."; return 1; fi
            sudo bash -c "cat > /usr/local/bin/tgcp-bot" <<EOF
#!/bin/bash
cd ${BOT_INSTALL_PATH}
MODE=\$(grep '^INSTALL_MODE=' .env | cut -d'=' -f2 | tr -d '"')
CONTAINER="tg-bot-\$MODE"
if [ "\$1" = "tls" ] && [ "\$2" = "finalize" ]; then
    sudo /usr/bin/python3 "${BOT_INSTALL_PATH}/scripts/tls_finalize.py"
    exit \$?
fi
if [ "\$1" = "restart" ]; then
    sudo $dc_cmd --profile "\$MODE" restart "\$CONTAINER"
    exit \$?
fi
if [ "\$1" = "status" ]; then
    sudo $dc_cmd --profile "\$MODE" ps
    exit \$?
fi
if [ "\$1" = "webpass" ]; then
    sudo $dc_cmd --profile "\$MODE" exec "\$CONTAINER" python manage.py "\$@"
    result=\$?
    if [ \$result -ne 0 ]; then exit \$result; fi
    sudo /usr/bin/python3 "${BOT_INSTALL_PATH}/scripts/tls_finalize.py" clear-initial-password
    exit \$?
fi
sudo $dc_cmd --profile "\$MODE" exec -T \$CONTAINER python manage.py "\$@"
EOF
            sudo chmod +x /usr/local/bin/tgcp-bot
        else msg_error "Нет docker-compose.yml"; return 1; fi
    else
        run_with_spinner "Обновление pip" $exec_cmd "${VENV_PATH}/bin/pip" install -r "${BOT_INSTALL_PATH}/requirements.txt" --upgrade
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
        echo -e "${C_CYAN}🔍 Проверка конфигурации...${C_RESET}"
        echo "❓ Хотите сбросить мета-данные WebUI (заголовок, фавикон, SEO) до стандартных?"
        read -p "Сбросить? (y/N): " reset_meta_answer
        if [[ "$reset_meta_answer" =~ ^[Yy]$ ]]; then
            MIGRATE_ARGS="--reset-meta"
            echo -e "${C_YELLOW}⚠️  Будет выполнен сброс мета-данных.${C_RESET}"
        fi
    fi

    if [ "$current_mode" == "docker" ]; then
         local mode=$(grep '^INSTALL_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
         local cn="tg-bot-${mode}"
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} aerich migrate --name update >/dev/null 2>&1 || true
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} aerich upgrade >/dev/null 2>&1
         sudo $dc_cmd --profile "${mode}" exec -T ${cn} python migrate.py $MIGRATE_ARGS >/dev/null 2>&1
         
         cleanup_for_docker "обновления"
    else
         run_db_migrations "$exec_cmd"
         cleanup_for_systemd "обновления"
    fi

    msg_success "Агент обновлён."
}

check_agent_monitoring_status() {
    if [ ! -f "${ENV_FILE}" ]; then
        echo "выкл"
        return
    fi

    local bot_token_value=$(grep '^BOT_TOKEN=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local chat_ids_value=$(grep '^CRITICAL_ALERT_CHAT_IDS=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)

    if [ -n "$bot_token_value" ] && [ -n "$chat_ids_value" ]; then
        echo "вкл"
    else
        echo "выкл"
    fi
}

toggle_agent_monitoring() {
    if [ ! -f "${ENV_FILE}" ]; then
        msg_error "Файл .env не найден!"
        return
    fi

    local current_bot_token=$(grep '^BOT_TOKEN=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_chat_ids=$(grep '^CRITICAL_ALERT_CHAT_IDS=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_node_name=$(grep '^NODE_NAME=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"')
    local current_node_name_sync_mode=$(grep '^NODE_NAME_SYNC_MODE=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_delay=$(grep '^AGENT_ALERT_DELAY_SECONDS=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_agent_url=$(grep '^AGENT_BASE_URL=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local current_agent_token=$(grep '^AGENT_TOKEN=' "${ENV_FILE}" | tail -n 1 | cut -d'=' -f2- | tr -d '"' | xargs)
    local status=$(check_agent_monitoring_status)

    if [ "$status" == "вкл" ]; then
        msg_warning "Отключение мониторинга агента..."
        sed -i '/^# Agent Monitoring Configuration$/d' "${ENV_FILE}"
        sed -i '/^DEBUG=/d' "${ENV_FILE}"
        sed -i '/^BOT_TOKEN=/d' "${ENV_FILE}"
        sed -i '/^CRITICAL_ALERT_CHAT_IDS=/d' "${ENV_FILE}"
        sed -i '/^AGENT_ALERT_DELAY_SECONDS=/d' "${ENV_FILE}"
        msg_success "Мониторинг агента отключен. Переменные удалены из .env"
        local deploy_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ "$deploy_mode" == "docker" ]; then
            msg_info "Перезапуск Docker контейнера..."
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            cd "${BOT_INSTALL_PATH}" && sudo $dc_cmd restart
            msg_success "Docker контейнер перезапущен"
        else
            msg_info "Перезапуск ноды..."
            sudo systemctl restart ${NODE_SERVICE_NAME}
            msg_success "Нода перезапущена"
        fi
    else
        msg_info "Настройка мониторинга агента..."
        if [ -z "$current_bot_token" ]; then
            msg_warning "BOT_TOKEN отсутствует или пустой в .env"
        fi
        if [ -z "$current_chat_ids" ]; then
            msg_warning "CRITICAL_ALERT_CHAT_IDS отсутствует или пустой в .env"
        fi
        if [ -z "$current_node_name" ]; then
            msg_warning "NODE_NAME отсутствует или пустой в .env"
        fi
        if [ -z "$current_delay" ]; then
            msg_warning "AGENT_ALERT_DELAY_SECONDS отсутствует или пустой в .env"
        fi

        echo ""
        echo -e "${C_CYAN}Для работы мониторинга агента нужны:${C_RESET}"
        echo -e "  1. BOT_TOKEN - токен вашего Telegram бота"
        echo -e "  2. CRITICAL_ALERT_CHAT_IDS - ID чатов для критических алертов (через запятую)"
        echo -e "  3. AGENT_ALERT_DELAY_SECONDS - задержка перед отправкой алерта (в секундах)"
        echo -e "  4. NODE_NAME - имя этой ноды (если оставить пустым, будет синхронизироваться с агентом)"
        echo ""
        echo -e "${C_YELLOW}Важно:${C_RESET} не используйте chat_id другого бота (Telegram блокирует отправку боту от бота)."
        echo ""
        echo -e "${C_YELLOW}Как получить Chat ID:${C_RESET}"
        echo -e "  • Напишите боту @userinfobot команду /start"
        echo -e "  • Или добавьте бота в группу и используйте /start"
        echo ""

        local resolved_agent_node_name=""
        if [ -z "$current_node_name" ]; then
            resolved_agent_node_name=$(fetch_node_name_from_agent "$current_agent_url" "$current_agent_token")
            if [ -n "$resolved_agent_node_name" ]; then
                msg_info "Будет использовано имя ноды с агента: ${resolved_agent_node_name}"
            fi
        fi

        read -p "Введите BOT_TOKEN [текущее: ${current_bot_token:-пусто}]: " bot_token
        if [ -z "$bot_token" ]; then
            bot_token="$current_bot_token"
        fi
        if [ -z "$bot_token" ]; then
            msg_error "BOT_TOKEN не может быть пустым!"
            return
        fi

        read -p "Введите CRITICAL_ALERT_CHAT_IDS (через запятую) [текущее: ${current_chat_ids:-пусто}]: " chat_ids
        if [ -z "$chat_ids" ]; then
            chat_ids="$current_chat_ids"
        fi
        if [ -z "$chat_ids" ]; then
            msg_error "CRITICAL_ALERT_CHAT_IDS не может быть пустым!"
            return
        fi

        read -p "Введите NODE_NAME [текущее: ${current_node_name:-${resolved_agent_node_name:-Node}}]: " node_name
        if [ -z "$node_name" ]; then
            node_name="${current_node_name:-${resolved_agent_node_name:-Node}}"
        fi

        local node_name_sync_mode="manual"
        if [ -z "$current_node_name" ] && [ -n "$resolved_agent_node_name" ] && [ "$node_name" = "$resolved_agent_node_name" ]; then
            node_name_sync_mode="agent"
        elif [ -n "$current_node_name_sync_mode" ] && [ "$node_name" = "$current_node_name" ]; then
            node_name_sync_mode="$current_node_name_sync_mode"
        fi

        read -p "Введите AGENT_ALERT_DELAY_SECONDS [текущее: ${current_delay:-15}]: " alert_delay
        if [ -z "$alert_delay" ]; then
            alert_delay="${current_delay:-15}"
        fi

        sed -i '/^# Agent Monitoring Configuration$/d' "${ENV_FILE}"
        sed -i '/^DEBUG=/d' "${ENV_FILE}"
        sed -i '/^BOT_TOKEN=/d' "${ENV_FILE}"
        sed -i '/^CRITICAL_ALERT_CHAT_IDS=/d' "${ENV_FILE}"
        sed -i '/^AGENT_ALERT_DELAY_SECONDS=/d' "${ENV_FILE}"
        sed -i '/^NODE_NAME=/d' "${ENV_FILE}"
        sed -i '/^NODE_NAME_SYNC_MODE=/d' "${ENV_FILE}"
        echo "" >> "${ENV_FILE}"
        echo "DEBUG=\"false\"" >> "${ENV_FILE}"
        echo "BOT_TOKEN=\"${bot_token}\"" >> "${ENV_FILE}"
        echo "CRITICAL_ALERT_CHAT_IDS=\"${chat_ids}\"" >> "${ENV_FILE}"
        echo "AGENT_ALERT_DELAY_SECONDS=\"${alert_delay}\"" >> "${ENV_FILE}"
        echo "NODE_NAME=\"${node_name}\"" >> "${ENV_FILE}"
        echo "NODE_NAME_SYNC_MODE=\"${node_name_sync_mode}\"" >> "${ENV_FILE}"

        msg_success "Мониторинг агента включен/обновлен!"
        local deploy_mode=$(grep '^DEPLOY_MODE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d '"')
        if [ "$deploy_mode" == "docker" ]; then
            msg_info "Перезапуск Docker контейнера..."
            local dc_cmd=""; if sudo docker compose version &>/dev/null; then dc_cmd="docker compose"; else dc_cmd="docker-compose"; fi
            cd "${BOT_INSTALL_PATH}" && sudo $dc_cmd restart
            msg_success "Docker контейнер перезапущен"
        else
            msg_info "Перезапуск ноды..."
            sudo systemctl restart ${NODE_SERVICE_NAME}
            msg_success "Нода перезапущена"
        fi
    fi
}

manage_alert_module() {
    clear
    echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║       Управление Alert-модулем    ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"

    local current_token=""
    if [ -f "${ENV_FILE}" ]; then
        current_token=$(grep '^ALERT_BOT_TOKEN=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"')
    fi

    if [ -n "$current_token" ]; then
        # Токен уже задан — предлагаем удалить модуль
        echo -e "  ${C_GREEN}✅ Alert Bot активен (токен задан)${C_RESET}"
        echo ""
        echo -e "  ${C_YELLOW}Вы хотите удалить (деактивировать) Alert-модуль?${C_RESET}"
        echo "  Это удалит ALERT_BOT_TOKEN из .env и перезапустит сервис."
        echo ""
        read -p "$(echo -e "${C_BOLD}Подтвердить удаление? (y/n): ${C_RESET}")" confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            # Удаляем строку ALERT_BOT_TOKEN из .env
            sed -i '/^ALERT_BOT_TOKEN=/d' "${ENV_FILE}"
            msg_success "ALERT_BOT_TOKEN удалён из .env"
            # Перезапускаем сервис для применения изменений
            if systemctl is-active --quiet "${SERVICE_NAME}"; then
                msg_info "Перезапуск сервиса ${SERVICE_NAME}..."
                sudo systemctl restart "${SERVICE_NAME}"
                msg_success "Сервис перезапущен. Alert-модуль деактивирован."
            else
                msg_warning "Сервис ${SERVICE_NAME} не запущен. Изменения применятся при следующем запуске."
            fi
        else
            msg_info "Отменено."
        fi
    else
        # Токен не задан — предлагаем установить
        echo -e "  ${C_YELLOW}⚠️  Alert Bot не активирован (ALERT_BOT_TOKEN не задан)${C_RESET}"
        echo ""
        echo "  Для активации нужен токен отдельного Telegram-бота."
        echo "  Создайте нового бота через @BotFather и скопируйте токен."
        echo ""
        read -p "$(echo -e "${C_BOLD}Введите токен Alert Bot (или Enter для отмены): ${C_RESET}")" new_token
        if [ -z "$new_token" ]; then
            msg_info "Отменено."
            return
        fi
        # Базовая проверка формата токена (цифры:строка)
        if ! echo "$new_token" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{35,}$'; then
            msg_error "Некорректный формат токена. Ожидается: 123456789:ABCdef..."
            return
        fi
        # Сохраняем токен в .env
        echo "ALERT_BOT_TOKEN=\"${new_token}\"" >> "${ENV_FILE}"
        msg_success "ALERT_BOT_TOKEN сохранён в .env"
        # Перезапускаем сервис
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            msg_info "Перезапуск сервиса ${SERVICE_NAME}..."
            sudo systemctl restart "${SERVICE_NAME}"
            msg_success "Сервис перезапущен. Alert-модуль активирован!"
        else
            msg_warning "Сервис ${SERVICE_NAME} не запущен. Запустите его вручную."
        fi
    fi
}

main_menu() {
    local local_version=$(get_local_version)
    while true; do
        clear
        echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}║    Менеджер VPS Telegram Бот      ║${C_RESET}"
        echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
        check_integrity
        local item_type="агента"
        if [ "$IS_NODE" == "yes" ]; then
            item_type="ноду"
        fi
        echo -e "  Ветка: ${GIT_BRANCH} | Версия: ${local_version}"
        echo -e "  Тип: ${INSTALL_TYPE} | Статус: ${STATUS_MESSAGE}"
        if [ -n "$INTEGRITY_STATUS" ]; then echo -e "  Интегритет: ${INTEGRITY_STATUS}"; fi
        echo "--------------------------------------------------------"
        echo "  1) Обновить ${item_type}"
        echo "  2) Удалить ${item_type}"
        echo "  3) Переустановить (Systemd - Secure)"
        echo "  4) Переустановить (Systemd - Root)"
        echo "  5) Переустановить (Docker - Secure)"
        echo "  6) Переустановить (Docker - Root)"
        if [ "$IS_NODE" == "yes" ]; then
            echo -e "${C_GREEN}  7) Установить НОДУ (Клиент)${C_RESET}"
        fi
        
        if [ "$IS_NODE" == "yes" ]; then
            local monitoring_status=$(check_agent_monitoring_status)
            echo -e "${C_YELLOW}  8) Мониторинг агента (${monitoring_status})${C_RESET}"
        fi

        # Пункт Alert-модуля — только для не-нодового режима
        if [ "$IS_NODE" != "yes" ]; then
            local alert_status="не активен"
            if [ -f "${ENV_FILE}" ] && grep -q '^ALERT_BOT_TOKEN=' "${ENV_FILE}"; then
                alert_status="${C_GREEN}активен${C_RESET}"
            fi
            echo -e "  9) Управление Alert-модулем (${alert_status})"
        fi

        echo "  0) Выход"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Ваш выбор: ${C_RESET}")" choice
        case $choice in
            1) update_bot; read -p "Нажмите Enter..." ;;
            2) msg_question "Удалить ${item_type}? (y/n): " c; if [[ "$c" =~ ^[Yy]$ ]]; then uninstall_bot; return; fi ;;
            3) install_systemd_logic "secure"; read -p "Нажмите Enter..." ;;
            4) install_systemd_logic "root"; read -p "Нажмите Enter..." ;;
            5) install_docker_logic "secure"; read -p "Нажмите Enter..." ;;
            6) install_docker_logic "root"; read -p "Нажмите Enter..." ;;
            7) if [ "$IS_NODE" == "yes" ]; then install_node_logic; read -p "Нажмите Enter..."; else msg_error "Пункт доступен только в режиме НОДЫ."; sleep 2; fi ;;
            8) if [ "$IS_NODE" == "yes" ]; then toggle_agent_monitoring; read -p "Нажмите Enter..."; fi ;;
            9) if [ "$IS_NODE" != "yes" ]; then manage_alert_module; read -p "Нажмите Enter..."; fi ;;
            0) break ;;
        esac
    done
}

if [ "$(id -u)" -ne 0 ]; then msg_error "Нужен root."; exit 1; fi
if [ "$AUTO_MODE" = true ] && [ -n "$AUTO_AGENT_URL" ] && [ -n "$AUTO_NODE_TOKEN" ]; then install_node_logic; exit 0; fi

check_integrity
if [ "$INSTALL_TYPE" == "НЕТ" ]; then
    clear
    echo -e "${C_BLUE}${C_BOLD}╔═══════════════════════════════════╗${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}║      Установка VPS Manager Bot    ║${C_RESET}"
    echo -e "${C_BLUE}${C_BOLD}╚═══════════════════════════════════╝${C_RESET}"
    echo -e "  Выберите режим установки:"
    echo "--------------------------------------------------------"
    echo "  1) АГЕНТ (Systemd - Secure)  [Рекомендуется]"
    echo "  2) АГЕНТ (Systemd - Root)    [Полный доступ]"
    echo "  3) АГЕНТ (Docker - Secure)   [Изоляция]"
    echo "  4) АГЕНТ (Docker - Root)     [Docker + Host]"
    echo -e "${C_GREEN}  7) НОДА (Клиент)${C_RESET}"
    echo "  0) Выход"
    echo "--------------------------------------------------------"
    read -p "$(echo -e "${C_BOLD}Ваш выбор: ${C_RESET}")" ch
    case $ch in
        1) install_systemd_logic "secure"; read -p "Нажмите Enter..." ;;
        2) install_systemd_logic "root"; read -p "Нажмите Enter..." ;;
        3) install_docker_logic "secure"; read -p "Нажмите Enter..." ;;
        4) install_docker_logic "root"; read -p "Нажмите Enter..." ;;
        7) install_node_logic; read -p "Нажмите Enter..." ;;
        0) exit 0 ;;
        *) msg_error "Неверный выбор."; sleep 2 ;;
    esac
    main_menu
else
    main_menu
fi
