/* /core/static/js/login.js */

// --- COOKIE & LANG LOGIC ---
document.addEventListener("DOMContentLoaded", () => {
    initLanguage();
    checkCookieConsent();
    initLoginInputs();
});

// --- LANGUAGE ---
async function setLoginLanguage(lang) {
    // Сохраняем выбор в LocalStorage (чтобы запомнить "навсегда" на клиенте)
    localStorage.setItem('user_lang_choice', lang);
    
    // Отправляем запрос на сервер для смены языка сессии/контекста (если нужно)
    try {
        await fetch('/api/settings/language', { 
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify({ lang: lang }) 
        });
    } catch (e) { console.error(e); }

    // Перезагружаем страницу чтобы применились переводы (так как login.html рендерится сервером)
    window.location.reload(); 
}

function initLanguage() {
    // Проверяем, есть ли сохраненный выбор
    const savedLang = localStorage.getItem('user_lang_choice');
    
    // Если есть сохраненный язык, и он отличается от текущего (можно проверить через I18N, но проще не усложнять на логине),
    // то сервер уже должен был его подхватить если мы его туда отправляли.
    // Но так как это страница логина, она может быть анонимной. 
    // Если сервер не знает языка, можно попробовать форсировать релоад один раз, но это может вызвать циклы.
    // Поэтому просто оставляем кнопки выбора доступными.
}

// --- COOKIE BANNER ---
function checkCookieConsent() {
    const consent = localStorage.getItem('cookie_consent');
    if (!consent) {
        // Показываем баннер с небольшой задержкой для анимации
        setTimeout(() => {
            const banner = document.getElementById('cookie-banner');
            if (banner) {
                banner.classList.remove('hidden');
                banner.classList.add('animate-fade-in-up'); // Ensure you have this animation or generic transition
            }
        }, 1000);
    }
}

function acceptCookies() {
    localStorage.setItem('cookie_consent', 'true');
    const banner = document.getElementById('cookie-banner');
    if (banner) {
        banner.classList.add('opacity-0', 'translate-y-10', 'transition-all', 'duration-500');
        setTimeout(() => banner.remove(), 500);
    }
}
window.acceptCookies = acceptCookies;
window.setLoginLanguage = setLoginLanguage;

// --- SUPPORT MODAL ---
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


// --- EXISTING LOGIN LOGIC ---
function initLoginInputs() {
    const idInput = document.getElementById('login_id');
    const passInput = document.getElementById('login_pass');

    // Auto-focus logic
    if (idInput && !idInput.value) {
        idInput.focus();
    } else if (passInput) {
        passInput.focus();
    }

    // Enter key support
    const handleEnter = (e) => { if(e.key === 'Enter') performLogin(); };
    if(idInput) idInput.addEventListener('keydown', handleEnter);
    if(passInput) passInput.addEventListener('keydown', handleEnter);
}

async function performLogin() {
    const idInput = document.getElementById('login_id');
    const passInput = document.getElementById('login_pass');
    const btn = document.getElementById('btn_login');
    const errorDiv = document.getElementById('login_error');
    const errorText = document.getElementById('login_error_text');

    if (!idInput || !passInput || !btn) return;

    const id = idInput.value.trim();
    const password = passInput.value.trim();

    if (!id || !password) {
        showLoginError("Please enter ID and Password");
        return;
    }

    // UI Loading state
    const originalBtnContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    errorDiv.classList.add('hidden');

    try {
        const response = await fetch('/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: id, password: password })
        });

        const data = await response.json();

        if (response.ok) {
            // Success
            btn.classList.remove('from-blue-600', 'to-purple-600');
            btn.classList.add('bg-green-500');
            btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>`;
            
            setTimeout(() => {
                window.location.href = data.redirect || '/dashboard';
            }, 500);
        } else {
            // Error
            showLoginError(data.error || "Login failed");
            btn.disabled = false;
            btn.innerHTML = originalBtnContent;
        }
    } catch (error) {
        showLoginError("Connection error");
        btn.disabled = false;
        btn.innerHTML = originalBtnContent;
    }
}

function showLoginError(msg) {
    const errorDiv = document.getElementById('login_error');
    const errorText = document.getElementById('login_error_text');
    if (errorDiv && errorText) {
        errorText.innerText = msg;
        errorDiv.classList.remove('hidden');
        errorDiv.classList.add('animate-shake'); // Ensure you have this animation in CSS or remove class
        setTimeout(() => errorDiv.classList.remove('animate-shake'), 500);
    }
}