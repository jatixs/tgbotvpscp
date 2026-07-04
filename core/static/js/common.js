/* /core/static/js/common.js */

// Global Event Delegation setup
document.addEventListener('click', e => {
    const actionEl = e.target.closest('[data-action]');
    if (!actionEl) return;
    const action = actionEl.getAttribute('data-action');
    const event = new CustomEvent(`app:action:${action}`, { bubbles: true, detail: { target: actionEl, originalEvent: e } });
    actionEl.dispatchEvent(event);
});

document.addEventListener('change', e => {
    const actionEl = e.target.closest('[data-action]');
    if (!actionEl) return;
    const action = actionEl.getAttribute('data-action');
    const event = new CustomEvent(`app:change:${action}`, { bubbles: true, detail: { target: actionEl, originalEvent: e } });
    actionEl.dispatchEvent(event);
});

document.addEventListener('keydown', e => {
    const actionEl = e.target.closest('[data-action]');
    if (!actionEl) return;
    const action = actionEl.getAttribute('data-action');
    const event = new CustomEvent(`app:action:${action}`, { bubbles: true, detail: { target: actionEl, originalEvent: e } });
    actionEl.dispatchEvent(event);
});

// Security: Safe HTML helpers
function getSecureRandom() {
    return window.crypto.getRandomValues(new Uint32Array(1))[0] / 4294967295;
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

function setSafeText(element, text) {
    if (!element) return;
    element.textContent = text;
}

function setSafeHTML(element, html) {
    if (!element) return;
    element.innerHTML = DOMPurify.sanitize(html);  // Only use with trusted HTML
}

window.__chartRegistry = window.__chartRegistry || {};

function ensureChartZoomRegistered() {
    if (typeof Chart === 'undefined' || window.__chartZoomRegistered) return;

    const candidates = [
        window.ChartZoom,
        window.chartjsPluginZoom,
        window['chartjs-plugin-zoom'],
        window.zoomPlugin
    ];

    for (const plugin of candidates) {
        if (!plugin) continue;
        try {
            Chart.register(plugin);
            window.__chartZoomRegistered = true;
            break;
        } catch (e) {
            console.debug('Chart zoom plugin registration skipped:', e);
        }
    }
}

function getChartResetLabel() {
    if (typeof I18N !== 'undefined') {
        return I18N.web_nodes_monitor_filter_reset || I18N.web_traffic_reset_no_emoji || 'Сбросить';
    }
    return 'Сбросить';
}

function getChartHintText() {
    return 'Колесо — масштаб, выделение мышью — увеличить область, Shift + перетаскивание — панорама, двойной клик — сброс';
}

function refreshChartZoomState(chart, canvasOrId) {
    if (!chart) return { isZoomed: false, freezeUpdates: false, atLiveEdge: true };

    const canvas = typeof canvasOrId === 'string' ? document.getElementById(canvasOrId) : (canvasOrId || chart.canvas);
    const state = chart.__liveZoomState = chart.__liveZoomState || {};
    const total = Array.isArray(chart.data?.labels) ? chart.data.labels.length : 0;
    const maxIndex = Math.max(0, total - 1);
    const xScale = chart.scales?.x;

    let min = 0;
    let max = maxIndex;

    if (xScale) {
        const rawMin = Number(xScale.min);
        const rawMax = Number(xScale.max);
        if (Number.isFinite(rawMin)) min = Math.max(0, Math.round(rawMin));
        if (Number.isFinite(rawMax)) max = Math.min(maxIndex, Math.round(rawMax));
    }

    const hasZoom = total > 1 && (min > 0 || max < maxIndex);
    const atLiveEdge = total <= 1 || max >= (maxIndex - 1);
    const visibleRange = Math.max(1, max - min);

    if (!state.liveRangeSize || !state.freezeUpdates) {
        state.liveRangeSize = visibleRange;
    }

    state.isZoomed = hasZoom;
    state.atLiveEdge = atLiveEdge;
    state.freezeUpdates = hasZoom && !atLiveEdge;

    const wrapper = canvas?.parentElement;
    const resetBtn = wrapper?.querySelector('.chart-reset-zoom-btn');
    if (resetBtn) {
        resetBtn.textContent = getChartResetLabel();
        resetBtn.title = getChartResetLabel();
        resetBtn.classList.toggle('hidden', !hasZoom);
    }

    return state;
}
window.refreshChartZoomState = refreshChartZoomState;

function alignChartToLiveWindow(chart) {
    if (!chart?.options?.scales?.x) return;

    const total = Array.isArray(chart.data?.labels) ? chart.data.labels.length : 0;
    if (total <= 1) return;

    const state = chart.__liveZoomState = chart.__liveZoomState || {};
    const maxIndex = total - 1;
    const liveRangeSize = Math.max(1, Math.min(maxIndex, state.liveRangeSize || maxIndex));

    chart.options.scales.x.min = Math.max(0, maxIndex - liveRangeSize);
    chart.options.scales.x.max = maxIndex;
    state.freezeUpdates = false;
    state.atLiveEdge = true;
}
window.alignChartToLiveWindow = alignChartToLiveWindow;

function updateChartWithLiveData(chart, applyData, canvasOrId) {
    if (!chart || typeof applyData !== 'function') return false;

    const state = chart.__liveZoomState = chart.__liveZoomState || {};
    state.pendingUpdate = applyData;

    refreshChartZoomState(chart, canvasOrId);
    if (state.freezeUpdates) {
        return false;
    }

    applyData();
    alignChartToLiveWindow(chart);
    chart.update('none');
    refreshChartZoomState(chart, canvasOrId);
    return true;
}
window.updateChartWithLiveData = updateChartWithLiveData;

function buildInteractiveChartOptions(baseOptions = {}) {
    ensureChartZoomRegistered();

    return {
        ...baseOptions,
        plugins: {
            ...(baseOptions.plugins || {}),
            zoom: {
                pan: {
                    enabled: true,
                    mode: 'x',
                    modifierKey: 'shift',
                    onPanComplete: ({ chart }) => {
                        window.refreshChartZoomState?.(chart);
                    }
                },
                zoom: {
                    wheel: { enabled: true },
                    pinch: { enabled: true },
                    drag: {
                        enabled: true,
                        backgroundColor: 'rgba(59, 130, 246, 0.10)',
                        borderColor: 'rgba(59, 130, 246, 0.45)',
                        borderWidth: 1
                    },
                    mode: 'x',
                    onZoomComplete: ({ chart }) => {
                        window.refreshChartZoomState?.(chart);
                    }
                },
                limits: {
                    x: { min: 'original', max: 'original', minRange: 2 },
                    y: { min: 'original', max: 'original' }
                }
            }
        }
    };
}
window.buildInteractiveChartOptions = buildInteractiveChartOptions;

function attachChartInteractions(chart, canvasOrId) {
    if (!chart) return;

    const canvas = typeof canvasOrId === 'string' ? document.getElementById(canvasOrId) : canvasOrId;
    if (!canvas) return;

    ensureChartZoomRegistered();

    if (canvas.id) {
        window.__chartRegistry[canvas.id] = chart;
    }

    canvas.title = getChartHintText();

    const applyPendingAndReset = () => {
        const activeChart = canvas.id ? window.__chartRegistry[canvas.id] : chart;
        if (!activeChart) return;

        if (typeof activeChart.resetZoom === 'function') {
            activeChart.resetZoom();
        }

        const state = activeChart.__liveZoomState = activeChart.__liveZoomState || {};
        state.freezeUpdates = false;

        if (typeof state.pendingUpdate === 'function') {
            state.pendingUpdate();
        }

        window.alignChartToLiveWindow?.(activeChart);
        activeChart.update('none');
        window.refreshChartZoomState?.(activeChart, canvas);
    };

    if (!canvas.dataset.zoomResetBound) {
        canvas.addEventListener('dblclick', () => {
            applyPendingAndReset();
        });

        ['wheel', 'mouseup', 'touchend'].forEach(eventName => {
            canvas.addEventListener(eventName, () => {
                setTimeout(() => {
                    const activeChart = canvas.id ? window.__chartRegistry[canvas.id] : chart;
                    window.refreshChartZoomState?.(activeChart, canvas);
                }, 60);
            }, { passive: true });
        });

        canvas.dataset.zoomResetBound = 'true';
    }

    const wrapper = canvas.parentElement;
    if (wrapper) {
        if (!wrapper.classList.contains('relative')) {
            wrapper.classList.add('relative');
        }

        let resetBtn = wrapper.querySelector('.chart-reset-zoom-btn');
        if (!resetBtn) {
            resetBtn = document.createElement('button');
            resetBtn.type = 'button';
            resetBtn.className = 'chart-reset-zoom-btn hidden absolute top-2 left-2 z-10 px-2 py-1 rounded-md text-[10px] font-bold bg-white/90 dark:bg-gray-900/90 text-blue-600 dark:text-blue-400 border border-blue-500/20 shadow-sm hover:bg-blue-50 dark:hover:bg-blue-500/10 transition';
            resetBtn.textContent = getChartResetLabel();
            resetBtn.title = getChartResetLabel();
            resetBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                applyPendingAndReset();
            });
            wrapper.appendChild(resetBtn);
        }
    }

    refreshChartZoomState(chart, canvas);
}
window.attachChartInteractions = attachChartInteractions;

function getCookieValue(name) {
    const prefix = `${name}=`;
    const cookie = document.cookie
        .split(';')
        .map(part => part.trim())
        .find(part => part.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : '';
}

function getCsrfToken() {
    return getCookieValue('csrf_token');
}

(function patchFetchWithCsrf() {
    if (typeof window.fetch !== 'function' || window.__csrfFetchPatched) return;

    const originalFetch = window.fetch.bind(window);
    window.fetch = function(resource, options = {}) {
        const requestUrl = typeof resource === 'string' ? resource : (resource && resource.url) ? resource.url : '';
        const method = String(options.method || (resource && resource.method) || 'GET').toUpperCase();
        const isMutating = ['POST', 'PUT', 'DELETE'].includes(method);

        if (isMutating && requestUrl) {
            let url = null;
            try {
                url = new URL(requestUrl, window.location.origin);
            } catch (e) {
                url = null;
            }

            if (url && url.origin === window.location.origin && url.pathname.startsWith('/api/')) {
                const headers = new Headers(options.headers || (resource instanceof Request ? resource.headers : undefined));
                const csrfToken = getCsrfToken();
                if (csrfToken && !headers.has('X-CSRF-Token')) {
                    headers.set('X-CSRF-Token', csrfToken);
                }
                options = { ...options, headers };
                if (!options.credentials) {
                    options.credentials = 'same-origin';
                }
            }
        }

        return originalFetch(resource, options);
    };

    window.__csrfFetchPatched = true;
})();

(function patchResponseJson() {
    if (typeof Response === 'undefined' || window.__jsonParsePatched) return;
    const originalJson = Response.prototype.json;
    Response.prototype.json = async function() {
        try {
            return await originalJson.call(this);
        } catch (e) {
            if (e instanceof SyntaxError && e.message.includes("Unexpected token")) {
                const friendlyMessage = (typeof I18N !== 'undefined' && I18N.web_json_parse_error) ? I18N.web_json_parse_error : "Ошибка сервера: неверный формат ответа (возможно, сессия истекла или сервер недоступен).";
                const err = new Error(friendlyMessage);
                err.original = e;
                throw err;
            }
            throw e;
        }
    };
    window.__jsonParsePatched = true;
})();

const themes = ['dark', 'light', 'system', 'amoled'];
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

    const blocks = document.querySelectorAll('.lazy-block:not(.is-visible)');
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
    initHapticsToggle();
    initAddNodeLogic();
    initBrandEasterEgg();
    if (document.getElementById('logsContainer')) {
        if (typeof window.switchLogType === 'function') {
            window.switchLogType('bot');
        }
    }

    // Unlock Vibration API on first interaction
    const unlockHaptics = () => {
        try { if (navigator.vibrate) navigator.vibrate(0); } catch (e) {}
        document.body.removeEventListener('touchstart', unlockHaptics);
        document.body.removeEventListener('click', unlockHaptics);
    };
    document.body.addEventListener('touchstart', unlockHaptics, { once: true, passive: true });
    document.body.addEventListener('click', unlockHaptics, { once: true, passive: true });

    window.playHaptic = function(pattern) {
        if (navigator.vibrate && localStorage.getItem('haptics_enabled') !== 'false') {
            navigator.vibrate(pattern);
        }
    };

    document.body.addEventListener('input', (e) => {
        if (e.target && e.target.tagName === 'INPUT' && e.target.type === 'range') {
            playHaptic(5);
        }
    });

    document.body.addEventListener('change', (e) => {
        if (e.target && e.target.tagName === 'INPUT' && (e.target.type === 'checkbox' || e.target.type === 'radio')) {
            if (e.target.checked) {
                playHaptic([10, 30, 10]); 
            } else {
                playHaptic(10); 
            }
        }
    });

    pageCache.set(window.location.href, document.documentElement.outerHTML);
});

function initHapticsToggle() {
    updateHapticsUI();
}

function toggleHaptics() {
    const currentState = localStorage.getItem('haptics_enabled') !== 'false';
    localStorage.setItem('haptics_enabled', currentState ? 'false' : 'true');
    updateHapticsUI();
    if (!currentState) {
        if (navigator.vibrate) navigator.vibrate([10, 30, 10]);
        const msgOn = (typeof I18N !== 'undefined' && I18N.web_haptics_on) ? I18N.web_haptics_on : "Haptics: ON";
        if (window.showToast) window.showToast(msgOn);
    } else {
        const msgOff = (typeof I18N !== 'undefined' && I18N.web_haptics_off) ? I18N.web_haptics_off : "Haptics: OFF";
        if (window.showToast) window.showToast(msgOff);
    }
}

function updateHapticsUI() {
    const isEnabled = localStorage.getItem('haptics_enabled') !== 'false';
    
    // Новый стиль: checkbox peer-checked
    const checkbox = document.getElementById('mHapticsCheckbox');
    if (checkbox) {
        checkbox.checked = isEnabled;
    }
    
    // Обратная совместимость со старым стилем (если есть)
    const track = document.getElementById('mHapticsTrack');
    const thumb = document.getElementById('mHapticsThumb');
    if (track && thumb) {
        if (isEnabled) {
            track.classList.replace('bg-gray-200', 'bg-green-500');
            track.classList.replace('dark:bg-gray-700', 'dark:bg-green-500');
            thumb.style.transform = 'translateX(20px)';
        } else {
            track.classList.replace('bg-green-500', 'bg-gray-200');
            track.classList.replace('dark:bg-green-500', 'dark:bg-gray-700');
            thumb.style.transform = 'translateX(0px)';
        }
    }

    const statusText = document.getElementById('mobileHapticsStatus');
    if (statusText) {
        statusText.innerText = isEnabled ? 'Вкл' : 'Выкл';
        statusText.className = isEnabled ? 'text-xs font-bold uppercase text-green-500' : 'text-xs font-bold uppercase text-gray-500';
    }
}

function parsePageEmojis(element) {
    if (window.twemoji) {
        window.twemoji.parse(element || document.body, {
            callback: function(icon, options, variant) {
                if (icon.length === 11 && /^1f1[e-f][0-9a-f]-1f1[e-f][0-9a-f]$/.test(icon)) {
                    const code1 = parseInt(icon.substring(0, 5), 16);
                    const code2 = parseInt(icon.substring(6, 11), 16);
                    const char1 = String.fromCharCode(code1 - 0x1f1e6 + 97);
                    const char2 = String.fromCharCode(code2 - 0x1f1e6 + 97);
                    return 'https://flagcdn.com/' + char1 + char2 + '.svg';
                }
                return ''.concat(options.base, options.folder, '/', icon, options.ext);
            },
            attributes: function(icon, variant) {
                if (icon.length === 11 && /^1f1[e-f][0-9a-f]-1f1[e-f][0-9a-f]$/.test(icon)) {
                    return {
                        class: 'emoji flagcdn',
                        style: 'width: 1.4em; height: 1em; object-fit: cover; border-radius: 2px; display: inline-block; vertical-align: middle; box-shadow: 0 1px 2px rgba(0,0,0,0.1)'
                    };
                }
            },
            folder: 'svg',
            ext: '.svg',
            base: 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/'
        });
    }
}

function replaceEmojisWithFlagsHTML(text) {
    if (!text) return text;
    const regex = /([\uD83C][\uDDE6-\uDDFF]){2}/g;
    return text.replace(regex, function(match) {
        const code1 = match.codePointAt(0);
        const code2 = match.codePointAt(2);
        const char1 = String.fromCharCode(code1 - 0x1F1E6 + 97);
        const char2 = String.fromCharCode(code2 - 0x1F1E6 + 97);
        return `<img src="https://flagcdn.com/${char1}${char2}.svg" class="emoji flagcdn" style="width: 1.4em; height: 1em; object-fit: cover; border-radius: 2px; display: inline-block; vertical-align: middle; box-shadow: 0 1px 2px rgba(0,0,0,0.1)" alt="${match}" />`;
    });
}

function updateDOM(oldNode, newNode) {
    if (!oldNode || !newNode) return false;
    if (oldNode.nodeType !== newNode.nodeType) return false;
    if (oldNode.nodeType === 3) { // Node.TEXT_NODE
        if (oldNode.textContent !== newNode.textContent) oldNode.textContent = newNode.textContent;
        return true;
    }
    if (oldNode.nodeName !== newNode.nodeName) return false;
    
    if (newNode.attributes) {
        for (let i = 0; i < newNode.attributes.length; i++) {
            const attr = newNode.attributes[i];
            if (oldNode.getAttribute(attr.name) !== attr.value) {
                oldNode.setAttribute(attr.name, attr.value);
            }
        }
    }
    if (oldNode.attributes) {
        for (let i = oldNode.attributes.length - 1; i >= 0; i--) {
            const attr = oldNode.attributes[i];
            if (!newNode.hasAttribute(attr.name)) {
                oldNode.removeAttribute(attr.name);
            }
        }
    }
    
    if (oldNode.nodeName === 'INPUT' && (oldNode.type === 'checkbox' || oldNode.type === 'radio')) {
        if (oldNode.checked !== newNode.hasAttribute('checked')) {
            oldNode.checked = newNode.hasAttribute('checked');
        }
    }
    
    if (oldNode.childNodes.length !== newNode.childNodes.length) return false;
    for (let i = 0; i < oldNode.childNodes.length; i++) {
        if (!updateDOM(oldNode.childNodes[i], newNode.childNodes[i])) return false;
    }
    return true;
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
        } catch (e) { }
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
    const closeBtn = `<button data-action="close-toast" class="text-gray-400 hover:text-gray-600 dark:hover:text-white transition p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 ml-1 flex-shrink-0"><svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg></button>`;
    toast.innerHTML = DOMPurify.sanitize(`${icon}<div class="flex-1 min-w-0"><p class="text-sm font-medium text-gray-900 dark:text-white leading-snug break-words">${message}</p></div>${closeBtn}`);
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

document.addEventListener('app:action:close-toast', e => {
    closeToast(e.detail.target.closest('div'));
});

function launchBrandEasterEgg() {
    const overlay = document.createElement('div');
    overlay.className = 'pointer-events-none fixed inset-0 z-[9998] overflow-hidden';
    document.body.appendChild(overlay);

    const glyphs = ['✨', '🚀', '🖥️', '⚡', '🌟'];
    for (let index = 0; index < 18; index += 1) {
        const sparkle = document.createElement('div');
        sparkle.textContent = glyphs[index % glyphs.length];
        sparkle.style.position = 'absolute';
        sparkle.style.left = `${8 + getSecureRandom() * 84}%`;
        sparkle.style.top = `${10 + getSecureRandom() * 22}%`;
        sparkle.style.fontSize = `${16 + getSecureRandom() * 16}px`;
        sparkle.style.opacity = '0';
        sparkle.style.transform = 'translateY(8px) scale(0.8) rotate(0deg)';
        sparkle.style.transition = 'transform 900ms ease, opacity 900ms ease';
        sparkle.style.filter = 'drop-shadow(0 8px 24px rgba(59,130,246,0.35))';
        overlay.appendChild(sparkle);

        setTimeout(() => {
            sparkle.style.opacity = '1';
            sparkle.style.transform = `translateY(${-24 - getSecureRandom() * 36}px) scale(${1 + getSecureRandom() * 0.45}) rotate(${(-25 + getSecureRandom() * 50).toFixed(0)}deg)`;
        }, index * 35);
    }

    setTimeout(() => overlay.remove(), 1500);

    const isRu = (document.documentElement.lang || 'ru').toLowerCase().startsWith('ru');
    showToast(isRu ? 'Пасхалка найдена: панель одобряет любопытных.' : 'Easter egg found: the panel approves curious minds.');

    if (window.playHaptic) {
        window.playHaptic([25, 40, 25]);
    }
}

function initBrandEasterEgg() {
    const brandEl = document.querySelector('[data-i18n="web_brand_name"]');
    if (!brandEl || brandEl.dataset.easterEggBound === 'true') return;

    let clickCount = 0;
    let resetTimer = null;
    let cooldown = false;

    brandEl.dataset.easterEggBound = 'true';
    brandEl.classList.add('select-none');

    brandEl.addEventListener('click', () => {
        if (cooldown) return;

        clickCount += 1;
        clearTimeout(resetTimer);
        resetTimer = setTimeout(() => {
            clickCount = 0;
        }, 2200);

        if (clickCount < 7) return;

        clickCount = 0;
        cooldown = true;
        launchBrandEasterEgg();
        setTimeout(() => {
            cooldown = false;
        }, 2500);
    });
}

function toggleHint(e, id) {
    if (e) e.stopPropagation();
    const el = document.getElementById(id);
    if (!el) return;

    const m = document.getElementById('genericHintModal');
    const c = document.getElementById('hintModalContent');

    if (m && c) {
        c.innerHTML = DOMPurify.sanitize(el.innerHTML);

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
        if (i) setTimeout(() => i.focus({ preventScroll: true }), 100);
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
        btn.innerHTML = DOMPurify.sanitize(`<svg class="animate-spin h-5 w-5 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`);
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
            btn.innerHTML = DOMPurify.sanitize(originalHTML);
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
        holidayBtn.innerHTML = DOMPurify.sanitize(`<svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="2" x2="12" y2="22"></line><line x1="20" y1="12" x2="4" y2="12"></line><line x1="17.66" y1="6.34" x2="6.34" y2="17.66"></line><line x1="17.66" y1="17.66" x2="6.34" y2="6.34"></line><polyline points="9 4 12 7 15 4"></polyline><polyline points="15 20 12 17 9 20"></polyline><polyline points="20 9 17 12 20 15"></polyline><polyline points="4 15 7 12 4 9"></polyline></svg>`);
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
        s.innerText = icons[Math.floor(getSecureRandom() * icons.length)];
        s.style.left = getSecureRandom() * 100 + 'vw';
        s.style.animationDuration = (getSecureRandom() * 3 + 4) + 's';
        s.style.opacity = getSecureRandom() * 0.7;
        s.style.fontSize = (getSecureRandom() * 8 + 8) + 'px';
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
        .catch(() => { });
}

let lastUnreadCount = -1;
let lastNotificationsJson = "";

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
        if (!e.target.closest('#notifDropdown') && !e.target.closest('#notifBtn')) {
            if (typeof closeNotifications === 'function') closeNotifications();
        }
        if (!e.target.closest('#mobileSettingsDropdown') && !e.target.closest('#mobileSettingsBtn')) {
            if (typeof closeMobileSettings === 'function') closeMobileSettings();
        }
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

    overlay.innerHTML = DOMPurify.sanitize(`
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
    `);

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

    toast.innerHTML = DOMPurify.sanitize(`
        <div class="flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-red-600 dark:text-red-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span class="text-sm font-bold text-red-900 dark:text-red-100">${msg}</span>
        </div>
        <button data-action="retry-sse" class="w-full py-1.5 px-3 bg-red-200 hover:bg-red-300 dark:bg-red-800 dark:hover:bg-red-700 text-red-900 dark:text-red-100 rounded-lg text-xs font-bold transition flex items-center justify-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            ${btnText}
        </button>
    `);

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

window.retrySSEStream = retrySSEStream;

document.addEventListener('app:action:retry-sse', () => {
    retrySSEStream();
});

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
    overlay.innerHTML = DOMPurify.sanitize(`<div class="text-center">${content}</div>`);

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
    });
}

async function clearNotifications(e) {
    if (e) e.stopPropagation();

    if (!await window.showModalConfirm(I18N.web_clear_notif_confirm || "Clear all notifications?", I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/notifications/clear', {
            method: 'POST'
        });

        if (res.ok) {
            updateNotifUI([], 0);
            if (window.showToast) window.showToast(I18N.web_notifications_cleared);
        }
    } catch (e) {
        console.error("Clear notifications error:", e);
        if (window.showModalAlert) window.showModalAlert(String(e), I18N.web_error_short || "Error");
    }
}
window.clearNotifications = clearNotifications;

function updateNotifUI(list, count) {
    const badge = document.getElementById('notifBadge');
    const listContainer = document.getElementById('notifList');
    const bellIcon = document.querySelector('#notifBtn svg');

    // Skip if notification elements don't exist on this page
    if (!badge || !listContainer) return;

    if (count > 0) {
        setSafeText(badge, count > 99 ? '99+' : String(count));
        badge.classList.remove('hidden');
        if (lastUnreadCount !== -1 && count > lastUnreadCount && bellIcon) {
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

    const listJson = JSON.stringify(list);
    if (listJson === lastNotificationsJson) return;
    lastNotificationsJson = listJson;

    if (list.length === 0) {
        setSafeHTML(listContainer, `<div class="p-4 text-center text-gray-500 text-sm">${escapeHtml((typeof I18N !== 'undefined' ? I18N.web_no_notifications : "No notifications"))}</div>`);
    } else {
        listContainer.innerHTML = DOMPurify.sanitize("");
        list.forEach(n => {
            const div = document.createElement('div');
            div.className = "px-4 py-3 border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition last:border-0 group";
            const date = new Date(n.time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            let badgeHtml = '';
            if (n.source === 'node') {
                badgeHtml = `<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-100 text-purple-700 dark:bg-purple-500/20 dark:text-purple-200 mr-2 uppercase tracking-wider">${escapeHtml(I18N?.web_notif_source_node || '')}</span>`;
            } else {
                badgeHtml = `<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-200 mr-2 uppercase tracking-wider">${escapeHtml(I18N?.web_notif_source_agent || '')}</span>`;
            }

            // Sanitize text: escape everything via DOM, then re-allow <b>, </b>, <br>
            const tempSpan = document.createElement('span');
            tempSpan.textContent = n.text;
            let cleanText = tempSpan.innerHTML
                .replace(/&lt;b&gt;/gi, "<b>")
                .replace(/&lt;\/b&gt;/gi, "</b>")
                .replace(/\n/g, "<br>");
            cleanText = replaceEmojisWithFlagsHTML(cleanText);

            div.innerHTML = DOMPurify.sanitize(`
                <div class="flex justify-between items-start mb-1">
                    <div class="flex items-center">
                        ${badgeHtml}
                        <span class="text-[10px] text-gray-400 font-mono">${escapeHtml(date)}</span>
                    </div>
                </div>
                <div class="text-sm text-gray-700 dark:text-gray-300 leading-snug break-words group-hover:text-gray-900 dark:group-hover:text-white transition-colors">
                    ${cleanText}
                </div>`);
            listContainer.appendChild(div);
        });
    }
}

function toggleNotifications() {
    const dropdown = document.getElementById('notifDropdown');
    const badge = document.getElementById('notifBadge');
    if (!dropdown) return;
    if (dropdown.classList.contains('show')) closeNotifications();
    else {
        dropdown.classList.remove('hidden');
        setTimeout(() => dropdown.classList.add('show'), 10);
        if (lastUnreadCount > 0 && badge) {
            fetch('/api/notifications/read', {
                method: 'POST'
            }).then(() => badge.classList.add('hidden'));
        }
    }
}
window.toggleNotifications = toggleNotifications;
window.closeNotifications = closeNotifications;

function closeNotifications() {
    const d = document.getElementById('notifDropdown');
    if (d) {
        d.classList.remove('show');
        setTimeout(() => d.classList.add('hidden'), 200);
    }
}

function toggleMobileSettings(e) {
    if (e) e.stopPropagation();
    const dropdown = document.getElementById('mobileSettingsDropdown');
    if (!dropdown) return;

    if (!dropdown.classList.contains('hidden')) {
        closeMobileSettings();
    } else {
        if (typeof closeNotifications === 'function') closeNotifications();
        dropdown.classList.remove('hidden');
    }
}

function closeMobileSettings() {
    const dropdown = document.getElementById('mobileSettingsDropdown');
    if (dropdown) {
        dropdown.classList.add('hidden');
    }
}
window.closeMobileSettings = closeMobileSettings;
window.toggleMobileSettings = toggleMobileSettings;

function toggleTheme() {
    const themes = ["system", "dark", "light", "amoled"];
    let currentTheme = localStorage.getItem("theme");
    if (!currentTheme) currentTheme = "system";

    const currentIndex = themes.indexOf(currentTheme);
    const nextTheme = themes[(currentIndex + 1) % themes.length];

    setThemeDirect(nextTheme, null);
}

function setThemeDirect(theme, event) {
    if (event) event.stopPropagation();
    localStorage.setItem("theme", theme);
    document.documentElement.classList.toggle('dark', theme === 'dark' || theme === 'amoled' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches));
    document.documentElement.classList.toggle('amoled', theme === 'amoled');
    applyThemeUI(theme);
    window.dispatchEvent(new Event("themeChanged"));
}

function applyThemeUI(t) {
    if (!t) return;
    ['iconMoon', 'iconSun', 'iconSystem', 'iconAmoled'].forEach(id => document.getElementById(id)?.classList.add('hidden'));
    
    if (t === 'dark') {
        document.getElementById('iconMoon')?.classList.remove('hidden');
    } else if (t === 'light') {
        document.getElementById('iconSun')?.classList.remove('hidden');
    } else if (t === 'amoled') {
        document.getElementById('iconAmoled')?.classList.remove('hidden');
    } else {
        document.getElementById('iconSystem')?.classList.remove('hidden');
    }
    
    // Interactive segmented control style for active theme
    const baseClasses = ["text-gray-500", "hover:text-gray-700", "dark:text-gray-400", "dark:hover:text-gray-200", "hover:bg-gray-200", "dark:hover:bg-gray-800"];
    const activeClasses = ["bg-white", "dark:bg-gray-600", "shadow-sm", "text-gray-900", "dark:text-white"];
    
    ['mThemeSys', 'mThemeDark', 'mThemeLight', 'mThemeAmoled'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove(...activeClasses);
            el.classList.add(...baseClasses);
        }
    });

    const activeEl = document.getElementById(
        t === 'light' ? 'mThemeLight' : t === 'dark' ? 'mThemeDark' : t === 'amoled' ? 'mThemeAmoled' : 'mThemeSys'
    );
    if (activeEl) {
        activeEl.classList.remove(...baseClasses);
        activeEl.classList.add(...activeClasses);
    }
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

    // Taptic engine pop-in simulation for modals/hints
    if (window.playHaptic) playHaptic([8, 40, 10]);

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
            // ИСПРАВЛЕНИЕ: Отключаем плавную прокрутку при восстановлении позиции
            window.scrollTo({
                top: bodyScrollTop,
                behavior: 'auto'
            });
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
    }).catch(() => { });
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
                currentMain.innerHTML = DOMPurify.sanitize(newMain.innerHTML);
                currentMain.className = newMain.className;
                currentNav.innerHTML = DOMPurify.sanitize(newNav.innerHTML);
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
                } catch (e) { }
                initHolidayMood();
                initGlobalLazyLoad();

                try {
                    if (url.includes('/settings')) {
                        if (window.initSettings) window.initSettings();
                        else window.location.reload();
                    } else if (url.includes('/nodes')) {
                        if (window.initNodesMonitor) window.initNodesMonitor();
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
            const safeUrl = new URL(url, window.location.origin);
            if (safeUrl.origin === window.location.origin) {
                window.location.assign(safeUrl.href);
            } else {
                window.location.assign('/');
            }
        }
    } catch (error) {
        console.error("SPA Error:", error);
        const safeUrl = new URL(url, window.location.origin);
        if (safeUrl.origin === window.location.origin) {
            window.location.assign(safeUrl.href);
        } else {
            window.location.assign('/');
        }
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
    btn.innerHTML = DOMPurify.sanitize(`<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${I18N.web_logs_clearing}`);

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
            btn.innerHTML = DOMPurify.sanitize(`<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> <span class="font-bold text-xs uppercase ml-1">${doneText}</span>`);

            setTimeout(() => {
                btn.innerHTML = DOMPurify.sanitize(originalHTML);
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
            btn.innerHTML = DOMPurify.sanitize(originalHTML);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
        btn.disabled = false;
        btn.innerHTML = DOMPurify.sanitize(originalHTML);
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
    btn.innerHTML = DOMPurify.sanitize(`<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`);

    try {
        const res = await fetch('/api/traffic/reset', {
            method: 'POST'
        });
        if (res.ok) {
            btn.classList.remove(...redClasses);
            btn.classList.remove(...hoverClasses);
            btn.classList.add(...greenClasses);
            const doneText = (typeof I18N !== 'undefined' && I18N.web_traffic_reset_no_emoji) ? I18N.web_traffic_reset_no_emoji : "Done!";
            btn.innerHTML = DOMPurify.sanitize(`<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> <span class="font-bold text-xs uppercase ml-1">${doneText}</span>`);

            setTimeout(() => {
                btn.innerHTML = DOMPurify.sanitize(originalHTML);
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
            btn.innerHTML = DOMPurify.sanitize(originalHTML);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
        btn.disabled = false;
        btn.innerHTML = DOMPurify.sanitize(originalHTML);
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const modals = document.querySelectorAll('[id$="Modal"]');
        modals.forEach(modal => {
            if (!modal.classList.contains('hidden')) {
                if (modal.id === 'nodeModal' && typeof closeNodeModal === 'function') {
                    closeNodeModal();
                } else if (modal.id === 'addNodeModal' && typeof closeAddNodeModal === 'function') {
                    closeAddNodeModal();
                } else if (modal.id === 'systemModal' && typeof closeSystemModal === 'function') {
                    closeSystemModal(null);
                } else if (modal.id === 'servicesEditModal' && typeof closeServicesEditModal === 'function') {
                    closeServicesEditModal();
                } else if (modal.id === 'serviceInfoModal' && typeof closeServiceInfoModal === 'function') {
                    closeServiceInfoModal();
                } else if (modal.id === 'agentIpsModal' && typeof closeAgentIpsModal === 'function') {
                    closeAgentIpsModal();
                } else if (modal.id === 'genericHintModal' && typeof closeHintModal === 'function') {
                    closeHintModal();
                }
                else {
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                }
            }
        });
    }
});

// --- UI Modes Toggles (Perf Mode & A11y Mode) ---
function togglePerfMode() {
    const isPerfMode = document.documentElement.classList.toggle('perf-mode');
    localStorage.setItem('perf_mode', isPerfMode ? '1' : '0');
    if (typeof showToast === 'function') {
        showToast(isPerfMode ? (I18N?.web_perf_mode_on || 'Light mode enabled') : (I18N?.web_perf_mode_off || 'Light mode disabled'));
    }
    if (window.playHaptic) playHaptic([8, 40, 10]);
}

function toggleA11yMode() {
    const isA11yMode = document.documentElement.classList.toggle('a11y-mode');
    localStorage.setItem('a11y_mode', isA11yMode ? '1' : '0');
    if (typeof showToast === 'function') {
        showToast(isA11yMode ? (I18N?.web_a11y_mode_on || 'Accessibility mode enabled') : (I18N?.web_a11y_mode_off || 'Accessibility mode disabled'));
    }
    if (window.playHaptic) playHaptic([8, 40, 10]);
}

window.togglePerfMode = togglePerfMode;
window.toggleA11yMode = toggleA11yMode;

document.addEventListener('app:action:toggle-perf-mode', () => togglePerfMode());
document.addEventListener('app:action:toggle-a11y-mode', () => toggleA11yMode());

// --- Billing UI Logic ---

window.calculateDaysLeft = function(isoDateString) {
    if (!isoDateString) return null;
    const targetDate = new Date(isoDateString);
    if (isNaN(targetDate)) return null;
    const now = new Date();
    const diffMs = targetDate - now;
    const days = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
    return days;
};

window.getBillingBadgeHtml = function(daysLeft) {
    if (daysLeft === null) return '';
    let badgeClass = "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400";
    if (daysLeft < 0) {
        badgeClass = "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    } else if (daysLeft <= 3) {
        badgeClass = "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    } else if (daysLeft <= 7) {
        badgeClass = "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400";
    }
    const isSmall = typeof window !== 'undefined' && window.innerWidth <= 380;
    const daysTemplate = isSmall
        ? (I18N?.web_billing_badge_days_short || "{days} д.")
        : (I18N?.web_billing_badge_days || "{days} дней");
    const txt = daysLeft < 0 ? (I18N?.web_billing_expired || "Expired!") : daysTemplate.replace("{days}", daysLeft);
    return `<span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ml-1.5 shadow-sm border border-black/5 dark:border-white/5 ${badgeClass}">${txt}</span>`;
};

window.showBillingModal = function(name, amount, currency, dateStr, daysLeft) {
    const title = I18N?.web_billing_modal_title || "Детали аренды";
    const amountLbl = I18N?.web_billing_amount || "Стоимость аренды:";
    const dateLbl = I18N?.web_billing_date || "Ближайший платёж:";
    const hintText = I18N?.web_billing_bot_hint || "Управлять настройками оплаты можно в Telegram-боте.";
    
    let statusHtml = "";
    if (daysLeft !== null) {
        if (daysLeft < 0) {
            statusHtml = `<span class="px-2 py-1 rounded text-xs font-bold bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">${I18N?.web_billing_status_expired || "Просрочен!"}</span>`;
        } else {
            const activeText = (I18N?.web_billing_active_days || "Активен (осталось {days} дней)").replace("{days}", daysLeft);
            statusHtml = `<span class="px-2 py-1 rounded text-xs font-bold bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">${activeText}</span>`;
        }
    } else {
        statusHtml = `<span class="text-xs text-gray-400 font-medium">${I18N?.web_billing_not_set || "Не установлена"}</span>`;
    }
    
    const amountVal = amount !== null && amount !== undefined ? `${amount} ${currency}` : (I18N?.web_billing_not_set || "Не установлена");
    const dateVal = dateStr ? new Date(dateStr).toLocaleDateString() : (I18N?.web_billing_not_set || "Не установлена");

    const contentHtml = `
        <div class="mb-4 text-center">
            <h3 class="text-xl font-black text-gray-900 dark:text-white">${name}</h3>
        </div>
        <div class="bg-gray-50 dark:bg-black/20 rounded-xl p-4 space-y-3 border border-gray-100 dark:border-white/5 shadow-inner">
            <div class="flex justify-between items-center border-b border-gray-200 dark:border-white/10 pb-2">
                <span class="text-sm text-gray-500 dark:text-gray-400 font-medium">${amountLbl}</span>
                <span class="text-sm font-bold text-gray-900 dark:text-white bg-white dark:bg-black/40 px-2 py-0.5 rounded shadow-sm border border-gray-100 dark:border-white/5">${amountVal}</span>
            </div>
            <div class="flex justify-between items-center border-b border-gray-200 dark:border-white/10 pb-2">
                <span class="text-sm text-gray-500 dark:text-gray-400 font-medium">${dateLbl}</span>
                <span class="text-sm font-bold text-gray-900 dark:text-white bg-white dark:bg-black/40 px-2 py-0.5 rounded shadow-sm border border-gray-100 dark:border-white/5">${dateVal}</span>
            </div>
            <div class="flex justify-between items-center">
                <span class="text-sm text-gray-500 dark:text-gray-400 font-medium">${I18N?.web_billing_status || 'Статус:'}</span>
                ${statusHtml}
            </div>
        </div>
        <div class="mt-6 p-3 rounded-xl bg-blue-50/50 dark:bg-blue-900/20 flex gap-3 items-start">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-blue-500 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p class="text-xs text-blue-800 dark:text-blue-300 leading-relaxed font-medium">${hintText}</p>
        </div>
    `;

    showModal({
        title: title,
        content: contentHtml,
        buttons: [
            { text: I18N?.modal_btn_ok || "OK", class: "bg-blue-600 text-white hover:bg-blue-500 shadow-lg shadow-blue-500/20 w-full", close: true }
        ]
    });
};

window.renderHeaderBilling = function() {
    if (typeof master_billing_json === 'undefined' || !master_billing_json) return;
    const container = document.getElementById('headerBillingContainer');
    if (!container) return;
    
    let isSet = master_billing_json.amount !== null && master_billing_json.amount !== undefined;
    let daysLeft = null;
    
    if (master_billing_json.next_payment_date) {
        daysLeft = calculateDaysLeft(master_billing_json.next_payment_date);
    }
    
    // Only show the header icon if billing is enabled or data exists.
    if (!isSet && !master_billing_json.next_payment_date) return;
    
    let btnHtml = `
        <button class="flex items-center justify-center h-8 px-2 sm:px-3 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-600 dark:text-gray-400 font-medium text-xs sm:text-sm gap-1 whitespace-nowrap group"
                title="${I18N?.web_billing_modal_title || 'Детали оплаты'}">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-500 group-hover:text-blue-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
            <span class="hidden sm:inline-flex">${getBillingBadgeHtml(daysLeft)}</span>
        </button>
    `;
    container.innerHTML = DOMPurify.sanitize(btnHtml);
    const badgeBtn = container.querySelector('button');
    if (badgeBtn) {
        badgeBtn.onclick = () => {
            showBillingModal(
                I18N?.master_server_name || "Мой сервер (Агент)",
                master_billing_json.amount !== null && master_billing_json.amount !== undefined ? master_billing_json.amount : null,
                master_billing_json.currency || '$',
                master_billing_json.next_payment_date || null,
                daysLeft
            );
        };
    }
};

document.addEventListener('DOMContentLoaded', () => {
    if (typeof renderHeaderBilling === 'function') {
        renderHeaderBilling();
    }
});

window.showModal = function(options) {
    const { title, content, buttons } = options;
    const modalId = 'dynamicModal_' + Math.random().toString(36).substr(2, 9);
    
    const modal = document.createElement('div');
    modal.id = modalId;
    modal.className = "fixed inset-0 z-[9999] hidden items-center justify-center bg-black/50 dark:bg-black/80 backdrop-blur-sm p-4";
    modal.onclick = (e) => { if (e.target === modal) window.closeDynamicModal(modalId); };
    
    let buttonsHtml = '';
    if (buttons && buttons.length > 0) {
        buttonsHtml = `<div class="p-4 border-t border-gray-200 dark:border-white/5 flex justify-end gap-2 rounded-b-2xl">`;
        buttons.forEach((btn, idx) => {
            buttonsHtml += `<button id="${modalId}_btn_${idx}" class="px-4 py-2 rounded-xl text-sm font-bold shadow-sm transition ${btn.class || 'bg-gray-200 text-gray-800 hover:bg-gray-300 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600'}">${btn.text}</button>`;
        });
        buttonsHtml += `</div>`;
    }

    modal.innerHTML = `
        <div class="bg-white dark:bg-gray-800 border border-white/20 dark:border-white/10 rounded-2xl shadow-2xl w-full max-w-md relative flex flex-col" style="transition: opacity 0.2s ease-out, transform 0.2s ease-out;">
            <div class="p-4 border-b border-gray-200 dark:border-white/5 flex justify-between items-center rounded-t-2xl">
                <h3 class="text-lg font-bold text-gray-900 dark:text-white">${title || ''}</h3>
                <button id="${modalId}_close_btn" class="text-gray-400 hover:text-gray-600 dark:hover:text-white transition p-1">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            </div>
            <div class="p-5 text-sm text-gray-700 dark:text-gray-300">
                ${content || ''}
            </div>
            ${buttonsHtml}
        </div>
    `;
    
    document.body.appendChild(modal);
    
    const closeBtn = document.getElementById(`${modalId}_close_btn`);
    if (closeBtn) {
        closeBtn.onclick = () => window.closeDynamicModal(modalId);
    }
    
    if (buttons && buttons.length > 0) {
        buttons.forEach((btn, idx) => {
            const btnEl = document.getElementById(`${modalId}_btn_${idx}`);
            if (btnEl) {
                btnEl.onclick = () => {
                    if (btn.onClick) btn.onClick();
                    if (btn.close) window.closeDynamicModal(modalId);
                };
            }
        });
    }
    
    if (typeof animateModalOpen === 'function') {
        animateModalOpen(modal);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
};

window.closeDynamicModal = function(id) {
    const modal = document.getElementById(id);
    if (modal) {
        if (typeof animateModalClose === 'function') {
            animateModalClose(modal);
            setTimeout(() => {
                if (modal.parentNode) modal.parentNode.removeChild(modal);
            }, 300);
        } else {
            if (modal.parentNode) modal.parentNode.removeChild(modal);
        }
    }
};
