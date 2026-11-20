// Browser-independent smoke regressions for SPA notifications and ping target modal.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function source(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'core', 'static', 'js', name), 'utf8');
}
function section(text, start, end) {
    const a = text.indexOf(start), b = text.indexOf(end, a + start.length);
    assert.ok(a >= 0 && b > a, `Missing ${start}`);
    return text.slice(a, b);
}

test('target modal saves the selected target as system config without switching ping modes', async () => {
    const code = section(source('settings.js'),
        'window.savePingTargetModal = async function() {', '\nwindow.destroySettings');
    const calls = [];
    const target = { value: 'google' };
    const label = { textContent: '', title: '' };
    const context = {
        window: {
            closePingTargetModal() { calls.push('close'); },
            async saveSystemConfig(group) { calls.push(['save', group, target.value]); },
        },
        document: {
            querySelector() { return { value: 'cloudflare' }; },
            getElementById(id) { return id === 'conf_ping_target' ? target : label; },
        },
        checkForChanges(group) { calls.push(['changed', group]); },
        I18N: {},
    };
    vm.runInNewContext(code, context);
    await context.window.savePingTargetModal();
    assert.equal(target.value, 'cloudflare');
    assert.deepEqual(calls.map(String), ['close', 'changed,intervals', 'save,intervals,cloudflare']);
    calls.length = 0;
    await context.window.savePingTargetModal();
    assert.deepEqual(calls, ['close'], 'unchanged target should not trigger another save');
    assert.match(source('settings.js'), /ids: \[[^\]]*'conf_ping_target'/);
});

test('SPA navigation restores notifications and delegated bell/clear clicks survive nav replacement', () => {
    const text = source('common.js');
    const init = section(text, 'function initNotifications() {', '\nfunction handleSessionExpired');
    let outsideListeners = 0;
    let handler = null;
    let draws = 0;
    let bellClicks = 0;
    let clearClicks = 0;
    let closeClicks = 0;
    const buttons = {notifBtn: {}, notifClearBtn: {}};
    const context = {
        window: {location: {pathname: '/'}},
        document: {
            getElementById(id) { return buttons[id] || null; },
            addEventListener(event, fn) {
                if (event === 'click') {
                    outsideListeners++;
                    handler = fn;
                }
            },
        },
        toggleNotifications() { bellClicks++; },
        clearNotifications() { clearClicks++; },
        closeNotifications() { closeClicks++; },
        closeMobileSettings() {},
        updateNotifUI(list, count) {
            draws++;
            assert.equal(list[0].text, 'Saved notification');
            assert.equal(count, 1);
        },
        lastNotificationsJson: 'cached',
        lastNotificationsList: [{text: 'Saved notification'}],
        lastUnreadCount: 1,
        notificationOutsideClickBound: false,
    };
    vm.runInNewContext(init, context);
    context.initNotifications();

    // The entire header (including the buttons) is replaced by SPA navigation.
    buttons.notifBtn = {};
    buttons.notifClearBtn = {};
    context.window.location.pathname = '/settings';
    context.initNotifications();
    assert.equal(draws, 2);
    assert.equal(outsideListeners, 1, 'only one delegated click handler for all headers');
    assert.equal(context.lastNotificationsJson, '');

    const click = (id) => handler({
        target: { closest: selector => selector === '#' + id ? {} : null },
        preventDefault() {}, stopPropagation() {},
    });
    click('notifBtn');
    click('notifClearBtn');
    click('outside');
    assert.equal(bellClicks, 1, 'new SPA bell must open through delegation');
    assert.equal(clearClicks, 1, 'new SPA clear button must run the handler');
    assert.equal(closeClicks, 1, 'outside click must still close the dropdown');
});

test('confirming Clear all sends POST, empties the list and shows a success toast', async () => {
    const code = section(source('common.js'),
        'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    const calls = [];
    let resolveConfirm;
    const button = {disabled: false, isConnected: true};
    const context = {
        document: {getElementById: id => id === 'notifClearBtn' ? button : null},
        window: {
            showModalConfirm: () => new Promise(resolve => { resolveConfirm = resolve; }),
            showToast: message => calls.push(['toast', message]),
        },
        I18N: {web_clear_notif_confirm: 'Clear all?', web_notifications_cleared: 'Cleared', web_error_short: 'Error'},
        fetch: async (url, opts) => {
            calls.push(['fetch', url, opts.method]);
            return {ok: true, json: async () => ({status: 'ok'})};
        },
        updateNotifUI: (notifications, count) => calls.push(['render', notifications.length, count]),
        console,
    };
    vm.runInNewContext(code, context);
    const event = {preventDefault() {}, stopPropagation() {}};
    const pending = context.clearNotifications(event);
    await Promise.resolve();
    assert.equal(button.disabled, true);
    assert.equal(calls.length, 0, 'no API call before confirmation');
    resolveConfirm(true);
    await pending;
    assert.equal(button.disabled, false);
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
        ['fetch', '/api/notifications/clear', 'POST'], ['render', 0, 0], ['toast', 'Cleared'],
    ]);
});

test('Clear all reports rejected requests and preserves the visible list', async () => {
    const code = section(source('common.js'),
        'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    const calls = [];
    const button = {disabled: false, isConnected: true};
    const context = {
        document: {getElementById: () => button},
        window: {
            showModalConfirm: async () => true,
            showToast: message => calls.push(['toast', message]),
        },
        I18N: {web_error_short: 'Error'},
        fetch: async () => ({ok: false, status: 403, json: async () => ({error: 'Invalid CSRF token'})}),
        updateNotifUI: () => calls.push(['render']),
        console: {error() {}},
    };
    vm.runInNewContext(code, context);
    await context.clearNotifications();
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['toast', 'Error: Invalid CSRF token']]);
    assert.equal(button.disabled, false);
});

test('cancelling notification clear does not call API or show a toast', async () => {
    const code = section(source('common.js'),
        'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    let calls = 0;
    const button = {disabled: false, isConnected: true};
    const context = {
        document: {getElementById: () => button},
        window: {showModalConfirm: async () => false, showToast: () => calls++},
        I18N: {},
        fetch: () => { calls++; },
        updateNotifUI: () => { calls++; },
        console,
    };
    vm.runInNewContext(code, context);
    await context.clearNotifications();
    assert.equal(calls, 0);
    assert.equal(button.disabled, false);
});

test('expired CSRF refreshes session token and retries notification clear once', async () => {
    const code = section(source('common.js'),
        'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    const calls = [];
    const button = {disabled: false, isConnected: true};
    let attempts = 0;
    const context = {
        document: {getElementById: () => button},
        window: {showModalConfirm: async () => true, showToast: message => calls.push(['toast', message])},
        I18N: {web_notifications_cleared: 'Cleared'},
        fetch: async (url, options) => {
            calls.push(['fetch', url]);
            if (url === '/api/auth/status') return {ok: true};
            attempts++;
            if (attempts === 1) {
                return {ok: false, status: 403, json: async () => ({error: 'Invalid CSRF token'})};
            }
            return {ok: true, json: async () => ({status: 'ok'})};
        },
        updateNotifUI: (list, count) => calls.push(['render', list.length, count]),
        console,
    };
    vm.runInNewContext(code, context);
    await context.clearNotifications();
    assert.equal(attempts, 2);
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
        ['fetch', '/api/notifications/clear'],
        ['fetch', '/api/auth/status'],
        ['fetch', '/api/notifications/clear'],
        ['render', 0, 0], ['toast', 'Cleared'],
    ]);
});

test('permission errors are never retried as CSRF refreshes', async () => {
    const code = section(source('common.js'),
        'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    const calls = [];
    const context = {
        document: {getElementById: () => ({disabled: false, isConnected: true})},
        window: {showModalConfirm: async () => true, showToast: message => calls.push(message)},
        I18N: {web_error_short: 'Error'},
        fetch: async (url) => {
            calls.push(url);
            return {ok: false, status: 403, json: async () => ({error: 'Forbidden'})};
        },
        updateNotifUI: () => { throw new Error('Must not render success'); },
        console: {error() {}},
    };
    vm.runInNewContext(code, context);
    await context.clearNotifications();
    assert.deepEqual(calls, ['/api/notifications/clear', 'Error: Forbidden']);
});

test('modal OK releases pending notification clear even if closing animation throws', async () => {
    const common = source('common.js');
    const modalCode = section(common, 'let sysModalResolve = null;', '\nfunction _showSystemModalBase(');
    const clearCode = section(common, 'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    const calls = [];
    const button = {disabled: false, isConnected: true};
    const modal = {classList: {add() {}, remove() {}}};
    const context = {
        document: {getElementById: id => id === 'systemModal' ? modal : button},
        window: {showToast: msg => calls.push(['toast', msg])},
        I18N: {web_notifications_cleared: 'Cleared'},
        fetch: async url => {
            calls.push(['fetch', url]);
            return {ok: true, json: async () => ({status: 'ok'})};
        },
        updateNotifUI: (list, count) => calls.push(['render', list.length, count]),
        animateModalClose: () => { throw new Error('Animation failed'); },
        console: {error() {}},
    };
    vm.runInNewContext(modalCode + '\n' + clearCode + `
        window.showModalConfirm = () => new Promise(resolve => { sysModalResolve = resolve; });
    `, context);
    const pending = context.clearNotifications();
    assert.equal(button.disabled, true);
    assert.equal(calls.length, 0);
    context.closeSystemModal(true);
    await pending;
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
        ['fetch', '/api/notifications/clear'], ['render', 0, 0], ['toast', 'Cleared'],
    ]);
    assert.equal(button.disabled, false);
});

test('node-monitor bundle must not hijack shared confirmation before notification POST', async () => {
    const common = source('common.js');
    const nodes = source('nodes_monitor.js');
    const modalCode = section(common, 'let sysModalResolve = null;', '\nwindow.animateModalOpen = animateModalOpen;');
    const clearCode = section(common, 'let notificationClearInProgress = false;', '\nwindow.clearNotifications = clearNotifications;');
    const nodeModalCode = section(nodes, '// Modal functions', '// Theme toggle (if not defined in common.js)');
    const nodeExports = section(nodes, 'window.showAlert = showAlert;', '\n})();');

    assert.doesNotMatch(nodes, /window\.closeSystemModal\s*=/,
        'nodes_monitor.js must not replace the global promise-resolving closeSystemModal');

    const classList = {add() {}, remove() {}, toggle() {}};
    const elements = new Map([
        ['systemModal', {classList}],
        ['sysModalTitle', {innerText: ''}],
        ['sysModalMessage', {replaceChildren() {}}],
        ['sysModalInput', {classList}],
        ['sysModalCancel', {classList}],
        ['sysModalOk', {innerText: ''}],
        ['notifClearBtn', {disabled: false, isConnected: true}],
    ]);
    const calls = [];
    const context = {
        window: {showToast: message => calls.push(['toast', message])},
        document: {
            getElementById: id => elements.get(id) || null,
            createTextNode: text => text,
            createElement: tag => ({tag}),
        },
        I18N: {web_notifications_cleared: 'Cleared'},
        animateModalOpen() {},
        animateModalClose() {},
        updateNotifUI: (list, count) => calls.push(['render', list.length, count]),
        fetch: async (url, options) => {
            calls.push(['fetch', url, options.method]);
            return {ok: true, json: async () => ({status: 'ok'})};
        },
        console,
    };
    vm.runInNewContext(modalCode + '\n' + clearCode, context);
    const sharedClose = context.window.closeSystemModal;

    // Execute the node module's actual private modal functions and its actual exports
    // as if its bundle loaded after common.js on any SPA-enabled page.
    vm.runInNewContext('(() => {\nfunction resolveLocalizedMessage(m) { return m; }\n'
        + nodeModalCode + '\n' + nodeExports + '\n})();', context);
    assert.equal(context.window.closeSystemModal, sharedClose);

    const pending = context.clearNotifications();
    await Promise.resolve();
    assert.equal(calls.length, 0);
    elements.get('sysModalOk').onclick();
    await pending;
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
        ['fetch', '/api/notifications/clear', 'POST'],
        ['render', 0, 0],
        ['toast', 'Cleared'],
    ]);
});

test('SPA settings bootstrap restores inline-only globals and renders billing on the replaced nav', () => {
    const tpl = fs.readFileSync(path.join(__dirname, '..', 'core', 'templates', 'settings.html'), 'utf8');
    const dash = fs.readFileSync(path.join(__dirname, '..', 'core', 'templates', 'dashboard.html'), 'utf8');
    for (const key of ['billing', 'users', 'nodes', 'keyboard', 'user-alerts', 'has-active-nodes']) {
        assert.match(tpl, new RegExp('data-panel-' + key + '='));
    }
    assert.match(dash, /data-panel-config=/);
    assert.match(tpl, /window\.USERS_DATA =/);
    assert.match(tpl, /window\.KEYBOARD_CONFIG =/);

    let attrs = {
        'data-panel-i18n': JSON.stringify({web_billing_modal_title: 'Billing'}),
        'data-panel-billing': JSON.stringify({amount: 42, currency: 'EUR'}),
        'data-panel-users': JSON.stringify([{id: 1}]),
        'data-panel-nodes': JSON.stringify([{id: 7}]),
        'data-panel-keyboard': JSON.stringify({btn_start: true}),
        'data-panel-user-alerts': JSON.stringify({downtime: true}),
    };
    const page = {
        dataset: {panelPage: 'settings', panelRole: 'admins', panelRoleLevel: '9',
            panelOwner: 'true', panelHasActiveNodes: 'true'},
        getAttribute: key => Object.hasOwn(attrs, key) ? attrs[key] : null,
    };
    let rendered = null;
    const button = {};
    const container = {
        textContent: '',
        appendChild(fragment) { rendered = fragment.html; },
        querySelector: () => button,
    };
    const ctx = {
        document: {
            querySelector: () => page,
            getElementById: id => id === 'headerBillingContainer' ? container : null,
        },
        DOMPurify: {sanitize: html => ({html})},
        getBillingStatusColor: () => 'normal',
        getBillingBadgeHtml: () => '42 EUR',
        calculateDaysLeft: () => null,
        showBillingModal() {},
    };
    ctx.window = ctx;
    vm.runInNewContext(source('panel_bootstrap.js'), ctx);
    assert.equal(ctx.USERS_DATA[0].id, 1);
    assert.equal(ctx.NODES_DATA[0].id, 7);
    assert.equal(ctx.KEYBOARD_CONFIG.btn_start, true);
    assert.equal(ctx.USER_ALERTS.downtime, true);
    assert.equal(ctx.HAS_ACTIVE_NODES, true);
    assert.equal(vm.runInNewContext('USERS_DATA[0].id + NODES_DATA[0].id', ctx), 8,
        'settings functions must resolve restored globals without executing inline scripts');

    const billingCode = section(source('common.js'),
        'window.renderHeaderBilling = function() {', "\ndocument.addEventListener('DOMContentLoaded', () => {");
    vm.runInNewContext(billingCode, ctx);
    ctx.renderHeaderBilling();
    assert.match(rendered, /header-billing-btn/);
    assert.equal(typeof button.onclick, 'function');

    // Navigation back to the dashboard refreshes its own config, too.
    page.dataset.panelPage = 'dashboard';
    attrs = {
        'data-panel-i18n': '{}',
        'data-panel-billing': JSON.stringify({amount: 11}),
        'data-panel-config': JSON.stringify({cpu_threshold: 90}),
    };
    ctx.applyPanelBootstrap();
    assert.equal(ctx.SYS_CONFIG.cpu_threshold, 90);
    assert.equal(ctx.master_billing_json.amount, 11);
});
