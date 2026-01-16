/* /core/static/js/reset_password.js */

document.addEventListener('DOMContentLoaded', () => {
    // --- Локализация ---
    const pageTitle = document.getElementById('page-title');
    if (pageTitle) pageTitle.innerText = I18N.reset_page_title || "Reset Password";
    
    const brandName = document.getElementById('brand-name');
    if (brandName) brandName.innerText = I18N.web_brand_name || "VPS Manager";
    
    const lblNew = document.getElementById('lbl-new-pass');
    if (lblNew) lblNew.innerText = I18N.web_new_password || "New Password";
    
    const lblConfirm = document.getElementById('lbl-confirm-pass');
    if (lblConfirm) lblConfirm.innerText = I18N.web_confirm_password || "Confirm Password";
    
    const btnText = document.getElementById('btn-text');
    if (btnText) btnText.innerText = I18N.web_save_btn || "Save";
    
    const txtHintLen = document.getElementById('txt-hint-len');
    if (txtHintLen) txtHintLen.innerText = I18N.pass_req_length || "Min 8 chars";
    
    const txtHintNum = document.getElementById('txt-hint-num');
    if (txtHintNum) txtHintNum.innerText = I18N.pass_req_num || "Min 1 digit";

    // --- Элементы формы ---
    const passInput = document.getElementById('new_pass');
    const confirmInput = document.getElementById('confirm_pass');
    const submitBtn = document.getElementById('btn-save');
    const matchError = document.getElementById('match-error');
    
    // --- Индикаторы ---
    const strengthBar = document.getElementById('strength-bar');
    const strengthText = document.getElementById('strength-text');
    const hintLen = document.getElementById('hint-len');
    const hintNum = document.getElementById('hint-num');

    // --- Логика проверки пароля ---
    function checkStrength(password) {
        let score = 0;
        // 1. Длина
        if (password.length >= 8) {
            score += 1;
            hintLen.classList.remove('text-gray-500');
            hintLen.classList.add('text-green-400');
        } else {
            hintLen.classList.remove('text-green-400');
            hintLen.classList.add('text-gray-500');
        }
        
        // 2. Цифры
        if (/\d/.test(password)) {
            score += 1;
            hintNum.classList.remove('text-gray-500');
            hintNum.classList.add('text-green-400');
        } else {
            hintNum.classList.remove('text-green-400');
            hintNum.classList.add('text-gray-500');
        }

        // Дополнительные баллы
        if (password.length >= 12) score += 1;
        if (/[!@#$%^&*]/.test(password)) score += 1;

        // Визуализация
        let width = '0%';
        let color = 'bg-red-500';
        let label = "";

        if (password.length === 0) {
            width = '0%';
        } else if (score < 2) {
            width = '33%';
            color = 'bg-red-500';
            label = I18N.pass_strength_weak || "Weak";
        } else if (score < 3) {
            width = '66%';
            color = 'bg-yellow-500';
            label = I18N.pass_strength_fair || "Normal";
        } else {
            width = '100%';
            color = 'bg-green-500';
            label = I18N.pass_strength_strong || "Strong";
        }

        strengthBar.style.width = width;
        strengthBar.className = `h-full transition-all duration-500 ease-out ${color}`;
        strengthText.innerText = label;

        return score >= 2; // Минимальное требование: длина + цифра
    }

    function validateMatch() {
        if (confirmInput.value && passInput.value !== confirmInput.value) {
            matchError.innerText = I18N.pass_match_error || "Passwords do not match";
            matchError.classList.remove('hidden');
            confirmInput.classList.add('border-red-500');
            confirmInput.classList.remove('border-white/10');
            return false;
        } else {
            matchError.classList.add('hidden');
            confirmInput.classList.remove('border-red-500');
            confirmInput.classList.add('border-white/10');
            return true;
        }
    }

    function updateState() {
        const isStrong = checkStrength(passInput.value);
        const isMatch = validateMatch();
        const isFilled = passInput.value.length > 0 && confirmInput.value.length > 0;
        
        if (submitBtn) {
            submitBtn.disabled = !(isStrong && isMatch && isFilled);
        }
    }

    if (passInput) passInput.addEventListener('input', updateState);
    if (confirmInput) confirmInput.addEventListener('input', updateState);

    // --- Модальное окно ---
    const modal = document.getElementById('systemModal');
    const modalTitle = document.getElementById('sysModalTitle');
    const modalMsg = document.getElementById('sysModalMessage');
    const modalOk = document.getElementById('sysModalOk');
    let modalResolve = null;

    window.showAlert = function(msg) {
        return new Promise(resolve => {
            modalResolve = resolve;
            modalTitle.innerText = I18N.modal_title_alert || "Alert";
            modalMsg.innerText = msg;
            modalOk.innerText = I18N.modal_btn_ok || "OK";
            
            modal.classList.remove('hidden');
            requestAnimationFrame(() => {
                modal.classList.remove('opacity-0');
                modal.querySelector('div').classList.remove('scale-95');
                modal.querySelector('div').classList.add('scale-100');
            });
        });
    };

    if (modalOk) {
        modalOk.addEventListener('click', () => {
            modal.classList.add('opacity-0');
            modal.querySelector('div').classList.remove('scale-100');
            modal.querySelector('div').classList.add('scale-95');
            setTimeout(() => {
                modal.classList.add('hidden');
                if (modalResolve) modalResolve();
            }, 300);
        });
    }

    // --- Отправка формы ---
    window.resetConfirm = async function() {
        const pwd = passInput.value;
        const confirm = confirmInput.value;

        if (!pwd || !confirm) {
            await showAlert(I18N.pass_is_empty || "Fill all fields");
            return;
        }
        if (pwd !== confirm) {
            await showAlert(I18N.pass_match_error || "Mismatch");
            return;
        }
        if (!checkStrength(pwd)) {
            await showAlert("Password is too weak");
            return;
        }

        const originalText = document.getElementById('btn-text').innerText;
        document.getElementById('btn-text').innerText = "...";
        submitBtn.disabled = true;

        try {
            // Используем глобальную переменную RESET_TOKEN, внедренную в HTML
            const token = (typeof RESET_TOKEN !== 'undefined') ? RESET_TOKEN : (new URLSearchParams(window.location.search).get('token'));

            const res = await fetch('/api/reset/confirm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token: token, password: pwd })
            });
            
            const data = await res.json();
            
            if (res.ok) {
                await showAlert(I18N.web_pass_changed || "Password changed!");
                window.location.href = '/login';
            } else {
                await showAlert(I18N.web_error + ": " + (data.error || "Unknown"));
                document.getElementById('btn-text').innerText = originalText;
                submitBtn.disabled = false;
            }
        } catch (e) {
            await showAlert(I18N.web_conn_error || "Connection error");
            document.getElementById('btn-text').innerText = originalText;
            submitBtn.disabled = false;
        }
    };
});