/* /core/static/js/login.js */

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

// --- UI Logic: Language & Slider ---

function updateLangSlider(lang) {
    const slider = document.getElementById('lang-slider-bg');
    const btnRu = document.getElementById('btn-ru');
    const btnEn = document.getElementById('btn-en');

    if (slider) {
        slider.style.transition = 'transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)';
        slider.style.willChange = 'transform';
        
        if (lang === 'en') {
            slider.style.transform = 'translate3d(100%, 0, 0)';
        } else {
            slider.style.transform = 'translate3d(0, 0, 0)';
        }
    }

    if (btnRu && btnEn) {
        btnRu.style.outline = 'none';
        btnEn.style.outline = 'none';
        
        const transition = 'all 0.4s ease';
        btnRu.style.transition = transition;
        btnEn.style.transition = transition;

        if (lang === 'ru') {
            btnRu.style.opacity = '1';
            btnRu.style.transform = 'scale(1.1)';
            btnRu.style.filter = 'drop-shadow(0 0 8px rgba(255,255,255,0.3))';
            
            btnEn.style.opacity = '0.4';
            btnEn.style.transform = 'scale(0.9)';
            btnEn.style.filter = 'none';
            
            btnRu.querySelector('span')?.classList.add('font-bold');
            btnEn.querySelector('span')?.classList.remove('font-bold');
        } else {
            btnEn.style.opacity = '1';
            btnEn.style.transform = 'scale(1.1)';
            btnEn.style.filter = 'drop-shadow(0 0 8px rgba(255,255,255,0.3))';
            
            btnRu.style.opacity = '0.4';
            btnRu.style.transform = 'scale(0.9)';
            btnRu.style.filter = 'none';
            
            btnEn.querySelector('span')?.classList.add('font-bold');
            btnRu.querySelector('span')?.classList.remove('font-bold');
        }
    }
}
window.updateLangSlider = updateLangSlider;

function setLoginLanguage(lang) {
    document.cookie = "guest_lang=" + lang + "; path=/; max-age=31536000";
    updateLangSlider(lang);

    if (typeof I18N_ALL !== 'undefined' && I18N_ALL[lang]) {
        const dict = I18N_ALL[lang];
        window.I18N = dict; 

        const elements = document.querySelectorAll('[data-i18n]');
        elements.forEach(el => {
            el.style.transition = 'opacity 0.2s ease';
            el.style.opacity = '0';
        });

        setTimeout(() => {
            elements.forEach(el => {
                const key = el.getAttribute('data-i18n');
                if (dict[key]) {
                    if (el.tagName === 'INPUT') el.placeholder = dict[key];
                    else el.innerHTML = dict[key];
                }
                el.style.opacity = '1';
            });
            
            if (dict.web_title) document.title = dict.web_title;
            
            const gh = document.querySelector('a[title="GitHub"]');
            if(gh && dict['login_github_tooltip']) gh.title = dict['login_github_tooltip'];
            
            const sp = document.querySelector('button[title="Support"]');
            if(sp && dict['login_support_tooltip']) sp.title = dict['login_support_tooltip'];
        }, 200);
    }
}
window.setLoginLanguage = setLoginLanguage;

function toggleLoginLanguage(checkbox) {
    const lang = checkbox.checked ? 'en' : 'ru';
    setLoginLanguage(lang);
}

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
    const backArrow = document.getElementById('back-arrow');
    
    [magic, password, reset, setPass].forEach(el => el?.classList.add('hidden'));
    if (errorBlock) errorBlock.classList.add('hidden');

    const show = (el) => {
        if (!el) return;
        el.classList.remove('hidden');
        el.classList.remove('animate-fade-in-up');
        void el.offsetWidth; // trigger reflow
        el.classList.add('animate-fade-in-up');
    };

    // Show/Hide Back Arrow based on context
    if (backArrow) {
        if (target === 'password') {
            backArrow.classList.remove('hidden');
            backArrow.onclick = () => toggleForms('magic');
        } else if (target === 'reset') {
            backArrow.classList.remove('hidden');
            backArrow.onclick = () => toggleForms('password');
        } else {
            backArrow.classList.add('hidden');
        }
    }

    if (target === 'password') show(password);
    else if (target === 'reset') show(reset);
    else if (target === 'set-password') show(setPass);
    else show(magic);
}

// --- API: Reset Password Request ---
async function requestPasswordReset() {
    const userIdInput = document.getElementById('reset_user_id');
    const btn = document.getElementById('btn-reset-send');
    const errorBlock = document.getElementById('reset-error-block');
    const adminLinkBtn = document.getElementById('admin-link-btn');
    const container = document.getElementById('forms-container');
    const backArrow = document.getElementById('back-arrow');

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
            // Hide back arrow on success screen
            if (backArrow) backArrow.classList.add('hidden');

            const title = (I18N && I18N.login_link_sent_title) || "Link Sent!";
            const desc = (I18N && I18N.login_link_sent_desc) || "Check your Telegram messages.";
            const btnText = (I18N && I18N.login_go_to_bot) || "Go to Bot";
            const botLink = (typeof BOT_USERNAME !== 'undefined' && BOT_USERNAME) ? `https://t.me/${BOT_USERNAME}` : "#";

            // ИСПРАВЛЕНО: Кнопка "Перейти в бот" вместо назад
            container.innerHTML = `
                <div class="text-center py-8 animate-fade-in-up">
                    <div class="w-16 h-16 bg-yellow-500/20 rounded-full flex items-center justify-center mx-auto mb-4 border border-yellow-500/30">
                        <svg class="w-8 h-8 text-yellow-400 transform rotate-45 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path>
                        </svg>
                    </div>
                    <h3 class="text-lg font-bold text-white mb-2">${title}</h3>
                    <p class="text-sm text-gray-300">${desc}</p>
                    <a href="${botLink}" target="_blank" class="inline-block mt-6 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-bold transition shadow-lg shadow-blue-500/20">${btnText}</a>
                </div>
            `;
        } else {
            if (data.error === 'not_found' && errorBlock) {
                const errMsg = (I18N && I18N.login_error_user_not_found) || "User not found.";
                const errP = errorBlock.querySelector('p');
                if(errP) errP.textContent = errMsg;
                
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
            const title = (I18N && I18N.reset_success_title) || "Success!";
            const desc = (I18N && I18N.reset_success_desc) || "Password changed successfully.";
            const btnText = (I18N && I18N.web_login_btn) || "Login";

            container.innerHTML = `
                <div class="text-center py-8 animate-fade-in-up">
                    <div class="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4 border border-green-500/30">
                        <svg class="w-8 h-8 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <h3 class="text-lg font-bold text-white mb-2">${title}</h3>
                    <p class="text-sm text-gray-300">${desc}</p>
                    <a href="/login" class="w-full block text-center mt-6 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded-xl font-bold text-white shadow-lg transition">${btnText}</a>
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
    if (typeof CURRENT_LANG !== 'undefined' && typeof updateLangSlider === 'function') {
        updateLangSlider(CURRENT_LANG);
    }

    if (typeof I18N !== 'undefined' && I18N.web_title) {
        document.title = I18N.web_title;
    }

    if (window.twemoji) window.twemoji.parse(document.body, { folder: 'svg', ext: '.svg' });

    if (typeof I18N !== 'undefined') {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (I18N[key]) {
                if (el.tagName === 'INPUT') el.placeholder = I18N[key];
                else el.innerHTML = I18N[key];
            }
            if (el.title && I18N[key]) el.title = I18N[key];
        });
        
        const gh = document.querySelector('a[title="GitHub"]');
        if(gh && I18N['login_github_tooltip']) gh.title = I18N['login_github_tooltip'];
        const sp = document.querySelector('button[title="Support"]');
        if(sp && I18N['login_support_tooltip']) sp.title = I18N['login_support_tooltip'];
    }

    // 4. Handle URL Params
    const urlParams = new URLSearchParams(window.location.search);
    const formsContainer = document.getElementById('forms-container');
    const backArrow = document.getElementById('back-arrow');
    
    if (urlParams.get('sent') === 'true' && formsContainer) {
        if (backArrow) backArrow.classList.add('hidden'); // Hide arrow on success

        const title = (I18N && I18N.login_link_sent_title) || "Magic Link Sent!";
        const desc = (I18N && I18N.login_link_sent_desc) || "Check your Telegram messages.";
        const btnText = (I18N && I18N.login_go_to_bot) || "Go to Bot";
        const botLink = (typeof BOT_USERNAME !== 'undefined' && BOT_USERNAME) ? `https://t.me/${BOT_USERNAME}` : "#";

        // ИСПРАВЛЕНО: Кнопка "Перейти в бот" вместо назад
        formsContainer.innerHTML = `
            <div class="text-center py-8 animate-fade-in-up">
                <div class="w-16 h-16 bg-blue-500/20 rounded-full flex items-center justify-center mx-auto mb-4 border border-blue-500/30">
                    <svg class="w-8 h-8 text-blue-400 transform rotate-45 -ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path>
                    </svg>
                </div>
                <h3 class="text-lg font-bold text-white mb-2">${title}</h3>
                <p class="text-sm text-gray-300">${desc}</p>
                <a href="${botLink}" target="_blank" class="inline-block mt-6 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-bold transition shadow-lg shadow-blue-500/20">${btnText}</a>
            </div>
        `;
    } else if (urlParams.get('token')) {
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
    
    const isIp = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/.test(window.location.hostname);
    const isLocalhost = window.location.hostname === 'localhost';
    const isHttps = window.location.protocol === 'https:';
    
    if (botUsername && !isIp && !isLocalhost && isHttps && container && magicForm) {
        const script = document.createElement('script');
        script.async = true;
        script.src = "https://telegram.org/js/telegram-widget.js?22";
        script.setAttribute('data-telegram-login', botUsername);
        script.setAttribute('data-size', 'large');
        script.setAttribute('data-radius', '12');
        script.setAttribute('data-onauth', 'onTelegramAuth(user)');
        script.setAttribute('data-request-access', 'write');
        container.appendChild(script);
        container.classList.remove('hidden');
        magicForm.classList.add('hidden');
    }
});