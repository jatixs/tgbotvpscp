/* /core/static/js/login.js */

// --- Tailwind Config & Hacks ---
// Настройка цветов и анимаций для Tailwind прямо в браузере (если CDN используется)
if (window.tailwind) {
    window.tailwind.config = {
        darkMode: 'class',
        theme: {
            extend: {
                animation: {
                    'float': 'float 6s ease-in-out infinite',
                    'blob': 'blob 7s infinite',
                    'fade-in-up': 'fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards',
                },
                keyframes: {
                    float: { '0%, 100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-20px)' } },
                    blob: { '0%': { transform: 'translate(0px, 0px) scale(1)' }, '33%': { transform: 'translate(30px, -50px) scale(1.1)' }, '66%': { transform: 'translate(-20px, 20px) scale(0.9)' }, '100%': { transform: 'translate(0px, 0px) scale(1)' } },
                    fadeInUp: { '0%': { opacity: '0', transform: 'translateY(20px) scale(0.95)' }, '100%': { opacity: '1', transform: 'translateY(0) scale(1)' } },
                }
            }
        }
    };
}

// --- Cookie Management ---
function acceptCookies() {
    localStorage.setItem('cookie_consent', 'true');
    const banner = document.getElementById('cookieConsent');
    if (banner) banner.classList.add('translate-y-full');
}

// --- Telegram Auth Widget ---
async function onTelegramAuth(user) {
    console.log("Telegram Auth", user);
    acceptCookies();
    try {
        const response = await fetch('/api/auth/telegram', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(user)
        });
        if (response.ok) {
            window.location.reload();
        } else {
            const d = await response.json();
            if(window.showModalAlert) await window.showModalAlert("Error: " + (d.error || "Unknown"), "Auth Error");
            else alert("Auth Error: " + (d.error || "Unknown"));
        }
    } catch (e) { console.error(e); }
}

// --- UI Logic: Language ---
function setLoginLanguage(lang) {
    document.cookie = "guest_lang=" + lang + "; path=/; max-age=31536000";
    window.location.reload();
}
window.setLoginLanguage = setLoginLanguage;

// --- UI Logic: Modals ---
function openSupportModal() {
    const modal = document.getElementById('support-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
    }
}

function closeSupportModal() {
    const modal = document.getElementById('support-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = '';
    }
}
window.openSupportModal = openSupportModal;
window.closeSupportModal = closeSupportModal;

// --- UI Logic: Forms Switcher ---
function toggleForms(target) {
    const magic = document.getElementById('magic-form');
    const password = document.getElementById('password-form');
    const reset = document.getElementById('reset-form');
    const setPass = document.getElementById('set-password-form');
    const errorBlock = document.getElementById('reset-error-block');
    
    // Скрываем все
    [magic, password, reset, setPass].forEach(el => el?.classList.add('hidden'));
    if (errorBlock) errorBlock.classList.add('hidden');

    // Показываем целевой
    if (target === 'password' && password) password.classList.remove('hidden');
    else if (target === 'reset' && reset) reset.classList.remove('hidden');
    else if (target === 'set-password' && setPass) setPass.classList.remove('hidden');
    else if (magic) magic.classList.remove('hidden');
}

// --- API: Reset Password Request ---
async function requestPasswordReset() {
    const userIdInput = document.getElementById('reset_user_id');
    const btn = document.getElementById('btn-reset-send');
    const errorBlock = document.getElementById('reset-error-block');
    const adminLinkBtn = document.getElementById('admin-link-btn');
    const container = document.getElementById('forms-container');

    if (!userIdInput || !btn) return;

    const userId = userIdInput.value.trim();
    if (!userId) {
        userIdInput.focus();
        return;
    }

    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "...";
    if (errorBlock) errorBlock.classList.add('hidden');

    try {
        const response = await fetch('/api/login/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });

        const data = await response.json();

        if (response.ok) {
            container.innerHTML = `
                <div class="text-center py-8 animate-fade-in-up">
                    <div class="w-16 h-16 bg-yellow-500/20 rounded-full flex items-center justify-center mx-auto mb-4 border border-yellow-500/30">
                        <svg class="w-8 h-8 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 00-2-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                    </div>
                    <h3 class="text-lg font-bold text-white mb-2">Link Sent!</h3>
                    <p class="text-sm text-gray-300">Check your Telegram messages.</p>
                    <a href="/login" class="inline-block mt-6 px-6 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm font-bold transition">Back</a>
                </div>
            `;
        } else {
            if (data.error === 'not_found' && errorBlock) {
                errorBlock.classList.remove('hidden');
                if (data.admin_url && adminLinkBtn) {
                    adminLinkBtn.href = data.admin_url;
                }
            } else {
                if (window.showModalAlert) await window.showModalAlert("Error: " + (data.error || "Unknown"), 'Error');
                else alert("Error: " + (data.error || "Unknown"));
            }
        }
    } catch (e) {
        if (window.showModalAlert) await window.showModalAlert("Connection Error: " + e, 'Network Error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    }
}

// --- API: Submit New Password (Reset) ---
async function submitNewPassword() {
    const p1 = document.getElementById('new_pass').value;
    const p2 = document.getElementById('confirm_pass').value;
    const btn = document.getElementById('btn-save-pass');
    const container = document.getElementById('forms-container');
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    if (!p1 || p1.length < 4) {
        if(window.showModalAlert) await window.showModalAlert("Password too short (min 4 chars).", 'Error');
        return;
    }
    if (p1 !== p2) {
        if(window.showModalAlert) await window.showModalAlert("Passwords do not match.", 'Error');
        return;
    }

    btn.disabled = true;
    btn.innerText = "Saving...";

    try {
        const res = await fetch('/api/reset/confirm', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ token: token, password: p1 })
        });
        
        const data = await res.json();
        if (res.ok) {
            container.innerHTML = `
                <div class="text-center py-8 animate-fade-in-up">
                    <div class="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4 border border-green-500/30">
                        <svg class="w-8 h-8 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <h3 class="text-lg font-bold text-white mb-2">Success!</h3>
                    <p class="text-sm text-gray-300">Password changed successfully.</p>
                    <a href="/login" class="w-full block text-center mt-6 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded-xl font-bold text-white shadow-lg transition">Login</a>
                </div>
            `;
            window.history.replaceState({}, document.title, "/login");
        } else {
            if(window.showModalAlert) await window.showModalAlert("Error: " + data.error, 'Error');
            btn.disabled = false;
            btn.innerText = "Save Password";
        }
    } catch (e) {
        if(window.showModalAlert) await window.showModalAlert("Network Error: " + e, 'Error');
        btn.disabled = false;
        btn.innerText = "Save Password";
    }
}

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
    // 1. Fix Title
    if (typeof I18N !== 'undefined' && I18N.web_title) {
        document.title = I18N.web_title;
    }

    // 2. Parse Emojis
    if (window.twemoji) window.twemoji.parse(document.body, { folder: 'svg', ext: '.svg' });

    // 3. I18N Apply
    if (typeof I18N !== 'undefined') {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (I18N[key]) {
                if (el.tagName === 'INPUT') el.placeholder = I18N[key];
                else el.innerHTML = I18N[key];
            }
            if (el.title && I18N[key]) el.title = I18N[key];
        });
        
        // Manual tooltips
        const gh = document.querySelector('a[title="GitHub"]');
        if(gh && I18N['login_github_tooltip']) gh.title = I18N['login_github_tooltip'];
        const sp = document.querySelector('button[title="Support"]');
        if(sp && I18N['login_support_tooltip']) sp.title = I18N['login_support_tooltip'];
    }

    // 4. Handle URL Params (Reset Token or Sent Magic Link)
    const urlParams = new URLSearchParams(window.location.search);
    const formsContainer = document.getElementById('forms-container');
    
    if (urlParams.get('sent') === 'true' && formsContainer) {
        formsContainer.innerHTML = `
            <div class="text-center py-8 animate-fade-in-up">
                <div class="w-16 h-16 bg-blue-500/20 rounded-full flex items-center justify-center mx-auto mb-4 border border-blue-500/30">
                    <svg class="w-8 h-8 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 00-2-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                </div>
                <h3 class="text-lg font-bold text-white mb-2">Magic Link Sent!</h3>
                <p class="text-sm text-gray-300">Check your Telegram messages.</p>
                <a href="/login" class="inline-block mt-6 px-6 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm font-bold transition">Return</a>
            </div>
        `;
    } else if (urlParams.get('token')) {
        // Если есть токен сброса в URL -> показываем форму смены пароля
        toggleForms('set-password');
    }

    // 5. Check Cookie Consent
    if (!localStorage.getItem('cookie_consent')) {
        setTimeout(() => {
            const banner = document.getElementById('cookieConsent');
            if(banner) banner.classList.remove('translate-y-full');
        }, 1000);
    }
    
    // 6. Init Telegram Widget
    const botUsername = (typeof BOT_USERNAME !== 'undefined') ? BOT_USERNAME : "";
    const container = document.getElementById('telegram-widget-container');
    const magicForm = document.getElementById('magic-link-form');
    
    // Проверки безопасности для виджета (HTTPS + не IP + не localhost)
    const isIp = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/.test(window.location.hostname);
    const isLocalhost = window.location.hostname === 'localhost';
    const isHttps = window.location.protocol === 'https:';
    
    if (botUsername && !isIp && !isLocalhost && isHttps && container && magicForm) {
        const script = document.createElement('script');
        script.async = true;
        script.src = "https://telegram.org/js/telegram-widget.js?22";
        script.setAttribute('data-telegram-login', botUsername);
        script.setAttribute('data-size', 'large');
        script.setAttribute('data-radius', '12'); // Скругление под стиль кнопок
        script.setAttribute('data-onauth', 'onTelegramAuth(user)');
        script.setAttribute('data-request-access', 'write');
        container.appendChild(script);
        container.classList.remove('hidden');
        magicForm.classList.add('hidden'); // Скрываем форму ввода ID, если виджет доступен
    }
});