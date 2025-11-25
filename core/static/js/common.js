// Общие функции для всех страниц

// --- ЛОГИКА ТЕМЫ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
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

// --- СИСТЕМНЫЕ МОДАЛЬНЫЕ ОКНА (Alert, Confirm, Prompt) ---
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
            // Fallback, если HTML модалки нет на странице
            if (type === 'confirm') resolve(confirm(message));
            else if (type === 'prompt') resolve(prompt(message, placeholder));
            else { alert(message); resolve(true); }
            return;
        }

        titleEl.innerText = title;
        msgEl.innerHTML = message.replace(/\n/g, '<br>'); // Поддержка переносов строк
        
        // Сброс состояния
        inputEl.classList.add('hidden');
        cancelBtn.classList.add('hidden');
        inputEl.value = '';

        // Переводы кнопок
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
            
            // Enter в поле ввода
            inputEl.onkeydown = (e) => {
                if(e.key === 'Enter') closeSystemModal(inputEl.value);
            };
        } else {
            // Alert
            okBtn.onclick = () => closeSystemModal(true);
        }

        modal.classList.remove('hidden');
        modal.classList.add('flex');
    });
}

window.showModalAlert = (message, title) => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_alert : 'Alert'), message, 'alert');
window.showModalConfirm = (message, title) => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_confirm : 'Confirm'), message, 'confirm');
window.showModalPrompt = (message, title, placeholder = '') => _showSystemModalBase(title || (typeof I18N !== 'undefined' ? I18N.modal_title_prompt : 'Prompt'), message, 'prompt', placeholder);