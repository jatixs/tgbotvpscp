/* /core/static/js/common.js */

const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';
let latestNotificationTime = Math.floor(Date.now() / 1000);
const pageCache = new Map();
let sseSource = null;

let connectionTimer = null;
let isSseConnected = false;

let modalCloseTimer = null;
let activeMobileModal = null;
let bodyScrollTop = 0;

function initGlobalLazyLoad() {
    if (window.innerWidth >= 1024) return;

    const observerOptions = {
        root: null,
        rootMargin: '0px',
        threshold: 0.1 // 10% видимости
    };

    const observer = new IntersectionObserver((entries, obs) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                obs.unobserve(entry.target);
            }
        });
    }, observerOptions);

    const blocks = document.querySelectorAll('.lazy-block');
    blocks.forEach(block => {
        observer.observe(block);
    });
}
document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    if (typeof window.parsePageEmojis === 'function') {
        window.parsePageEmojis();
    } else {
        parsePageEmojis();
    }
    initGlobalLazyLoad();
    initNotifications();
    initSSE();
    initSessionSync();
    initHolidayMood();
    initAddNodeLogic();
    if (document.getElementById('logsContainer')) {
        if (typeof window.switchLogType === 'function') {
            window.switchLogType('bot');
        }
    }
    pageCache.set(window.location.href, document.documentElement.outerHTML);
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

async function setLanguage(lang) {
    try {
        await fetch('/api/settings/language', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                lang: lang
            })
        });
        window.location.reload();
    } catch (e) {
        console.error(e);
    }
}
window.setLanguage = setLanguage;

function copyToken(el) {
    copyTextToClipboard(document.getElementById('modalToken').innerText);
}

function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(showCopyFeedback);
    } else {
        const t = document.createElement("textarea");
        t.value = text;
        t.style.position = "fixed";
        document.body.appendChild(t);
        t.focus();
        t.select();
        try {
            document.execCommand('copy');
            showCopyFeedback();
        } catch (e) {}
        document.body.removeChild(t);
    }
}
window.copyTextToClipboard = copyTextToClipboard;

function showCopyFeedback() {
    if (window.showToast) window.showToast((typeof I18N !== 'undefined' && I18N.web_copied) ? I18N.web_copied : "Copied!");
}
window.copyToken = copyToken;

let toastContainer = null;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'fixed bottom-4 right-4 z-[9999] flex flex-col items-end gap-2 pointer-events-none max-w-[calc(100vw-2rem)]';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

function showToast(message) {
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = 'pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-2xl shadow-xl backdrop-blur-md border transition-all duration-500 ease-out transform translate-y-10 opacity-0 bg-white/90 dark:bg-gray-800/90 border-gray-200 dark:border-white/10 w-auto max-w-sm';
    const icon = `<div class="p-1.5 rounded-full bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex-shrink-0"><svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg></div>`;
    const closeBtn = `<button onclick="closeToast(this.closest('div'))" class="text-gray-400 hover:text-gray-600 dark:hover:text-white transition p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 ml-1 flex-shrink-0"><svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg></button>`;
    toast.innerHTML = `${icon}<div class="flex-1 min-w-0"><p class="text-sm font-medium text-gray-900 dark:text-white leading-snug break-words">${message}</p></div>${closeBtn}`;
    container.appendChild(toast);
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            toast.classList.remove('translate-y-10', 'opacity-0');
        });
    });
    const autoClose = setTimeout(() => {
        closeToast(toast);
    }, 5000);
    toast.onmouseenter = () => clearTimeout(autoClose);
    toast.onmouseleave = () => {
        setTimeout(() => closeToast(toast), 2000);
    };
}

function closeToast(el) {
    if (!el) return;
    el.classList.add('opacity-0', 'translate-x-10');
    setTimeout(() => {
        if (el.parentElement) el.remove();
    }, 500);
}
window.showToast = showToast;
window.closeToast = closeToast;

function toggleHint(e, id) {
    if (e) e.stopPropagation();
    const el = document.getElementById(id);
    if (!el) return;

    const m = document.getElementById('genericHintModal');
    const c = document.getElementById('hintModalContent');

    if (m && c) {
        c.innerHTML = el.innerHTML;

        let titleEl = el.closest('.flex')?.querySelector('span, label, p, h3');
        if (!titleEl) {
            titleEl = el.parentElement?.parentElement?.querySelector('span, label, p, h3');
        }
        const defaultTitle = (typeof I18N !== 'undefined' && I18N.modal_title_info) ? I18N.modal_title_info : 'Info';
        document.getElementById('hintModalTitle').innerText = titleEl ? titleEl.innerText : defaultTitle;

        animateModalOpen(m, false);
    }
}

function closeHintModal() {
    const m = document.getElementById('genericHintModal');
    if (m) {
        animateModalClose(m);
    }
}
window.toggleHint = toggleHint;
window.closeHintModal = closeHintModal;

function initAddNodeLogic() {
    const i = document.getElementById('newNodeNameDash');
    if (i) {
        i.addEventListener('input', validateNodeInput);
        i.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !document.getElementById('btnAddNodeDash').disabled) addNodeDash();
        });
    }
}

function openAddNodeModal() {
    const m = document.getElementById('addNodeModal');
    if (m) {
        document.getElementById('nodeResultDash')?.classList.add('hidden');
        const i = document.getElementById('newNodeNameDash');
        if (i) {
            i.value = '';
            validateNodeInput();
        }
        animateModalOpen(m, true);
        if (i) setTimeout(() => i.focus(), 100);
    }
}

function closeAddNodeModal() {
    const m = document.getElementById('addNodeModal');
    if (m) {
        animateModalClose(m);
    }
}

function validateNodeInput() {
    const i = document.getElementById('newNodeNameDash');
    const b = document.getElementById('btnAddNodeDash');
    if (!i || !b) return;

    if (i.value.trim().length >= 2) {
        b.disabled = false;
        b.classList.remove('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
        b.classList.add('bg-purple-600', 'text-white', 'hover:bg-purple-700', 'shadow-lg');
    } else {
        b.disabled = true;
        b.classList.remove('bg-purple-600', 'text-white', 'hover:bg-purple-700', 'shadow-lg');
        b.classList.add('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
    }
}

window.openAddNodeModal = openAddNodeModal;
window.closeAddNodeModal = closeAddNodeModal;
window.validateNodeInput = validateNodeInput;
async function addNodeDash() {
    const i = document.getElementById('newNodeNameDash');
    const n = i.value.trim();
    if (!n) return;

    const btn = document.getElementById('btnAddNodeDash');
    const originalHTML = btn.innerHTML;

    if (btn) {
        btn.style.width = getComputedStyle(btn).width;
        btn.disabled = true;
        btn.innerHTML = `<svg class="animate-spin h-5 w-5 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    }

    try {
        const r = await fetch('/api/nodes/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: n
            })
        });
        const d = await r.json();
        if (r.ok) {
            document.getElementById('nodeResultDash').classList.remove('hidden');
            const tokenVal = (typeof decryptData === 'function') ? decryptData(d.token) : d.token;
            const cmdVal = (typeof decryptData === 'function') ? decryptData(d.command) : d.command;
            document.getElementById('newNodeTokenDash').innerText = tokenVal;
            document.getElementById('newNodeCmdDash').innerText = cmdVal;
            if (typeof NODES_DATA !== 'undefined') NODES_DATA.push({
                token: d.token,
                name: n,
                ip: 'Unknown'
            });
            if (typeof renderNodes === 'function') renderNodes();
            if (typeof fetchNodesList === 'function') fetchNodesList();
            i.value = '';
            validateNodeInput();
        } else {
            const errTxt = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : 'Error';
            window.showModalAlert(d.error, errTxt);
        }
    } catch (e) {
        const errTxt = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : 'Error';
        window.showModalAlert(e, errTxt);
    } finally {
        if (btn) {
            btn.innerHTML = originalHTML;
            btn.style.width = '';
            validateNodeInput();
        }
    }
}

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
    if (document.getElementById('holiday-lights')) return;
    const nav = document.querySelector('nav');
    if (!nav) return;
    let lights = document.createElement('ul');
    lights.id = 'holiday-lights';
    lights.className = 'lights-garland';
    const spacing = window.innerWidth < 640 ? 50 : 60;
    const count = Math.floor(window.innerWidth / spacing);
    for (let i = 0; i < count; i++) {
        lights.appendChild(document.createElement('li'));
    }
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
    if (newState) {
        startHolidayEffects();
        btn?.classList.add('holiday-btn-active');
    } else {
        stopHolidayEffects();
        btn?.classList.remove('holiday-btn-active');
    }
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
    if (!container) return;
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

function stopSnow() {
    clearInterval(snowInterval);
    snowInterval = null;
    if (document.getElementById('snow-container')) document.getElementById('snow-container').innerHTML = '';
}

function initSSE() {
    if (window.location.pathname === '/login' || window.location.pathname.startsWith('/reset_password')) return;

    if (sseSource) {
        sseSource.close();
    }

    isSseConnected = false;
    if (connectionTimer) clearTimeout(connectionTimer);

    const resetConnectionWatchdog = () => {
        if (connectionTimer) clearTimeout(connectionTimer);
        connectionTimer = setTimeout(() => {
            if (navigator.onLine) {
                const weakText = (typeof I18N !== 'undefined' && I18N.web_weak_conn) ? I18N.web_weak_conn : "Weak internet connection...";
                showToast(weakText);
            } else {
                handleConnectionError();
            }
        }, 15000);
    };

    resetConnectionWatchdog();

    sseSource = new EventSource('/api/events');

    sseSource.onopen = () => {
        isSseConnected = true;
        resetConnectionWatchdog();
        const errToast = document.getElementById('conn-error-toast');
        if (errToast) errToast.remove();
    };

    sseSource.addEventListener('agent_stats', () => {
        isSseConnected = true;
        resetConnectionWatchdog();
    });

    sseSource.addEventListener('notifications', (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.notifications && data.notifications.length > 0) {
                let maxTime = latestNotificationTime;
                data.notifications.forEach(notif => {
                    if (notif.time > latestNotificationTime) {
                        showToast(notif.text);
                        if (notif.time > maxTime) maxTime = notif.time;
                    }
                });
                latestNotificationTime = maxTime;
            }
            updateNotifUI(data.notifications, data.unread_count);
        } catch (err) {
            console.error("Error parsing notification event", err);
        }
    });

    sseSource.addEventListener('session_status', (e) => {
        if (e.data === 'expired') {
            handleSessionExpired();
        }
    });

    sseSource.addEventListener('shutdown', (e) => {
        sseSource.close();
        handleServerRestart();
    });

    sseSource.onerror = () => {
        if (isSseConnected) {
            handleConnectionError();
        }
    };

    window.sseSource = sseSource;
}

function initSessionSync() {
    if (window.location.pathname === '/login' || window.location.pathname.startsWith('/reset_password')) return;

    window.addEventListener('storage', (e) => {
        if (e.key === 'session_status' && e.newValue && e.newValue.startsWith('logged_out')) {
            handleSessionExpired();
        }
    });


    const logoutForms = document.querySelectorAll('form[action="/logout"]');
    logoutForms.forEach(form => {
        form.addEventListener('submit', () => {
            localStorage.setItem('session_status', 'logged_out_' + Date.now());
        });
    });
}

function checkSessionStatus() {
    if (document.getElementById('session-expired-overlay')) return;

    fetch('/api/settings/language', {
            method: 'HEAD',
            cache: 'no-store'
        })
        .then(res => {
            if (res.status === 401 || res.status === 403) {
                handleSessionExpired();
            }
        })
        .catch(() => {});
}

let lastUnreadCount = -1;

function initNotifications() {
    if (window.location.pathname === '/login' || window.location.pathname.startsWith('/reset_password')) return;

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
}

function handleSessionExpired() {
    if (document.getElementById('session-expired-overlay')) return;

    if (window.sseSource) {
        window.sseSource.close();
        window.sseSource = null;
    }

    const title = (typeof I18N !== 'undefined' && I18N.web_session_expired) ? I18N.web_session_expired : "Session expired";
    const msg = (typeof I18N !== 'undefined' && I18N.web_please_relogin) ? I18N.web_please_relogin : "Please login again";
    const btnText = (typeof I18N !== 'undefined' && I18N.web_login_btn) ? I18N.web_login_btn : "Login";

    const overlay = document.createElement('div');
    overlay.id = 'session-expired-overlay';
    overlay.className = 'fixed inset-0 z-[9999] bg-white/30 dark:bg-black/50 backdrop-blur-md flex items-center justify-center p-4 transition-opacity duration-300 opacity-0';

    overlay.innerHTML = `
        <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-8 max-w-sm w-full text-center border border-gray-200 dark:border-white/10 transform scale-95 transition-transform duration-300">
            <div class="mb-4 text-red-500 mx-auto bg-red-100 dark:bg-red-900/20 w-16 h-16 flex items-center justify-center rounded-full">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
            </div>
            <h3 class="text-xl font-bold text-gray-900 dark:text-white mb-2">${title}</h3>
            <p class="text-gray-500 dark:text-gray-400 mb-6 text-sm leading-relaxed">${msg}</p>
            <a href="/login" class="block w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-bold transition shadow-lg shadow-blue-500/20 active:scale-95">
                ${btnText}
            </a>
        </div>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    const modals = document.querySelectorAll('[id$="Modal"]');
    modals.forEach(m => m.classList.add('hidden'));

    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
        overlay.querySelector('div').classList.remove('scale-95');
        overlay.querySelector('div').classList.add('scale-100');
    });
}

function handleConnectionError() {
    if (document.getElementById('connection-error-overlay')) return;

    const msg = (typeof I18N !== 'undefined' && I18N.web_conn_problem) ? I18N.web_conn_problem : "Possible internet connection problems";
    const btnText = (typeof I18N !== 'undefined' && I18N.web_refresh_stream) ? I18N.web_refresh_stream : "Refresh";

    const toastContainer = getToastContainer();
    const existing = document.getElementById('conn-error-toast');
    if (existing) return;

    const toast = document.createElement('div');
    toast.id = 'conn-error-toast';
    toast.className = 'pointer-events-auto flex flex-col gap-2 px-4 py-3 rounded-2xl shadow-xl backdrop-blur-md border bg-red-50/90 dark:bg-red-900/90 border-red-200 dark:border-red-800 w-auto max-w-sm transition-all duration-300 transform translate-y-0 opacity-100 mb-2';

    toast.innerHTML = `
        <div class="flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-red-600 dark:text-red-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span class="text-sm font-bold text-red-900 dark:text-red-100">${msg}</span>
        </div>
        <button onclick="retrySSEStream()" class="w-full py-1.5 px-3 bg-red-200 hover:bg-red-300 dark:bg-red-800 dark:hover:bg-red-700 text-red-900 dark:text-red-100 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            ${btnText}
        </button>
    `;

    toastContainer.appendChild(toast);
}

function retrySSEStream() {
    const toast = document.getElementById('conn-error-toast');
    if (toast) toast.remove();

    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }

    initSSE();

    setTimeout(() => {
        if (!isSseConnected) {
            handleFatalConnectionError();
        }
    }, 5000);
}

function handleFatalConnectionError() {
    if (document.getElementById('fatal-error-overlay')) return;

    const msg = (typeof I18N !== 'undefined' && I18N.web_fatal_conn) ? I18N.web_fatal_conn : "Internet connection problems...";
    const reloadMsg = (typeof I18N !== 'undefined' && I18N.web_reloading_page) ? I18N.web_reloading_page : "Reloading page...";

    createBlurOverlay('fatal-error-overlay', `
        <div class="text-red-500 mb-4 animate-bounce">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.167-9.238m7.824 2.167a1 1 0 111.414 1.414m-1.414-1.414L3 3m8.293 8.293l1.414 1.414" />
            </svg>
        </div>
        <h2 class="text-xl font-bold text-gray-900 dark:text-white mb-2">${msg}</h2>
        <p class="text-gray-500 dark:text-gray-400 text-sm">${reloadMsg}</p>
    `);

    setTimeout(() => {
        window.location.reload();
    }, 5000);
}

function handleServerRestart() {
    if (document.getElementById('server-restart-overlay')) return;

    const msg = (typeof I18N !== 'undefined' && I18N.web_server_rebooting) ? I18N.web_server_rebooting : "Server/bot went into reboot.";

    createBlurOverlay('server-restart-overlay', `
        <div class="text-blue-500 mb-4 animate-spin">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
        </div>
        <h2 class="text-xl font-bold text-gray-900 dark:text-white">${msg}</h2>
    `);

    const checkServer = () => {
        fetch('/api/settings/language', {
                method: 'HEAD',
                cache: 'no-store'
            })
            .then(res => {
                if (res.status === 200 || res.status === 401 || res.status === 403) {
                    window.location.reload();
                } else {
                    setTimeout(checkServer, 2000);
                }
            })
            .catch(() => {
                setTimeout(checkServer, 2000);
            });
    };

    setTimeout(checkServer, 3000);
}

function createBlurOverlay(id, content) {
    const overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'fixed inset-0 z-[10000] bg-white/60 dark:bg-gray-900/80 backdrop-blur-lg flex items-center justify-center p-4 transition-opacity duration-500 opacity-0';
    overlay.innerHTML = `<div class="text-center">${content}</div>`;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
    });
}

async function clearNotifications(e) {
    if (e) e.stopPropagation();

    // 1. Fallback text (English default)
    let msg = "Clear all notifications?";
    let title = "Confirmation";
    let successMsg = "Success";

    // 2. Try to get translated text from I18N
    if (typeof I18N !== 'undefined') {
        if (I18N.web_clear_notif_confirm) {
            msg = I18N.web_clear_notif_confirm;
        } else if (I18N.web_clear_notifications) {
            // Partial fallback: "Clear notifications" + "?"
            msg = I18N.web_clear_notifications + "?";
        }

        if (I18N.modal_title_confirm) {
            title = I18N.modal_title_confirm;
        }

        if (I18N.web_notifications_cleared) {
            successMsg = I18N.web_notifications_cleared;
        } else if (I18N.web_success) {
            successMsg = I18N.web_success;
        }
    }

    if (!await window.showModalConfirm(msg, title)) return;

    try {
        const res = await fetch('/api/notifications/clear', {
            method: 'POST'
        });

        if (res.ok) {
            updateNotifUI([], 0);
            if (window.showToast) window.showToast(successMsg);
        }
    } catch (e) {
        console.error("Clear notifications error:", e);

        let errorShort = "Error";
        if (typeof I18N !== 'undefined' && I18N.web_error_short) {
            errorShort = I18N.web_error_short;
        }

        if (window.showModalAlert) window.showModalAlert(String(e), errorShort);
    }
}
window.clearNotifications = clearNotifications;

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
        listContainer.innerHTML = `<div class="p-4 text-center text-gray-500 text-sm">${(typeof I18N !== 'undefined' ? I18N.web_no_notifications : "No notifications")}</div>`;
    } else {
        listContainer.innerHTML = list.map(n => `<div class="notif-item"><div class="text-sm text-gray-800 dark:text-gray-200 leading-snug">${n.text}</div><div class="notif-time">${new Date(n.time * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</div></div>`).join('');
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
            fetch('/api/notifications/read', {
                method: 'POST'
            }).then(() => badge.classList.add('hidden'));
        }
    }
}

function closeNotifications() {
    const d = document.getElementById('notifDropdown');
    if (d) {
        d.classList.remove('show');
        setTimeout(() => d.classList.add('hidden'), 200);
    }
}

function toggleTheme() {
    const n = (themes.indexOf(currentTheme) + 1) % themes.length;
    currentTheme = themes[n];
    localStorage.setItem('theme', currentTheme);
    applyThemeUI(currentTheme);
    document.documentElement.classList.toggle('dark', currentTheme === 'dark' || (currentTheme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches));

    window.dispatchEvent(new Event('themeChanged'));
}

function applyThemeUI(t) {
    ['iconMoon', 'iconSun', 'iconSystem'].forEach(id => document.getElementById(id)?.classList.add('hidden'));
    if (t === 'dark') document.getElementById('iconMoon')?.classList.remove('hidden');
    else if (t === 'light') document.getElementById('iconSun')?.classList.remove('hidden');
    else document.getElementById('iconSystem')?.classList.remove('hidden');
}

function handleVisualViewportResize() {
    if (!activeMobileModal) return;
    const viewport = window.visualViewport;
    const keyboardHeight = window.innerHeight - viewport.height;
    activeMobileModal.style.height = '100dvh';
    activeMobileModal.style.paddingBottom = `${Math.max(0, keyboardHeight)}px`;
    activeMobileModal.style.top = '0';
}

function handleModalInputClick(e) {
    const el = e.target.closest('input, textarea, select');
    if (el) {
        el.scrollIntoView({
            behavior: 'smooth',
            block: 'center'
        });
    }
}

function animateModalOpen(modal, isInput = false) {
    if (!modal) return;

    if (modalCloseTimer) {
        clearTimeout(modalCloseTimer);
        modalCloseTimer = null;
    }

    const isMobile = window.innerWidth < 640;
    const card = modal.firstElementChild;

    if (isMobile) {
        bodyScrollTop = window.scrollY;
        document.body.style.position = 'fixed';
        document.body.style.top = `-${bodyScrollTop}px`;
        document.body.style.width = '100%';
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = 'hidden';
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');

    modal.style.height = '';
    modal.style.top = '';
    modal.style.paddingBottom = '';
    modal.style.transition = '';
    modal.style.willChange = '';

    if (isMobile && isInput) {
        activeMobileModal = modal;
        modal.style.willChange = 'padding-bottom';
        modal.style.transition = 'padding-bottom 0.3s cubic-bezier(0.2, 0, 0, 1)';

        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', handleVisualViewportResize);
            window.visualViewport.addEventListener('scroll', handleVisualViewportResize);
            handleVisualViewportResize();
        } else {
            modal.style.height = '100dvh';
        }

        modal.addEventListener('click', handleModalInputClick);
        modal.classList.add('items-center', 'overflow-y-auto');
        modal.classList.remove('items-start', 'pt-4', 'pt-20');

        if (card) {
            card.classList.add('my-auto');
            card.style.marginBottom = 'auto';
        }

    } else {
        if (activeMobileModal === modal) {
            if (window.visualViewport) {
                window.visualViewport.removeEventListener('resize', handleVisualViewportResize);
                window.visualViewport.removeEventListener('scroll', handleVisualViewportResize);
            }
            activeMobileModal = null;
        }

        modal.classList.add('items-center');
        modal.classList.remove('items-start', 'pt-4', 'pt-20', 'overflow-y-auto');

        if (card) {
            card.classList.add('my-auto');
            card.style.marginBottom = '';
        }

        if (isMobile) {
            modal.style.height = '100dvh';
        } else {
            modal.style.height = '';
        }
    }

    if (card) {
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                card.style.opacity = '1';
                card.style.transform = 'scale(1)';
            });
        });
    }
}

function animateModalClose(modal) {
    if (!modal) return;
    const card = modal.firstElementChild;
    if (card) {
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
    }

    if (activeMobileModal === modal && window.visualViewport) {
        window.visualViewport.removeEventListener('resize', handleVisualViewportResize);
        window.visualViewport.removeEventListener('scroll', handleVisualViewportResize);
        activeMobileModal = null;
    }

    modal.removeEventListener('click', handleModalInputClick);

    modalCloseTimer = setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');

        if (document.body.style.position === 'fixed') {
            document.body.style.position = '';
            document.body.style.top = '';
            document.body.style.width = '';
            document.body.style.overflow = '';
            window.scrollTo(0, bodyScrollTop);
        } else {
            document.body.style.overflow = '';
        }

        modal.style.height = '';
        modal.style.top = '';
        modal.style.paddingBottom = '';
        modal.style.transition = '';
        modal.style.willChange = '';

        modal.classList.remove('items-start', 'pt-4', 'overflow-y-auto');
        modal.classList.add('items-center');

        if (card) {
            card.classList.add('my-auto');
            card.style.marginBottom = '';
        }
        modalCloseTimer = null;
    }, 200);
}

let sysModalResolve = null;

function closeSystemModal(result) {
    const modal = document.getElementById('systemModal');
    animateModalClose(modal);
    if (sysModalResolve) {
        sysModalResolve(result);
        sysModalResolve = null;
    }
}
window.closeSystemModal = closeSystemModal;

function _showSystemModalBase(title, message, type = 'alert', placeholder = '', inputType = 'text') {
    return new Promise((resolve) => {
        sysModalResolve = resolve;
        const modal = document.getElementById('systemModal');
        if (!modal) {
            resolve(type === 'confirm' ? confirm(message) : prompt(message, placeholder));
            return;
        }

        if (typeof I18N !== 'undefined') {
            const btnCancel = document.getElementById('sysModalCancel');
            const btnOk = document.getElementById('sysModalOk');
            if (btnCancel && I18N.modal_btn_cancel) btnCancel.innerText = I18N.modal_btn_cancel;
            if (btnOk && I18N.modal_btn_ok) btnOk.innerText = I18N.modal_btn_ok;
        }

        const t = (typeof I18N !== 'undefined' && I18N['modal_title_' + type]) ? I18N['modal_title_' + type] : (title || 'Alert');
        document.getElementById('sysModalTitle').innerText = t;
        document.getElementById('sysModalMessage').innerHTML = message ? String(message).replace(/\n/g, '<br>') : "";

        const input = document.getElementById('sysModalInput');
        const cancel = document.getElementById('sysModalCancel');
        input.classList.toggle('hidden', type !== 'prompt');
        cancel.classList.toggle('hidden', type === 'alert');

        animateModalOpen(modal, type === 'prompt');

        if (type === 'prompt') {
            input.value = '';
            input.placeholder = placeholder;

            if (inputType === 'number') {
                input.type = 'number';
                input.inputMode = 'numeric';
                input.pattern = '[0-9]*';
            } else {
                input.type = 'text';
                input.inputMode = 'text';
                input.removeAttribute('pattern');
            }

            setTimeout(() => input.focus(), 100);
            input.onkeydown = (e) => {
                if (e.key === 'Enter') document.getElementById('sysModalOk').click();
            };
        }

        document.getElementById('sysModalOk').onclick = () => closeSystemModal(type === 'prompt' ? input.value : true);
        cancel.onclick = () => closeSystemModal(type === 'prompt' ? null : false);
    });
}
window.showModalAlert = (m, t) => _showSystemModalBase(t || 'Alert', m, 'alert');
window.showModalConfirm = (m, t) => _showSystemModalBase(t || 'Confirm', m, 'confirm');
window.showModalPrompt = (m, t, p, it) => _showSystemModalBase(t || 'Prompt', m, 'prompt', p, it);

function prefetchUrl(url) {
    if (pageCache.has(url)) return;
    fetch(url).then(res => {
        if (res.ok) return res.text();
        throw new Error('err');
    }).then(text => {
        pageCache.set(url, text);
    }).catch(() => {});
}

document.addEventListener('mouseover', (e) => {
    const link = e.target.closest('a');
    if (shouldHandleLink(link)) prefetchUrl(link.href);
});

document.addEventListener('touchstart', (e) => {
    const link = e.target.closest('a');
    if (shouldHandleLink(link)) prefetchUrl(link.href);
}, {
    passive: true
});

function shouldHandleLink(link) {
    return link &&
        link.href.startsWith(window.location.origin) &&
        link.target !== '_blank' &&
        !link.hasAttribute('download') &&
        link.getAttribute('href') !== '/logout' &&
        link.href !== window.location.href;
}

document.addEventListener('click', async (e) => {
    const link = e.target.closest('a');
    if (!shouldHandleLink(link)) return;

    e.preventDefault();
    const url = link.href;

    const progressBar = document.createElement('div');
    progressBar.className = 'fixed top-0 left-0 h-1 bg-blue-500 z-[9999] transition-all duration-300 ease-out';
    progressBar.style.width = '0%';
    document.body.appendChild(progressBar);
    requestAnimationFrame(() => progressBar.style.width = '40%');

    try {
        let htmlContent;
        if (pageCache.has(url)) {
            htmlContent = pageCache.get(url);
            progressBar.style.width = '100%';
        } else {
            const response = await fetch(url);
            if (!response.ok) throw new Error('Network error');
            htmlContent = await response.text();
            pageCache.set(url, htmlContent);
        }

        const parser = new DOMParser();
        const doc = parser.parseFromString(htmlContent, 'text/html');

        const newMain = doc.querySelector('main');
        const newNav = doc.querySelector('nav');
        const currentMain = document.querySelector('main');
        const currentNav = document.querySelector('nav');

        if (newMain && currentMain && newNav && currentNav) {
            document.title = doc.title;

            const elementsToFade = [currentNav, currentMain];
            elementsToFade.forEach(el => {
                el.style.transition = 'opacity 0.2s ease-out, transform 0.2s ease-out';
                el.style.opacity = '0';
                el.style.transform = 'translateY(10px)';
            });

            setTimeout(() => {
                currentMain.innerHTML = newMain.innerHTML;
                currentMain.className = newMain.className;
                currentNav.innerHTML = newNav.innerHTML;
                currentNav.className = newNav.className;

                const scripts = doc.querySelectorAll('script');
                scripts.forEach(s => {
                    const content = s.innerText || s.textContent;
                    if (content && (
                            content.includes('const I18N') ||
                            content.includes('const USERS_DATA') ||
                            content.includes('const NODES_DATA') ||
                            content.includes('const KEYBOARD_CONFIG') ||
                            content.includes('const USER_ROLE')
                        )) {
                        try {
                            const patched = content
                                .replace(/const\s+I18N\s*=/g, 'window.I18N =')
                                .replace(/const\s+USERS_DATA\s*=/g, 'window.USERS_DATA =')
                                .replace(/const\s+NODES_DATA\s*=/g, 'window.NODES_DATA =')
                                .replace(/const\s+KEYBOARD_CONFIG\s*=/g, 'window.KEYBOARD_CONFIG =')
                                .replace(/const\s+USER_ROLE\s*=/g, 'window.USER_ROLE =');
                            (1, eval)(patched);
                        } catch (err) {
                            console.error("Error evaluating injected script:", err);
                        }
                    }
                });

                window.scrollTo(0, 0);
                window.history.pushState({}, '', url);

                requestAnimationFrame(() => {
                    elementsToFade.forEach(el => {
                        el.style.opacity = '1';
                        el.style.transform = 'translateY(0)';
                    });
                });

                try {
                    if (typeof parsePageEmojis === 'function') parsePageEmojis();
                } catch (e) {}
                initHolidayMood();
                initGlobalLazyLoad();

                try {
                    if (url.includes('/settings')) {
                        if (window.initSettings) window.initSettings();
                        else window.location.reload();
                    } else if (url.endsWith('/') || url.includes('/dashboard')) {
                        if (window.initDashboard) window.initDashboard();
                        else window.location.reload();
                    }
                    initNotifications();
                } catch (e) {
                    window.location.reload();
                }

                setTimeout(() => progressBar.remove(), 200);
            }, 200);
        } else {
            window.location.href = url;
        }
    } catch (error) {
        console.error("SPA Error:", error);
        window.location.href = url;
    }
});

window.addEventListener('popstate', async () => {
    window.location.reload();
});

window.animateModalOpen = animateModalOpen;
window.animateModalClose = animateModalClose;

async function clearLogs() {
    if (!await window.showModalConfirm(I18N.web_clear_logs_confirm, I18N.modal_title_confirm)) return;

    const btn = document.getElementById('clearLogsBtn');
    const originalHTML = btn.innerHTML;
    const redClasses = ['bg-red-50', 'dark:bg-red-900/10', 'border-red-200', 'dark:border-red-800', 'text-red-600', 'dark:text-red-400', 'hover:bg-red-100', 'dark:hover:bg-red-900/30', 'active:bg-red-200'];
    const greenClasses = ['bg-green-600', 'text-white', 'border-transparent', 'hover:bg-green-500', 'px-3', 'py-2'];

    // Classes that cause hover expansion
    const hoverClasses = ['hover:pr-4', 'group'];

    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${I18N.web_logs_clearing}`;

    try {
        const res = await fetch('/api/logs/clear', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                type: 'all'
            })
        });
        if (res.ok) {
            btn.classList.remove(...redClasses);
            btn.classList.remove(...hoverClasses);
            btn.classList.add(...greenClasses);
            const doneText = (typeof I18N !== 'undefined' && I18N.web_logs_cleared_alert) ? I18N.web_logs_cleared_alert : "Cleared!";
            btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> <span class="font-bold text-xs uppercase ml-1">${doneText}</span>`;

            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.classList.remove(...greenClasses);
                btn.classList.add(...redClasses);
                btn.classList.add(...hoverClasses);
                btn.disabled = false;
            }, 2000);
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error || "Failed"), errorShort);
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}

async function resetTrafficSettings() {
    if (!await window.showModalConfirm(I18N.web_traffic_reset_confirm || "Are you sure? This will zero out the counters.", I18N.modal_title_confirm)) return;

    const btn = document.getElementById('resetTrafficBtn');
    const originalHTML = btn.innerHTML;

    const redClasses = ['bg-red-50', 'dark:bg-red-900/10', 'border-red-200', 'dark:border-red-800', 'text-red-600', 'dark:text-red-400', 'hover:bg-red-100', 'dark:hover:bg-red-900/30', 'active:bg-red-200'];
    const greenClasses = ['bg-green-600', 'text-white', 'border-transparent', 'hover:bg-green-500', 'px-3', 'py-2'];

    const hoverClasses = ['hover:pr-4', 'group'];

    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;

    try {
        const res = await fetch('/api/traffic/reset', {
            method: 'POST'
        });
        if (res.ok) {
            btn.classList.remove(...redClasses);
            btn.classList.remove(...hoverClasses);
            btn.classList.add(...greenClasses);
            const doneText = (typeof I18N !== 'undefined' && I18N.web_traffic_reset_no_emoji) ? I18N.web_traffic_reset_no_emoji : "Done!";
            btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> <span class="font-bold text-xs uppercase ml-1">${doneText}</span>`;

            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.classList.remove(...greenClasses);
                btn.classList.add(...redClasses);
                btn.classList.add(...hoverClasses);
                btn.disabled = false;
            }, 2000);
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error || "Failed"), errorShort);
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}
