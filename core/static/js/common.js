// --- ИНИЦИАЛИЗАЦИЯ ПРИ ЗАГРУЗКЕ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

// Переменная для отслеживания времени последнего полученного уведомления
// Инициализируем текущим временем, чтобы не показывать старые уведомления при перезагрузке страницы
let latestNotificationTime = Math.floor(Date.now() / 1000);

document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    
    // Фикс флагов Windows
    if (typeof window.parsePageEmojis === 'function') { window.parsePageEmojis(); } else { parsePageEmojis(); }

    // Инициализация глобальных компонентов
    initNotifications(); 
    initHolidayMood(); 
    initAddNodeLogic();

    // Автозагрузка системных логов (если есть контейнер)
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

// --- ПЕРЕКЛЮЧАТЕЛЬ ЯЗЫКА ---
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

// --- КОПИРОВАНИЕ ТОКЕНА ---
function copyToken(el) {
    const tokenText = document.getElementById('modalToken').innerText;
    if (!tokenText || tokenText === '...') return;
    copyTextToClipboard(tokenText);
}

function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            showCopyFeedback();
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
            showCopyFeedback();
        } catch (err) {
            console.error('Fallback copy failed', err);
        }
        document.body.removeChild(textArea);
    }
}
window.copyTextToClipboard = copyTextToClipboard;

function showCopyFeedback() {
    if (window.showToast) window.showToast(typeof I18N !== 'undefined' ? I18N.web_copied : "Скопировано!");
}
window.copyToken = copyToken;

// --- ВСПЛЫВАЮЩИЕ УВЕДОМЛЕНИЯ (TOASTS) - НОВЫЙ ДИЗАЙН ---
let toastContainer = null;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        // Контейнер для тостов: фиксирован снизу справа, элементы складываются стопкой
        toastContainer.className = 'fixed bottom-5 right-5 z-[9999] flex flex-col items-end gap-3 pointer-events-none';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

function showToast(message) {
    const container = getToastContainer();
    
    // Создаем элемент тоста
    const toast = document.createElement('div');
    
    // Стили: Glassmorphism, тени, анимация появления снизу
    toast.className = 'pointer-events-auto flex items-start gap-3 p-4 rounded-2xl shadow-xl backdrop-blur-md border transition-all duration-500 ease-out transform translate-y-10 opacity-0 bg-white/90 dark:bg-gray-800/90 border-gray-200 dark:border-white/10 max-w-sm w-full sm:w-80';
    
    // Иконка
    const icon = `
    <div class="p-1.5 rounded-full bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
    </div>`;

    // Кнопка закрытия (крестик)
    const closeBtn = `
    <button onclick="this.closest('div').classList.add('opacity-0', 'translate-x-10'); setTimeout(() => this.closest('div').remove(), 300)" class="text-gray-400 hover:text-gray-600 dark:hover:text-white transition -mr-1 -mt-1 p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/10">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
    </button>`;

    toast.innerHTML = `
        ${icon}
        <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-900 dark:text-white leading-snug break-words">${message}</p>
        </div>
        ${closeBtn}
    `;
    
    container.appendChild(toast);
    
    // Запуск анимации появления
    requestAnimationFrame(() => {
        toast.classList.remove('translate-y-10', 'opacity-0');
    });

    // Автоматическое закрытие через 5 секунд
    const autoClose = setTimeout(() => {
        closeToast(toast);
    }, 5000);

    // Пауза при наведении
    toast.onmouseenter = () => clearTimeout(autoClose);
    toast.onmouseleave = () => {
        setTimeout(() => closeToast(toast), 2000);
    };
}

function closeToast(toastElement) {
    if (!toastElement) return;
    toastElement.classList.add('opacity-0', 'translate-x-10');
    setTimeout(() => {
        if (toastElement.parentElement) toastElement.remove();
    }, 500); 
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

// --- ЛОГИКА ДОБАВЛЕНИЯ НОДЫ ---
function initAddNodeLogic() {
    const input = document.getElementById('newNodeNameDash');
    if (input) {
        input.removeEventListener('input', validateNodeInput); 
        input.addEventListener('input', validateNodeInput);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !document.getElementById('btnAddNodeDash').disabled) {
                addNodeDash();
            }
        });
    }
}

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
window.openAddNodeModal = openAddNodeModal;

function closeAddNodeModal() {
    const modal = document.getElementById('addNodeModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
}
window.closeAddNodeModal = closeAddNodeModal;

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
            
            if (typeof NODES_DATA !== 'undefined') {
                NODES_DATA.push({token: data.token, name: name, ip: 'Unknown'});
            }
            if (typeof renderNodes === 'function') renderNodes(); 
            if (typeof fetchNodesList === 'function') fetchNodesList(); 
            
            nameInput.value = "";
            validateNodeInput();
        } else {
            await window.showModalAlert((typeof I18N !== 'undefined' ? I18N.web_error : "Error").replace('{error}', data.error), 'Ошибка');
        }
    } catch (e) {
        await window.showModalAlert((typeof I18N !== 'undefined' ? I18N.web_conn_error : "Connection Error").replace('{error}', e), 'Ошибка соединения');
    } finally {
        btn.innerText = originalText;
        validateNodeInput();
    }
}

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

// --- УВЕДОМЛЕНИЯ (КОЛОКОЛЬЧИК И TOASTS) ---
let lastUnreadCount = -1;
function initNotifications() {
    const btn = document.getElementById('notifBtn');
    if (!btn) return;
    
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener('click', toggleNotifications);
    
    const clearBtn = document.getElementById('notifClearBtn');
    if (clearBtn) {
        const newClearBtn = clearBtn.cloneNode(true);
        clearBtn.parentNode.replaceChild(newClearBtn, clearBtn);
        newClearBtn.addEventListener('click', clearNotifications);
    }

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
        
        // --- ЛОГИКА ОТОБРАЖЕНИЯ TOAST-УВЕДОМЛЕНИЙ ---
        if (data.notifications && data.notifications.length > 0) {
            let maxTime = latestNotificationTime;
            
            data.notifications.forEach(notif => {
                // Если уведомление пришло позже, чем последнее зафиксированное время
                if (notif.time > latestNotificationTime) {
                    showToast(notif.text);
                    if (notif.time > maxTime) maxTime = notif.time;
                }
            });
            
            latestNotificationTime = maxTime;
        }
        
        updateNotifUI(data.notifications, data.unread_count);
    } catch (e) {}
}

async function clearNotifications(e) {
    if (e) e.stopPropagation();
    
    const msg = (typeof I18N !== 'undefined' && I18N.web_clear_notif_confirm) ? I18N.web_clear_notif_confirm : "Очистить все уведомления?";
    const title = (typeof I18N !== 'undefined' && I18N.modal_title_confirm) ? I18N.modal_title_confirm : "Подтверждение";
    
    // Используем системное модальное окно в дизайне сайта
    // Элемент #systemModal присутствует на всех страницах (dashboard.html, settings.html)
    if (!await window.showModalConfirm(msg, title)) return;

    try { 
        const res = await fetch('/api/notifications/clear', { method: 'POST' }); 
        if (res.ok) {
            updateNotifUI([], 0); 
            // Показываем подтверждение через новый Toast
            if (window.showToast) window.showToast((typeof I18N !== 'undefined' && I18N.web_logs_cleared_alert) ? I18N.web_logs_cleared_alert : "Очищено!");
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
    
    const clearBtn = document.getElementById('notifClearBtn');
    if (clearBtn) {
        if (list.length > 0) clearBtn.classList.remove('hidden');
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
        // Fallback если модалки нет в DOM (маловероятно, так как она есть в шаблонах)
        if (!modal) { resolve(type === 'confirm' ? confirm(message) : prompt(message, placeholder)); return; }
        
        document.getElementById('sysModalTitle').innerText = title;
        const safeMessage = message ? String(message).replace(/\n/g, '<br>') : "";
        document.getElementById('sysModalMessage').innerHTML = safeMessage;
        
        const input = document.getElementById('sysModalInput');
        const cancel = document.getElementById('sysModalCancel');
        input.classList.toggle('hidden', type !== 'prompt');
        cancel.classList.toggle('hidden', type === 'alert');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        if (type === 'prompt') {
            input.value = placeholder;
            setTimeout(() => input.focus(), 50);
        }

        document.getElementById('sysModalOk').onclick = () => closeSystemModal(type === 'prompt' ? input.value : true);
        cancel.onclick = () => closeSystemModal(type === 'prompt' ? null : false);
        
        if (type === 'prompt') {
            input.onkeydown = (e) => { if(e.key === 'Enter') document.getElementById('sysModalOk').click(); };
        }
    });
}
window.showModalAlert = (m, t) => _showSystemModalBase(t || 'Alert', m, 'alert');
window.showModalConfirm = (m, t) => _showSystemModalBase(t || 'Confirm', m, 'confirm');
window.showModalPrompt = (m, t, p) => _showSystemModalBase(t || 'Prompt', m, 'prompt', p);