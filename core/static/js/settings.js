/**
 * WebUI settings page logic.
 * API interaction for panel settings, form handling and UI animations.
 */
/* /core/static/js/settings.js */

const isMainAdmin = (typeof window.IS_MAIN_ADMIN !== 'undefined') ? window.IS_MAIN_ADMIN : false;

function createSpinnerSvg(className = 'animate-spin h-4 w-4 text-gray-500 inline-block mr-2') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', className);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('viewBox', '0 0 24 24');
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('class', 'opacity-25');
    circle.setAttribute('cx', '12');
    circle.setAttribute('cy', '12');
    circle.setAttribute('r', '10');
    circle.setAttribute('stroke', 'currentColor');
    circle.setAttribute('stroke-width', '4');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('class', 'opacity-75');
    path.setAttribute('fill', 'currentColor');
    path.setAttribute('d', 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z');
    svg.appendChild(circle);
    svg.appendChild(path);
    return svg;
}

function createTrashSvg(className = 'h-4 w-4') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', className);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('stroke', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('d', 'M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16');
    svg.appendChild(path);
    return svg;
}

function createSwitchArrowsSvg(className = 'h-3.5 w-3.5 opacity-60') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', className);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('stroke', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('d', 'M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4');
    svg.appendChild(path);
    return svg;
}

function createStatusSvg(state) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'w-3 h-3' + (state === 'neutral' ? ' animate-spin' : ''));
    svg.setAttribute('fill', 'none');
    svg.setAttribute('viewBox', '0 0 24 24');
    if (state === 'neutral') {
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('class', 'opacity-25');
        circle.setAttribute('cx', '12');
        circle.setAttribute('cy', '12');
        circle.setAttribute('r', '10');
        circle.setAttribute('stroke', 'currentColor');
        circle.setAttribute('stroke-width', '4');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('class', 'opacity-75');
        path.setAttribute('fill', 'currentColor');
        path.setAttribute('d', 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z');
        svg.appendChild(circle);
        svg.appendChild(path);
    } else {
        svg.setAttribute('stroke', 'currentColor');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        path.setAttribute('stroke-width', '3');
        path.setAttribute('d', state === 'success' ? 'M5 13l4 4L19 7' : 'M6 18L18 6M6 6l12 12');
        svg.appendChild(path);
    }
    return svg;
}

window.initSettings = function () {
    window.initGlobalLazyLoad?.();

    renderUsers();
    renderNodes();
    initSystemSettingsTracking();
    renderKeyboardConfig();
    updateBulkButtonsUI();
    fetchSessions();
    initPushNotificationsUI();

    // initInputScrollLogic(); 

    const input = document.getElementById('newNodeNameDash');
    if (input) {
        input.addEventListener('input', window.validateNodeInput);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !document.getElementById('btnAddNodeDash').disabled) {
                window.addNodeDash();
            }
        });
    }

    const btnCheckUpdate = document.getElementById('btn-check-update');
    let btnDoUpdate = document.getElementById('btn-do-update');
    const updateStatusArea = document.getElementById('update-status-area');
    const updateProgress = document.getElementById('update-progress');
    let targetBranch = null;
    let nodeUpdatePlan = null;

    if (btnCheckUpdate) {
        const newBtn = btnCheckUpdate.cloneNode(true);
        btnCheckUpdate.parentNode.replaceChild(newBtn, btnCheckUpdate);

        newBtn.addEventListener('click', async function () {
            newBtn.disabled = true;
            const checkingText = (typeof window.I18N !== 'undefined' && window.I18N.web_update_checking) ? window.I18N.web_update_checking : "Checking...";
            const spinnerSpan = document.createElement('span');
            spinnerSpan.className = 'text-gray-500';
            spinnerSpan.textContent = checkingText;
            updateStatusArea.replaceChildren(createSpinnerSvg(), spinnerSpan);
            if (btnDoUpdate) btnDoUpdate.classList.add('d-none');
            targetBranch = null;
            nodeUpdatePlan = null;

            try {
                const data = await window.sseRequest('/api/update/check', 'update_check');
                if (data && data.error) throw new Error(data.error);

                if (data.update_available) {
                    const infoText = (window.I18N.web_update_info || "Current: {local} -> New: {remote}").replace('{local}', data.local_version).replace('{remote}', data.remote_version);
                    const updateAvailTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_update_available_title) ? window.I18N.web_update_available_title : "Update Available!";
                    const availContainer = document.createElement('div');
                    const titleDiv = document.createElement('div');
                    titleDiv.className = "font-bold text-green-600 dark:text-green-400";
                    titleDiv.textContent = updateAvailTitle;
                    const infoDiv = document.createElement('div');
                    infoDiv.className = "text-xs text-gray-500 dark:text-gray-400 mt-1";
                    infoDiv.textContent = infoText;
                    availContainer.appendChild(titleDiv);
                    availContainer.appendChild(infoDiv);
                    updateStatusArea.replaceChildren(availContainer);
                    targetBranch = data.target_branch;
                    nodeUpdatePlan = data.node_plan;
                    if (btnDoUpdate) btnDoUpdate.classList.remove('d-none');
                } else {
                    const uptodateText = (window.I18N.web_update_uptodate || "Latest version installed ({version})").replace('{version}', data.local_version);
                    const span = document.createElement('span');
                    span.className = 'text-gray-500 dark:text-gray-400 text-sm';
                    const icon = document.createElement('i');
                    icon.className = 'fas fa-check-circle text-green-500 mr-1';
                    span.appendChild(icon);
                    span.appendChild(document.createTextNode(' ' + uptodateText));
                    updateStatusArea.replaceChildren(span);
                }
                for (const node of data.node_updates || []) {
                    const row = document.createElement('div');
                    row.className = 'text-xs text-gray-500 dark:text-gray-400 mt-1';
                    const nodeStatusText = (typeof window.I18N !== 'undefined') ? Reflect.get(window.I18N, `node_client_update_${node.status}`) : undefined;
                    row.textContent = `${node.name} · ${nodeStatusText || node.status}`;
                    updateStatusArea.appendChild(row);
                }
            } catch (error) {
                const errorText = (window.I18N.web_update_error || "Error: {error}").replace('{error}', error.message);
                const span = document.createElement('span');
                span.className = 'text-red-500 text-sm';
                const icon = document.createElement('i');
                icon.className = 'fas fa-exclamation-triangle mr-1';
                span.appendChild(icon);
                span.appendChild(document.createTextNode(' ' + errorText));
                updateStatusArea.replaceChildren(span);
            } finally {
                newBtn.disabled = false;
            }
        });
    }

    if (btnDoUpdate) {
        const newBtnDo = btnDoUpdate.cloneNode(true);
        btnDoUpdate.parentNode.replaceChild(newBtnDo, btnDoUpdate);
        btnDoUpdate = newBtnDo;

        newBtnDo.addEventListener('click', async function () {
            if (!targetBranch || newBtnDo.disabled) return;
            const currentCheckBtn = document.getElementById('btn-check-update');
            if (currentCheckBtn) currentCheckBtn.disabled = true;
            newBtnDo.disabled = true;
            const skipped = nodeUpdatePlan?.skipped
                ? '\n\n' + window.I18N.node_client_update_skipped.replace('{count}', nodeUpdatePlan.skipped)
                : '';
            if (!await window.showModalConfirm(window.I18N.web_update_confirm + skipped, window.I18N.modal_title_confirm)) {
                if (currentCheckBtn) currentCheckBtn.disabled = false;
                newBtnDo.disabled = false;
                return;
            }

            const requestBody = { branch: targetBranch };
            if (nodeUpdatePlan?.nodes?.length) {
                const names = nodeUpdatePlan.nodes.map(node => `• #${node.id} ${node.name}`).join('\n');
                const message = window.I18N.node_client_update_confirm.replace('{nodes}', () => names)
                    + '\n\n' + window.I18N.web_node_client_update_cancel;
                if (await window.showModalConfirm(message, window.I18N.modal_title_confirm)) {
                    requestBody.node_confirmation = nodeUpdatePlan.token;
                }
            }

            if (updateProgress) updateProgress.classList.remove('d-none');

            const updatingText = (typeof window.I18N !== 'undefined' && window.I18N.web_update_started) ? window.I18N.web_update_started : "Updating...";
            const updatingSpan = document.createElement('span');
            updatingSpan.className = 'text-blue-600 dark:text-blue-400 font-medium animate-pulse';
            updatingSpan.textContent = updatingText;
            updateStatusArea.replaceChildren(updatingSpan);

            try {
                const response = await fetch('/api/update/run', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(requestBody)
                });
                const data = await response.json();
                if (!response.ok || data.error) throw new Error(data.error || response.statusText);

                let alertMsg = window.I18N.web_update_started_alert || "Update started! Page will reload in 15 seconds.";
                if (data.nodes_confirmed) {
                    alertMsg += '\n\n' + window.I18N.node_client_update_queued
                        .replace('{count}', data.nodes_queued).replace('{total}', data.nodes_confirmed);
                }
                const alertTitle = (typeof window.I18N !== 'undefined' && window.I18N.modal_title_info) ? window.I18N.modal_title_info : "Info";

                await window.showModalAlert(alertMsg, alertTitle);
                setTimeout(() => location.reload(), 15000);
            } catch (error) {
                const errorText = (window.I18N.web_update_error || "Error: {error}").replace('{error}', error.message);
                const errorSpan = document.createElement('span');
                errorSpan.className = 'text-red-500 text-sm';
                errorSpan.textContent = errorText;
                updateStatusArea.replaceChildren(errorSpan);
                if (updateProgress) updateProgress.classList.add('d-none');
                if (currentCheckBtn) currentCheckBtn.disabled = false;
                newBtnDo.disabled = false;
            }
        });
    }
};

function handleSettingsScrollIntoView(e) {
    e.target.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
    });
}

function updateFaviconPreview() {
    const favInput = document.getElementById('meta_favicon');
    const favImg = document.getElementById('faviconPreview');
    const favFallback = document.getElementById('faviconFallback');
    if (!favInput || !favImg) return;
    const val = favInput.value.trim();
    if (val) {
        // Validate URL scheme via URL API to prevent javascript: injection
        let safeUrl = null;
        try {
            const parsed = new URL(val, window.location.origin);
            if (['http:', 'https:', 'data:'].includes(parsed.protocol)) {
                // For data: URIs, only allow image types
                if (parsed.protocol === 'data:' && !/^data:image\//i.test(val)) {
                    safeUrl = null;
                } else {
                    safeUrl = parsed.href;
                }
            }
        } catch {
            safeUrl = null;
        }
        if (safeUrl) {
            favImg.src = safeUrl;
            favImg.style.display = 'block';
            if (favFallback) favFallback.style.display = 'none';
        } else {
            favImg.removeAttribute('src');
            favImg.style.display = 'none';
            if (favFallback) favFallback.style.display = 'block';
        }
    } else {
        favImg.style.display = 'none';
        if (favFallback) favFallback.style.display = 'block';
    }
}

window.initInputScrollLogic = function() {
    const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    if (!isTouchDevice) return;

    const ids = ['conf_traffic', 'conf_timeout', 'pass_current', 'pass_new', 'pass_confirm', 'meta_favicon', 'meta_title', 'meta_desc', 'meta_keywords'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('click', handleSettingsScrollIntoView);
            el.addEventListener('focus', handleSettingsScrollIntoView);
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById('usersSection')) {
        window.initSettings();
    }

    // Favicon Logic
    const favInput = document.getElementById('meta_favicon');
    const favImg = document.getElementById('faviconPreview');
    const favFallback = document.getElementById('faviconFallback');
    const fileInput = document.getElementById('favFileInput');

    if (favInput && favImg) {
        favInput.addEventListener('input', updateFaviconPreview);

        favImg.addEventListener('error', () => {
            favImg.style.display = 'none';
            if (favFallback) favFallback.style.display = 'block';
        });

        // --- RESIZE LOGIC (Max 512x512) ---
        const processAndResizeImage = (file) => {
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function (e) {
                const img = new Image();
                img.onload = function () {
                    const canvas = document.createElement('canvas');
                    let width = img.width;
                    let height = img.height;
                    const maxSize = 512;

                    // Calculate aspect ratio
                    if (width > height) {
                        if (width > maxSize) {
                            height = Math.round(height * (maxSize / width));
                            width = maxSize;
                        }
                    } else {
                        if (height > maxSize) {
                            width = Math.round(width * (maxSize / height));
                            height = maxSize;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);

                    // To Base64 (PNG)
                    const dataUrl = canvas.toDataURL('image/png');

                    // Insert into input
                    favInput.value = dataUrl;
                    updateFaviconPreview();

                    const msg = (typeof window.I18N !== 'undefined' && window.I18N.web_image_uploaded)
                        ? window.I18N.web_image_uploaded
                        : "Image resized & loaded!";
                    if (window.showToast) window.showToast(msg);
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        };
        // ----------------------------------

        // Paste Handler
        favInput.addEventListener('paste', (e) => {
            const items = (e.clipboardData || e.originalEvent.clipboardData).items;
            for (let i = 0; i < items.length; i++) {
                if (items[i].type.indexOf("image") === 0) {
                    e.preventDefault();
                    processAndResizeImage(items[i].getAsFile());
                    break;
                }
            }
        });

        // File Input Handler
        if (fileInput) {
            fileInput.addEventListener('change', (e) => {
                processAndResizeImage(e.target.files[0]);
                e.target.value = ''; // Reset to allow re-selection
            });
        }
    }
});

// Default Favicon
window.setDefaultFavicon = function () {
    const input = document.getElementById('meta_favicon');
    if (input) {
        input.value = '/static/favicon.ico';
        input.dispatchEvent(new Event('input'));
    }
};

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

    function step(timestamp) {
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
        ids: ['conf_traffic', 'conf_services', 'conf_ping', 'conf_ping_mode', 'conf_ping_target', 'conf_timeout'],
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

    // Ping Mode Toggle Logic
    const pingModeGroup = document.getElementById('conf_ping_mode_group');
    if (pingModeGroup) {
        const pingModeInput = document.getElementById('conf_ping_mode');
        const buttons = pingModeGroup.querySelectorAll('button');
        
        buttons.forEach(btn => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.mode;
                pingModeInput.value = mode;
                
                // Update active state
                buttons.forEach(b => {
                    if (b.dataset.mode === mode) {
                        b.className = 'px-2 py-1.5 text-xs font-medium rounded-lg transition-colors bg-white dark:bg-gray-800 shadow text-gray-900 dark:text-white';
                    } else {
                        b.className = 'px-2 py-1.5 text-xs font-medium rounded-lg transition-colors text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200';
                    }
                });
                
                // Trigger change
                checkForChanges('intervals');
            });
        });
    }
}

function initChangePasswordUI() {
    const ids = ['pass_current', 'pass_new', 'pass_confirm'];
    const btn = document.getElementById('btnChangePass');
    if (!btn) return;

    function updateBtnState() {
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
        errorMsg.innerText = (typeof window.I18N !== 'undefined' && window.I18N.web_fill_field) ? window.I18N.web_fill_field : 'Fill in the field';
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
            if (el.value !== initialConfig[groupName][id]) {
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

window.saveSystemConfig = async function(groupName) {
    const config = groups[groupName];
    const btn = document.getElementById(config.btnId);
    if (!btn) return;

    const originalText = window.I18N.web_save_btn;
    btn.innerText = window.I18N.web_saving_btn;
    btn.disabled = true;
    document.querySelectorAll('[id^="error_"]').forEach(el => { el.classList.add('hidden'); });

    for (const id of config.ids) {
        const val = document.getElementById(id).value.trim();
        if (!val) {
            showError(id, (typeof window.I18N !== 'undefined' && window.I18N.web_error_empty_field) ? window.I18N.web_error_empty_field : "Fill in all fields");
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
            return;
        }
    }

    if (groupName === 'intervals') {
        const trafficVal = parseInt(document.getElementById('conf_traffic').value);
        const servicesVal = parseInt(document.getElementById('conf_services').value);
        const pingVal = parseInt(document.getElementById('conf_ping').value);
        
        if (trafficVal < 5) {
            showError('conf_traffic', window.I18N.error_traffic_interval_low);
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
            return;
        }
        if (trafficVal > 100) {
            showError('conf_traffic', window.I18N.error_traffic_interval_high);
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
            return;
        }
        if (servicesVal < 2) {
            showError('conf_services', window.I18N.error_services_interval_low);
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
            return;
        }
        if (pingVal < 10) {
            showError('conf_ping', window.I18N.error_ping_interval_low);
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
        SERVICES_INTERVAL: document.getElementById('conf_services').value,
        PING_INTERVAL: document.getElementById('conf_ping').value,
        PING_MODE: document.getElementById('conf_ping_mode').value,
        PING_TARGET: document.getElementById('conf_ping_target').value,
        NODE_OFFLINE_TIMEOUT: document.getElementById('conf_timeout').value
    };

    try {
        const res = await fetch('/api/settings/system', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            for (const [grp, cfg] of Object.entries(groups)) {
                cfg.ids.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) initialConfig[grp][id] = el.value;
                });
            }
            btn.innerText = window.I18N.web_saved_btn;
            btn.classList.remove('bg-blue-600', 'hover:bg-blue-500', 'bg-gray-200', 'dark:bg-gray-700');
            btn.classList.add('bg-green-600', 'hover:bg-green-500', 'text-white');
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.remove('bg-green-600', 'hover:bg-green-500', 'text-white');
                toggleSaveButton(config.btnId, false);
            }, 2000);
        } else {
            const json = await res.json();
            await window.showRequestError(json.error || 'Save failed');
            btn.innerText = originalText;
            toggleSaveButton(config.btnId, true);
        }
    } catch (e) {
        await window.showRequestError(e, true);
        btn.innerText = originalText;
        toggleSaveButton(config.btnId, true);
    }
}

function createUserRow(u) {
    const tr = document.createElement('tr');
    tr.className = "border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition";

    const tdId = document.createElement('td');
    tdId.className = "px-2 sm:px-4 py-3 font-mono text-[10px] sm:text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap";
    tdId.textContent = u.id;
    tr.appendChild(tdId);

    const tdName = document.createElement('td');
    tdName.className = "px-2 sm:px-4 py-3 font-medium text-sm text-gray-900 dark:text-white break-all max-w-[100px] sm:max-w-none";
    tdName.textContent = u.name;
    tr.appendChild(tdName);

    const tdRole = document.createElement('td');
    tdRole.className = "px-2 sm:px-4 py-3";
    const isAdmin = u.role === 'admins';
    const badgeClass = isAdmin ? 'border-green-500/30 bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400' : 'border-blue-500/30 bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400';
    const roleSpan = document.createElement('span');
    roleSpan.className = `px-1.5 sm:px-2 py-0.5 rounded text-[9px] sm:text-[10px] uppercase font-bold border ${badgeClass}`;
    roleSpan.textContent = u.role;
    tdRole.appendChild(roleSpan);
    tr.appendChild(tdRole);

    const tdAction = document.createElement('td');
    tdAction.className = "px-2 sm:px-4 py-3 text-right";
    const delBtn = document.createElement('button');
    delBtn.dataset.action = 'delete-user';
    delBtn.dataset.id = u.id;
    delBtn.dataset.name = u.name;
    delBtn.className = "text-red-500 hover:text-red-700 dark:hover:text-red-300 transition p-1";
    delBtn.title = "Delete";
    delBtn.appendChild(createTrashSvg());
    tdAction.appendChild(delBtn);
    tr.appendChild(tdAction);

    return tr;
}

function renderUsers() {
    const tbody = document.getElementById('usersTableBody');
    const section = document.getElementById('usersSection');
    if (window.USERS_DATA === null) return;
    section.classList.remove('hidden');

    if (window.USERS_DATA.length > 0) {
        tbody.replaceChildren(...window.USERS_DATA.map(createUserRow));
        if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
    } else {
        const noUsers = (typeof window.I18N !== 'undefined' && window.I18N.web_no_users) ? window.I18N.web_no_users : "No users";
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 4;
        td.className = "px-4 py-3 text-center text-gray-500 text-xs";
        td.textContent = noUsers;
        tr.appendChild(td);
        tbody.replaceChildren(tr);
    }
}

function escapeHtml(text) {
    if (!text) return text;
    return text.toString().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

async function deleteUser(id, name) {
    const displayName = name || id;
    if (!await window.showModalConfirm(window.I18N.web_confirm_delete_user.replace('{id}', displayName), window.I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'delete',
                id: id
            })
        });
        if (res.ok) {
            const idx = window.USERS_DATA.findIndex(u => String(u.id) === String(id));
            if (idx > -1) window.USERS_DATA.splice(idx, 1);
            renderUsers();
        } else {
            await window.showRequestError('Delete failed');
        }
    } catch (e) {
        await window.showRequestError(e, true);
    }
}

window.openAddUserModal = async function() {
    const promptText = (typeof window.I18N !== 'undefined' && window.I18N.web_add_user_prompt) ? window.I18N.web_add_user_prompt : "Enter user's Telegram ID:";
    const titleText = (typeof window.I18N !== 'undefined' && window.I18N.modal_title_prompt) ? window.I18N.modal_title_prompt : "Input";
    const id = await window.showModalPrompt(promptText, titleText, "123456789");

    if (!id) return;

    try {
        const res = await fetch('/api/users/action', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                action: 'add',
                id: id,
                role: 'users'
            })
        });
        const data = await res.json();
        if (res.ok) {
            window.USERS_DATA.push({
                id: id,
                name: data.name || `ID: ${id}`,
                role: 'users'
            });
            renderUsers();
        } else {
            await window.showRequestError(data.error || "Unknown");
        }
    } catch (e) {
        await window.showRequestError(e, true);
    }
}

function createNodeRow(n) {
    const decryptedIp = window.decryptData(n.ip);
    const nodeId = String(n.id);
    const tr = document.createElement('tr');
    tr.className = "border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition group";

    const tdId = document.createElement('td');
    tdId.className = "px-2 sm:px-4 py-3 font-mono text-[10px] text-gray-400 dark:text-gray-500 whitespace-nowrap";
    tdId.textContent = nodeId;
    tr.appendChild(tdId);

    const tdName = document.createElement('td');
    tdName.className = "px-2 sm:px-4 py-3 font-medium text-sm text-gray-900 dark:text-white w-full sm:w-auto";
    const nameRel = document.createElement('div');
    nameRel.className = "relative";

    if (isMainAdmin) {
        const editor = document.createElement('div');
        editor.id = `edit_name_${nodeId}`;
        editor.className = "node-name-editor hidden absolute inset-0 flex items-center gap-1";
        const input = document.createElement('input');
        input.type = "text";
        input.id = `input_name_${nodeId}`;
        input.value = n.name || '';
        input.className = "bg-white dark:bg-black/20 border border-gray-200 dark:border-white/10 rounded px-2 h-full min-w-0 w-24 sm:w-48 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500";
        input.dataset.action = "node-rename-keydown";
        input.dataset.token = nodeId;
        editor.appendChild(input);

        const btnWrap = document.createElement('div');
        btnWrap.className = "flex items-center flex-shrink-0";
        const saveBtn = document.createElement('button');
        saveBtn.dataset.action = "save-node-rename";
        saveBtn.dataset.token = nodeId;
        saveBtn.className = "text-green-500 hover:text-green-600 p-1";
        const checkSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        checkSvg.setAttribute('class', 'h-4 w-4');
        checkSvg.setAttribute('fill', 'none');
        checkSvg.setAttribute('viewBox', '0 0 24 24');
        checkSvg.setAttribute('stroke', 'currentColor');
        const checkPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        checkPath.setAttribute('stroke-linecap', 'round');
        checkPath.setAttribute('stroke-linejoin', 'round');
        checkPath.setAttribute('stroke-width', '2');
        checkPath.setAttribute('d', 'M5 13l4 4L19 7');
        checkSvg.appendChild(checkPath);
        saveBtn.appendChild(checkSvg);
        btnWrap.appendChild(saveBtn);

        const cancelBtn = document.createElement('button');
        cancelBtn.dataset.action = "cancel-node-rename";
        cancelBtn.dataset.token = nodeId;
        cancelBtn.className = "text-red-500 hover:text-red-600 p-1";
        const cancelSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        cancelSvg.setAttribute('class', 'h-4 w-4');
        cancelSvg.setAttribute('fill', 'none');
        cancelSvg.setAttribute('viewBox', '0 0 24 24');
        cancelSvg.setAttribute('stroke', 'currentColor');
        const cancelPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        cancelPath.setAttribute('stroke-linecap', 'round');
        cancelPath.setAttribute('stroke-linejoin', 'round');
        cancelPath.setAttribute('stroke-width', '2');
        cancelPath.setAttribute('d', 'M6 18L18 6M6 6l12 12');
        cancelSvg.appendChild(cancelPath);
        cancelBtn.appendChild(cancelSvg);
        btnWrap.appendChild(cancelBtn);

        editor.appendChild(btnWrap);
        nameRel.appendChild(editor);
    }

    const nameDisplay = document.createElement('div');
    nameDisplay.className = "node-name-display flex items-center gap-2 max-w-[120px] sm:max-w-none";
    const nameSpan = document.createElement('span');
    nameSpan.className = "truncate block";
    nameSpan.title = n.name || '';
    nameSpan.textContent = n.name || '';
    nameDisplay.appendChild(nameSpan);

    if (isMainAdmin) {
        const editBtn = document.createElement('button');
        editBtn.dataset.action = "start-node-rename";
        editBtn.dataset.token = nodeId;
        editBtn.className = "text-gray-400 hover:text-blue-500 p-1 flex-shrink-0 transition-colors";
        const editSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        editSvg.setAttribute('class', 'h-4 w-4');
        editSvg.setAttribute('fill', 'none');
        editSvg.setAttribute('viewBox', '0 0 24 24');
        editSvg.setAttribute('stroke', 'currentColor');
        const editPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        editPath.setAttribute('stroke-linecap', 'round');
        editPath.setAttribute('stroke-linejoin', 'round');
        editPath.setAttribute('stroke-width', '2');
        editPath.setAttribute('d', 'M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z');
        editSvg.appendChild(editPath);
        editBtn.appendChild(editSvg);
        nameDisplay.appendChild(editBtn);
    }
    nameRel.appendChild(nameDisplay);
    tdName.appendChild(nameRel);
    tr.appendChild(tdName);

    const tdIp = document.createElement('td');
    tdIp.className = "px-2 sm:px-4 py-3 text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap";
    const ipContainer = document.createElement('div');
    ipContainer.className = "ip-copy-container inline-flex items-center gap-1.5 group/ip";
    ipContainer.dataset.copyIp = decryptedIp || '';
    const ipSpan = document.createElement('span');
    ipSpan.className = "ip-copy-text font-mono select-all";
    ipSpan.title = (typeof window.I18N !== 'undefined' && window.I18N.web_copy_ip) ? window.I18N.web_copy_ip : 'Copy IP';
    ipSpan.textContent = decryptedIp || 'Unknown';
    ipContainer.appendChild(ipSpan);
    if (decryptedIp && decryptedIp !== 'Unknown' && decryptedIp !== '-') {
        const copyWrapper = document.createElement('span');
        window.setSafeHTML(copyWrapper, window.renderCopyIpButton(decryptedIp));
        if (copyWrapper.firstElementChild) {
            ipContainer.appendChild(copyWrapper.firstElementChild);
        }
    }
    tdIp.appendChild(ipContainer);
    tr.appendChild(tdIp);

    const tdAction = document.createElement('td');
    tdAction.className = "px-2 sm:px-4 py-3 text-right";
    const delBtn = document.createElement('button');
    delBtn.dataset.action = "delete-node";
    delBtn.dataset.token = nodeId;
    delBtn.className = "text-red-500 hover:text-red-700 dark:hover:text-red-300 transition p-1";
    delBtn.title = "Delete";
    delBtn.appendChild(createTrashSvg());
    tdAction.appendChild(delBtn);
    tr.appendChild(tdAction);

    return tr;
}

function renderNodes() {
    const tbody = document.getElementById('nodesTableBody');
    const section = document.getElementById('nodesSection');
    if (window.NODES_DATA === null) return;
    section.classList.remove('hidden');

    if (window.NODES_DATA.length > 0) {
        tbody.replaceChildren(...window.NODES_DATA.map(createNodeRow));
        if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
    } else {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 4;
        td.className = "px-4 py-3 text-center text-gray-500 text-xs";
        td.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_no_nodes) ? window.I18N.web_no_nodes : "No nodes";
        tr.appendChild(td);
        tbody.replaceChildren(tr);
    }
}
window.startNodeRename = function (token) {
    if (token) {
        const editEl = document.getElementById(`edit_name_${token}`);
        if (editEl) editEl.classList.remove('hidden');
        const input = document.getElementById(`input_name_${token}`);
        if (input) {
            input.focus({ preventScroll: true });
            if (typeof window.NODES_DATA !== 'undefined' && Array.isArray(window.NODES_DATA)) {
                const node = window.NODES_DATA.find(n => String(n.id) === String(token));
                if (node) input.value = node.name;
            }
        }
        return;
    }
    const nameDisplay = document.getElementById('nodeNameContainer');
    const nameInputContainer = document.getElementById('nodeNameInputContainer');
    const nameInput = document.getElementById('modalNodeNameInput');
    const currentName = document.getElementById('modalNodeName')?.textContent?.trim();
    if (nameDisplay && nameInputContainer && nameInput) {
        nameDisplay.classList.add('hidden');
        nameInputContainer.classList.remove('hidden');
        nameInput.value = currentName || '';
        nameInput.focus({ preventScroll: true });
    }
};

window.cancelNodeRename = function (token) {
    if (token) {
        const el = document.getElementById(`edit_name_${token}`);
        if (el) el.classList.add('hidden');
        return;
    }
    const nameDisplay = document.getElementById('nodeNameContainer');
    const nameInputContainer = document.getElementById('nodeNameInputContainer');
    if (nameDisplay && nameInputContainer) {
        nameDisplay.classList.remove('hidden');
        nameInputContainer.classList.add('hidden');
    }
};

window.saveNodeRename = async function (token) {
    if (token) {
        const input = document.getElementById(`input_name_${token}`);
        if (!input) return;
        const newName = input.value.trim();
        if (!newName) return;

        // Optimistic update
        const nodeIndex = typeof window.NODES_DATA !== 'undefined' && Array.isArray(window.NODES_DATA)
            ? window.NODES_DATA.findIndex(n => String(n.id) === String(token))
            : -1;
        const targetNode = nodeIndex > -1 ? window.NODES_DATA.at(nodeIndex) : null;
        const oldName = targetNode ? targetNode.name : '';
        if (targetNode) {
            targetNode.name = newName;
            if (typeof renderNodes === 'function') renderNodes();
        }

        try {
            const res = await fetch('/api/nodes/rename', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    node_id: Number(token),
                    name: newName
                })
            });

            if (res.ok) {
                if (window.showToast) {
                    const msg = (typeof window.I18N !== 'undefined' && window.I18N.web_node_rename_success) ? window.I18N.web_node_rename_success : "Name updated";
                    window.showToast(msg);
                }
            } else {
                let data = {};
                try { data = await res.json(); } catch {}
                // Revert
                if (targetNode) {
                    targetNode.name = oldName;
                    if (typeof renderNodes === 'function') renderNodes();
                }
                const errorMsg = (typeof window.I18N !== 'undefined' && window.I18N.web_node_rename_error) ? window.I18N.web_node_rename_error : "Error updating name";
                const errTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
                if (window.showModalAlert) await window.showModalAlert(data.error || errorMsg, errTitle);
            }
        } catch (e) {
            console.error(e);
            // Revert
            if (targetNode) {
                targetNode.name = oldName;
                if (typeof renderNodes === 'function') renderNodes();
            }
            const errTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
            if (window.showModalAlert) await window.showModalAlert(String(e), errTitle);
        }
        return;
    }

    const nameInput = document.getElementById('modalNodeNameInput');
    if (!nameInput) return;
    const newName = nameInput.value.trim();
    if (!newName || typeof window.currentNodeId === 'undefined' || !window.currentNodeId) return;
    if (typeof window.renderNodeModalTitle === 'function') {
        window.renderNodeModalTitle(document.getElementById('modalNodeName'), newName);
    }
    if (typeof window.cancelNodeRename === 'function') window.cancelNodeRename();
    try {
        const res = await fetch('/api/nodes/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ node_id: window.currentNodeId, name: newName })
        });
        if (!res.ok) throw new Error("Failed to rename node");
        if (typeof window.updateNodeNameInList === 'function') window.updateNodeNameInList(window.currentNodeId, newName);
    } catch (e) {
        console.error("Dashboard node rename error:", e);
        const errTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
        if (window.showModalAlert) await window.showModalAlert(String(e), errTitle);
    }
};

window.handleSettingsRenameKeydown = function (event, token) {
    if (event.key === 'Enter') {
        window.saveNodeRename(token);
    } else if (event.key === 'Escape') {
        window.cancelNodeRename(token);
    }
};

async function deleteNode(nodeId) {
    const confirmMsg = (typeof window.I18N !== 'undefined' && window.I18N.web_node_delete_confirm) ? window.I18N.web_node_delete_confirm : "Delete this node?";
    const confirmTitle = (typeof window.I18N !== 'undefined' && window.I18N.modal_title_confirm) ? window.I18N.modal_title_confirm : "Confirm";
    if (!await window.showModalConfirm(confirmMsg, confirmTitle)) return;

    try {
        const res = await fetch('/api/nodes/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                node_id: Number(nodeId)
            })
        });
        if (res.ok) {
            const idx = window.NODES_DATA.findIndex(n => String(n.id) === nodeId);
            if (idx > -1) window.NODES_DATA.splice(idx, 1);
            renderNodes();
        } else {
            const data = await res.json();
            await window.showRequestError(data.error || 'Delete failed');
        }
    } catch (e) {
        await window.showRequestError(e, true);
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
        const errorShort = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
        await window.showModalAlert(window.I18N.web_pass_mismatch, errorShort);
        return;
    }

    const origText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "...";

    try {
        const res = await fetch('/api/settings/password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                current_password: current,
                new_password: newPass
            })
        });
        const data = await res.json();

        if (res.ok) {
            const successText = (typeof window.I18N !== 'undefined' && window.I18N.web_success) ? window.I18N.web_success : "Success";
            await window.showModalAlert(window.I18N.web_pass_changed, successText);
            currentEl.value = "";
            newPassEl.value = "";
            confirmEl.value = "";
            if (typeof initChangePasswordUI === 'function') {
                const dummyEvent = new Event('input');
                currentEl.dispatchEvent(dummyEvent);
            }
        } else {
            await window.showRequestError(data.error);
        }
    } catch (e) {
        await window.showRequestError(e, true);
    }
    btn.disabled = false;
    btn.innerText = origText;
}

// --- WEB PUSH NOTIFICATIONS LOGIC ---

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding)
        .replace(/\-/g, '+')
        .replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

function arrayBufferToBase64Url(buffer) {
    if (!buffer) return '';
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '');
}

async function getSwRegistration() {
    if (window.swRegistration) return window.swRegistration;
    if ('serviceWorker' in navigator) {
        try {
            return await navigator.serviceWorker.ready;
        } catch (e) {
            console.debug('Failed to get SW ready:', e);
        }
    }
    return null;
}

function updatePushTestButtonState(isActive) {
    const btn = document.getElementById('sendTestPushBtn');
    if (!btn) return;
    const icon = btn.querySelector('svg');
    btn.disabled = false;
    if (isActive) {
        btn.className = 'flex-1 w-full sm:w-auto min-h-[38px] py-2 px-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/40 rounded-xl text-xs font-semibold sm:font-bold transition flex items-center justify-center gap-1.5 shadow-xs cursor-pointer active:scale-[0.98] select-none text-center';
        if (icon) icon.className = 'h-4 w-4 shrink-0 text-blue-500';
    } else {
        btn.className = 'flex-1 w-full sm:w-auto min-h-[38px] py-2 px-3 bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-400 dark:text-gray-500 hover:bg-gray-200/60 dark:hover:bg-white/10 rounded-xl text-xs font-semibold sm:font-bold transition flex items-center justify-center gap-1.5 shadow-xs cursor-pointer active:scale-[0.98] select-none text-center';
        if (icon) icon.className = 'h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500';
    }
}
window.updatePushTestButtonState = updatePushTestButtonState;

async function initPushNotificationsUI() {
    const toggle = document.getElementById('pushNotificationToggle');
    const badge = document.getElementById('pushStatusBadge');
    const warning = document.getElementById('pushHintWarning');

    if (!toggle || !badge) return;

    const isSupported = ('serviceWorker' in navigator) && ('PushManager' in window) && ('Notification' in window);
    const isSecure = window.isSecureContext || window.location.protocol === 'https:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';

    if (!isSupported || !isSecure) {
        toggle.disabled = true;
        updatePushTestButtonState(false);
        badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_unsupported) ? window.I18N.web_push_status_unsupported : 'Unsupported / HTTPS required';
        badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400 shrink-0 whitespace-nowrap';
        if (warning) {
            warning.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_unsupported) ? window.I18N.web_push_status_unsupported : 'Web Push requires HTTPS or localhost';
            warning.classList.remove('hidden');
        }
        return;
    }

    if (Notification.permission === 'denied') {
        toggle.checked = false;
        toggle.disabled = false;
        updatePushTestButtonState(false);
        badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_blocked) ? window.I18N.web_push_status_blocked : 'Blocked';
        badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 shrink-0 whitespace-nowrap';
        if (warning) {
            warning.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_permission_denied) ? window.I18N.web_push_permission_denied : 'Permission denied in browser settings';
            warning.classList.remove('hidden');
        }
        return;
    }

    try {
        const reg = await getSwRegistration();
        const sub = reg ? await reg.pushManager.getSubscription() : null;
        if (sub) {
            toggle.checked = true;
            updatePushTestButtonState(true);
            badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_active) ? window.I18N.web_push_status_active : 'Active';
            badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 shrink-0 whitespace-nowrap';
            if (warning) warning.classList.add('hidden');
        } else {
            toggle.checked = false;
            updatePushTestButtonState(false);
            badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_inactive) ? window.I18N.web_push_status_inactive : 'Disabled';
            badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0 whitespace-nowrap';
            if (warning) warning.classList.add('hidden');
        }
    } catch (e) {
        console.debug('Error checking push subscription:', e);
    }
}
window.initPushNotificationsUI = initPushNotificationsUI;

async function togglePushNotifications(checkbox) {
    const badge = document.getElementById('pushStatusBadge');
    const warning = document.getElementById('pushHintWarning');
    const spinner = document.getElementById('pushToggleSpinner');

    checkbox.disabled = true;
    if (spinner) spinner.classList.remove('hidden');

    if (checkbox.checked) {
        if (badge) {
            badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_waiting)
                ? window.I18N.web_push_status_waiting
                : ((typeof window.CURRENT_LANG !== 'undefined' && window.CURRENT_LANG === 'en') ? 'Waiting for confirmation' : 'Ожидание подтверждения');
            badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300 shrink-0 whitespace-nowrap';
        }

        try {
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                checkbox.checked = false;
                updatePushTestButtonState(false);
                if (badge) {
                    badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_blocked) ? window.I18N.web_push_status_blocked : 'Blocked';
                    badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 shrink-0 whitespace-nowrap';
                }
                if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_push_permission_denied) ? window.I18N.web_push_permission_denied : 'Permission denied', 'warning');
                return;
            }

            const resp = await fetch('/api/push/vapid-key');
            const data = await resp.json();
            if (!data || !data.publicKey) {
                throw new Error(data?.error || 'Failed to get VAPID key');
            }

            const reg = await getSwRegistration();
            if (!reg) throw new Error('Service Worker not ready');

            const sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(data.publicKey)
            });

            const subPayload = {
                endpoint: sub.endpoint,
                keys: {
                    p256dh: arrayBufferToBase64Url(sub.getKey('p256dh')),
                    auth: arrayBufferToBase64Url(sub.getKey('auth'))
                }
            };

            const saveResp = await fetch('/api/push/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(subPayload)
            });

            if (saveResp.ok) {
                if (badge) {
                    badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_active) ? window.I18N.web_push_status_active : 'Active';
                    badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 shrink-0 whitespace-nowrap';
                }
                updatePushTestButtonState(true);
                if (warning) warning.classList.add('hidden');
                if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_push_subscribed) ? window.I18N.web_push_subscribed : 'Push notifications enabled!');
            } else {
                throw new Error('Failed to save push subscription');
            }
        } catch (e) {
            console.error('Push subscribe error:', e);
            checkbox.checked = false;
            updatePushTestButtonState(false);
            if (badge) {
                badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_inactive) ? window.I18N.web_push_status_inactive : 'Disabled';
                badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0 whitespace-nowrap';
            }
            if (window.showToast) window.showToast(String(e.message || e), 'error');
        } finally {
            if (spinner) spinner.classList.add('hidden');
            checkbox.disabled = false;
        }
    } else {
        try {
            const reg = await getSwRegistration();
            if (reg) {
                const sub = await reg.pushManager.getSubscription();
                if (sub) {
                    const endpoint = sub.endpoint;
                    await sub.unsubscribe();
                    await fetch('/api/push/unsubscribe', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ endpoint })
                    });
                }
            }
            if (badge) {
                badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_inactive) ? window.I18N.web_push_status_inactive : 'Disabled';
                badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0 whitespace-nowrap';
            }
            updatePushTestButtonState(false);
            if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_push_unsubscribed) ? window.I18N.web_push_unsubscribed : 'Push notifications disabled');
        } catch (e) {
            console.error('Push unsubscribe error:', e);
            if (window.showToast) window.showToast(String(e.message || e), 'error');
        } finally {
            if (spinner) spinner.classList.add('hidden');
            checkbox.disabled = false;
        }
    }
}
window.togglePushNotifications = togglePushNotifications;

async function sendTestPushNotification(btn) {
    if (!btn) return;
    const toggle = document.getElementById('pushNotificationToggle');
    if (!toggle || !toggle.checked) {
        const defaultHint = (typeof window.CURRENT_LANG !== 'undefined' && window.CURRENT_LANG === 'en')
            ? 'Cannot send test notification: please enable Web Push first'
            : 'Невозможно отправить тестовое уведомление: включите Web Push';
        const hint = (typeof window.I18N !== 'undefined' && window.I18N.web_push_test_disabled_hint)
            ? window.I18N.web_push_test_disabled_hint
            : defaultHint;
        if (window.showToast) window.showToast(hint, 'warning');
        return;
    }
    const originalNodes = Array.from(btn.childNodes);
    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-4 w-4 text-blue-500 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;

    try {
        const resp = await fetch('/api/push/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data && data.status === 'ok') {
            if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_push_test_success) ? window.I18N.web_push_test_success : 'Test notification sent!');
        } else if (data && data.status === 'no_subscriptions') {
            if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_push_test_fail) ? window.I18N.web_push_test_fail : 'No active subscriptions', 'warning');
        } else {
            throw new Error(data?.error || 'Failed to send test push');
        }
    } catch (e) {
        console.error('Test push error:', e);
        if (window.showToast) window.showToast(String(e.message || e), 'error');
    } finally {
        btn.replaceChildren(...originalNodes);
        btn.disabled = false;
    }
}
window.sendTestPushNotification = sendTestPushNotification;

async function revokeAllPushSubscriptions(btn) {
    if (!btn) return;
    const confirmMsg = (typeof window.I18N !== 'undefined' && window.I18N.web_push_revoke_confirm)
        ? window.I18N.web_push_revoke_confirm
        : 'Revoke all push subscriptions across all your devices?';
    const confirmTitle = (typeof window.I18N !== 'undefined' && window.I18N.modal_title_confirm)
        ? window.I18N.modal_title_confirm
        : 'Confirm';

    if (window.showModalConfirm) {
        if (!await window.showModalConfirm(confirmMsg, confirmTitle)) return;
    } else if (!confirm(confirmMsg)) {
        return;
    }

    const originalNodes = Array.from(btn.childNodes);
    btn.disabled = true;
    btn.innerHTML = `<svg class="animate-spin h-4 w-4 text-red-500 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;

    try {
        try {
            const reg = await getSwRegistration();
            if (reg) {
                const sub = await reg.pushManager.getSubscription();
                if (sub) await sub.unsubscribe();
            }
        } catch (swErr) {
            console.debug('Error unsubscribing current device:', swErr);
        }

        const resp = await fetch('/api/push/revoke-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data && data.status === 'ok') {
            const toggle = document.getElementById('pushNotificationToggle');
            const badge = document.getElementById('pushStatusBadge');
            if (toggle) toggle.checked = false;
            updatePushTestButtonState(false);
            if (badge) {
                badge.textContent = (typeof window.I18N !== 'undefined' && window.I18N.web_push_status_inactive) ? window.I18N.web_push_status_inactive : 'Disabled';
                badge.className = 'px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300 shrink-0 whitespace-nowrap';
            }
            if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_push_revoked_success) ? window.I18N.web_push_revoked_success : 'All push subscriptions revoked!');
        } else {
            throw new Error(data?.error || 'Failed to revoke subscriptions');
        }
    } catch (e) {
        console.error('Revoke push error:', e);
        if (window.showToast) window.showToast(String(e.message || e), 'error');
    } finally {
        btn.replaceChildren(...originalNodes);
        btn.disabled = false;
    }
}
window.revokeAllPushSubscriptions = revokeAllPushSubscriptions;

// --- NOTIFICATIONS MENU LOGIC ---
let currentNodeForNotif = null;
let currentNotifView = 'menu';

window.switchNotifView = function(view) {
    document.getElementById('notifViewMenu').classList.add('hidden');
    document.getElementById('notifViewGlobal').classList.add('hidden');
    document.getElementById('notifViewNodes').classList.add('hidden');
    document.getElementById('notifViewNodeDetail').classList.add('hidden');

    currentNotifView = view;
    
    const backBtn = document.getElementById('notifHeaderBackBtn');
    if (backBtn) {
        if (view === 'menu') {
            backBtn.classList.add('hidden');
            backBtn.classList.remove('flex');
        } else {
            backBtn.classList.remove('hidden');
            backBtn.classList.add('flex');
        }
    }

    if (view === 'menu') {
        document.getElementById('notifViewMenu').classList.remove('hidden');
    } else if (view === 'global') {
        document.getElementById('notifViewGlobal').classList.remove('hidden');
    } else if (view === 'nodes') {
        document.getElementById('notifViewNodes').classList.remove('hidden');
        renderNotifNodesList();
    } else if (view === 'node_detail') {
        document.getElementById('notifViewNodeDetail').classList.remove('hidden');
        renderNotifNodeDetail();
    }
};

window.notifGoBack = function() {
    if (currentNotifView === 'node_detail') {
        window.switchNotifView('nodes');
    } else {
        window.switchNotifView('menu');
    }
};

function renderNotifNodesList() {
    const container = document.getElementById('notifNodesListContainer');
    if (!container || !window.NODES_DATA || window.NODES_DATA.length === 0) {
        window.setSafeHTML(container, `<div class="text-center text-gray-500 py-4">${window.I18N.web_no_nodes || ''}</div>`);
        return;
    }

    window.setSafeHTML(container, window.NODES_DATA.map(n => {
        return `
        <button data-action="switch-notif-view" data-token="${n.id}" class="flex items-center justify-between w-full bg-gray-50 dark:bg-black/20 p-4 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer group">
            <div class="flex items-center gap-3 min-w-0">
                <i class="icon icon-monitor icon-lg text-blue-500 group-hover:scale-110 transition-transform flex-shrink-0"></i>
                <span data-sensitive class="text-sm font-bold text-gray-900 dark:text-white text-left truncate">${escapeHtml(n.name)}</span>
            </div>
            <svg class="w-5 h-5 text-gray-400 group-hover:text-blue-500 transition-colors flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
        </button>`;
    }).join(''));
}

function renderNotifNodeDetail() {
    const container = document.getElementById('notifNodeDetailContainer');
    const nameEl = document.getElementById('notifDetailNodeName');
    const titleEl = document.getElementById('notifNodeSettingsTitle');
    if (!container || !currentNodeForNotif) return;

    const node = window.NODES_DATA.find(n => String(n.id) === currentNodeForNotif);
    if (node) {
        const textSpan = nameEl.querySelector('span.truncate');
        if (textSpan) {
            textSpan.innerText = node.name;
        } else {
            nameEl.innerText = node.name;
        }
        if (window.I18N.notif_node_settings_title) {
            let cleanTitle = window.I18N.notif_node_settings_title.replace('{name}', node.name);
            let prevTitle;
            do {
                prevTitle = cleanTitle;
                cleanTitle = cleanTitle.replace(/<[^>]*>?/gm, '');
            } while (cleanTitle !== prevTitle);
            
            titleEl.innerText = cleanTitle;
        }
    }

    const t = currentNodeForNotif;
    
    // Check if override exists, else use global state
    function isChecked(type) {
        const key = `node_${t}_${type}`;
        if (window.USER_ALERTS) {
            const overrideVal = Reflect.get(window.USER_ALERTS, key);
            if (typeof overrideVal !== 'undefined') return overrideVal;
            const globalVal = Reflect.get(window.USER_ALERTS, type);
            return globalVal || false;
        }
        return false;
    }

    window.setSafeHTML(container, `
        <div class="flex items-center justify-between bg-gray-50 dark:bg-black/20 p-4 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer" data-action="click-alert-toggle" data-target="n_alert_${t}_downtime">
            <div>
                <div class="text-sm font-bold text-gray-900 dark:text-white">${window.I18N.notifications_alert_name_downtime || 'Downtime Alert'}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">${window.I18N.web_notif_downtime_desc || 'Notify when node goes offline'}</div>
            </div>
            <label class="relative inline-flex items-center cursor-pointer" data-action="stop-propagation">
                <input type="checkbox" id="n_alert_${t}_downtime" class="sr-only peer" data-action="trigger-auto-save" data-view="node_detail" ${isChecked('downtime') ? 'checked' : ''}>
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-green-500"></div>
            </label>
        </div>
        <div class="flex items-center justify-between bg-gray-50 dark:bg-black/20 p-4 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer" data-action="click-alert-toggle" data-target="n_alert_${t}_node_resources">
            <div>
                <div class="text-sm font-bold text-gray-900 dark:text-white">${window.I18N.notifications_alert_name_res || 'High Resource Usage'}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">${window.I18N.web_notif_resources_desc || 'CPU/RAM > 90%'}</div>
            </div>
            <label class="relative inline-flex items-center cursor-pointer" data-action="stop-propagation">
                <input type="checkbox" id="n_alert_${t}_node_resources" class="sr-only peer" data-action="trigger-auto-save" data-view="node_detail" ${isChecked('node_resources') ? 'checked' : ''}>
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-green-500"></div>
            </label>
        </div>
        <div class="flex items-center justify-between bg-gray-50 dark:bg-black/20 p-4 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer" data-action="click-alert-toggle" data-target="n_alert_${t}_node_logins">
            <div>
                <div class="text-sm font-bold text-gray-900 dark:text-white">${window.I18N.notifications_alert_name_logins || 'SSH Logins'}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">${window.I18N.web_notif_logins_desc || 'Successful SSH connections'}</div>
            </div>
            <label class="relative inline-flex items-center cursor-pointer" data-action="stop-propagation">
                <input type="checkbox" id="n_alert_${t}_node_logins" class="sr-only peer" data-action="trigger-auto-save" data-view="node_detail" ${isChecked('node_logins') ? 'checked' : ''}>
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-green-500"></div>
            </label>
        </div>
        <div class="flex items-center justify-between bg-gray-50 dark:bg-black/20 p-4 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer" data-action="click-alert-toggle" data-target="n_alert_${t}_billing">
            <div>
                <div class="text-sm font-bold text-gray-900 dark:text-white">${window.I18N.billing_toggle_reminder || 'Billing Notifications'}</div>
            </div>
            <label class="relative inline-flex items-center cursor-pointer" data-action="stop-propagation">
                <input type="checkbox" id="n_alert_${t}_billing" class="sr-only peer" data-action="trigger-auto-save" data-view="node_detail" ${node && node.reminder_enabled ? 'checked' : ''}>
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-green-500"></div>
            </label>
        </div>
    `);
}

let notifStatusHideTimer = null;

function getNotifStatusElement(scope = 'agent') {
    if (scope === 'node_detail') return document.getElementById('notifStatusNodeDetail');
    if (scope === 'nodes_global') return document.getElementById('notifStatusNodesGlobal');
    return document.getElementById('notifStatusAgent');
}

function resetNotifStatusElement(statusEl) {
    if (!statusEl) return;
    statusEl.classList.remove(
        'opacity-100',
        'text-gray-500', 'bg-gray-200', 'dark:text-gray-400', 'dark:bg-white/10',
        'text-green-700', 'bg-green-100', 'dark:text-green-300', 'dark:bg-green-900/30',
        'text-red-700', 'bg-red-100', 'dark:text-red-300', 'dark:bg-red-900/30'
    );
    statusEl.classList.add('opacity-0');
    // Do not clear innerHTML immediately to allow opacity transition to play smoothly
}

function showNotifStatus(message, state = 'neutral', autoHideMs = 1800, scope = 'agent') {
    const statusEls = [
        document.getElementById('notifStatusAgent'),
        document.getElementById('notifStatusNodesGlobal'),
        document.getElementById('notifStatusNodeDetail')
    ];
    const statusEl = getNotifStatusElement(scope);
    if (!statusEl) return;

    if (notifStatusHideTimer) {
        clearTimeout(notifStatusHideTimer);
        notifStatusHideTimer = null;
    }

    statusEls.forEach((element) => {
        if (element && element !== statusEl) {
            resetNotifStatusElement(element);
        }
    });

    statusEl.classList.remove(
        'opacity-0', 'opacity-100',
        'text-gray-500', 'bg-gray-200', 'dark:text-gray-400', 'dark:bg-white/10',
        'text-green-700', 'bg-green-100', 'dark:text-green-300', 'dark:bg-green-900/30',
        'text-red-700', 'bg-red-100', 'dark:text-red-300', 'dark:bg-red-900/30'
    );

    const stateClasses = {
        neutral: ['text-gray-500', 'bg-gray-200', 'dark:text-gray-400', 'dark:bg-white/10'],
        success: ['text-green-700', 'bg-green-100', 'dark:text-green-300', 'dark:bg-green-900/30'],
        error: ['text-red-700', 'bg-red-100', 'dark:text-red-300', 'dark:bg-red-900/30']
    };

    statusEl.replaceChildren();
    statusEl.appendChild(createStatusSvg(state));
    if (message) {
        const textSpan = document.createElement('span');
        textSpan.textContent = message;
        statusEl.appendChild(textSpan);
    }
    statusEl.classList.add('opacity-100', ...(stateClasses[state] || stateClasses.neutral));

    if (autoHideMs > 0) {
        notifStatusHideTimer = setTimeout(() => {
            resetNotifStatusElement(statusEl);
        }, autoHideMs);
    }
}

async function triggerAutoSave(scope = 'agent') {
    showNotifStatus((typeof window.I18N !== 'undefined' && window.I18N.web_saving_btn) ? window.I18N.web_saving_btn : '', 'neutral', 0, scope);

    const data = {
        resources: document.getElementById('alert_resources')?.checked || false,
        logins: document.getElementById('alert_logins')?.checked || false,
        bans: document.getElementById('alert_bans')?.checked || false,
        downtime: document.getElementById('alert_downtime')?.checked || false,
        node_resources: document.getElementById('alert_node_resources')?.checked || false,
        node_logins: document.getElementById('alert_node_logins')?.checked || false,
        master_billing: document.getElementById('alert_master_billing')?.checked || false,
    };
    
    if (typeof window.USER_ALERTS === 'undefined') window.USER_ALERTS = {};
    Object.assign(window.USER_ALERTS, data);

    if (currentNodeForNotif && !document.getElementById('notifViewNodeDetail').classList.contains('hidden')) {
        const t = currentNodeForNotif;
        const nDowntime = document.getElementById(`n_alert_${t}_downtime`)?.checked;
        const nRes = document.getElementById(`n_alert_${t}_node_resources`)?.checked;
        const nLogins = document.getElementById(`n_alert_${t}_node_logins`)?.checked;
        const nBilling = document.getElementById(`n_alert_${t}_billing`)?.checked;
        
        if (nDowntime !== undefined) { Reflect.set(data, `node_${t}_downtime`, nDowntime); Reflect.set(window.USER_ALERTS, `node_${t}_downtime`, nDowntime); }
        if (nRes !== undefined) { Reflect.set(data, `node_${t}_node_resources`, nRes); Reflect.set(window.USER_ALERTS, `node_${t}_node_resources`, nRes); }
        if (nLogins !== undefined) { Reflect.set(data, `node_${t}_node_logins`, nLogins); Reflect.set(window.USER_ALERTS, `node_${t}_node_logins`, nLogins); }
        if (nBilling !== undefined) { Reflect.set(data, `node_${t}_billing`, nBilling); }
    }

    try {
        const res = await fetch('/api/settings/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });

        if (res.ok) {
            showNotifStatus((typeof window.I18N !== 'undefined' && window.I18N.web_saved_btn) ? window.I18N.web_saved_btn : '', 'success', 1600, scope);
        } else {
            showNotifStatus((typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : '', 'error', 2500, scope);
        }
    } catch (e) {
        console.error(e);
        showNotifStatus((typeof window.I18N !== 'undefined' && window.I18N.web_conn_error_short) ? window.I18N.web_conn_error_short : '', 'error', 2500, scope);
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
        keys: ["enable_nodes", "enable_users", "enable_services", "enable_update", "enable_optimize", "enable_billing"]
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
    if (typeof window.KEYBOARD_CONFIG === 'undefined') return keys;
    for (const catData of Object.values(btnCategories)) {
        catData.keys.forEach(k => {
            if (Object.hasOwn(window.KEYBOARD_CONFIG, k)) {
                keys.push(k);
            }
        });
    }
    return keys;
}

function renderKeyboardPreview() {
    const container = document.getElementById('keyboardPreview');
    if (!container || typeof window.KEYBOARD_CONFIG === 'undefined') return;

    const visibleKeys = getVisibleKeys();
    const totalAll = visibleKeys.length;
    const totalEnabled = visibleKeys.filter(k => Reflect.get(window.KEYBOARD_CONFIG, k)).length;
    const activeText = (typeof window.I18N !== 'undefined' && window.I18N.web_kb_active) ? window.I18N.web_kb_active : "Active:";
    const prevEl = document.getElementById('kbActiveCount');
    let startVal = 0;
    if (prevEl) {
        startVal = parseInt(prevEl.innerText) || 0;
    }

    window.setSafeHTML(container, `<span class="px-3 py-1 rounded-full bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-300 text-xs font-bold border border-green-200 dark:border-green-500/20">${activeText} <span id="kbActiveCount">${startVal}</span> / ${totalAll}</span>`);

    const countEl = document.getElementById('kbActiveCount');
    if (countEl) {
        animateCounter(countEl, startVal, totalEnabled, 1000);
    }
}

window.toggleCategoryKeyboard = async function (catKey) {
    const catData = Reflect.get(btnCategories, catKey);
    if (!catData) return;
    const keys = catData.keys.filter(k => Object.hasOwn(window.KEYBOARD_CONFIG, k));
    const allEnabled = keys.length > 0 && keys.every(k => Reflect.get(window.KEYBOARD_CONFIG, k));
    const newVal = !allEnabled;
    keys.forEach(key => { Reflect.set(window.KEYBOARD_CONFIG, key, newVal); });
    renderKeyboardModalContent();
    renderKeyboardPreview();
    updateBulkButtonsUI();
    await triggerKeyboardSave(true);
};

function renderKeyboardModalContent() {
    const container = document.getElementById('keyboardModalContent');
    if (!container || typeof window.KEYBOARD_CONFIG === 'undefined') return;

    const sections = [];
    const iconMap = {
        'enable_selftest': 'icon-wrench text-blue-500',
        'enable_traffic': 'icon-radar text-indigo-500',
        'enable_uptime': 'icon-clock text-green-500',
        'enable_speedtest': 'icon-rocket text-purple-500',
        'enable_top': 'icon-fire text-orange-500',
        'enable_nodes': 'icon-monitor text-blue-400',
        'enable_users': 'icon-user text-indigo-400',
        'enable_services': 'icon-gear text-gray-500',
        'enable_update': 'icon-refresh text-green-400',
        'enable_optimize': 'icon-lightning text-yellow-500',
        'enable_restart': 'icon-refresh text-teal-500',
        'enable_reboot': 'icon-refresh text-red-500',
        'enable_billing': 'icon-credit-card text-emerald-500',
        'enable_sshlog': 'icon-document text-gray-400',
        'enable_fail2ban': 'icon-lock text-red-400',
        'enable_logs': 'icon-document text-gray-400',
        'enable_xray': 'icon-xray text-cyan-500',
        'enable_vless': 'icon-link text-blue-400',
        'enable_notifications': 'icon-bell text-yellow-400',
        'enable_client_alerts': 'icon-megaphone text-orange-400'
    };

    for (const [catKey, catData] of Object.entries(btnCategories)) {
        const categoryKeys = catData.keys.filter(k => Object.hasOwn(window.KEYBOARD_CONFIG, k));
        if (categoryKeys.length === 0) continue;

        const catTitleVal = (typeof window.I18N !== 'undefined' && catData.titleKey) ? Reflect.get(window.I18N, catData.titleKey) : null;
        let title = catTitleVal || catKey;
        title = title.replace(/[\u2600-\u27bf\u2b50\u2b55\u23e9-\u23f3\u23f8-\u23fa\u25b6\u25c0\u2328\ud83c-\ud83e][\udc00-\udfff]?/g, '').replace(/[\u2600-\u27BF]/g, '').trim();

        const enabledCount = categoryKeys.filter(k => Reflect.get(window.KEYBOARD_CONFIG, k)).length;
        const totalCount = categoryKeys.length;
        const allOn = enabledCount === totalCount;
        const badgeColor = enabledCount === 0
            ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50'
            : allOn
                ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50'
                : 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 hover:bg-yellow-200 dark:hover:bg-yellow-900/50';

        const catWrapper = document.createElement('div');
        catWrapper.className = "mb-2";

        const catHeader = document.createElement('div');
        catHeader.className = "flex items-center justify-between mb-3";

        const h4 = document.createElement('h4');
        h4.className = "text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider ml-1";
        h4.textContent = title;
        catHeader.appendChild(h4);

        const toggleBtn = document.createElement('button');
        toggleBtn.id = `kb-badge-${catKey}`;
        toggleBtn.dataset.action = "toggle-category-keyboard";
        toggleBtn.dataset.cat = catKey;
        toggleBtn.className = `flex items-center justify-center gap-1.5 text-xs font-bold px-3 py-1 rounded-lg transition-all duration-200 cursor-pointer shadow-sm hover:shadow active:scale-95 select-none ${badgeColor}`;
        toggleBtn.title = "Toggle All";

        const countSpan = document.createElement('span');
        countSpan.textContent = `${enabledCount}/${totalCount}`;
        toggleBtn.appendChild(countSpan);
        toggleBtn.appendChild(createSwitchArrowsSvg());
        catHeader.appendChild(toggleBtn);
        catWrapper.appendChild(catHeader);

        const grid = document.createElement('div');
        grid.className = "grid grid-cols-1 sm:grid-cols-2 gap-3";

        categoryKeys.forEach(key => {
            const enabled = Boolean(Reflect.get(window.KEYBOARD_CONFIG, key));
            const i18nLabel = (typeof window.I18N !== 'undefined') ? Reflect.get(window.I18N, `lbl_${key}`) : undefined;
            let label = i18nLabel || key;
            label = label.replace(/[\u2600-\u27bf\u2b50\u2b55\u23e9-\u23f3\u23f8-\u23fa\u25b6\u25c0\u2328\ud83c-\ud83e][\udc00-\udfff]?/g, '').replace(/[\u2600-\u27BF]/g, '').trim();
            const iconClass = Reflect.get(iconMap, key) || 'icon-gear text-gray-400';

            const card = document.createElement('div');
            card.className = "flex items-center justify-between bg-gray-50 dark:bg-black/20 p-3 rounded-xl hover:bg-gray-100 dark:hover:bg-black/30 transition border border-gray-200 dark:border-white/5 cursor-pointer select-none";
            card.dataset.action = "click-alert-toggle";
            card.dataset.target = key;

            const iconLabelDiv = document.createElement('div');
            iconLabelDiv.className = "flex items-center gap-2 min-w-0 pr-2";
            const iconEl = document.createElement('i');
            iconEl.className = `icon ${iconClass} icon-sm flex-shrink-0`;
            iconLabelDiv.appendChild(iconEl);

            const labelSpan = document.createElement('span');
            labelSpan.className = "text-sm font-medium text-gray-900 dark:text-white truncate";
            labelSpan.title = label;
            labelSpan.textContent = label;
            iconLabelDiv.appendChild(labelSpan);
            card.appendChild(iconLabelDiv);

            const labelEl = document.createElement('label');
            labelEl.className = "relative inline-flex items-center cursor-pointer flex-shrink-0";
            labelEl.dataset.action = "stop-propagation";

            const input = document.createElement('input');
            input.type = "checkbox";
            input.id = key;
            input.className = "sr-only peer";
            input.dataset.action = "trigger-keyboard-save";
            input.checked = enabled;
            labelEl.appendChild(input);

            const slider = document.createElement('div');
            slider.className = "w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600";
            labelEl.appendChild(slider);
            card.appendChild(labelEl);

            grid.appendChild(card);
        });

        catWrapper.appendChild(grid);
        sections.push(catWrapper);

        const divider = document.createElement('div');
        divider.className = "h-px bg-gray-200 dark:bg-white/5 last:hidden";
        sections.push(divider);
    }

    container.replaceChildren(...sections);
}

window.openKeyboardModal = function () {
    const modal = document.getElementById('keyboardModal');
    if (modal) {
        window.animateModalOpen(modal);
    }
};

window.closeKeyboardModal = function () {
    const modal = document.getElementById('keyboardModal');
    if (modal) {
        window.animateModalClose(modal);
    }
};

function updateDoneButtonState(state) {
    const btn = document.getElementById('keyboardModalDoneBtn');
    if (!btn) return;

    const activeText = (typeof window.I18N !== 'undefined' && window.I18N.web_kb_active) ? window.I18N.web_kb_active : "Active:";
    const savingText = (typeof window.I18N !== 'undefined' && window.I18N.web_saving_btn) ? window.I18N.web_saving_btn : "Saving...";
    const savedText = (typeof window.I18N !== 'undefined' && window.I18N.web_saved_btn) ? window.I18N.web_saved_btn : "Saved!";

    const visibleKeys = getVisibleKeys();
    const totalAll = visibleKeys.length;
    const totalEnabled = visibleKeys.filter(k => Reflect.get(window.KEYBOARD_CONFIG, k)).length;
    const counterText = `${activeText} ${totalEnabled} / ${totalAll}`;

    const defaultClasses = ['bg-blue-600', 'hover:bg-blue-500', 'text-white', 'shadow-blue-500/20'];
    const savingClasses = ['bg-yellow-500', 'hover:bg-yellow-400', 'text-white', 'shadow-yellow-500/20', 'cursor-wait'];
    const savedClasses = ['bg-green-600', 'hover:bg-green-500', 'text-white', 'shadow-green-500/20'];

    btn.classList.remove(...defaultClasses, ...savingClasses, ...savedClasses);

    if (state === 'saving') {
        window.setSafeHTML(btn, `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${savingText}`);
        btn.classList.add(...savingClasses);
        btn.disabled = true;
    } else if (state === 'saved') {
        window.setSafeHTML(btn, `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg> ${savedText}`);
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
    if (typeof window.KEYBOARD_CONFIG !== 'undefined') {
        Object.keys(window.KEYBOARD_CONFIG).forEach(key => {
            const el = document.getElementById(key);
            if (el) {
                Reflect.set(data, key, el.checked);
            } else {
                Reflect.set(data, key, Reflect.get(window.KEYBOARD_CONFIG, key));
            }
        });
    }

    Object.assign(window.KEYBOARD_CONFIG, data);
    if (!skipPreviewUpdate) {
        renderKeyboardPreview();
        updateBulkButtonsUI();
    }
    updateDoneButtonState('saving');

    setTimeout(async () => {
        try {
            const res = await fetch('/api/settings/keyboard', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
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
        } catch {
            updateDoneButtonState('default');
        }
    }, 300);
}

function getBulkStatus() {
    const keys = getVisibleKeys();
    const total = keys.length;
    const enabled = keys.filter(k => Reflect.get(window.KEYBOARD_CONFIG, k)).length;
    return {
        allEnabled: total > 0 && enabled === total,
        allDisabled: total > 0 && enabled === 0
    };
}

function updateBulkButtonsUI() {
    const status = getBulkStatus();
    const btnEnable = document.getElementById('btnEnableAllKb');
    const btnDisable = document.getElementById('btnDisableAllKb');

    function setDeactivated(btn, isDeactivated) {
        if (!btn) return;
        if (isDeactivated) {
            btn.classList.add('opacity-50', 'cursor-not-allowed');
        } else {
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    };
    setDeactivated(btnEnable, status.allEnabled);
    setDeactivated(btnDisable, status.allDisabled);
    updateCategoryBadges();
}

function updateCategoryBadges() {
    if (typeof window.KEYBOARD_CONFIG === 'undefined' || typeof btnCategories === 'undefined') return;

    for (const [catKey, catData] of Object.entries(btnCategories)) {
        const badgeBtn = document.getElementById(`kb-badge-${catKey}`);
        if (!badgeBtn) continue;

        const categoryKeys = catData.keys.filter(k => Object.hasOwn(window.KEYBOARD_CONFIG, k));
        if (categoryKeys.length === 0) continue;

        const enabledCount = categoryKeys.filter(k => Reflect.get(window.KEYBOARD_CONFIG, k)).length;
        const totalCount = categoryKeys.length;
        const allOn = enabledCount === totalCount;
        
        const colorClasses = [
            'bg-red-100', 'dark:bg-red-900/30', 'text-red-700', 'dark:text-red-400', 'hover:bg-red-200', 'dark:hover:bg-red-900/50',
            'bg-green-100', 'dark:bg-green-900/30', 'text-green-700', 'dark:text-green-400', 'hover:bg-green-200', 'dark:hover:bg-green-900/50',
            'bg-yellow-100', 'dark:bg-yellow-900/30', 'text-yellow-700', 'dark:text-yellow-400', 'hover:bg-yellow-200', 'dark:hover:bg-yellow-900/50'
        ];
        
        badgeBtn.classList.remove(...colorClasses);
        
        let newColorClasses = [];
        if (enabledCount === 0) {
            newColorClasses = ['bg-red-100', 'dark:bg-red-900/30', 'text-red-700', 'dark:text-red-400', 'hover:bg-red-200', 'dark:hover:bg-red-900/50'];
        } else if (allOn) {
            newColorClasses = ['bg-green-100', 'dark:bg-green-900/30', 'text-green-700', 'dark:text-green-400', 'hover:bg-green-200', 'dark:hover:bg-green-900/50'];
        } else {
            newColorClasses = ['bg-yellow-100', 'dark:bg-yellow-900/30', 'text-yellow-700', 'dark:text-yellow-400', 'hover:bg-yellow-200', 'dark:hover:bg-yellow-900/50'];
        }
        
        badgeBtn.classList.add(...newColorClasses);
        
        const span = badgeBtn.querySelector('span');
        if (span) {
            span.innerText = `${enabledCount}/${totalCount}`;
        }
    }
}

function animateBulkButton(btnId, state, originalText) {
    const btn = document.getElementById(btnId);
    if (!btn) return;

    if (state === 'loading') {
        window.setSafeHTML(btn, `<svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`);
        btn.disabled = true;
    } else if (state === 'success') {
        window.setSafeHTML(btn, `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>`);
        btn.disabled = true;
    } else {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

window.enableAllKeyboard = async function () {
    const btnId = 'btnEnableAllKb';
    const btn = document.getElementById(btnId);
    if (btn && (btn.disabled || btn.querySelector('.animate-spin'))) return;

    const status = getBulkStatus();
    if (status.allEnabled) {
        window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_kb_all_on_alert) ? window.I18N.web_kb_all_on_alert : "All buttons already enabled!");
        return;
    }

    const originalText = btn ? btn.innerText : (typeof window.I18N !== 'undefined' && window.I18N.web_kb_enable_all) ? window.I18N.web_kb_enable_all : 'Enable All';
    animateBulkButton(btnId, 'loading', originalText);

    let changed = false;
    const keys = getVisibleKeys();
    keys.forEach(key => {
        if (!Reflect.get(window.KEYBOARD_CONFIG, key)) {
            Reflect.set(window.KEYBOARD_CONFIG, key, true);
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

window.disableAllKeyboard = async function () {
    const btnId = 'btnDisableAllKb';
    const btn = document.getElementById(btnId);
    if (btn && (btn.disabled || btn.querySelector('.animate-spin'))) return;

    const status = getBulkStatus();
    if (status.allDisabled) {
        window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_kb_all_off_alert) ? window.I18N.web_kb_all_off_alert : "All buttons already disabled!");
        return;
    }

    const originalText = btn ? btn.innerText : (typeof window.I18N !== 'undefined' && window.I18N.web_kb_disable_all) ? window.I18N.web_kb_disable_all : 'Disable All';
    animateBulkButton(btnId, 'loading', originalText);

    let changed = false;
    const keys = getVisibleKeys();
    keys.forEach(key => {
        if (Reflect.get(window.KEYBOARD_CONFIG, key)) {
            Reflect.set(window.KEYBOARD_CONFIG, key, false);
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
        const data = await window.sseRequest('/api/sessions/list', 'sessions_list');
        if (data.sessions) {
            ALL_SESSIONS = data.sessions;
            renderSessionsMainWidget(data.sessions);
        }
    } catch (e) {
        const errorLoading = (typeof window.I18N !== 'undefined' && window.I18N.web_error_loading_sessions) ? window.I18N.web_error_loading_sessions : "Error loading sessions";
        window.setSafeHTML(container, `<div class="text-red-500 text-sm text-center">${errorLoading}</div>`);
    }
}

function renderSessionsMainWidget(sessions) {
    const container = document.getElementById('sessionsList');
    if (!container) return;

    const currentSession = sessions.find(s => s.current);
    if (currentSession) {
        window.setSafeHTML(container, `${renderSessionItem(currentSession)}`);
    } else {
        const noSessions = (typeof window.I18N !== 'undefined' && window.I18N.web_no_sessions) ? window.I18N.web_no_sessions : "No active sessions";
        window.setSafeHTML(container, `<div class="text-gray-500 text-sm text-center">${noSessions}</div>`);
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
    else if (iconType === "terminal") iconPath = "M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z";

    let userBadge = "";
    if (!isMine) {
        userBadge = `<div class="text-[10px] font-bold text-blue-500 mb-0.5 uppercase tracking-wide flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>${escapeHtml(s.user_name)}</div>`;
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
                <div class="text-sm font-bold text-gray-900 dark:text-white truncate" title="${escapeHtml(s.ua)}">${escapeHtml(deviceText)}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
                    <span data-sensitive class="font-mono">${escapeHtml(window.decryptData(s.ip))}</span>
                    <span>•</span>
                    <span>${date}</span>
                </div>
            </div>
        </div>
        <div class="flex-shrink-0 ml-2">
            ${isCurrent ?
            `<span class="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 text-[10px] font-bold uppercase rounded-lg tracking-wider">${window.I18N.web_session_current || 'Current'}</span>` :
            `<button data-action="revoke-session" data-id="${escapeHtml(s.id)}" class="p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition" title="${window.I18N.web_session_revoke || 'Revoke'}">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                </button>`
        }
        </div>
    </div>`;
}

window.openSessionsModal = function () {
    const modal = document.getElementById('sessionsModal');
    const content = document.getElementById('sessionsModalContent');
    const btnRevokeAll = document.getElementById('btnRevokeAllSessions');

    if (modal && content) {
        if (ALL_SESSIONS.length > 0) {
            window.setSafeHTML(content, ALL_SESSIONS.map(s => renderSessionItem(s)).join(''));
        } else {
            window.setSafeHTML(content, `<div class="text-center text-gray-500 py-4">No sessions</div>`);
        }

        if (ALL_SESSIONS.length <= 1 && btnRevokeAll) {
            btnRevokeAll.disabled = true;
            btnRevokeAll.classList.add('opacity-50', 'cursor-not-allowed');
        } else if (btnRevokeAll) {
            btnRevokeAll.disabled = false;
            btnRevokeAll.classList.remove('opacity-50', 'cursor-not-allowed');
            const originalText = window.I18N.web_sessions_revoke_all || "Revoke all other";
            window.setSafeHTML(btnRevokeAll, `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg> ${originalText}`);
            btnRevokeAll.className = "w-full py-3 bg-red-600 hover:bg-red-500 text-white rounded-xl font-bold shadow-lg shadow-red-500/20 transition-all duration-300 active:scale-[0.98] flex items-center justify-center gap-2";
        }
        window.animateModalOpen(modal);
    }
};

window.closeSessionsModal = function () {
    const modal = document.getElementById('sessionsModal');
    if (modal) {
        window.animateModalClose(modal);
    }
};

async function revokeSession(token) {
    if (!await window.showModalConfirm(window.I18N.web_session_revoke + "?", window.I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/sessions/revoke', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                token: token
            })
        });
        if (res.ok) {
            await fetchSessions();
            const content = document.getElementById('sessionsModalContent');
            if (content && !document.getElementById('sessionsModal').classList.contains('hidden')) {
                window.setSafeHTML(content, ALL_SESSIONS.map(s => renderSessionItem(s)).join(''));
                const btnRevokeAll = document.getElementById('btnRevokeAllSessions');
                if (ALL_SESSIONS.length <= 1 && btnRevokeAll) {
                    btnRevokeAll.disabled = true;
                    btnRevokeAll.classList.add('opacity-50', 'cursor-not-allowed');
                }
            }
            if (window.showToast) window.showToast((typeof window.I18N !== 'undefined' && window.I18N.web_success) ? window.I18N.web_success : "Success");
        } else {
            const data = await res.json();
            const errorShort = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
            await window.showModalAlert(data.error || "Failed", errorShort);
        }
    } catch (e) {
        console.error(e);
    }
}

async function revokeAllSessions() {
    if (!await window.showModalConfirm(window.I18N.web_sessions_revoke_all + "?", window.I18N.modal_title_confirm)) return;

    const btn = document.getElementById('btnRevokeAllSessions');
    const originalText = btn ? btn.innerHTML : "";

    if (btn) {
        btn.disabled = true;
        window.setSafeHTML(btn, `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`);
    }

    try {
        const res = await fetch('/api/sessions/revoke_all', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        if (res.ok) {
            if (btn) {
                btn.className = "w-full py-3 bg-green-600 text-white rounded-xl font-bold shadow-lg shadow-green-500/20 transition-all duration-300 flex items-center justify-center gap-2";
                window.setSafeHTML(btn, `<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg> ${window.I18N.web_sessions_revoked_alert}`);
            }
            await fetchSessions();
            const content = document.getElementById('sessionsModalContent');
            if (content) {
                window.setSafeHTML(content, ALL_SESSIONS.map(s => renderSessionItem(s)).join(''));
            }
            setTimeout(() => {
                if (btn) {
                    btn.disabled = true;
                    btn.classList.add('opacity-50', 'cursor-not-allowed');
                }
            }, 2000);
        } else {
            const data = await res.json();
            const errorShort = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
            await window.showModalAlert(data.error || "Failed", errorShort);
            if (btn) {
                btn.disabled = false;
                window.setSafeHTML(btn, originalText);
            }
        }
    } catch (e) {
        console.error(e);
        if (btn) {
            btn.disabled = false;
            window.setSafeHTML(btn, originalText);
        }
    }
}

let settingsBtnTimer = null;

async function handleSettingsBtnClick(btn, actionCallback) {
    const container = btn.closest('div');
    if (container) {
        const allBtns = container.querySelectorAll('button');
        allBtns.forEach(b => { b.classList.remove('force-expanded'); });
    }
    if (settingsBtnTimer) clearTimeout(settingsBtnTimer);
    btn.classList.add('force-expanded');

    try {
        if (typeof actionCallback === 'function') {
            await actionCallback();
        }
    } catch (error) {
        console.error('Settings action failed:', error);
        const message = window.I18N?.web_services_request_failed
            || (document.documentElement.lang === 'ru'
                ? 'Не удалось выполнить действие. Повторите попытку.'
                : 'The action failed. Please try again.');
        window.showToast?.(message);
    } finally {
        settingsBtnTimer = setTimeout(() => {
            btn.classList.remove('force-expanded');
            btn.blur();
        }, 2500);
    }
}


// --- Meta/SEO Modal Logic ---

window.openMetaModal = function () {
    const modal = document.getElementById('metaModal');
    if (modal) {
        window.animateModalOpen(modal);
    }
};

window.closeMetaModal = function () {
    const modal = document.getElementById('metaModal');
    if (modal) {
        window.animateModalClose(modal);
    }
};

window.saveMetaData = async function () {
    const btn = document.getElementById('btnSaveMeta');
    const locked = document.getElementById('meta_lock_forever').checked;

    if (locked) {
        const confirmMsg = (typeof window.I18N !== 'undefined' && window.I18N.web_meta_lock_confirm)
            ? window.I18N.web_meta_lock_confirm
            : "WARNING: You are about to lock settings forever. The settings button will disappear and you won't be able to change this data. Continue?";
        const confirmTitle = (typeof window.I18N !== 'undefined' && window.I18N.modal_title_confirm) ? window.I18N.modal_title_confirm : "Confirm";
        if (!await window.showModalConfirm(confirmMsg, confirmTitle)) {
            return;
        }
    }

    const originalText = btn.innerHTML;
    btn.disabled = true;
    window.setSafeHTML(btn, `<svg class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`);

    const data = {
        favicon: document.getElementById('meta_favicon').value.trim(),
        title: document.getElementById('meta_title').value.trim(),
        description: document.getElementById('meta_desc').value.trim(),
        keywords: document.getElementById('meta_keywords').value.trim(),
        locked: locked
    };

    try {
        const res = await fetch('/api/settings/metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        const responseText = await res.text();
        let json;
        try {
            json = JSON.parse(responseText);
        } catch (e) {
            console.error("Server Response:", responseText);
            throw new Error(`Server Error (${res.status}): ${responseText.substring(0, 150)}...`);
        }

        if (res.ok) {
            const successTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_success) ? window.I18N.web_success : "Success";
            const msgNormal = (typeof window.I18N !== 'undefined' && window.I18N.web_meta_success)
                ? window.I18N.web_meta_success
                : "Metadata updated successfully.";
            const msgLocked = (typeof window.I18N !== 'undefined' && window.I18N.web_meta_locked_alert)
                ? window.I18N.web_meta_locked_alert
                : "Settings saved and LOCKED forever. Reloading...";

            const successMsg = locked ? msgLocked : msgNormal;

            await window.showModalAlert(successMsg, successTitle);

            if (locked) {
                location.reload();
            } else {
                window.closeMetaModal();
                window.setSafeHTML(btn, originalText);
                btn.disabled = false;
            }
        } else {
            const errorTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
            await window.showModalAlert(json.error || "Failed to save", errorTitle);
            window.setSafeHTML(btn, originalText);
            btn.disabled = false;
        }
    } catch (e) {
        const errorTitle = (typeof window.I18N !== 'undefined' && window.I18N.web_conn_error_short) ? window.I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(e.message || e.toString(), errorTitle);
        window.setSafeHTML(btn, originalText);
        btn.disabled = false;
    }
};

// animateModalClose is provided by common.js (shared scroll-lock stack tracking).

// --- Telegram Only Mode Logic ---
let telegramOnlyMode = false;

async function loadTelegramOnlyMode() {
    try {
        const data = await window.sseRequest('/api/security/telegram_only_mode', 'telegram_only_mode');
        telegramOnlyMode = data.enabled || false;
        updateLockIcon();
    } catch (e) {
        console.error('Failed to load telegram only mode:', e);
    }
}

function updateLockIcon() {
    const lockIcon = document.getElementById('lockIcon');
    const passwordSection = document.getElementById('passwordChangeSection');
    const passwordOverlay = document.getElementById('passwordChangeOverlay');
    
    if (!lockIcon || !passwordSection) return;
    
    if (telegramOnlyMode) {
        lockIcon.classList.add('lock-active');
        passwordSection.classList.add('blurred');
        if (passwordOverlay) passwordOverlay.classList.remove('hidden');
    } else {
        lockIcon.classList.remove('lock-active');
        passwordSection.classList.remove('blurred');
        if (passwordOverlay) passwordOverlay.classList.add('hidden');
    }
}

async function toggleTelegramOnlyMode() {
    try {
        const newMode = !telegramOnlyMode;
        const res = await fetch('/api/security/telegram_only_mode', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                enabled: newMode
            })
        });
        
        if (res.ok) {
            telegramOnlyMode = newMode;
            updateLockIcon();
            localStorage.setItem('telegram_only_mode', newMode ? '1' : '0');
            
            const message = newMode 
                ? (window.I18N.web_telegram_only_enabled || 'Telegram only mode enabled. Password login disabled.')
                : (window.I18N.web_telegram_only_disabled || 'All login methods enabled.');
            
            if (window.showToast) {
                window.showToast(message);
            }
        } else {
            const data = await res.json();
            const errorShort = (typeof window.I18N !== 'undefined' && window.I18N.web_error_short) ? window.I18N.web_error_short : "Error";
            await window.showModalAlert(data.error || 'Failed to toggle mode', errorShort);
        }
    } catch (e) {
        console.error('Failed to toggle telegram only mode:', e);
        const errorShort = (typeof window.I18N !== 'undefined' && window.I18N.web_conn_error_short) ? window.I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(String(e), errorShort);
    }
}

window.toggleTelegramOnlyMode = toggleTelegramOnlyMode;

// Load telegram only mode on settings init
if (typeof window.initSettings === 'function') {
    const originalInit = window.initSettings;
    window.initSettings = function() {
        originalInit.apply(this, arguments);
        loadTelegramOnlyMode();
    };
}

// Global CustomEvent delegation for settings.js
document.addEventListener('app:action:delete-user', e => {
    deleteUser(e.detail.target.getAttribute('data-id'), e.detail.target.getAttribute('data-name'));
});
document.addEventListener('app:action:start-node-rename', e => {
    window.startNodeRename(e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:node-rename-keydown', e => {
    window.handleSettingsRenameKeydown(e.detail.originalEvent, e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:save-node-rename', e => {
    window.saveNodeRename(e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:cancel-node-rename', e => {
    window.cancelNodeRename(e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:delete-node', e => {
    deleteNode(e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:switch-notif-view', e => {
    currentNodeForNotif = e.detail.target.getAttribute('data-token');
    window.switchNotifView('node_detail');
});
document.addEventListener('app:action:click-alert-toggle', e => {
    document.getElementById(e.detail.target.getAttribute('data-target')).click();
});
document.addEventListener('app:action:stop-propagation', e => {
    e.detail.originalEvent.stopPropagation();
});
document.addEventListener('app:action:toggle-category-keyboard', e => {
    window.toggleCategoryKeyboard(e.detail.target.getAttribute('data-cat'));
});
document.addEventListener('app:action:revoke-session', e => {
    revokeSession(e.detail.target.getAttribute('data-id'));
});

// For inputs/checkboxes that trigger onchange
document.addEventListener('app:change:trigger-auto-save', e => {
    triggerAutoSave(e.detail.target.getAttribute('data-view'));
});
document.addEventListener('app:change:trigger-keyboard-save', () => {
    triggerKeyboardSave();
});

window.openPingTargetModal = function() {
    const modal = document.getElementById('pingTargetModal');
    const currentTarget = document.getElementById('conf_ping_target').value || 'google';

    const hasNodes = window.HAS_ACTIVE_NODES || false;
    const internalLabel = document.getElementById('ping_target_internal_label');
    if (internalLabel) {
        if (!hasNodes) {
            internalLabel.classList.add('opacity-50', 'pointer-events-none');
            internalLabel.title = (typeof window.I18N !== 'undefined' && window.I18N.web_ping_target_no_nodes) ? window.I18N.web_ping_target_no_nodes : "No active nodes available";
        } else {
            internalLabel.classList.remove('opacity-50', 'pointer-events-none');
            internalLabel.title = "";
        }
    }

    const radios = document.getElementsByName('ping_target_radio');
    for(let r of radios) {
        if(r.value === currentTarget) {
            r.checked = true;
        }
        if (r.value === 'internal' && !hasNodes) {
             r.disabled = true;
             if (currentTarget === 'internal') {
                 // fallback
                 document.querySelector('input[name="ping_target_radio"][value="google"]').checked = true;
             }
        }
    }

    if (modal) {
        window.animateModalOpen(modal);
    }
};

window.closePingTargetModal = function() {
    const modal = document.getElementById('pingTargetModal');
    if (modal) {
        window.animateModalClose(modal);
    }
};

window.savePingTargetModal = async function() {
    const selected = document.querySelector('input[name="ping_target_radio"]:checked');
    if (!selected) return;

    const val = selected.value;
    const hiddenInput = document.getElementById('conf_ping_target');
    const btnLabel = document.getElementById('label_ping_server');
    if (!hiddenInput) return;

    let text = "Google";
    if (val === "cloudflare") text = "Cloudflare";
    if (val === "internal") text = (typeof window.I18N !== 'undefined' && window.I18N.web_ping_target_internal)
        ? window.I18N.web_ping_target_internal : "Internal network";

    const changed = hiddenInput.value !== val;
    hiddenInput.value = val;
    if (btnLabel) {
        btnLabel.textContent = val === 'internal' && typeof window.I18N !== 'undefined'
            ? window.I18N.web_ping_target_internal_short || text
            : text;
        btnLabel.title = text;
    }
    window.closePingTargetModal();

    if (changed) {
        // PING_TARGET is part of system configuration, not notification preferences.
        checkForChanges('intervals');
        await window.saveSystemConfig('intervals');
    }
};

window.destroySettings = function () {
    if (typeof window.closeHintModal === 'function') window.closeHintModal();
    if (typeof window.closeKeyboardModal === 'function') window.closeKeyboardModal();
    if (typeof window.closePingTargetModal === 'function') window.closePingTargetModal();
};


window.changePassword = changePassword;

window.revokeAllSessions = revokeAllSessions;

window.handleSettingsBtnClick = handleSettingsBtnClick;
