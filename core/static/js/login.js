function toggleForms(target) {
    const magic = document.getElementById('magic-form');
    const password = document.getElementById('password-form');
    
    if (target === 'password') {
        magic.classList.add('hidden');
        password.classList.remove('hidden');
    } else {
        password.classList.add('hidden');
        magic.classList.remove('hidden');
    }
}

document.addEventListener("DOMContentLoaded", () => {
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