function setSafeHTML(element, html) {
    if (!element) return;
    element.replaceChildren(window.DOMPurify.sanitize(html, { RETURN_DOM_FRAGMENT: true }));
}

/* Shared browser helpers; loaded before page-specific scripts. */

function getCookieValue(name) {
    const prefix = `${name}=`;
    const cookie = document.cookie.split(';').map(part => part.trim())
        .find(part => part.startsWith(prefix));
    return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : '';
}

function getCsrfToken() {
    return getCookieValue('csrf_token');
}

function showRequestError(error, connection = false) {
    const strings = typeof window.I18N !== 'undefined' ? window.I18N : {};
    const title = connection ? (strings.web_conn_error_short || 'Conn Error') : (strings.web_error_short || 'Error');
    const message = connection ? (strings.web_conn_error || '{error}') : (strings.web_error || '{error}');
    return window.showModalAlert(message.replace('{error}', error), title);
}

function renderCopyIpButton(ip) {
    return `<button type="button" class="ip-copy-btn p-0.5 text-gray-400 hover:text-blue-500 dark:hover:text-blue-400 rounded transition opacity-70 group-hover/ip:opacity-100 flex-shrink-0" data-action="copy-ip" data-ip="${window.escapeHtml(ip)}" title="${(typeof window.I18N !== 'undefined' && window.I18N.web_copy_ip) ? window.I18N.web_copy_ip : 'Copy IP'}">
<svg class="w-3.5 h-3.5 ip-copy-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
</svg>
</button>`;
}

function restoreMaintenanceButton(button, original) {
    button.replaceChildren(...original.children);
    button.className = original.className;
    Object.assign(button.style, original.style);
    button.disabled = false;
}

async function runMaintenanceAction({ buttonId, url, confirmText, doneText, busyText = '', payload }) {
    if (!await window.showModalConfirm(confirmText, window.I18N.modal_title_confirm)) return;
    const btn = document.getElementById(buttonId);
    if (!btn || btn.disabled) return;
    const original = {
        children: Array.from(btn.childNodes),
        className: btn.className,
        style: { width: btn.style.width, height: btn.style.height },
    };
    const fixedSize = btn.dataset.fixedSize === 'true';
    const redClasses = ['bg-red-50', 'dark:bg-red-900/10', 'border-red-200', 'dark:border-red-800', 'text-red-600', 'dark:text-red-400', 'hover:bg-red-100', 'dark:hover:bg-red-900/30', 'active:bg-red-200'];
    const greenClasses = ['bg-green-600', 'text-white', 'hover:bg-green-500',
        ...(fixedSize ? ['border-green-600'] : ['border-transparent', 'px-3', 'py-2'])];
    const hoverClasses = fixedSize ? [] : ['hover:pr-4', 'group'];
    const spinner = `<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;
    if (fixedSize) {
        const size = getComputedStyle(btn);
        btn.style.width = size.width;
        btn.style.height = size.height;
    }
    btn.disabled = true;
    setSafeHTML(btn, fixedSize
        ? `<div class="flex items-center justify-center w-full h-full">${spinner}</div>`
        : `${spinner}${busyText ? ` ${busyText}` : ''}`);
    let succeeded = false;
    try {
        const options = { method: 'POST' };
        if (payload !== undefined) {
            options.headers = { 'Content-Type': 'application/json' };
            options.body = JSON.stringify(payload);
        }
        const res = await fetch(url, options);
        if (!res.ok) {
            const data = await res.json();
            await showRequestError(data.error || 'Failed');
            return;
        }
        btn.classList.remove(...redClasses, ...hoverClasses);
        btn.classList.add(...greenClasses);
        const check = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>`;
        const icon = fixedSize ? check.replace('text-white', 'text-white shrink-0') : check;
        setSafeHTML(btn, fixedSize
            ? `<div class="flex items-center justify-center gap-2 w-full h-full">${icon} <span class="whitespace-nowrap text-[10px] font-bold uppercase tracking-wider leading-4">${doneText}</span></div>`
            : `${icon} <span class="font-bold text-xs uppercase ml-1">${doneText}</span>`);
        setTimeout(restoreMaintenanceButton, 2000, btn, original);
        succeeded = true;
    } catch (error) {
        await showRequestError(error, true);
    } finally {
        if (!succeeded) restoreMaintenanceButton(btn, original);
    }
}

// Fernet wire format shared with cryptography.fernet on the server.
// CryptoJS WordArrays use big-endian 32-bit words.
function panelCipherKeys() {
    const key = window.CryptoJS.enc.Hex.parse(window.WEB_KEY);
    return {
        signing: window.CryptoJS.lib.WordArray.create(key.words.slice(0, 4)),
        encryption: window.CryptoJS.lib.WordArray.create(key.words.slice(4, 8)),
    };
}

function encryptData(text) {
    const keys = panelCipherKeys();
    const iv = window.CryptoJS.lib.WordArray.random(16);
    const ciphertext = window.CryptoJS.AES.encrypt(String(text), keys.encryption, { iv }).ciphertext;
    const timestamp = Math.floor(Date.now() / 1000).toString(16).padStart(16, '0');
    const body = window.CryptoJS.enc.Hex.parse('80' + timestamp).concat(iv).concat(ciphertext);
    const mac = window.CryptoJS.HmacSHA256(body, keys.signing);
    return 'fw1:' + body.concat(mac).toString(window.CryptoJS.enc.Base64).replace(/\+/g, '-').replace(/\//g, '_');
}

function decryptData(value) {
    if (!value || typeof value !== 'string' || !value.startsWith('fw1:')) return value || '';
    const keys = panelCipherKeys();
    const hex = window.CryptoJS.enc.Base64.parse(value.slice(4).replace(/-/g, '+').replace(/_/g, '/'))
        .toString(window.CryptoJS.enc.Hex);
    if (!hex.startsWith('80') || hex.length < 146 || (hex.length - 114) % 32 !== 0) {
        throw new Error('Invalid encrypted panel data');
    }
    const body = hex.slice(0, -64);
    const expected = window.CryptoJS.HmacSHA256(window.CryptoJS.enc.Hex.parse(body), keys.signing).toString();
    const supplied = hex.slice(-64);
    let mismatch = 0;
    for (let i = 0; i < expected.length; i++) mismatch |= expected.charCodeAt(i) ^ supplied.charCodeAt(i);
    if (mismatch) throw new Error('Invalid encrypted panel data');
    const iv = window.CryptoJS.enc.Hex.parse(body.slice(18, 50));
    const ciphertext = window.CryptoJS.enc.Hex.parse(body.slice(50));
    return window.CryptoJS.AES.decrypt({ ciphertext }, keys.encryption, { iv }).toString(window.CryptoJS.enc.Utf8);
}

// Public API for the panel's classic scripts and extensions.
Object.assign(window, { getCsrfToken, runMaintenanceAction, renderCopyIpButton, encryptData, decryptData });
