function toggleForms(target) {
    const magic = document.getElementById('magic-form');
    const password = document.getElementById('password-form');
    const reset = document.getElementById('reset-form');
    const setPass = document.getElementById('set-password-form');
    const errorBlock = document.getElementById('reset-error-block');
    
    // Скрываем всё, если элементы существуют
    if (magic) magic.classList.add('hidden');
    if (password) password.classList.add('hidden');
    if (reset) reset.classList.add('hidden');
    if (setPass) setPass.classList.add('hidden');
    if (errorBlock) errorBlock.classList.add('hidden');

    // Показываем нужное
    if (target === 'password' && password) {
        password.classList.remove('hidden');
    } else if (target === 'reset' && reset) {
        reset.classList.remove('hidden');
    } else if (target === 'set-password' && setPass) {
        setPass.classList.remove('hidden');
    } else if (magic) {
        magic.classList.remove('hidden');
    }
}

// Запрос на сброс (отправка ссылки в ТГ)
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
    btn.innerText = "Загрузка...";
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
                <div class="text-center py-4 animate-pulse">
                    <div class="w-16 h-16 bg-yellow-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg class="w-8 h-8 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
                    </div>
                    <h3 class="text-lg font-bold text-white mb-2">Ссылка отправлена!</h3>
                    <p class="text-sm text-gray-300">Проверьте сообщения от бота.</p>
                    <a href="/login" class="inline-block mt-4 text-xs text-blue-400 hover:text-blue-300">Вернуться</a>
                </div>
            `;
        } else {
            if (data.error === 'not_found' && errorBlock) {
                errorBlock.classList.remove('hidden');
                if (data.admin_url && adminLinkBtn) {
                    adminLinkBtn.href = data.admin_url;
                }
            } else {
                // Using the new modal!
                if (window.showModalAlert) {
                    await window.showModalAlert("Ошибка: " + (data.error || "Unknown"), 'Ошибка');
                } else {
                    alert("Ошибка: " + (data.error || "Unknown"));
                }
            }
        }
    } catch (e) {
        if (window.showModalAlert) {
            await window.showModalAlert("Ошибка соединения: " + e, 'Ошибка сети');
        } else {
            alert("Ошибка соединения: " + e);
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    }
}

// Сохранение нового пароля (по токену)
async function submitNewPassword() {
    const p1 = document.getElementById('new_pass').value;
    const p2 = document.getElementById('confirm_pass').value;
    const btn = document.getElementById('btn-save-pass');
    const container = document.getElementById('forms-container');
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');

    if (!p1 || p1.length < 4) {
        if (window.showModalAlert) await window.showModalAlert("Пароль слишком короткий (минимум 4 символа).", 'Ошибка');
        else alert("Пароль слишком короткий (минимум 4 символа).");
        return;
    }
    if (p1 !== p2) {
        if (window.showModalAlert) await window.showModalAlert("Пароли не совпадают.", 'Ошибка');
        else alert("Пароли не совпадают.");
        return;
    }

    btn.disabled = true;
    btn.innerText = "Сохранение...";

    try {
        const res = await fetch('/api/reset/confirm', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ token: token, password: p1 })
        });
        
        const data = await res.json();
        if (res.ok) {
            container.innerHTML = `
                <div class="text-center py-4">
                    <div class="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg class="w-8 h-8 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    </div>
                    <h3 class="text-lg font-bold text-white mb-2">Успешно!</h3>
                    <p class="text-sm text-gray-300">Пароль изменен.</p>
                    <a href="/login" class="w-full block text-center mt-6 py-3 bg-white/10 hover:bg-white/20 rounded-xl font-bold transition">Войти</a>
                </div>
            `;
            window.history.replaceState({}, document.title, "/login");
        } else {
            if (window.showModalAlert) await window.showModalAlert("Ошибка: " + data.error, 'Ошибка');
            else alert("Ошибка: " + data.error);
            btn.disabled = false;
            btn.innerText = "Сохранить пароль";
        }
    } catch (e) {
        if (window.showModalAlert) await window.showModalAlert("Ошибка сети: " + e, 'Ошибка сети');
        else alert("Ошибка сети: " + e);
        btn.disabled = false;
        btn.innerText = "Сохранить пароль";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    if (window.twemoji) {
        window.twemoji.parse(document.body, { folder: 'svg', ext: '.svg' });
    }

    const urlParams = new URLSearchParams(window.location.search);
    const formsContainer = document.getElementById('forms-container');
    
    if (urlParams.get('sent') === 'true' && formsContainer) {
        formsContainer.innerHTML = `
            <div class="text-center py-4 animate-pulse">
                <div class="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                    <svg class="w-8 h-8 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                </div>
                <h3 class="text-lg font-bold text-white mb-2">Готово!</h3>
                <p class="text-sm text-gray-300">Ссылка отправлена в Telegram.</p>
                <p class="text-xs text-gray-500 mt-4">Проверьте сообщения от бота.</p>
                <a href="/login" class="inline-block mt-4 text-xs text-blue-400 hover:text-blue-300">Вернуться</a>
            </div>
        `;
    } else if (urlParams.get('token')) {
        // Проверяем, есть ли форма смены пароля на странице (чтобы не вызывать на login.html)
        if (document.getElementById('set-password-form')) {
            toggleForms('set-password');
        }
    }
});