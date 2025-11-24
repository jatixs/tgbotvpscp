document.addEventListener("DOMContentLoaded", () => {
    renderUsers();
    initSystemSettingsTracking();
});

// Храним начальные значения раздельно для каждой группы
const initialConfig = {
    thresholds: {},
    intervals: {}
};

// Конфигурация групп полей
const groups = {
    thresholds: {
        ids: ['conf_cpu', 'conf_ram', 'conf_disk'],
        btnId: 'saveThresholdsBtn'
    },
    intervals: {
        ids: ['conf_traffic', 'conf_timeout'],
        btnId: 'saveIntervalsBtn'
    }
};

function initSystemSettingsTracking() {
    // Инициализируем каждую группу
    for (const [groupName, config] of Object.entries(groups)) {
        const btn = document.getElementById(config.btnId);
        if (!btn) continue;

        config.ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                // Сохраняем начальное значение
                initialConfig[groupName][id] = el.value;
                
                // Навешиваем слушатели
                el.addEventListener('input', () => checkForChanges(groupName));
                el.addEventListener('change', () => checkForChanges(groupName));
            }
        });
    }
}

function showError(fieldId, message) {
    const errorEl = document.getElementById('error_' + fieldId);
    if (errorEl) {
        errorEl.innerText = message;
        errorEl.classList.remove('hidden');
    }
}

function checkForChanges(groupName) {
    const config = groups[groupName];
    let hasChanges = false;
    
    config.ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            // Обновляем визуальные значения ползунков (только для порогов)
            if (groupName === 'thresholds') { 
                const displayId = id.replace('conf_', 'val_') + '_display';
                const displayEl = document.getElementById(displayId);
                if (displayEl) {
                    displayEl.innerText = el.value + '%';
                }
            }

            // Сравниваем с начальным значением этой группы
            if (el.value != initialConfig[groupName][id]) {
                hasChanges = true;
            }
        }
    });
    
    toggleSaveButton(config.btnId, hasChanges);
}

function toggleSaveButton(btnId, enable) {
    const btn = document.getElementById(btnId);
    if (!btn) return;

    if (enable) {
        btn.disabled = false;
        btn.classList.remove('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
        btn.classList.add('bg-blue-600', 'hover:bg-blue-500', 'text-white', 'shadow-lg', 'shadow-blue-900/20', 'active:scale-95', 'cursor-pointer');
    } else {
        btn.disabled = true;
        btn.classList.remove('bg-blue-600', 'hover:bg-blue-500', 'text-white', 'shadow-lg', 'shadow-blue-900/20', 'active:scale-95', 'cursor-pointer');
        btn.classList.add('bg-gray-200', 'dark:bg-gray-700', 'text-gray-400', 'dark:text-gray-500', 'cursor-not-allowed');
    }
}

async function saveSystemConfig(groupName) {
    const config = groups[groupName];
    const btn = document.getElementById(config.btnId);
    if (!btn) return;
    
    const originalText = I18N.web_save_btn;
    
    // Блокируем кнопку и показываем процесс
    btn.innerText = I18N.web_saving_btn;
    btn.disabled = true;

    // Скрываем ошибки
    document.querySelectorAll('[id^="error_"]').forEach(el => el.classList.add('hidden'));

    // Валидация (специфична для интервалов)
    if (groupName === 'intervals') {
        const trafficVal = parseInt(document.getElementById('conf_traffic').value);
        if (trafficVal < 5) {
            showError('conf_traffic', I18N.error_traffic_interval_low);
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
            return;
        }
        if (trafficVal > 100) {
            showError('conf_traffic', I18N.error_traffic_interval_high);
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
            return;
        }
    }

    // Собираем данные (отправляем всё, чтобы не затереть другие настройки на бэкенде)
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
            // Обновляем "начальные" значения для ВСЕХ групп, так как сохранение прошло успешно
            for (const [grp, cfg] of Object.entries(groups)) {
                cfg.ids.forEach(id => {
                    const el = document.getElementById(id);
                    if(el) initialConfig[grp][id] = el.value;
                });
            }

            // Анимация успеха
            btn.innerText = I18N.web_saved_btn;
            btn.classList.remove('bg-blue-600', 'hover:bg-blue-500');
            btn.classList.remove('bg-gray-200', 'dark:bg-gray-700');
            btn.classList.add('bg-green-600', 'hover:bg-green-500', 'text-white');
            
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.remove('bg-green-600', 'hover:bg-green-500', 'text-white');
                // Кнопка остается выключенной, так как изменения сохранены
                toggleSaveButton(config.btnId, false);
            }, 2000);
        } else {
            const json = await res.json();
            alert(I18N.web_error.replace('{error}', json.error || 'Save failed'));
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
        }
    } catch(e) {
        console.error(e);
        alert(I18N.web_conn_error.replace('{error}', e));
        btn.innerText = originalText;
        toggleSaveButton(config.btnId, true);
    }
}

async function clearLogs() {
    if(!confirm(I18N.web_clear_logs_confirm)) return;
    
    const btn = document.getElementById('clearLogsBtn');
    const originalHTML = btn.innerHTML;
    
    // Анимация загрузки
    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-5 w-5 text-red-600 dark:text-red-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${I18N.web_logs_clearing}`;
    
    try {
        const res = await fetch('/api/logs/clear', { method: 'POST' });
        if(res.ok) {
            // ИЗМЕНЕНО: Ярко-зеленая кнопка при успехе
            btn.className = "w-full px-4 py-3 rounded-xl text-sm font-bold transition flex items-center justify-center gap-2 bg-green-600 text-white shadow-lg shadow-green-900/20";
            btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> ${I18N.web_logs_cleared_alert}`;
            
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                // Возврат к красному стилю
                btn.className = "w-full px-4 py-3 bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 active:scale-95 active:bg-red-200 transition-all duration-150 rounded-xl text-sm font-medium flex items-center justify-center gap-2 shadow-sm";
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

async function triggerAutoSave() {
    const statusEl = document.getElementById('notifStatus');
    if(statusEl) {
        statusEl.innerText = I18N.web_saving_btn;
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
                    statusEl.innerText = I18N.web_saved_btn;
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

function renderUsers() {
    const tbody = document.getElementById('usersTableBody');
    const section = document.getElementById('usersSection');
    
    if (USERS_DATA === null) return; 

    section.classList.remove('hidden');
    
    if (USERS_DATA.length > 0) {
        tbody.innerHTML = USERS_DATA.map(u => `
            <tr class="border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition">
                <td class="px-2 sm:px-4 py-3 font-mono text-[10px] sm:text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
                    ${u.id}
                </td>
                <td class="px-2 sm:px-4 py-3 font-medium text-sm text-gray-900 dark:text-white break-all max-w-[100px] sm:max-w-none">
                    ${u.name}
                </td>
                <td class="px-2 sm:px-4 py-3">
                    <span class="px-1.5 sm:px-2 py-0.5 rounded text-[9px] sm:text-[10px] uppercase font-bold border ${u.role === 'admins' ? 'border-green-500/30 bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400' : 'border-gray-300 dark:border-gray-500/30 bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-300'}">
                        ${u.role}
                    </span>
                </td>
                <td class="px-2 sm:px-4 py-3 text-right">
                    <button onclick="deleteUser(${u.id})" class="text-red-500 hover:text-red-700 dark:hover:text-red-300 transition p-1" title="Delete">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </td>
            </tr>
        `).join('');
        
        if (window.parsePageEmojis) window.parsePageEmojis();
        
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

async function changePassword() {
    const current = document.getElementById('pass_current').value;
    const newPass = document.getElementById('pass_new').value;
    const confirm = document.getElementById('pass_confirm').value;
    const btn = document.getElementById('btnChangePass');
    
    if(!current || !newPass || !confirm) return;
    if(newPass !== confirm) {
        alert(I18N.web_pass_mismatch);
        return;
    }
    
    const origText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "...";
    
    try {
        const res = await fetch('/api/settings/password', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                current_password: current,
                new_password: newPass
            })
        });
        
        const data = await res.json();
        
        if(res.ok) {
            alert(I18N.web_pass_changed);
            document.getElementById('pass_current').value = "";
            document.getElementById('pass_new').value = "";
            document.getElementById('pass_confirm').value = "";
        } else {
            alert(I18N.web_error.replace('{error}', data.error));
        }
    } catch(e) {
        alert(I18N.web_conn_error.replace('{error}', e));
    }
    
    btn.disabled = false;
    btn.innerText = origText;
}
