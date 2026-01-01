// Общие функции для всех страниц

// --- ЛОГИКА ТЕМЫ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
    initNotifications(); 
    initHolidayMood(); // ЗАПУСК НОВОГОДНЕГО НАСТРОЕНИЯ
});

// --- НОВОГОДНЯЯ ЛОГИКА ---
function isHolidayPeriod() {
    const now = new Date();
    const month = now.getMonth(); // 0-11 (Декабрь - 11, Январь - 0)
    const day = now.getDate();
    return (month === 11 && day === 31) || (month === 0 && day <= 14);
}

let snowInterval = null;

function initHolidayMood() {
    if (!isHolidayPeriod()) return;

    const themeBtn = document.getElementById('themeBtn');
    if (themeBtn) {
        const holidayBtn = document.createElement('button');
        holidayBtn.id = 'holidayBtn';
        holidayBtn.className = 'flex items-center justify-center w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400 mr-1';
        holidayBtn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 4.5l4 2 4-2M12 2v4.5m-4 12l4-2 4 2M12 22v-4.5m-10-5.5l2 4 4-2M2 12h4.5m15.5 4l-2-4-4 2M22 12h-4.5M4.5 8l2 4-4 2M4.5 16l2-4-4-2M19.5 8l-2 4 4 2M19.5 16l-2-4 4-2" />
            </svg>
        `;
        holidayBtn.onclick = toggleHolidayMood;
        themeBtn.parentNode.insertBefore(holidayBtn, themeBtn);
    }

    const snowContainer = document.createElement('div');
    snowContainer.id = 'snow-container';
    document.body.appendChild(snowContainer);

    const isEnabled = localStorage.getItem('holiday_mood') !== 'false';
    if (isEnabled) {
        startSnow();
        document.getElementById('holidayBtn')?.classList.add('holiday-btn-active');
    }
}

function toggleHolidayMood() {
    const isEnabled = localStorage.getItem('holiday_mood') !== 'false';
    const newState = !isEnabled;
    localStorage.setItem('holiday_mood', newState);

    const btn = document.getElementById('holidayBtn');
    if (newState) {
        startSnow();
        btn?.classList.add('holiday-btn-active');
    } else {
        stopSnow();
        btn?.classList.remove('holiday-btn-active');
    }
}

function startSnow() {
    if (snowInterval) return;
    const container = document.getElementById('snow-container');
    const icons = ['❄', '❅', '❆'];

    snowInterval = setInterval(() => {
        const snowflake = document.createElement('div');
        snowflake.className = 'snowflake';
        snowflake.innerText = icons[Math.floor(Math.random() * icons.length)];
        snowflake.style.left = Math.random() * 100 + 'vw';
        snowflake.style.animationDuration = (Math.random() * 3 + 2) + 's';
        snowflake.style.opacity = Math.random();
        snowflake.style.fontSize = (Math.random() * 10 + 10) + 'px';
        
        container.appendChild(snowflake);

        setTimeout(() => { snowflake.remove(); }, 5000);
    }, 200);
}

function stopSnow() {
    clearInterval(snowInterval);
    snowInterval = null;
    const container = document.getElementById('snow-container');
    if (container) container.innerHTML = '';
}

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
    if (isDark) document.documentElement.classList.add('dark');
    else document.documentElement.classList.remove('dark');
    
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
            inputEl.onkeydown = (e) => { if(e.key === 'Enter') closeSystemModal(inputEl.value); };
        } else { okBtn.onclick = () => closeSystemModal(true); }

        modal.classList.remove('hidden');
        modal.classList.add('flex');
    });
}

window.showModalAlert = (message, title) => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_alert : 'Alert'), message, 'alert');
window.showModalConfirm = (message, title) => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_confirm : 'Confirm'), message, 'confirm');
window.showModalPrompt = (message, title, placeholder = '') => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_prompt : 'Prompt'), message, 'prompt', placeholder);

// --- NOTIFICATION SYSTEM ---
let lastUnreadCount = -1;

function initNotifications() {
    const btn = document.getElementById('notifBtn');
    if (!btn) return;
    btn.addEventListener('click', toggleNotifications);
    const clearBtn = document.getElementById('notifClearBtn');
    if(clearBtn) clearBtn.addEventListener('click', clearNotifications);
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#notifDropdown') && !e.target.closest('#notifBtn')) closeNotifications();
    });
    pollNotifications();
    setInterval(pollNotifications, 3000);
}

async function pollNotifications() {
    try {
        const res = await fetch('/api/notifications/list');
        if (!res.ok) return;
        const data = await res.json();
        updateNotifUI(data.notifications, data.unread_count);
    } catch (e) { console.error("Notif poll error", e); }
}

async function clearNotifications(e) {
    e.stopPropagation();
    const msg = (typeof I18N !== 'undefined' && I18N.web_clear_notif_confirm) ? I18N.web_clear_notif_confirm : "Очистить все уведомления?";
    if(!await window.showModalConfirm(msg, (typeof I18N !== 'undefined' ? I18N.modal_title_confirm : "Подтверждение"))) return;
    try {
        await fetch('/api/notifications/clear', { method: 'POST' });
        updateNotifUI([], 0);
    } catch(e) { console.error(e); }
}

function updateNotifUI(list, count) {
    const badge = document.getElementById('notifBadge');
    const listContainer = document.getElementById('notifList');
    const bellIcon = document.querySelector('#notifBtn svg');
    
    if (count > 0) {
        badge.innerText = count > 99 ? '99+' : count;
        badge.classList.remove('hidden');
        if (lastUnreadCount !== -1 && count > lastUnreadCount) {
            bellIcon.classList.add('notif-bell-shake');
            setTimeout(() => bellIcon.classList.remove('notif-bell-shake'), 500);
        }
    } else badge.classList.add('hidden');
    
    lastUnreadCount = count;
    const clearBtn = document.getElementById('notifClearBtn');
    if(clearBtn) {
        if(list.length > 0) clearBtn.classList.remove('hidden');
        else clearBtn.classList.add('hidden');
    }

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
            </div>`;
        }).join('');
    }
}

function toggleNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    const badge = document.getElementById('notifBadge');
    if (dropdown.classList.contains('show')) closeNotifications();
    else {
        dropdown.classList.remove('hidden');
        setTimeout(() => dropdown.classList.add('show'), 10);
        if (lastUnreadCount > 0) {
            setTimeout(async () => {
                try {
                    await fetch('/api/notifications/read', { method: 'POST' });
                    badge.classList.add('hidden'); 
                } catch(e) { console.error(e); }
            }, 3000);
        }
    }
}

function closeNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    if(dropdown) {
        dropdown.classList.remove('show');
        setTimeout(() => dropdown.classList.add('hidden'), 200);
    }
}