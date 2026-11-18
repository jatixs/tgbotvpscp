/* Read server-rendered page configuration without evaluating inline JavaScript. */
window.applyPanelBootstrap = function (root = document) {
    const page = root.querySelector('main[data-panel-page]');
    if (!page) return;
    window.WEB_KEY = page.dataset.panelKey || '';
    window.USER_ROLE = page.dataset.panelRole || 'users';
    window.USER_ROLE_LEVEL = Number(page.dataset.panelRoleLevel || 0);
    window.IS_MAIN_ADMIN = page.dataset.panelOwner === 'true';
    try {
        window.I18N = JSON.parse(page.dataset.panelI18n || '{}');
    } catch {
        window.I18N = {};
    }
    window.i18n = window.i18n || {};
    try {
        window.master_billing_json = JSON.parse(page.dataset.panelBilling || 'null');
    } catch {
        window.master_billing_json = null;
    }
    window.GLOBAL_PING_MODE = page.dataset.panelPingMode || 'http';
};
window.applyPanelBootstrap();
