// --- ИНИЦИАЛИЗАЦИЯ ПРИ ЗАГРУЗКЕ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    
    // Фикс флагов Windows
    if (typeof window.parsePageEmojis === 'function') { window.parsePageEmojis(); } else { parsePageEmojis(); }

    initNotifications(); 
    initHolidayMood(); 
    initToasts();

    // Автозагрузка системных логов
    if (document.getElementById('logsContainer')) {
        if (typeof window.switchLogType === 'function') { window.switchLogType('bot'); }
    }
});

function parsePageEmojis() {
    if (window.twemoji) {
        window.twemoji.parse(document.body, { 
            folder: 'svg', ext: '.svg',
            base: 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/'
        });
    }
}

// --- ПЕРЕКЛЮЧАТЕЛЬ ЯЗЫКА (ИСПРАВЛЕНО) ---
async function setLanguage(lang) {
    try {
        const response = await fetch('/api/settings/language', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lang: lang })
        });
        if (response.ok) {
            window.location.reload(); 
        } else {
            console.error("Failed to set language");
        }
    } catch (e) {
        console.error("Language switch error:", e);
    }
}
window.setLanguage = setLanguage;

// --- КОПИРОВАНИЕ ТОКЕНА (ИСПРАВЛЕНО) ---
function copyToken(el) {
    const tokenText = document.getElementById('modalToken').innerText;
    if (!tokenText || tokenText === '...') return;

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tokenText).then(() => {
            showCopyFeedback();
        });
    } else {
        const textArea = document.createElement("textarea");
        textArea.value = tokenText;
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand('copy');
            showCopyFeedback();
        } catch (err) {
            console.error('Fallback copy failed', err);
        }
        document.body.removeChild(textArea);
    }
}

function showCopyFeedback() {
    const toast = document.getElementById('copyToast');
    if (toast) {
        toast.classList.replace('translate-y-full', 'translate-y-0');
        setTimeout(() => {
            toast.classList.replace('translate-y-0', 'translate-y-full');
        }, 2000);
    }
    if (window.showToast) window.showToast(I18N.web_copied || "Скопировано!");
}
window.copyToken = copyToken;

// --- ВСПЛЫВАЮЩИЕ УВЕДОМЛЕНИЯ (TOASTS) ---
function initToasts() {
    if (!document.getElementById('toast-container')) {
        const container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }
}

function showToast(message, duration = 3000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-msg';
    toast.innerHTML = `
        <div class="flex-1">${message}</div>
        <div class="toast-close" onclick="this.parentElement.remove()">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </div>
    `;

    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, duration);
}
window.showToast = showToast;

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
    return (now.getMonth() === 11 && now.getDate() === 31) || (now.getMonth() === 0 && now.getDate() <= 14);
}

let snowInterval = null;

function initHolidayMood() {
    if (!isHolidayPeriod()) return;

    const themeBtn = document.getElementById('themeBtn');
    if (themeBtn && !document.getElementById('holidayBtn')) {
        const holidayBtn = document.createElement('button');
        holidayBtn.id = 'holidayBtn';
        holidayBtn.className = 'flex items-center justify-center w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400 mr-1';
        holidayBtn.innerHTML = `<svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="22"></line><line x1="20" y1="12" x2="4" y2="12"></line><line x1="17.66" y1="6.34" x2="6.34" y2="17.66"></line><line x1="17.66" y1="17.66" x2="6.34" y2="6.34"></line><polyline points="9 4 12 7 15 4"></polyline><polyline points="15 20 12 17 9 20"></polyline><polyline points="20 9 17 12 20 15"></polyline><polyline points="4 15 7 12 4 9"></polyline></svg>`;
        holidayBtn.onclick = toggleHolidayMood;
        themeBtn.parentNode.insertBefore(holidayBtn, themeBtn);
    }

    createHolidayStructure();
    window.addEventListener('resize', () => {
        clearTimeout(window.resizeTimer);
        window.resizeTimer = setTimeout(createHolidayStructure, 250);
    });

    if (localStorage.getItem('holiday_mood') !== 'false') {
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
    for (let i = 0; i < count; i++) { lights.appendChild(document.createElement('li')); }
    nav.appendChild(lights);
    if (localStorage.getItem('holiday_mood') !== 'false') lights.classList.add('garland-on');

    if (!document.getElementById('snow-container')) {
        const snow = document.createElement('div');
        snow.id = 'snow-container';
        document.body.appendChild(snow);
    }
}

function toggleHolidayMood() {
    const newState = localStorage.getItem('holiday_mood') === 'false';
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
        const s = document.createElement('div');
        s.className = 'snowflake';
        s.innerText = icons[Math.floor(Math.random() * icons.length)];
        s.style.left = Math.random() * 100 + 'vw';
        s.style.animationDuration = (Math.random() * 3 + 4) + 's';
        s.style.opacity = Math.random() * 0.7;
        s.style.fontSize = (Math.random() * 8 + 8) + 'px';
        container.appendChild(s);
        setTimeout(() => s.remove(), 6000);
    }, 300);
}

function stopSnow() { clearInterval(snowInterval); snowInterval = null; if (document.getElementById('snow-container')) document.getElementById('snow-container').innerHTML = ''; }

// --- УВЕДОМЛЕНИЯ (КОЛОКОЛЬЧИК) ---
let lastUnreadCount = -1;
function initNotifications() {
    const btn = document.getElementById('notifBtn');
    if (!btn) return;
    btn.addEventListener('click', toggleNotifications);
    if (document.getElementById('notifClearBtn')) document.getElementById('notifClearBtn').addEventListener('click', clearNotifications);
    document.addEventListener('click', (e) => { if (!e.target.closest('#notifDropdown') && !e.target.closest('#notifBtn')) closeNotifications(); });
    pollNotifications();
    setInterval(pollNotifications, 3000);
}

async function pollNotifications() {
    try {
        const res = await fetch('/api/notifications/list');
        if (!res.ok) return;
        const data = await res.json();
        updateNotifUI(data.notifications, data.unread_count);
    } catch (e) {}
}

// --- УВЕДОМЛЕНИЯ: ОЧИСТИТЬ ВСЁ (ИСПРАВЛЕНО) ---
async function clearNotifications(e) {
    if (e) e.stopPropagation();
    
    // Вызов модального окна подтверждения (как в настройках)
    const msg = I18N.web_clear_notif_confirm || "Очистить все уведомления?";
    const title = I18N.modal_title_confirm || "Подтверждение";
    if (!await window.showModalConfirm(msg, title)) return;

    try { 
        const res = await fetch('/api/notifications/clear', { method: 'POST' }); 
        if (res.ok) {
            updateNotifUI([], 0); 
            if (window.showToast) window.showToast(I18N.web_logs_cleared_alert || "Очищено!");
        }
    } catch (e) {
        console.error("Clear notifications error:", e);
    }
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
    if (document.getElementById('notifClearBtn')) {
        if (list.length > 0) document.getElementById('notifClearBtn').classList.remove('hidden');
        else document.getElementById('notifClearBtn').classList.add('hidden');
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
    if (dropdown.classList.contains('show')) closeNotifications();
    else {
        dropdown.classList.remove('hidden');
        setTimeout(() => dropdown.classList.add('show'), 10);
        if (lastUnreadCount > 0) { fetch('/api/notifications/read', { method: 'POST' }).then(() => badge.classList.add('hidden')); }
    }
}

function closeNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    if (dropdown) { dropdown.classList.remove('show'); setTimeout(() => dropdown.classList.add('hidden'), 200); }
}

// --- ТЕМА И СИСТЕМНЫЕ ОКНА ---
function toggleTheme() {
    const nextIdx = (themes.indexOf(currentTheme) + 1) % themes.length;
    currentTheme = themes[nextIdx];
    localStorage.setItem('theme', currentTheme);
    const isDark = currentTheme === 'dark' || (currentTheme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', isDark);
    applyThemeUI(currentTheme);
}

function applyThemeUI(theme) {
    const icons = ['iconMoon', 'iconSun', 'iconSystem'];
    icons.forEach(id => document.getElementById(id)?.classList.add('hidden'));
    if (theme === 'dark') document.getElementById('iconMoon')?.classList.remove('hidden');
    else if (theme === 'light') document.getElementById('iconSun')?.classList.remove('hidden');
    else document.getElementById('iconSystem')?.classList.remove('hidden');
}

let sysModalResolve = null;
function closeSystemModal(result) {
    const modal = document.getElementById('systemModal');
    if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
    if (sysModalResolve) { sysModalResolve(result); sysModalResolve = null; }
}
window.closeSystemModal = closeSystemModal;

function _showSystemModalBase(title, message, type = 'alert', placeholder = '') {
    return new Promise((resolve) => {
        sysModalResolve = resolve;
        const modal = document.getElementById('systemModal');
        if (!modal) { resolve(type === 'confirm' ? confirm(message) : prompt(message, placeholder)); return; }
        document.getElementById('sysModalTitle').innerText = title;
        document.getElementById('sysModalMessage').innerHTML = message.replace(/\n/g, '<br>');
        const input = document.getElementById('sysModalInput');
        const cancel = document.getElementById('sysModalCancel');
        input.classList.toggle('hidden', type !== 'prompt');
        cancel.classList.toggle('hidden', type === 'alert');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.getElementById('sysModalOk').onclick = () => closeSystemModal(type === 'prompt' ? input.value : true);
        cancel.onclick = () => closeSystemModal(type === 'prompt' ? null : false);
    });
}
window.showModalAlert = (m, t) => _showSystemModalBase(t || 'Alert', m, 'alert');
window.showModalConfirm = (m, t) => _showSystemModalBase(t || 'Confirm', m, 'confirm');
window.showModalPrompt = (m, t, p) => _showSystemModalBase(t || 'Prompt', m, 'prompt', p);