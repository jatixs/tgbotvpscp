/* /core/static/js/settings.js */

const isMainAdmin = (typeof IS_MAIN_ADMIN !== 'undefined') ? IS_MAIN_ADMIN : false;

function decryptData(text) {
    if (!text) return "";
    if (typeof WEB_KEY === 'undefined' || !WEB_KEY) return text;
    try {
        const decoded = atob(text);
        let result = "";
        for (let i = 0; i < decoded.length; i++) {
            const keyChar = WEB_KEY[i % WEB_KEY.length];
            result += String.fromCharCode(decoded.charCodeAt(i) ^ keyChar.charCodeAt(0));
        }
        return result;
    } catch (e) {
        console.error("Decryption error:", e);
        return text;
    }
}

function encryptData(text) {
    if (!text) return "";
    if (typeof WEB_KEY === 'undefined' || !WEB_KEY) return text;
    try {
        let result = "";
        for (let i = 0; i < text.length; i++) {
            const keyChar = WEB_KEY[i % WEB_KEY.length];
            result += String.fromCharCode(text.charCodeAt(i) ^ keyChar.charCodeAt(0));
        }
        return btoa(result);
    } catch (e) {
        console.error("Encryption error:", e);
        return text;
    }
}


window.initSettings = function() {
    renderUsers();
    renderNodes();
    initSystemSettingsTracking();
    renderKeyboardConfig();
    updateBulkButtonsUI();
    initChangePasswordUI();
    fetchSessions();
    initInputScrollLogic();

    const input = document.getElementById('newNodeNameDash');
    if (input) {
        input.addEventListener('input', validateNodeInput);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !document.getElementById('btnAddNodeDash').disabled) {
                addNodeDash();
            }
        });
    }

    const btnCheckUpdate = document.getElementById('btn-check-update');
    const btnDoUpdate = document.getElementById('btn-do-update');
    const updateStatusArea = document.getElementById('update-status-area');
    const updateProgress = document.getElementById('update-progress');
    let targetBranch = null;

    if (btnCheckUpdate) {
        const newBtn = btnCheckUpdate.cloneNode(true);
        btnCheckUpdate.parentNode.replaceChild(newBtn, btnCheckUpdate);

        newBtn.addEventListener('click', async function() {
            newBtn.disabled = true;
            const spinner = '<svg class="animate-spin h-4 w-4 text-gray-500 inline-block mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';
            const checkingText = (typeof I18N !== 'undefined' && I18N.web_update_checking) ? I18N.web_update_checking : "Checking...";
            updateStatusArea.innerHTML = `${spinner} <span class="text-gray-500">${checkingText}</span>`;
            if (btnDoUpdate) btnDoUpdate.classList.add('d-none');

            try {
                const response = await fetch('/api/update/check');
                const data = await response.json();
                if (data.error) throw new Error(data.error);

                if (data.update_available) {
                    const infoText = (I18N.web_update_info || "Current: {local} -> New: {remote}").replace('{local}', 'v' + data.local_version).replace('{remote}', 'v' + data.remote_version);
                    const updateAvailTitle = (typeof I18N !== 'undefined' && I18N.web_update_available_title) ? I18N.web_update_available_title : "Update Available!";
                    updateStatusArea.innerHTML = `<div><div class="font-bold text-green-600 dark:text-green-400">${updateAvailTitle}</div><div class="text-xs text-gray-500 dark:text-gray-400 mt-1">${infoText}</div></div>`;
                    targetBranch = data.target_branch;
                    if (btnDoUpdate) btnDoUpdate.classList.remove('d-none');
                } else {
                    const uptodateText = (I18N.web_update_uptodate || "Latest version installed ({version})").replace('{version}', 'v' + data.local_version);
                    updateStatusArea.innerHTML = `<span class="text-gray-500 dark:text-gray-400 text-sm"><i class="fas fa-check-circle text-green-500 mr-1"></i> ${uptodateText}</span>`;
                }
            } catch (error) {
                const errorText = (I18N.web_update_error || "Error: {error}").replace('{error}', error.message);
                updateStatusArea.innerHTML = `<span class="text-red-500 text-sm"><i class="fas fa-exclamation-triangle mr-1"></i> ${errorText}</span>`;
            } finally {
                newBtn.disabled = false;
            }
        });
    }

    if (btnDoUpdate) {
        const newBtnDo = btnDoUpdate.cloneNode(true);
        btnDoUpdate.parentNode.replaceChild(newBtnDo, btnDoUpdate);

        newBtnDo.addEventListener('click', async function() {
            if (!await window.showModalConfirm(I18N.web_update_started || "Are you sure you want to update the bot? The server will restart.", I18N.modal_title_confirm)) return;

            const currentCheckBtn = document.getElementById('btn-check-update');
            if (currentCheckBtn) currentCheckBtn.disabled = true;

            newBtnDo.disabled = true;
            if (updateProgress) updateProgress.classList.remove('d-none');

            const updatingText = (typeof I18N !== 'undefined' && I18N.web_update_started) ? I18N.web_update_started : "Updating...";
            updateStatusArea.innerHTML = `<span class="text-blue-600 dark:text-blue-400 font-medium animate-pulse">${updatingText}</span>`;

            try {
                const response = await fetch('/api/update/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ branch: targetBranch })
                });
                const data = await response.json();
                if (data.error) throw new Error(data.error);

                await window.showModalAlert("Update started! Page will reload in 15 seconds.", "Info");
                setTimeout(() => location.reload(), 15000);
            } catch (error) {
                const errorText = (I18N.web_update_error || "Error: {error}").replace('{error}', error.message);
                updateStatusArea.innerHTML = `<span class="text-red-500 text-sm">${errorText}</span>`;
                if (updateProgress) updateProgress.classList.add('d-none');
                if (currentCheckBtn) currentCheckBtn.disabled = false;
                newBtnDo.disabled = false;
            }
        });
    }
};

function initInputScrollLogic() {
    const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    if (!isTouchDevice) return; 

    const ids = ['conf_traffic', 'conf_timeout', 'pass_current', 'pass_new', 'pass_confirm'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            const scrollFn = (e) => {
                e.target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            };
            el.addEventListener('click', scrollFn);
            el.addEventListener('focus', scrollFn);
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById('usersSection')) {
        window.initSettings();
    }
});

let activeCounterRafId = null;

function animateCounter(el, start, end, duration) {
    if (start === end) {
        el.innerText = end;
        return;
    }
    if (activeCounterRafId) {
        cancelAnimationFrame(activeCounterRafId);
        activeCounterRafId = null;
    }

    const range = end - start;
    let startTime = null;

    const step = (timestamp) => {
        if (!startTime) startTime = timestamp;
        const progress = Math.min((timestamp - startTime) / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 3);
        const current = Math.floor(start + range * ease);

        el.innerText = current;

        if (progress < 1) {
            activeCounterRafId = window.requestAnimationFrame(step);
        } else {
            el.innerText = end;
            activeCounterRafId = null;
        }
    };
    activeCounterRafId = window.requestAnimationFrame(step);
}

const initialConfig = {
    thresholds: {},
    intervals: {}
};
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
    for (const [groupName, config] of Object.entries(groups)) {
        const btn = document.getElementById(config.btnId);
        if (!btn) continue;

        config.ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                initialConfig[groupName][id] = el.value;
                el.addEventListener('input', () => checkForChanges(groupName));
                el.addEventListener('change', () => checkForChanges(groupName));
            }
        });
    }
}

function initChangePasswordUI() {
    const ids = ['pass_current', 'pass_new', 'pass_confirm'];
    const btn = document.getElementById('btnChangePass');
    if (!btn) return;

    const updateBtnState = () => {
        const allFilled = ids.every(id => {
            const el = document.getElementById(id);
            return el && el.value.trim().length > 0;
        });
        if (allFilled) {
            btn.classList.remove('opacity-50', 'grayscale', 'cursor-default');
            btn.classList.add('shadow-lg', 'shadow-red-500/20', 'hover:bg-red-600');
        } else {
            btn.classList.add('opacity-50', 'grayscale');
            btn.classList.remove('shadow-lg', 'shadow-red-500/20', 'hover:bg-red-600');
        }
    };

    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', () => {
                updateBtnState();
                clearInputError(el);
            });
        }
    });
    updateBtnState();
}

function showInputError(el) {
    if (!el) return;
    el.classList.add('border-red-500', 'focus:ring-red-500');
    el.classList.remove('border-gray-200', 'dark:border-white/10');
    let errorMsg = el.parentNode.querySelector('.pass-error-msg');
    if (!errorMsg) {
        errorMsg = document.createElement('div');
        errorMsg.className = 'pass-error-msg text-[10px] text-red-500 mt-1 ml-1 font-medium animate-pulse';
        errorMsg.innerText = (typeof I18N !== 'undefined' && I18N.web_fill_field) ? I18N.web_fill_field : 'Fill in the field';
        el.parentNode.appendChild(errorMsg);
    }
}

function clearInputError(el) {
    if (!el) return;
    el.classList.remove('border-red-500');
    el.classList.add('border-gray-200', 'dark:border-white/10');
    const errorMsg = el.parentNode.querySelector('.pass-error-msg');
    if (errorMsg) {
        errorMsg.remove();
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
            if (groupName === 'thresholds') {
                const displayId = id.replace('conf_', 'val_') + '_display';
                const displayEl = document.getElementById(displayId);
                if (displayEl) {
                    displayEl.innerText = el.value + '%';
                }
            }
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
    btn.innerText = I18N.web_saving_btn;
    btn.disabled = true;
    document.querySelectorAll('[id^="error_"]').forEach(el => el.classList.add('hidden'));

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
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            for (const [grp, cfg] of Object.entries(groups)) {
                cfg.ids.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) initialConfig[grp][id] = el.value;
                });
            }
            btn.innerText = I18N.web_saved_btn;
            btn.classList.remove('bg-blue-600', 'hover:bg-blue-500', 'bg-gray-200', 'dark:bg-gray-700');
            btn.classList.add('bg-green-600', 'hover:bg-green-500', 'text-white');
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.remove('bg-green-600', 'hover:bg-green-500', 'text-white');
                toggleSaveButton(config.btnId, false);
            }, 2000);
        } else {
            const json = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', json.error || 'Save failed'), errorShort);
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
        btn.innerText = originalText;
        toggleSaveButton(config.btnId, true);
    }
}

async function clearLogs() {
    if (!await window.showModalConfirm(I18N.web_clear_logs_confirm, I18N.modal_title_confirm)) return;

    const btn = document.getElementById('clearLogsBtn');
    const originalHTML = btn.innerHTML;
    const redClasses = ['bg-red-50', 'dark:bg-red-900/10', 'border-red-200', 'dark:border-red-800', 'text-red-600', 'dark:text-red-400', 'hover:bg-red-100', 'dark:hover:bg-red-900/30', 'active:bg-red-200'];
    const greenClasses = ['bg-green-600', 'text-white', 'border-transparent', 'hover:bg-green-500'];

    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${I18N.web_logs_clearing}`;

    try {
        const res = await fetch('/api/logs/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'all' })
        });
        if (res.ok) {
            btn.classList.remove(...redClasses);
            btn.classList.add(...greenClasses);
            btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg> ${I18N.web_logs_cleared_alert}`;
            setTimeout(() => {
                btn.innerHTML = originalHTML;
                btn.classList.remove(...greenClasses);
                btn.classList.add(...redClasses);
                btn.disabled = false;
            }, 2000);
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error || "Failed"), errorShort);
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}

function renderUsers() {
    const tbody = document.getElementById('usersTableBody');
    const section = document.getElementById('usersSection');
    if (USERS_DATA === null) return;
    section.classList.remove('hidden');

    if (USERS_DATA.length > 0) {
        tbody.innerHTML = USERS_DATA.map(u => {
            const isAdmin = u.role === 'admins';
            const badgeClass = isAdmin ? 'border-green-500/30 bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400' : 'border-blue-500/30 bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400';
            return `
            <tr class="border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition">
                <td class="px-2 sm:px-4 py-3 font-medium text-sm text-gray-900 dark:text-white break-all max-w-[100px] sm:max-w-none">${escapeHtml(u.name)}</td>
                <td class="px-2 sm:px-4 py-3"><span class="px-1.5 sm:px-2 py-0.5 rounded text-[9px] sm:text-[10px] uppercase font-bold border ${badgeClass}">${escapeHtml(u.role)}</span></td>
                <td class="px-2 sm:px-4 py-3 font-mono text-[10px] sm:text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">${u.id}</td>
                <td class="px-2 sm:px-4 py-3 text-right">
                    <button onclick="deleteUser(${u.id}, '${escapeHtml(u.name)}')" class="text-red-500 hover:text-red-700 dark:hover:text-red-300 transition p-1" title="Delete">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                </td>
            </tr>`;
        }).join('');
        if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
    } else {
        const noUsers = (typeof I18N !== 'undefined' && I18N.web_no_users) ? I18N.web_no_users : "No users";
        tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-3 text-center text-gray-500 text-xs">${noUsers}</td></tr>`;
    }
}

function escapeHtml(text) {
    if (!text) return text;
    return text.toString().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

async function deleteUser(id, name) {
    const displayName = name || id;
    if (!await window.showModalConfirm(I18N.web_confirm_delete_user.replace('{id}', displayName), I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'delete', id: id })
        });
        if (res.ok) {
            const idx = USERS_DATA.findIndex(u => u.id == id);
            if (idx > -1) USERS_DATA.splice(idx, 1);
            renderUsers();
        } else {
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', 'Delete failed'), errorShort);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
    }
}

async function openAddUserModal() {
	const promptText = (typeof I18N !== 'undefined' && I18N.web_add_user_prompt) ? I18N.web_add_user_prompt : "Введите Telegram ID пользователя:";
    const titleText = (typeof I18N !== 'undefined' && I18N.modal_title_prompt) ? I18N.modal_title_prompt : "Ввод данных";
    const id = await window.showModalPrompt(promptText, titleText, "123456789");
    
    if (!id) return;

    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'add', id: id, role: 'users' })
        });
        const data = await res.json();
        if (res.ok) {
            USERS_DATA.push({ id: id, name: data.name || `ID: ${id}`, role: 'users' });
            renderUsers();
        } else {
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error || "Unknown"), errorShort);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
    }
}

function renderNodes() {
    const tbody = document.getElementById('nodesTableBody');
    const section = document.getElementById('nodesSection');
    if (NODES_DATA === null) return;
    section.classList.remove('hidden');

    if (NODES_DATA.length > 0) {
        tbody.innerHTML = NODES_DATA.map(n => {
            const decryptedIp = decryptData(n.ip);
            const decryptedToken = decryptData(n.token);
            
            return `
        <tr class="border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition group">
            <td class="px-2 sm:px-4 py-3 font-medium text-sm text-gray-900 dark:text-white w-full sm:w-auto">
                <div id="disp_name_${n.token}" class="flex items-center gap-2 max-w-[120px] sm:max-w-none">
                    <span class="truncate block" title="${escapeHtml(n.name)}">${escapeHtml(n.name)}</span>
                    ${isMainAdmin ? `
                    <button onclick="startNodeRename('${n.token}')" class="text-gray-400 hover:text-blue-500 p-1 flex-shrink-0 transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
                    </button>
                    ` : ''}
                </div>
                <div id="edit_name_${n.token}" class="hidden flex items-center gap-1">
                    <input type="text" id="input_name_${n.token}" value="${escapeHtml(n.name)}" class="bg-white dark:bg-black/20 border border-gray-200 dark:border-white/10 rounded px-2 py-1 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 w-24 sm:w-48 transition-all" onkeydown="handleSettingsRenameKeydown(event, '${n.token}')">
                    <div class="flex items-center flex-shrink-0">
                        <button onclick="saveNodeRename('${n.token}')" class="text-green-500 hover:text-green-600 p-1"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg></button>
                        <button onclick="cancelNodeRename('${n.token}')" class="text-red-500 hover:text-red-600 p-1"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg></button>
                    </div>
                </div>
            </td>
            <td class="px-2 sm:px-4 py-3 text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">${escapeHtml(decryptedIp) || 'Unknown'}</td>
            <td class="px-2 sm:px-4 py-3 font-mono text-[10px] text-gray-400 dark:text-gray-500 truncate max-w-[80px]" title="${escapeHtml(decryptedToken)}">${escapeHtml(decryptedToken).substring(0, 8)}...</td>
            <td class="px-2 sm:px-4 py-3 text-right">
                <button onclick="deleteNode('${n.token}')" class="text-red-500 hover:text-red-700 dark:hover:text-red-300 transition p-1" title="Delete">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                </button>
            </td>
        </tr>`;
        }).join('');
        if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
    } else {
        tbody.innerHTML = `<tr><td colspan="4" class="px-4 py-3 text-center text-gray-500 text-xs">${I18N.web_no_nodes}</td></tr>`;
    }
}
window.startNodeRename = function(token) {
    document.getElementById(`disp_name_${token}`).classList.add('hidden');
    document.getElementById(`edit_name_${token}`).classList.remove('hidden');
    const input = document.getElementById(`input_name_${token}`);
    input.focus();
    const node = NODES_DATA.find(n => n.token === token);
    if (node) input.value = node.name;

    const scrollToInput = () => {
        input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    };
    setTimeout(scrollToInput, 50);
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => {
            setTimeout(scrollToInput, 50); 
        }, { once: true });
    } else {
        setTimeout(scrollToInput, 300);
    }
};
window.cancelNodeRename = function(token) {
    document.getElementById(`disp_name_${token}`).classList.remove('hidden');
    document.getElementById(`edit_name_${token}`).classList.add('hidden');
};

window.saveNodeRename = async function(token) {
    const input = document.getElementById(`input_name_${token}`);
    const newName = input.value.trim();
    if (!newName) return;

    // Optimistic update
    const nodeIndex = NODES_DATA.findIndex(n => n.token === token);
    const oldName = NODES_DATA[nodeIndex].name;
    if (nodeIndex > -1) {
        NODES_DATA[nodeIndex].name = newName;
        renderNodes();
    }

    try {
        const res = await fetch('/api/nodes/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token, name: newName })
        });
        
        if (res.ok) {
            if (window.showToast) {
                const msg = (typeof I18N !== 'undefined' && I18N.web_node_rename_success) ? I18N.web_node_rename_success : "Name updated";
                window.showToast(msg);
            }
        } else {
            const data = await res.json();
            // Revert
            if (nodeIndex > -1) {
                NODES_DATA[nodeIndex].name = oldName;
                renderNodes();
            }
            const errorMsg = (typeof I18N !== 'undefined' && I18N.web_node_rename_error) ? I18N.web_node_rename_error : "Error updating name";
            if (window.showModalAlert) await window.showModalAlert(data.error || errorMsg, "Error");
        }
    } catch (e) {
        console.error(e);
        // Revert
        if (nodeIndex > -1) {
            NODES_DATA[nodeIndex].name = oldName;
            renderNodes();
        }
        if (window.showModalAlert) await window.showModalAlert(String(e), "Error");
    }
};

window.handleSettingsRenameKeydown = function(event, token) {
    if (event.key === 'Enter') {
        saveNodeRename(token);
    } else if (event.key === 'Escape') {
        cancelNodeRename(token);
    }
};

async function deleteNode(token) {
    if (!await window.showModalConfirm(I18N.node_delete_select || "Удалить эту ноду?", I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/nodes/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token })
        });
        if (res.ok) {
            const idx = NODES_DATA.findIndex(n => n.token === token);
            if (idx > -1) NODES_DATA.splice(idx, 1);
            renderNodes();
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error || 'Delete failed'), errorShort);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
    }
}

async function changePassword() {
    const currentEl = document.getElementById('pass_current');
    const newPassEl = document.getElementById('pass_new');
    const confirmEl = document.getElementById('pass_confirm');
    const fields = [currentEl, newPassEl, confirmEl];
    let hasErrors = false;

    fields.forEach(el => {
        if (!el || !el.value.trim()) {
            showInputError(el);
            hasErrors = true;
        }
    });
    if (hasErrors) return;

    const current = currentEl.value;
    const newPass = newPassEl.value;
    const confirm = confirmEl.value;
    const btn = document.getElementById('btnChangePass');

    if (newPass !== confirm) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
        await window.showModalAlert(I18N.web_pass_mismatch, errorShort);
        return;
    }

    const origText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "...";

    try {
        const res = await fetch('/api/settings/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: current, new_password: newPass })
        });
        const data = await res.json();

        if (res.ok) {
            const successText = (typeof I18N !== 'undefined' && I18N.web_success) ? I18N.web_success : "Success";
            await window.showModalAlert(I18N.web_pass_changed, successText);
            currentEl.value = "";
            newPassEl.value = "";
            confirmEl.value = "";
            if (typeof initChangePasswordUI === 'function') {
                const dummyEvent = new Event('input');
                currentEl.dispatchEvent(dummyEvent);
            }
        } else {
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(I18N.web_error.replace('{error}', data.error), errorShort);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(I18N.web_conn_error.replace('{error}', e), errorShort);
    }
    btn.disabled = false;
    btn.innerText = origText;
}

async function triggerAutoSave() {
    const statusEl = document.getElementById('notifStatus');
    if (statusEl) {
        statusEl.innerText = (typeof I18N !== 'undefined' && I18N.web_saving_btn) ? I18N.web_saving_btn : "Saving...";
        statusEl.classList.remove('text-green-500', 'text-red-500', 'opacity-0');
        statusEl.classList.add('text-gray-500', 'dark:text-gray-400', 'opacity-100');
    }

    const data = {
        resources: document.getElementById('alert_resources')?.checked || false,
        logins: document.getElementById('alert_logins')?.checked || false,
        bans: document.getElementById('alert_bans')?.checked || false,
        downtime: document.getElementById('alert_downtime')?.checked || false
    };

    try {
        const res = await fetch('/api/settings/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (statusEl) {
            if (res.ok) {
                statusEl.innerText = (typeof I18N !== 'undefined' && I18N.web_saved_btn) ? I18N.web_saved_btn : "Saved!";
                statusEl.classList.remove('text-gray-500', 'dark:text-gray-400');
                statusEl.classList.add('text-green-500');
                setTimeout(() => {
                    statusEl.classList.add('opacity-0');
                }, 2000);
            } else {
                statusEl.innerText = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
                statusEl.classList.add('text-red-500');
            }
        }
    } catch (e) {
        console.error(e);
        if (statusEl) {
            statusEl.innerText = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
            statusEl.classList.add('text-red-500');
        }
    }
}

const btnCategories = {
    "monitoring": {
        titleKey: "web_kb_cat_monitoring",
        keys: ["enable_selftest", "enable_uptime", "enable_speedtest", "enable_traffic", "enable_top"]
    },
    "security": {
        titleKey: "web_kb_cat_security",
        keys: ["enable_fail2ban", "enable_sshlog", "enable_logs"]
    },
    "management": {
        titleKey: "web_kb_cat_management",
        keys: ["enable_nodes", "enable_users", "enable_update", "enable_optimize"]
    },
    "system": {
        titleKey: "web_kb_cat_system",
        keys: ["enable_restart", "enable_reboot"]
    },
    "tools": {
        titleKey: "web_kb_cat_tools",
        keys: ["enable_vless", "enable_xray", "enable_notifications"]
    }
};

function renderKeyboardConfig() {
    renderKeyboardPreview();
    renderKeyboardModalContent();
    updateDoneButtonState('default');
}

function getVisibleKeys() {
    let keys = [];
    if (typeof KEYBOARD_CONFIG === 'undefined') return keys;
    for (const catData of Object.values(btnCategories)) {
        catData.keys.forEach(k => {
            if (KEYBOARD_CONFIG.hasOwnProperty(k)) {
                keys.push(k);
            }
        });
    }
    return keys;
}

function renderKeyboardPreview() {
    const container = document.getElementById('keyboardPreview');
    if (!container || typeof KEYBOARD_CONFIG === 'undefined') return;

    const visibleKeys = getVisibleKeys();
    const totalAll = visibleKeys.length;
    const totalEnabled = visibleKeys.filter(k => KEYBOARD_CONFIG[k]).length;
    const activeText = (typeof I18N !== 'undefined' && I18N.web_kb_active) ? I18N.web_kb_active : "Активно:";
    const prevEl = document.getElementById('kbActiveCount');
    let startVal = 0;
    if (prevEl) {
        startVal = parseInt(prevEl.innerText) || 0;
    }

    container.innerHTML = `<span class="px-3 py-1 rounded-full bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-300 text-xs font-bold border border-green-200 dark:border-green-500/20">${activeText} <span id="kbActiveCount">${startVal}</span> / ${totalAll}</span>`;

    const countEl = document.getElementById('kbActiveCount');
    if (countEl) {
        animateCounter(countEl, startVal, totalEnabled, 1000);
    }
}

function renderKeyboardModalContent() {
    const container = document.getElementById('keyboardModalContent');
    if (!container || typeof KEYBOARD_CONFIG === 'undefined') return;

    let html = '';
    for (const [catKey, catData] of Object.entries(btnCategories)) {
        const categoryKeys = catData.keys.filter(k => KEYBOARD_CONFIG.hasOwnProperty(k));
        if (categoryKeys.length > 0) {
            const title = (typeof I18N !== 'undefined' && I18N[catData.titleKey]) ? I18N[catData.titleKey] : catKey;
            html += `<div class="mb-2"><h4 class="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3 ml-1">${title}</h4><div class="grid grid-cols-1 sm:grid-cols-2 gap-3">`;
            categoryKeys.forEach(key => {
                const enabled = KEYBOARD_CONFIG[key];
                const label = (typeof I18N !== 'undefined' && I18N[`lbl_${key}`]) ? I18N[`lbl_${key}`] : key;
                html += `
                <div class="flex items-center justify-between bg-gray-50 dark:bg-black/20 p-3 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer select-none" onclick="document.getElementById('${key}').click(); triggerKeyboardSave();">
                    <span class="text-sm font-medium text-gray-900 dark:text-white truncate pr-2" title="${label}">${label}</span>
                    <label class="relative inline-flex items-center cursor-pointer flex-shrink-0" onclick="event.stopPropagation(); triggerKeyboardSave();">
                        <input type="checkbox" id="${key}" class="sr-only peer" ${enabled ? 'checked' : ''}>
                        <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
                    </label>
                </div>`;
            });
            html += `</div></div><div class="h-px bg-gray-200 dark:bg-white/5 last:hidden"></div>`;
        }
    }
    container.innerHTML = html;
}

window.openKeyboardModal = function() {
    const modal = document.getElementById('keyboardModal');
    if (modal) {
        animateModalOpen(modal);
    }
};

window.closeKeyboardModal = function() {
    const modal = document.getElementById('keyboardModal');
    if (modal) {
        animateModalClose(modal);
    }
};

function updateDoneButtonState(state) {
    const btn = document.getElementById('keyboardModalDoneBtn');
    if (!btn) return;

    const activeText = (typeof I18N !== 'undefined' && I18N.web_kb_active) ? I18N.web_kb_active : "Активно:";
    const savingText = (typeof I18N !== 'undefined' && I18N.web_saving_btn) ? I18N.web_saving_btn : "Сохранение...";
    const savedText = (typeof I18N !== 'undefined' && I18N.web_saved_btn) ? I18N.web_saved_btn : "Сохранено!";

    const visibleKeys = getVisibleKeys();
    const totalAll = visibleKeys.length;
    const totalEnabled = visibleKeys.filter(k => KEYBOARD_CONFIG[k]).length;
    const counterText = `${activeText} ${totalEnabled} / ${totalAll}`;

    const defaultClasses = ['bg-blue-600', 'hover:bg-blue-500', 'text-white', 'shadow-blue-500/20'];
    const savingClasses = ['bg-yellow-500', 'hover:bg-yellow-400', 'text-white', 'shadow-yellow-500/20', 'cursor-wait'];
    const savedClasses = ['bg-green-600', 'hover:bg-green-500', 'text-white', 'shadow-green-500/20'];

    btn.classList.remove(...defaultClasses, ...savingClasses, ...savedClasses);

    if (state === 'saving') {
        btn.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${savingText}`;
        btn.classList.add(...savingClasses);
        btn.disabled = true;
    } else if (state === 'saved') {
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg> ${savedText}`;
        btn.classList.add(...savedClasses);
        btn.disabled = false;
    } else {
        btn.innerText = counterText;
        btn.classList.add(...defaultClasses);
        btn.disabled = false;
    }
}

async function triggerKeyboardSave(skipPreviewUpdate = false) {
    const data = {};
    if (typeof KEYBOARD_CONFIG !== 'undefined') {
        Object.keys(KEYBOARD_CONFIG).forEach(key => {
            const el = document.getElementById(key);
            if (el) {
                data[key] = el.checked;
            } else {
                data[key] = KEYBOARD_CONFIG[key];
            }
        });
    }

    Object.assign(KEYBOARD_CONFIG, data);
    if (!skipPreviewUpdate) {
        renderKeyboardPreview();
        updateBulkButtonsUI();
    }
    updateDoneButtonState('saving');

    setTimeout(async () => {
        try {
            const res = await fetch('/api/settings/keyboard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (res.ok) {
                updateDoneButtonState('saved');
                setTimeout(() => {
                    const btn = document.getElementById('keyboardModalDoneBtn');
                    if (btn && !btn.innerHTML.includes('spin')) {
                        updateDoneButtonState('default');
                    }
                }, 1500);
            } else {
                updateDoneButtonState('default');
            }
        } catch (e) {
            updateDoneButtonState('default');
        }
    }, 300);
}

function getBulkStatus() {
    const keys = getVisibleKeys();
    const total = keys.length;
    const enabled = keys.filter(k => KEYBOARD_CONFIG[k]).length;
    return {
        allEnabled: total > 0 && enabled === total,
        allDisabled: total > 0 && enabled === 0
    };
}

function updateBulkButtonsUI() {
    const status = getBulkStatus();
    const btnEnable = document.getElementById('btnEnableAllKb');
    const btnDisable = document.getElementById('btnDisableAllKb');

    const setDeactivated = (btn, isDeactivated) => {
        if (!btn) return;
        if (isDeactivated) {
            btn.classList.add('opacity-50', 'cursor-not-allowed');
        } else {
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    };
    setDeactivated(btnEnable, status.allEnabled);
    setDeactivated(btnDisable, status.allDisabled);
}

function animateBulkButton(btnId, state, originalText) {
    const btn = document.getElementById(btnId);
    if (!btn) return;

    if (state === 'loading') {
        btn.innerHTML = `<svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
        btn.disabled = true;
    } else if (state === 'success') {
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>`;
        btn.disabled = true;
    } else {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

window.enableAllKeyboard = async function() {
    const btnId = 'btnEnableAllKb';
    const btn = document.getElementById(btnId);
    if (btn && (btn.disabled || btn.querySelector('.animate-spin'))) return;

    const status = getBulkStatus();
    if (status.allEnabled) {
        showToast((typeof I18N !== 'undefined' && I18N.web_kb_all_on_alert) ? I18N.web_kb_all_on_alert : "All buttons already enabled!");
        return;
    }

    const originalText = btn ? btn.innerText : (typeof I18N !== 'undefined' && I18N.web_kb_enable_all) ? I18N.web_kb_enable_all : 'Enable All';
    animateBulkButton(btnId, 'loading', originalText);

    let changed = false;
    const keys = getVisibleKeys();
    keys.forEach(key => {
        if (!KEYBOARD_CONFIG[key]) {
            KEYBOARD_CONFIG[key] = true;
            changed = true;
            const el = document.getElementById(key);
            if (el) el.checked = true;
        }
    });

    if (changed) {
        await triggerKeyboardSave();
    }
    animateBulkButton(btnId, 'success', originalText);
    setTimeout(() => {
        animateBulkButton(btnId, 'default', originalText);
        updateBulkButtonsUI();
    }, 1500);
};

window.disableAllKeyboard = async function() {
    const btnId = 'btnDisableAllKb';
    const btn = document.getElementById(btnId);
    if (btn && (btn.disabled || btn.querySelector('.animate-spin'))) return;

    const status = getBulkStatus();
    if (status.allDisabled) {
        showToast((typeof I18N !== 'undefined' && I18N.web_kb_all_off_alert) ? I18N.web_kb_all_off_alert : "All buttons already disabled!");
        return;
    }

    const originalText = btn ? btn.innerText : (typeof I18N !== 'undefined' && I18N.web_kb_disable_all) ? I18N.web_kb_disable_all : 'Disable All';
    animateBulkButton(btnId, 'loading', originalText);

    let changed = false;
    const keys = getVisibleKeys();
    keys.forEach(key => {
        if (KEYBOARD_CONFIG[key]) {
            KEYBOARD_CONFIG[key] = false;
            changed = true;
            const el = document.getElementById(key);
            if (el) el.checked = false;
        }
    });

    if (changed) {
        await triggerKeyboardSave();
    }
    animateBulkButton(btnId, 'success', originalText);
    setTimeout(() => {
        animateBulkButton(btnId, 'default', originalText);
        updateBulkButtonsUI();
    }, 1500);
};

let ALL_SESSIONS = [];

async function fetchSessions() {
    const container = document.getElementById('sessionsList');
    if (!container) return;

    try {
        const res = await fetch('/api/sessions/list');
        const data = await res.json();
        if (data.sessions) {
            ALL_SESSIONS = data.sessions;
            renderSessionsMainWidget(data.sessions);
        }
    } catch (e) {
        const errorLoading = (typeof I18N !== 'undefined' && I18N.web_error_loading_sessions) ? I18N.web_error_loading_sessions : "Error loading sessions";
        container.innerHTML = `<div class="text-red-500 text-sm text-center">${errorLoading}</div>`;
    }
}

function renderSessionsMainWidget(sessions) {
    const container = document.getElementById('sessionsList');
    if (!container) return;

    const currentSession = sessions.find(s => s.current);
    if (currentSession) {
        container.innerHTML = `${renderSessionItem(currentSession)}`;
    } else {
        const noSessions = (typeof I18N !== 'undefined' && I18N.web_no_sessions) ? I18N.web_no_sessions : "No active sessions";
        container.innerHTML = `<div class="text-gray-500 text-sm text-center">${noSessions}</div>`;
    }
}

function renderSessionItem(s) {
    const isCurrent = s.current;
    const isMine = s.is_mine !== false;
    let deviceText = s.ua;
    let iconType = "desktop";

    const ua = s.ua.toLowerCase();
    let os = "";
    if (ua.includes('windows')) os = "Windows";
    else if (ua.includes('mac os')) os = "macOS";
    else if (ua.includes('android')) {
        os = "Android";
        iconType = "mobile";
    } else if (ua.includes('iphone')) {
        os = "iPhone";
        iconType = "mobile";
    } else if (ua.includes('ipad')) {
        os = "iPad";
        iconType = "mobile";
    } else if (ua.includes('linux')) os = "Linux";

    let browser = "";
    if (ua.includes('edg')) browser = "Edge";
    else if (ua.includes('opr') || ua.includes('opera')) browser = "Opera";
    else if (ua.includes('firefox')) browser = "Firefox";
    else if (ua.includes('chrome') && !ua.includes('edg') && !ua.includes('opr')) browser = "Chrome";
    else if (ua.includes('safari') && !ua.includes('chrome')) browser = "Safari";
    else if (ua.includes('telegram')) browser = "Telegram";
    else if (ua.includes('python') || ua.includes('curl')) {
        browser = "Script";
        iconType = "terminal";
    }

    if (os && browser) deviceText = `${browser} (${os})`;
    else if (os) deviceText = os;
    else if (browser) deviceText = browser;
    else deviceText = s.ua.length > 30 ? s.ua.substring(0, 30) + "..." : s.ua;

    const date = new Date(s.created * 1000).toLocaleString();
    let iconPath = "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z";
    if (iconType === "mobile") iconPath = "M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z";
    else if (iconType === "terminal") iconPath = "M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z";

    let userBadge = "";
    if (!isMine) {
        userBadge = `<div class="text-[10px] font-bold text-blue-500 mb-0.5 uppercase tracking-wide flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>${s.user_name}</div>`;
    }

    let bgClass = 'bg-gray-50 dark:bg-black/20 border-gray-100 dark:border-white/5';
    let iconBgClass = 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400';

    if (isCurrent) {
        bgClass = 'bg-green-50/50 dark:bg-green-900/10 border-green-200 dark:border-green-800';
        iconBgClass = 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400';
    } else if (!isMine) {
        bgClass = 'bg-blue-50/30 dark:bg-blue-900/10 border-blue-100 dark:border-blue-800';
        iconBgClass = 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400';
    }

    return `
    <div class="flex items-center justify-between p-3 rounded-xl border ${bgClass} transition hover:shadow-sm">
        <div class="flex items-center gap-3 overflow-hidden">
            <div class="p-2 rounded-lg ${iconBgClass} flex-shrink-0">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${iconPath}" />
                </svg>
            </div>
            <div class="min-w-0">
                ${userBadge}
                <div class="text-sm font-bold text-gray-900 dark:text-white truncate" title="${s.ua}">${deviceText}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
                    <span class="font-mono">${escapeHtml(decryptData(s.ip))}</span>
                    <span>•</span>
                    <span>${date}</span>
                </div>
            </div>
        </div>
        <div class="flex-shrink-0 ml-2">
            ${isCurrent ? 
                `<span class="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 text-[10px] font-bold uppercase rounded-lg tracking-wider">${I18N.web_session_current || 'Current'}</span>` : 
                `<button onclick="revokeSession('${s.id}')" class="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition" title="${I18N.web_session_revoke || 'Revoke'}">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                </button>`
            }
        </div>
    </div>`;
}

window.openSessionsModal = function() {
    const modal = document.getElementById('sessionsModal');
    const content = document.getElementById('sessionsModalContent');
    const btnRevokeAll = document.getElementById('btnRevokeAllSessions');

    if (modal && content) {
        if (ALL_SESSIONS.length > 0) {
            content.innerHTML = ALL_SESSIONS.map(s => renderSessionItem(s)).join('');
        } else {
            content.innerHTML = `<div class="text-center text-gray-500 py-4">No sessions</div>`;
        }

        if (ALL_SESSIONS.length <= 1 && btnRevokeAll) {
            btnRevokeAll.disabled = true;
            btnRevokeAll.classList.add('opacity-50', 'cursor-not-allowed');
        } else if (btnRevokeAll) {
            btnRevokeAll.disabled = false;
            btnRevokeAll.classList.remove('opacity-50', 'cursor-not-allowed');
            const originalText = I18N.web_sessions_revoke_all || "Revoke all other";
            btnRevokeAll.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg> ${originalText}`;
            btnRevokeAll.className = "w-full py-3 bg-red-600 hover:bg-red-500 text-white rounded-xl font-bold shadow-lg shadow-red-500/20 transition-all duration-300 active:scale-[0.98] flex items-center justify-center gap-2";
        }
        animateModalOpen(modal);
    }
};

window.closeSessionsModal = function() {
    const modal = document.getElementById('sessionsModal');
    if (modal) {
        animateModalClose(modal);
    }
};

async function revokeSession(token) {
    if (!await window.showModalConfirm(I18N.web_session_revoke + "?", I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/sessions/revoke', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token })
        });
        if (res.ok) {
            await fetchSessions();
            const content = document.getElementById('sessionsModalContent');
            if (content && !document.getElementById('sessionsModal').classList.contains('hidden')) {
                content.innerHTML = ALL_SESSIONS.map(s => renderSessionItem(s)).join('');
                const btnRevokeAll = document.getElementById('btnRevokeAllSessions');
                if (ALL_SESSIONS.length <= 1 && btnRevokeAll) {
                    btnRevokeAll.disabled = true;
                    btnRevokeAll.classList.add('opacity-50', 'cursor-not-allowed');
                }
            }
            if (window.showToast) window.showToast((typeof I18N !== 'undefined' && I18N.web_success) ? I18N.web_success : "Success");
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(data.error || "Failed", errorShort);
        }
    } catch (e) {
        console.error(e);
    }
}

async function revokeAllSessions() {
    if (!await window.showModalConfirm(I18N.web_sessions_revoke_all + "?", I18N.modal_title_confirm)) return;

    const btn = document.getElementById('btnRevokeAllSessions');
    const originalText = btn ? btn.innerHTML : "";

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    }

    try {
        const res = await fetch('/api/sessions/revoke_all', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        if (res.ok) {
            if (btn) {
                btn.className = "w-full py-3 bg-green-600 text-white rounded-xl font-bold shadow-lg shadow-green-500/20 transition-all duration-300 flex items-center justify-center gap-2";
                btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg> ${I18N.web_sessions_revoked_alert}`;
            }
            await fetchSessions();
            const content = document.getElementById('sessionsModalContent');
            if (content) {
                content.innerHTML = ALL_SESSIONS.map(s => renderSessionItem(s)).join('');
            }
            setTimeout(() => {
                if (btn) {
                    btn.disabled = true;
                    btn.classList.add('opacity-50', 'cursor-not-allowed');
                }
            }, 2000);
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(data.error || "Failed", errorShort);
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }
    } catch (e) {
        console.error(e);
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}