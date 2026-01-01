// Общие функции для всех страниц

// --- ЛОГИКА ТЕМЫ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
    initNotifications(); // ЗАПУСК СИСТЕМЫ УВЕДОМЛЕНИЙ
});

function parsePageEmojis() {
    if (window.twemoji) {
        window.twemoji.parse(document.body, { folder: 'svg', ext: '.svg' });
    }
}

function toggleTheme() {
    const idx = themes.indexOf(currentTheme);
    const nextIdx = (idx + 1) % themes.length;
    currentTheme = themes[nextIdx];
    localStorage.setItem('theme', currentTheme);
    
    const isDark = currentTheme === 'dark' || (currentTheme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (isDark) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
    
    applyThemeUI(currentTheme);
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: currentTheme, isDark: isDark } }));
}

function applyThemeUI(theme) {
    const iconMoon = document.getElementById('iconMoon');
    const iconSun = document.getElementById('iconSun');
    const iconSystem = document.getElementById('iconSystem');
    if (!iconMoon || !iconSun || !iconSystem) return;
    [iconMoon, iconSun, iconSystem].forEach(el => el.classList.add('hidden'));
    if (theme === 'dark') iconMoon.classList.remove('hidden');
    else if (theme === 'light') iconSun.classList.remove('hidden');
    else iconSystem.classList.remove('hidden');
}

async function setLanguage(lang) {
    try {
        const res = await fetch('/api/settings/language', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lang: lang})
        });
        if (res.ok) window.location.reload();
    } catch (e) { console.error("Lang switch failed", e); }
}

// --- УТИЛИТЫ ---
function copyToken(element) {
    const tokenEl = document.getElementById('modalToken');
    const tokenText = tokenEl ? tokenEl.innerText : '';
    if (!tokenText || tokenText === '...') return;
    // Используем новую систему тостов
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tokenText).then(() => showToast(I18N.web_copied || "Copied!")).catch(() => fallbackCopyTextToClipboard(tokenText));
    } else {
        fallbackCopyTextToClipboard(tokenText);
    }
}

function fallbackCopyTextToClipboard(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        if (document.execCommand('copy')) showToast(I18N.web_copied || "Copied!");
    } catch (err) { console.error('Fallback error', err); }
    document.body.removeChild(textArea);
}

function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            if(window.showToast) window.showToast(I18N.web_copied || "Copied!");
        });
    } else {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            document.execCommand('copy');
            if(window.showToast) window.showToast(I18N.web_copied || "Copied!");
        } catch (err) {}
        document.body.removeChild(textArea);
    }
}

// --- ЛОГИКА HINTS (Подсказки) ---
window.activeHint = null;
function openHintModal(event, hintId) {
    event.stopPropagation();
    const hintEl = document.getElementById(hintId);
    const errorMsg = (typeof I18N !== 'undefined' && I18N.web_error) ? I18N.web_error.replace('{error}', 'Hint text not found.') : 'Hint text not found.';
    const hintText = hintEl ? hintEl.innerHTML.trim() : errorMsg;
    
    let titleEl = event.currentTarget.closest('.bg-white\\/50, .bg-black\\/20, .flex.items-center.gap-1');
    let title = 'Информация';
    if (titleEl) {
        let metricSpan = titleEl.querySelector('.text-\\[9px\\], span:not(.cursor-help)');
        if (metricSpan) title = metricSpan.innerText || 'Информация';
    }
    
    const modal = document.getElementById('genericHintModal');
    if (!modal) return;
    document.getElementById('hintModalTitle').innerText = title;
    document.getElementById('hintModalContent').innerHTML = hintText;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    
    const parentContainer = event.currentTarget.closest('.relative.inline-block');
    if(parentContainer) parentContainer.style.zIndex = 10;
    
    if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
}

function closeHintModal() {
    const modal = document.getElementById('genericHintModal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = 'auto';
    document.querySelectorAll('[onclick^="toggleHint"]').forEach(btn => {
        const parentContainer = btn.closest('.relative.inline-block');
        if(parentContainer) parentContainer.style.zIndex = '';
    });
}
window.toggleHint = openHintModal;
window.closeHintModal = closeHintModal;

document.addEventListener('click', function(event) {
    if (window.activeHint) {
        const activeHintEl = document.getElementById(window.activeHint);
        if (activeHintEl && !activeHintEl.contains(event.target) && event.target.closest('button[onclick^="toggleHint"]') === null) {
            activeHintEl.classList.add('hidden');
            activeHintEl.classList.remove('block');
            window.activeHint = null;
        }
    }
});

// --- СИСТЕМНЫЕ МОДАЛЬНЫЕ ОКНА ---
let sysModalResolve = null;

function closeSystemModal(result) {
    const modal = document.getElementById('systemModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    if (sysModalResolve) {
        sysModalResolve(result);
        sysModalResolve = null;
    }
}
window.closeSystemModal = closeSystemModal;

function _showSystemModalBase(title, message, type = 'alert', placeholder = '') {
    return new Promise((resolve) => {
        sysModalResolve = resolve;
        const modal = document.getElementById('systemModal');
        const titleEl = document.getElementById('sysModalTitle');
        const msgEl = document.getElementById('sysModalMessage');
        const inputEl = document.getElementById('sysModalInput');
        const cancelBtn = document.getElementById('sysModalCancel');
        const okBtn = document.getElementById('sysModalOk');

        if (!modal) {
            if (type === 'confirm') resolve(confirm(message));
            else if (type === 'prompt') resolve(prompt(message, placeholder));
            else { alert(message); resolve(true); }
            return;
        }

        titleEl.innerText = title;
        msgEl.innerHTML = message.replace(/\n/g, '<br>');
        
        inputEl.classList.add('hidden');
        cancelBtn.classList.add('hidden');
        inputEl.value = '';

        if (typeof I18N !== 'undefined') {
            cancelBtn.innerText = I18N.modal_btn_cancel || 'Cancel';
            okBtn.innerText = I18N.modal_btn_ok || 'OK';
        }

        if (type === 'confirm') {
            cancelBtn.classList.remove('hidden');
            okBtn.onclick = () => closeSystemModal(true);
            cancelBtn.onclick = () => closeSystemModal(false);
        } else if (type === 'prompt') {
            cancelBtn.classList.remove('hidden');
            inputEl.classList.remove('hidden');
            inputEl.placeholder = placeholder;
            inputEl.focus();
            okBtn.onclick = () => closeSystemModal(inputEl.value);
            cancelBtn.onclick = () => closeSystemModal(null);
            
            inputEl.onkeydown = (e) => {
                if(e.key === 'Enter') closeSystemModal(inputEl.value);
            };
        } else {
            okBtn.onclick = () => closeSystemModal(true);
        }

        modal.classList.remove('hidden');
        modal.classList.add('flex');
    });
}

window.showModalAlert = (message, title) => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_alert : 'Alert'), message, 'alert');
window.showModalConfirm = (message, title) => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_confirm : 'Confirm'), message, 'confirm');
window.showModalPrompt = (message, title, placeholder = '') => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_prompt : 'Prompt'), message, 'prompt', placeholder);

// --- NOTIFICATION SYSTEM ---
let lastUnreadCount = -1; // -1 = первая загрузка (не показывать тост)

function initNotifications() {
    const btn = document.getElementById('notifBtn');
    if (!btn) return;

    btn.addEventListener('click', toggleNotifications);
    
    // Кнопка очистки
    const clearBtn = document.getElementById('notifClearBtn');
    if(clearBtn) {
        clearBtn.addEventListener('click', clearNotifications);
    }
    
    // Закрытие при клике вне области
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#notifDropdown') && !e.target.closest('#notifBtn')) {
            closeNotifications();
        }
    });

    // Запуск опроса
    pollNotifications();
    setInterval(pollNotifications, 3000);
}

async function pollNotifications() {
    try {
        const res = await fetch('/api/notifications/list');
        if (!res.ok) return;
        const data = await res.json();
        
        updateNotifUI(data.notifications, data.unread_count);
    } catch (e) {
        console.error("Notif poll error", e);
    }
}

// [FIX] Модальное окно для очистки уведомлений
async function clearNotifications(e) {
    e.stopPropagation();
    
    const msg = (typeof I18N !== 'undefined' && I18N.web_clear_notif_confirm) ? I18N.web_clear_notif_confirm : "Очистить все уведомления?";
    const title = (typeof I18N !== 'undefined' && I18N.modal_title_confirm) ? I18N.modal_title_confirm : "Подтверждение";
    
    if(!await window.showModalConfirm(msg, title)) return;
    
    try {
        await fetch('/api/notifications/clear', { method: 'POST' });
        updateNotifUI([], 0);
    } catch(e) { console.error(e); }
}

function updateNotifUI(list, count) {
    const badge = document.getElementById('notifBadge');
    const listContainer = document.getElementById('notifList');
    const bellIcon = document.querySelector('#notifBtn svg');
    const clearBtn = document.getElementById('notifClearBtn');
    
    // Обновление бейджа
    if (count > 0) {
        badge.innerText = count > 99 ? '99+' : count;
        badge.classList.remove('hidden');
        
        // Анимация и тост только если это НЕ первая загрузка и счетчик вырос
        if (lastUnreadCount !== -1 && count > lastUnreadCount) {
            bellIcon.classList.add('notif-bell-shake');
            setTimeout(() => bellIcon.classList.remove('notif-bell-shake'), 500);
            
            // Показываем тост только для самого нового
            if (list.length > 0) {
                const newest = list[0];
                const tmp = document.createElement("DIV");
                tmp.innerHTML = newest.text;
                const plainText = tmp.textContent || tmp.innerText || "";
                showToast(plainText);
            }
        }
    } else {
        badge.classList.add('hidden');
    }
    
    // Обновляем состояние
    lastUnreadCount = count;

    // Управление видимостью кнопки очистки
    if(clearBtn) {
        if(list.length > 0) clearBtn.classList.remove('hidden');
        else clearBtn.classList.add('hidden');
    }

    // Рендер списка
    if (list.length === 0) {
        const noText = (typeof I18N !== 'undefined' && I18N.web_no_notifications) ? I18N.web_no_notifications : "No notifications";
        listContainer.innerHTML = `<div class="p-4 text-center text-gray-500 text-sm">${noText}</div>`;
    } else {
        listContainer.innerHTML = list.map(n => {
            const date = new Date(n.time * 1000);
            const timeStr = date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            return `
            <div class="notif-item">
                <div class="text-sm text-gray-800 dark:text-gray-200 leading-snug">${n.text}</div>
                <div class="notif-time flex items-center gap-1">
                    <span>${timeStr}</span>
                    <span class="w-1 h-1 rounded-full bg-gray-300 dark:bg-gray-600"></span>
                    <span class="uppercase text-[9px] font-bold tracking-wider opacity-70">${n.type}</span>
                </div>
            </div>
            `;
        }).join('');
    }
}

function toggleNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    const badge = document.getElementById('notifBadge');
    
    if (dropdown.classList.contains('show')) {
        closeNotifications();
    } else {
        dropdown.classList.remove('hidden');
        setTimeout(() => dropdown.classList.add('show'), 10);
        
        // Сброс счетчика через 3 секунды
        if (lastUnreadCount > 0) {
            setTimeout(async () => {
                try {
                    await fetch('/api/notifications/read', { method: 'POST' });
                    badge.classList.add('hidden'); 
                    // Не сбрасываем lastUnreadCount в 0, чтобы избежать повторного тоста при следующем поллинге
                } catch(e) { console.error(e); }
            }, 3000);
        }
    }
}

function closeNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    dropdown.classList.remove('show');
    setTimeout(() => dropdown.classList.add('hidden'), 200);
}

// --- НОВАЯ СИСТЕМА TOAST (Снизу справа + крестик) ---
function showToast(message) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = 'toast-msg';
    toast.innerHTML = `
        <div class="p-1.5 rounded-full bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex-shrink-0">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
        </div>
        <div class="text-sm font-medium leading-tight pt-0.5 break-words w-full">${message}</div>
        <div class="toast-close" onclick="this.parentElement.remove()">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        </div>
    `;

    container.appendChild(toast);

    // Анимация
    requestAnimationFrame(() => {
        toast.classList.add('show');
    });

    // Автоскрытие через 5 сек
    setTimeout(() => {
        if (toast && toast.parentElement) {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 400);
        }
    }, 5000);
}

// --- ФУНКЦИИ ДОБАВЛЕНИЯ НОДЫ (ОБЩИЕ) ---
function openAddNodeModal() {
    const modal = document.getElementById('addNodeModal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        const resDiv = document.getElementById('nodeResultDash');
        if(resDiv) resDiv.classList.add('hidden');
        const input = document.getElementById('newNodeNameDash');
        if(input) {
            input.value = '';
            input.focus();
            validateNodeInput();
        }
    }
}

function closeAddNodeModal() {
    const modal = document.getElementById('addNodeModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
}

function validateNodeInput() {
    const input = document.getElementById('newNodeNameDash');
    const btn = document.getElementById('btnAddNodeDash');
    if (!input || !btn) return;
    if (input.value.trim().length >= 2) {
        btn.disabled = false;
        btn.classList.remove('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
        btn.classList.add('bg-purple-600', 'hover:bg-purple-500', 'active:scale-95', 'text-white', 'cursor-pointer', 'shadow-lg', 'shadow-purple-500/20');
    } else {
        btn.disabled = true;
        btn.classList.remove('bg-purple-600', 'hover:bg-purple-500', 'active:scale-95', 'text-white', 'cursor-pointer', 'shadow-lg', 'shadow-purple-500/20');
        btn.classList.add('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
    }
}

window.openAddNodeModal = openAddNodeModal;
window.closeAddNodeModal = closeAddNodeModal;
window.validateNodeInput = validateNodeInput;

async function addNodeDash() {
    const nameInput = document.getElementById('newNodeNameDash');
    const name = nameInput.value.trim();
    const btn = document.getElementById('btnAddNodeDash');
    if (!name) return;
    btn.disabled = true;
    const originalText = btn.innerText;
    btn.innerHTML = `<svg class="animate-spin h-5 w-5 text-white mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    try {
        const res = await fetch('/api/nodes/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name})
        });
        const data = await res.json();
        if (res.ok) {
            document.getElementById('nodeResultDash').classList.remove('hidden');
            document.getElementById('newNodeTokenDash').innerText = data.token;
            document.getElementById('newNodeCmdDash').innerText = data.command;
            
            // Обновляем списки на обеих страницах, если они есть
            if (typeof fetchNodesList === 'function') fetchNodesList(); // Dashboard
            if (typeof renderNodes === 'function' && typeof NODES_DATA !== 'undefined') { // Settings
                 NODES_DATA.push({token: data.token, name: name, ip: 'Unknown'});
                 renderNodes();
            }
            
            nameInput.value = "";
            validateNodeInput();
        } else {
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error), 'Ошибка');
        }
    } catch (e) {
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), 'Ошибка соединения');
    } finally {
        btn.innerText = originalText;
        validateNodeInput();
    }
}
window.addNodeDash = addNodeDash;