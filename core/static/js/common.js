// Общие функции для всех страниц

// --- ЛОГИКА ТЕМЫ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

// Инициализация (запуск после загрузки, чтобы подхватить иконки)
document.addEventListener("DOMContentLoaded", () => {
    applyThemeUI(currentTheme);
    parsePageEmojis(); // Парсим эмодзи при первой загрузке
});

// Функция для замены эмодзи на картинки Twemoji
function parsePageEmojis() {
    if (window.twemoji) {
        window.twemoji.parse(document.body, {
            folder: 'svg',
            ext: '.svg'
        });
    }
}

function toggleTheme() {
    const idx = themes.indexOf(currentTheme);
    const nextIdx = (idx + 1) % themes.length;
    currentTheme = themes[nextIdx];
    localStorage.setItem('theme', currentTheme);
    
    // Применяем класс к HTML (основная логика в theme_init.js, тут UI)
    const isDark = currentTheme === 'dark' || (currentTheme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (isDark) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
    
    applyThemeUI(currentTheme);
    
    // Событие для графиков
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: currentTheme, isDark: isDark } }));
}

function applyThemeUI(theme) {
    const iconMoon = document.getElementById('iconMoon');
    const iconSun = document.getElementById('iconSun');
    const iconSystem = document.getElementById('iconSystem');
    
    if (!iconMoon || !iconSun || !iconSystem) return;

    // Сброс иконок
    [iconMoon, iconSun, iconSystem].forEach(el => el.classList.add('hidden'));

    if (theme === 'dark') {
        iconMoon.classList.remove('hidden');
    } else if (theme === 'light') {
        iconSun.classList.remove('hidden');
    } else {
        iconSystem.classList.remove('hidden');
    }
}

// --- ЛОГИКА ЯЗЫКА ---
async function setLanguage(lang) {
    try {
        const res = await fetch('/api/settings/language', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lang: lang})
        });
        if (res.ok) {
            window.location.reload();
        }
    } catch (e) {
        console.error("Lang switch failed", e);
    }
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
            setTimeout(() => {
                toast.classList.add('translate-y-full');
            }, 2000);
        }
    };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tokenText).then(showToast).catch(err => {
            fallbackCopyTextToClipboard(tokenText, showToast);
        });
    } else {
        fallbackCopyTextToClipboard(tokenText, showToast);
    }
}

function fallbackCopyTextToClipboard(text, onSuccess) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed"; // avoid scrolling to bottom
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        const successful = document.execCommand('copy');
        if (successful && onSuccess) onSuccess();
    } catch (err) {
        console.error('Fallback error', err);
    }
    document.body.removeChild(textArea);
}