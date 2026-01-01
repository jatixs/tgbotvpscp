// --- ЛОГИКА ТЕМЫ И ИНИЦИАЛИЗАЦИЯ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    
    // ФИКС ФЛАГОВ ДЛЯ WINDOWS (библиотека Twemoji)
    if (typeof window.parsePageEmojis === 'function') {
        window.parsePageEmojis();
    } else {
        parsePageEmojis(); 
    }

    initNotifications(); 
    initHolidayMood(); 
    
    // Инициализация логов (автозагрузка при входе)
    if (document.getElementById('logsContainer')) {
        if (typeof window.switchLogType === 'function') {
            window.switchLogType('bot');
        }
    }
});

function parsePageEmojis() {
    if (window.twemoji) {
        window.twemoji.parse(document.body, { 
            folder: 'svg', 
            ext: '.svg',
            base: 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/'
        });
    }
}
window.parsePageEmojis = parsePageEmojis;

// --- ПОДСКАЗКИ (ХИНТЫ) ---
function toggleHint(event, hintId) {
    if (event) event.stopPropagation();
    const hintElement = document.getElementById(hintId);
    if (!hintElement) return;

    const modal = document.getElementById('genericHintModal');
    const content = document.getElementById('hintModalContent');
    const title = document.getElementById('hintModalTitle');

    if (modal && content) {
        content.innerHTML = hintElement.innerHTML;
        const parentLabel = hintElement.closest('div')?.querySelector('span, label')?.innerText;
        title.innerText = parentLabel || (typeof I18N !== 'undefined' ? I18N.modal_title_alert : 'Информация');
        
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
    }
}

function closeHintModal() {
    const modal = document.getElementById('genericHintModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
}
window.toggleHint = toggleHint;
window.closeHintModal = closeHintModal;

// --- НОВОГОДНЯЯ ЛОГИКА ---
function isHolidayPeriod() {
    const now = new Date();
    const month = now.getMonth(); 
    const day = now.getDate();
    return (month === 11 && day === 31) || (month === 0 && day <= 14);
}

let snowInterval = null;

function initHolidayMood() {
    if (!isHolidayPeriod()) return;

    const themeBtn = document.getElementById('themeBtn');
    if (themeBtn && !document.getElementById('holidayBtn')) {
        const holidayBtn = document.createElement('button');
        holidayBtn.id = 'holidayBtn';
        holidayBtn.className = 'flex items-center justify-center w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400 mr-1';
        
        holidayBtn.innerHTML = `
            <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="2" x2="12" y2="22"></line>
                <line x1="20" y1="12" x2="4" y2="12"></line>
                <line x1="17.66" y1="6.34" x2="6.34" y2="17.66"></line>
                <line x1="17.66" y1="17.66" x2="6.34" y2="6.34"></line>
                <polyline points="9 4 12 7 15 4"></polyline>
                <polyline points="15 20 12 17 9 20"></polyline>
                <polyline points="20 9 17 12 20 15"></polyline>
                <polyline points="4 15 7 12 4 9"></polyline>
            </svg>`;
        holidayBtn.onclick = toggleHolidayMood;
        themeBtn.parentNode.insertBefore(holidayBtn, themeBtn);
    }

    createHolidayStructure();

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(createHolidayStructure, 250);
    });

    const isEnabled = localStorage.getItem('holiday_mood') !== 'false';
    if (isEnabled) {
        startHolidayEffects();
        document.getElementById('holidayBtn')?.classList.add('holiday-btn-active');
    }
}

function createHolidayStructure() {
    const nav = document.querySelector('nav');
    if (!nav) return;

    let lights = document.getElementById('holiday-lights');
    if (lights) lights.remove(); 

    lights = document.createElement('ul');
    lights.id = 'holiday-lights';
    lights.className = 'lights-garland';
    
    const spacing = window.innerWidth < 640 ? 50 : 60;
    const count = Math.floor(window.innerWidth / spacing);
    
    for (let i = 0; i < count; i++) {
        lights.appendChild(document.createElement('li'));
    }
    nav.appendChild(lights);

    const isEnabled = localStorage.getItem('holiday_mood') !== 'false';
    if (isEnabled) {
        lights.classList.add('garland-on');
    }

    if (!document.getElementById('snow-container')) {
        const snowContainer = document.createElement('div');
        snowContainer.id = 'snow-container';
        document.body.appendChild(snowContainer);
    }
}

function toggleHolidayMood() {
    const isEnabled = localStorage.getItem('holiday_mood') !== 'false';
    const newState = !isEnabled;
    localStorage.setItem('holiday_mood', newState);
    const btn = document.getElementById('holidayBtn');
    if (newState) { startHolidayEffects(); btn?.classList.add('holiday-btn-active'); }
    else { stopHolidayEffects(); btn?.classList.remove('holiday-btn-active'); }
}

function startHolidayEffects() {
    startSnow();
    document.getElementById('holiday-lights')?.classList.add('garland-on');
}

function stopHolidayEffects() {
    stopSnow();
    document.getElementById('holiday-lights')?.classList.remove('garland-on');
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
        snowflake.style.animationDuration = (Math.random() * 3 + 4) + 's';
        snowflake.style.opacity = Math.random() * 0.7;
        snowflake.style.fontSize = (Math.random() * 8 + 8) + 'px';
        container.appendChild(snowflake);
        setTimeout(() => snowflake.remove(), 6000);
    }, 300);
}

function stopSnow() {
    clearInterval(snowInterval);
    snowInterval = null;
    const container = document.getElementById('snow-container');
    if (container) container.innerHTML = '';
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

// --- ТЕМА ---
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

// --- NOTIFICATION SYSTEM ---
let lastUnreadCount = -1;
function initNotifications() {
    const btn = document.getElementById('notifBtn');
    if (!btn) return;
    btn.addEventListener('click', toggleNotifications);
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

function updateNotifUI(list, count) {
    const badge = document.getElementById('notifBadge');
    const listContainer = document.getElementById('notifList');
    if (count > 0) {
        badge.innerText = count > 99 ? '99+' : count;
        badge.classList.remove('hidden');
    } else badge.classList.add('hidden');
    lastUnreadCount = count;

    const clearBtn = document.getElementById('notifClearBtn');
    if(clearBtn) {
        if(list.length > 0) clearBtn.classList.remove('hidden');
        else clearBtn.classList.add('hidden');
    }

    if (list.length === 0) {
        listContainer.innerHTML = `<div class="p-4 text-center text-gray-500 text-sm">${(typeof I18N !== 'undefined' ? I18N.web_no_notifications : "Нет уведомлений")}</div>`;
    } else {
        listContainer.innerHTML = list.map(n => `
            <div class="notif-item">
                <div class="text-sm text-gray-800 dark:text-gray-200 leading-snug">${n.text}</div>
                <div class="notif-time">${new Date(n.time * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</div>
            </div>`).join('');
    }
}

function toggleNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    const badge = document.getElementById('notifBadge');
    if (dropdown.classList.contains('show')) {
        dropdown.classList.remove('show');
        setTimeout(() => dropdown.classList.add('hidden'), 200);
    } else {
        dropdown.classList.remove('hidden');
        setTimeout(() => dropdown.classList.add('show'), 10);
        if (lastUnreadCount > 0) {
            fetch('/api/notifications/read', { method: 'POST' }).then(() => badge.classList.add('hidden'));
        }
    }
}