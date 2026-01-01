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
    const showToast = () => {
        const toast = document.getElementById('copyToast');
        if (toast) {
            toast.classList.remove('translate-y-full');
            setTimeout(() => toast.classList.add('translate-y-full'), 2000);
        }
    };
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tokenText).then(showToast).catch(() => fallbackCopyTextToClipboard(tokenText, showToast));
    } else {
        fallbackCopyTextToClipboard(tokenText, showToast);
    }
}

function fallbackCopyTextToClipboard(text, onSuccess) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        if (document.execCommand('copy') && onSuccess) onSuccess();
    } catch (err) { console.error('Fallback error', err); }
    document.body.removeChild(textArea);
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

// --- NOTIFICATION SYSTEM (NEW) ---
let lastUnreadCount = 0;

function initNotifications() {
    const btn = document.getElementById('notifBtn');
    if (!btn) return;

    btn.addEventListener('click', toggleNotifications);
    
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

function updateNotifUI(list, count) {
    const badge = document.getElementById('notifBadge');
    const listContainer = document.getElementById('notifList');
    const bellIcon = document.querySelector('#notifBtn svg');
    
    // Обновление бейджа
    if (count > 0) {
        badge.innerText = count > 99 ? '99+' : count;
        badge.classList.remove('hidden');
        
        // Анимация если счетчик увеличился
        if (count > lastUnreadCount) {
            bellIcon.classList.add('notif-bell-shake');
            setTimeout(() => bellIcon.classList.remove('notif-bell-shake'), 500);
            
            // Показываем всплывающее уведомление для самого нового
            if (list.length > 0) {
                const newest = list[0];
                const tmp = document.createElement("DIV");
                tmp.innerHTML = newest.text;
                const plainText = tmp.textContent || tmp.innerText || "";
                showToast(`🔔 ${plainText.substring(0, 50)}${plainText.length>50?'...':''}`);
            }
        }
    } else {
        badge.classList.add('hidden');
    }
    
    lastUnreadCount = count;

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
        
        // Отмечаем как прочитанное через 3 секунды
        if (lastUnreadCount > 0) {
            setTimeout(async () => {
                try {
                    await fetch('/api/notifications/read', { method: 'POST' });
                    badge.classList.add('hidden'); 
                    lastUnreadCount = 0;
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