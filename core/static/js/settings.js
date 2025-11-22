document.addEventListener("DOMContentLoaded", () => {
    renderUsers();
    initSystemSettingsTracking(); // Запускаем отслеживание изменений
});

let initialSysConfig = {};

function initSystemSettingsTracking() {
    const inputs = ['conf_cpu', 'conf_ram', 'conf_disk', 'conf_traffic', 'conf_timeout'];
    const btn = document.getElementById('saveSysBtn');
    
    if (!btn) return;

    // При инициализации сохраняем исходные значения
    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            initialSysConfig[id] = el.value;
            // Вешаем обработчики
            el.addEventListener('input', checkForChanges);
            el.addEventListener('change', checkForChanges); // Для range слайдеров важно событие change
        }
    });
}

function checkForChanges() {
    const inputs = ['conf_cpu', 'conf_ram', 'conf_disk', 'conf_traffic', 'conf_timeout'];
    let hasChanges = false;
    
    inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el && el.value != initialSysConfig[id]) {
            hasChanges = true;
        }
    });
    
    toggleSystemSaveButton(hasChanges);
}

function toggleSystemSaveButton(enable) {
    const btn = document.getElementById('saveSysBtn');
    if (!btn) return;

    if (enable) {
        btn.disabled = false;
        // Стили активной синей кнопки
        btn.classList.remove('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
        btn.classList.add('bg-blue-600', 'hover:bg-blue-500', 'text-white', 'shadow-lg', 'shadow-blue-900/20', 'active:scale-95', 'cursor-pointer');
    } else {
        btn.disabled = true;
        // Стили неактивной серой кнопки
        btn.classList.remove('bg-blue-600', 'hover:bg-blue-500', 'text-white', 'shadow-lg', 'shadow-blue-900/20', 'active:scale-95', 'cursor-pointer');
        btn.classList.add('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
    }
}

// --- СИСТЕМНЫЕ НАСТРОЙКИ (AJAX) ---
async function saveSystemConfig() {
    const btn = document.getElementById('saveSysBtn');
    if (!btn) return;
    
    const originalText = I18N.web_save_btn; // Берем из перевода, так как текст может быть изменен
    btn.innerText = I18N.web_saving_btn;
    btn.disabled = true;

    const data = {
        CPU_THRESHOLD: document.getElementById('conf_cpu').value,
        RAM_THRESHOLD: document.getElementById('conf_ram').value,
        DISK_THRESHOLD: document.getElementById('conf_disk').value,
        TRAFFIC_INTERVAL: document.getElementById('conf_traffic').value,
        NODE_OFFLINE_TIMEOUT: document.getElementById('conf_timeout').value
    };

    try {
        const res = await fetch('/api/settings/system', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        
        if(res.ok) {
            // Обновляем исходные значения на текущие (так как мы сохранили)
            ['conf_cpu', 'conf_ram', 'conf_disk', 'conf_traffic', 'conf_timeout'].forEach(id => {
                 const el = document.getElementById(id);
                 if(el) initialSysConfig[id] = el.value;
            });

            // Анимация успеха (Зеленая кнопка "Сохранено")
            btn.innerText = I18N.web_saved_btn;
            btn.classList.remove('bg-blue-600', 'hover:bg-blue-500'); // Удаляем синий (если был)
            btn.classList.remove('bg-gray-200', 'dark:bg-gray-700');   // Удаляем серый (на всякий)
            btn.classList.add('bg-green-600', 'hover:bg-green-500', 'text-white');
            
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.remove('bg-green-600', 'hover:bg-green-500', 'text-white');
                // После сохранения кнопка должна стать серой (неактивной), т.к. изменений нет
                toggleSystemSaveButton(false);
            }, 2000);
        } else {
            const json = await res.json();
            alert(I18N.web_error.replace('{error}', json.error || 'Save failed'));
            // В случае ошибки возвращаем кнопку в активное состояние (синяя), чтобы можно было поправить
            btn.innerText = originalText;
            toggleSystemSaveButton(true);
        }
    } catch(e) {
        console.error(e);
        alert(I18N.web_conn_error.replace('{error}', e));
        btn.innerText = originalText;
        toggleSystemSaveButton(true);
    }
}

async function clearLogs() {
    if(!confirm(I18N.web_clear_logs_confirm)) return;
    
    const btn = document.getElementById('clearLogsBtn');
    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerText = "Clearing...";
    
    try {
        const res = await fetch('/api/logs/clear', { method: 'POST' });
        if(res.ok) {
            btn.innerText = "Cleared!";
            btn.classList.remove('text-red-600', 'dark:text-red-400', 'bg-red-500/10', 'border-red-500/30');
            btn.classList.add('text-green-600', 'dark:text-green-400', 'bg-green-500/10', 'border-green-500/30');
            
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.classList.remove('text-green-600', 'dark:text-green-400', 'bg-green-500/10', 'border-green-500/30');
                btn.classList.add('text-red-600', 'dark:text-red-400', 'bg-red-500/10', 'border-red-500/30');
                btn.disabled = false;
            }, 2000);
        } else {
            alert("Failed");
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    } catch(e) {
        alert(I18N.web_conn_error.replace('{error}', e));
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}

// --- АВТОСОХРАНЕНИЕ УВЕДОМЛЕНИЙ ---
async function triggerAutoSave() {
    const statusEl = document.getElementById('notifStatus');
    if(statusEl) {
        statusEl.innerText = I18N.web_saving_btn; // "Saving..."
        statusEl.classList.remove('text-green-500', 'text-red-500', 'opacity-0');
        statusEl.classList.add('text-gray-500', 'dark:text-gray-400', 'opacity-100');
    }

    setTimeout(async () => {
        const data = {
            resources: document.getElementById('alert_resources').checked,
            logins: document.getElementById('alert_logins').checked,
            bans: document.getElementById('alert_bans').checked,
            downtime: document.getElementById('alert_downtime').checked
        };

        try {
            const res = await fetch('/api/settings/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            
            if(statusEl) {
                if(res.ok) {
                    statusEl.innerText = I18N.web_saved_btn; // "Saved!"
                    statusEl.classList.remove('text-gray-500', 'dark:text-gray-400');
                    statusEl.classList.add('text-green-500');
                    setTimeout(() => {
                        statusEl.classList.add('opacity-0');
                    }, 2000);
                } else {
                    statusEl.innerText = "Error";
                    statusEl.classList.add('text-red-500');
                }
            }
        } catch(e) {
            console.error(e);
            if(statusEl) {
                statusEl.innerText = "Conn Error";
                statusEl.classList.add('text-red-500');
            }
        }
    }, 50);
}

// --- ПОЛЬЗОВАТЕЛИ ---
function renderUsers() {
    const tbody = document.getElementById('usersTableBody');
    const section = document.getElementById('usersSection');
    
    if (USERS_DATA === null) return; 

    section.classList.remove('hidden');
    
    if (USERS_DATA.length > 0) {
        tbody.innerHTML = USERS_DATA.map(u => `
            <tr class="border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition">
                <td class="px-4 py-3 font-mono text-xs text-gray-500 dark:text-gray-400">${u.id}</td>
                <td class="px-4 py-3 font-medium text-gray-900 dark:text-white">${u.name}</td>
                <td class="px-4 py-3">
                    <span class="px-2 py-0.5 rounded text-[10px] border ${u.role === 'admins' ? 'border-green-500/30 bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400' : 'border-gray-300 dark:border-gray-500/30 bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-300'}">
                        ${u.role}
                    </span>
                </td>
                <td class="px-4 py-3 text-right">
                    <button onclick="deleteUser(${u.id})" class="text-red-500 hover:text-red-700 dark:hover:text-red-300 transition p-1" title="Delete">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </td>
            </tr>
        `).join('');
    } else {
        tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-3 text-center text-gray-500 text-xs">${I18N.web_no_users}</td></tr>`;
    }
}

async function deleteUser(id) {
    if(!confirm(I18N.web_confirm_delete_user.replace('{id}', id))) return;
    
    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'delete', id: id})
        });
        
        if(res.ok) {
            const idx = USERS_DATA.findIndex(u => u.id == id);
            if(idx > -1) USERS_DATA.splice(idx, 1);
            renderUsers();
        } else {
            alert(I18N.web_error.replace('{error}', 'Delete failed'));
        }
    } catch(e) {
        alert(I18N.web_conn_error.replace('{error}', e));
    }
}

async function openAddUserModal() {
    const id = prompt("Telegram ID:"); 
    if(!id) return;
    
    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'add', id: id, role: 'users'})
        });
        
        const data = await res.json();
        if(res.ok) {
            USERS_DATA.push({id: id, name: data.name || `ID: ${id}`, role: 'users'});
            renderUsers();
        } else {
            alert(I18N.web_error.replace('{error}', data.error || "Unknown"));
        }
    } catch(e) {
        alert(I18N.web_conn_error.replace('{error}', e));
    }
}

async function addNode() {
    const nameInput = document.getElementById('newNodeName');
    const name = nameInput.value.trim();
    if(!name) return alert("Name required");
    
    try {
        const res = await fetch('/api/nodes/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name})
        });
        
        const data = await res.json();
        if(res.ok) {
            document.getElementById('nodeResult').classList.remove('hidden');
            document.getElementById('newNodeToken').innerText = data.token;
            document.getElementById('newNodeCmd').innerText = data.command;
            nameInput.value = "";
        } else {
            alert(I18N.web_error.replace('{error}', data.error));
        }
    } catch(e) {
        alert(I18N.web_conn_error.replace('{error}', e));
    }
}