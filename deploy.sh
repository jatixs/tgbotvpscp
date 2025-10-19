# --- Функция для обновления URLов ---
update_file_urls() {
    local branch=$1
    # URL для raw контента GitHub использует имя ветки напрямую
    BOT_PY_URL="${GITHUB_RAW_BASE_URL}/${branch}/bot.py"
    REQUIREMENTS_URL="${GITHUB_RAW_BASE_URL}/${branch}/requirements.txt"
    WATCHDOG_PY_URL="${GITHUB_RAW_BASE_URL}/${branch}/watchdog.py"
    msg_info "URLы обновлены для ветки: ${C_YELLOW}${branch}${C_RESET}"
    # msg_info "URL bot.py: ${BOT_PY_URL}" # Debug
}

# --- Функция выбора ветки ---
select_branch() {
    echo "--------------------------------------------------------"
    # --- [ИЗМЕНЕНИЕ] Предлагаем только main и develop ---
    echo -e "  Доступные ветки:"
    echo -e "  1) ${C_YELLOW}main${C_RESET}    (Стабильная)"
    echo -e "  2) ${C_YELLOW}develop${C_RESET} (Разработка)"
    read -p "$(echo -e "${C_BOLD}Выберите ветку [1-2, Enter = ${CURRENT_BRANCH}]: ${C_RESET}")" branch_choice
    # --------------------------------------------------

    local new_branch=""
    case $branch_choice in
        1) new_branch="main" ;;
        2) new_branch="develop" ;;
        "") new_branch="$CURRENT_BRANCH" ;; # Оставить текущую по Enter
        *) msg_error "Неверный выбор." ;;
    esac

    # Обновляем ветку и URLы, только если new_branch установлен и отличается от текущей
    if [ -n "$new_branch" ] && [ "$new_branch" != "$CURRENT_BRANCH" ]; then
        CURRENT_BRANCH="$new_branch"
        update_file_urls "$CURRENT_BRANCH" # Обновляем URLы
        msg_success "Выбрана ветка: ${CURRENT_BRANCH}"
    elif [ "$branch_choice" == "" ]; then
        msg_info "Ветка не изменена (${CURRENT_BRANCH})."
    # Если был неверный выбор, new_branch будет пустым, и ничего не произойдет
    elif [ -z "$new_branch" ]; then
         msg_warning "Ветка не изменена (${CURRENT_BRANCH})." # Сообщаем об этом
    fi
    echo "--------------------------------------------------------"
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
        echo -e "  Текущая ветка: ${C_YELLOW}${CURRENT_BRANCH}${C_RESET}"
        echo "--------------------------------------------------------"
        echo -e "${C_GREEN}  1)${C_RESET} ${C_BOLD}Установить (Secure):${C_RESET} Рекомендуемый, безопасный режим"
        echo -e "${C_YELLOW}  2)${C_RESET} ${C_BOLD}Установить (Root):${C_RESET}   Менее безопасный, полный доступ"
        echo -e "${C_CYAN}  3)${C_RESET} ${C_BOLD}Обновить бота:${C_RESET}         Обновление бота и watchdog"
        echo -e "${C_RED}  4)${C_RESET} ${C_BOLD}Удалить бота:${C_RESET}          Полное удаление с сервера"
        echo -e "  ${C_BLUE}5)${C_RESET} ${C_BOLD}Выбрать ветку:${C_RESET}        Изменить ветку для установки/обновления"
        echo -e "  6) ${C_BOLD}Выход${C_RESET}"
        echo "--------------------------------------------------------"
        read -p "$(echo -e "${C_BOLD}Введите номер опции [1-6]: ${C_RESET}")" choice

        case $choice in
            1) install_secure ;;
            2) install_root ;;
            3) update_bot ;;
            4)
                read -p "$(echo -e "${C_RED}❓ ВЫ УВЕРЕНЫ, что хотите ПОЛНОСТЬЮ удалить бота и watchdog? (y/n): ${C_RESET}")" confirm_uninstall
                if [[ "$confirm_uninstall" =~ ^[Yy]$ ]]; then
                    uninstall_bot
                else
                    msg_info "Удаление отменено."
                fi
                ;;
            5) select_branch ;;
            6) break ;;
            *) msg_error "Неверный выбор." ;;
        esac
        # Пропускаем паузу после выбора ветки (опция 5)
        if [ "$choice" != "5" ]; then
             echo
             read -n 1 -s -r -p "Нажмите любую клавишу для возврата в меню..."
        fi
    done
    echo -e "\n${C_CYAN}👋 До свидания!${C_RESET}"
}