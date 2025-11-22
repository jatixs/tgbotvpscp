function toggleForms(target) {
    const magic = document.getElementById('magic-form');
    const password = document.getElementById('password-form');
    const reset = document.getElementById('reset-form');
    const errorBlock = document.getElementById('reset-error-block');
    
    // Скрываем всё
    magic.classList.add('hidden');
    password.classList.add('hidden');
    if(reset) reset.classList.add('hidden');
    if(errorBlock) errorBlock.classList.add('hidden'); // Сбрасываем ошибку при переключении

    if (target === 'password') {
        password.classList.remove('hidden');
    } else if (target === 'reset') {
        if(reset) reset.classList.remove('hidden');
    } else {
        magic.classList.remove('hidden');
    }
}

// Новая функция для отправки запроса сброса
async function requestPasswordReset() {
    const userIdInput = document.getElementById('reset_user_id');
    const btn = document.getElementById('btn-reset-send');
    const errorBlock = document.getElementById('reset-error-block');
    const adminLinkBtn = document.getElementById('admin-link-btn');
    const container = document.getElementById('forms-container');

    const userId = userIdInput.value.trim();
    if (!userId) {
        userIdInput.focus();
        return;
    }

    // UI: Загрузка
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "Загрузка...";
    errorBlock.classList.add('hidden');

    try {
        const response = await fetch('/api/login/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });

        const data = await response.json();

        if (response.ok) {
            // Успех: Показываем заглушку "Ссылка отправлена"
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
            // Ошибка
            if (data.error === 'not_found') {
                errorBlock.classList.remove('hidden');
                if (data.admin_url) {
                    adminLinkBtn.href = data.admin_url;
                }
            } else {
                alert("Ошибка: " + (data.error || "Unknown"));
            }
        }
    } catch (e) {
        alert("Ошибка соединения: " + e);
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // Парсинг эмодзи (если twemoji подключен)
    if (window.twemoji) {
        window.twemoji.parse(document.body, { folder: 'svg', ext: '.svg' });
    }

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('sent') === 'true') {
        document.getElementById('forms-container').innerHTML = `
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
    }
});