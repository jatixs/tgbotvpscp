/* Read server-rendered page configuration without evaluating inline JavaScript. */
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
    try {
        const rawBilling = page.getAttribute('data-panel-billing') || page.dataset.panelBilling || 'null';
        let parsedBilling = typeof rawBilling === 'string' ? JSON.parse(rawBilling) : rawBilling;
        if (typeof parsedBilling === 'string') {
            try { parsedBilling = JSON.parse(parsedBilling); } catch {}
        }
        window.master_billing_json = parsedBilling;
    } catch {
        window.master_billing_json = null;
    }
    window.GLOBAL_PING_MODE = page.dataset.panelPingMode || 'http';
};
window.applyPanelBootstrap();
