/* Read server-rendered page configuration without evaluating inline JavaScript. */
function readPanelJson(page, attribute, fallback = null) {
    const raw = page.getAttribute(attribute);
    if (raw === null) return fallback;
    try {
        let parsed = JSON.parse(raw);
        if (typeof parsed === 'string') {
            try { parsed = JSON.parse(parsed); } catch {}
        }
        return parsed;
    } catch {
        return fallback;
    }
}

window.applyPanelBootstrap = function (root = document) {
    const page = root.querySelector('main[data-panel-page]');
    if (!page) return;
    window.WEB_KEY = page.dataset.panelKey || '';
    window.USER_ROLE = page.dataset.panelRole || 'users';
    window.USER_ROLE_LEVEL = Number(page.dataset.panelRoleLevel || 0);
    window.IS_MAIN_ADMIN = page.dataset.panelOwner === 'true';
    try {
        const rawI18n = page.getAttribute('data-panel-i18n') || page.dataset.panelI18n || '{}';
        let parsed = typeof rawI18n === 'string' ? JSON.parse(rawI18n) : rawI18n;
        if (typeof parsed === 'string') {
            try { parsed = JSON.parse(parsed); } catch {}
        }
        if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) {
            window.I18N = Object.assign({}, window.I18N || {}, parsed);
        }
    } catch {
        if (!window.I18N) window.I18N = {};
    }
    if (typeof globalThis !== 'undefined' && window.I18N) {
        try { globalThis.I18N = window.I18N; } catch {}
    }
    window.i18n = window.i18n || {};
    // Every SPA target carries its own data; fetched <script> tags are not executed.
    // Rehydrate the globals that full page loads previously created inline.
    window.master_billing_json = readPanelJson(page, 'data-panel-billing');
    if (page.dataset.panelPage === 'settings') {
        window.USERS_DATA = readPanelJson(page, 'data-panel-users');
        window.NODES_DATA = readPanelJson(page, 'data-panel-nodes');
        window.KEYBOARD_CONFIG = readPanelJson(page, 'data-panel-keyboard', {});
        window.USER_ALERTS = readPanelJson(page, 'data-panel-user-alerts', {});
        window.HAS_ACTIVE_NODES = page.dataset.panelHasActiveNodes === 'true';
    } else if (page.dataset.panelPage === 'dashboard') {
        window.SYS_CONFIG = readPanelJson(page, 'data-panel-config', {});
    }
    if (page.dataset.panelPingMode) {
        window.GLOBAL_PING_MODE = page.dataset.panelPingMode;
    }
};
window.applyPanelBootstrap();
