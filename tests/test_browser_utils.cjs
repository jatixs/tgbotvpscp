const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const helpers = fs.readFileSync('core/static/js/browser_utils.js', 'utf8');
const common = fs.readFileSync('core/static/js/common.js', 'utf8');
const actions = common.slice(common.indexOf('window.clearLogs ='), common.indexOf("document.addEventListener('keydown'", common.indexOf('window.clearLogs =')));

function fixture({ fixedSize = true, confirmed = true, response = { ok: true }, error } = {}) {
    const classes = new Set(['bg-red-50']);
    const button = {
        childNodes: [{ markup: '<span>Original</span>' }], disabled: false,
        replaceChildren(...nodes) { this.childNodes = nodes; },
        dataset: { fixedSize: String(fixedSize) }, style: { width: '', height: '' },
        classList: {
            add(...names) { for (const name of names) classes.add(name); },
            remove(...names) { for (const name of names) classes.delete(name); },
        },
    };
    Object.defineProperty(button, 'className', {
        get: () => [...classes].join(' '),
        set: value => {
            classes.clear();
            button.classList.add(...value.split(/\s+/).filter(Boolean));
        },
    });
    const requests = [], alerts = [], timers = [], sanitized = [];
    const context = {
        window: {
            showModalConfirm: async () => confirmed,
            showModalAlert: async (...args) => alerts.push(args),
        },
        document: { cookie: 'other_csrf_token=bad; csrf_token=a%2Bb%3D', getElementById: () => button },
        I18N: {
            web_error: 'Error: {error}', web_conn_error: 'Connection: {error}',
            web_error_short: 'Error title', web_conn_error_short: 'Connection title',
            web_logs_cleared_alert: 'Cleared!', web_logs_clearing: 'Clearing...',
            web_clear_logs_confirm: 'Clear?', web_traffic_reset_confirm: 'Reset?',
            web_traffic_reset_no_emoji: 'Done!', modal_title_confirm: 'Confirm',
        },
        DOMPurify: { sanitize: html => { sanitized.push(html); return { markup: html }; } },
        getComputedStyle: () => ({ width: '120px', height: '40px' }),
        setTimeout: (callback, delay, ...args) => timers.push({ callback, delay, args }),
        fetch: async (url, options) => {
            requests.push({ url, options });
            if (error) throw error;
            return response;
        },
    };
    vm.createContext(context);
    vm.runInContext(helpers + '\n' + actions, context);
    return { context, button, classes, requests, alerts, timers, sanitized };
}

for (const fixedSize of [true, false]) {
    test(`maintenance actions preserve their requests and button layout (fixed: ${fixedSize})`, async () => {
        for (const [action, url, payload] of [
            ['clearLogs', '/api/logs/clear', { type: 'all' }],
            ['resetTrafficSettings', '/api/traffic/reset', undefined],
        ]) {
            const { context, button, classes, requests, timers, sanitized } = fixture({ fixedSize });
            const original = button.childNodes[0];
            await context.window[action]();
            assert.equal(requests[0].url, url);
            assert.equal(requests[0].options.method, 'POST');
            assert.equal(requests[0].options.body, payload && JSON.stringify(payload));
            if (payload) assert.equal(requests[0].options.headers['Content-Type'], 'application/json');
            assert.equal(button.disabled, true);
            assert.equal(button.style.width, fixedSize ? '120px' : '');
            assert.equal(classes.has('bg-green-600'), true);
            assert.equal(timers.length, 1);
            assert.equal(timers[0].delay, 2000);
            assert.match(sanitized[0], /animate-spin/);
            assert.match(button.childNodes[0].markup, action === 'clearLogs' ? /Cleared!/ : /Done!/);
            timers[0].callback(...timers[0].args);
            assert.equal(button.childNodes[0], original);
            assert.equal(button.disabled, false);
            assert.equal(button.style.width, '');
            assert.equal(classes.has('bg-green-600'), false);
            assert.equal(classes.has('bg-red-50'), true);
        }
    });
}

test('cancelled confirmation leaves both maintenance actions untouched', async () => {
    const { context, requests, button, timers } = fixture({ confirmed: false });
    await context.window.clearLogs();
    await context.window.resetTrafficSettings();
    assert.equal(requests.length, 0);
    assert.equal(timers.length, 0);
    assert.equal(button.childNodes[0].markup, '<span>Original</span>');
    assert.equal(button.disabled, false);
});

test('API and network failures restore button contents, dimensions and availability', async () => {
    for (const options of [
        { response: { ok: false, json: async () => ({ error: 'Denied' }) } },
        { error: new Error('offline') },
        { response: { ok: false, json: async () => { throw new Error('invalid JSON'); } } },
    ]) {
        const { context, button, alerts, timers } = fixture(options);
        button.style.width = '80%';
        await context.window.clearLogs();
        assert.equal(alerts.length, 1);
        assert.match(alerts[0][0], options.error ? /offline/ : /Denied|invalid JSON/);
        assert.equal(button.childNodes[0].markup, '<span>Original</span>');
        assert.equal(button.disabled, false);
        assert.equal(button.style.width, '80%');
        assert.equal(button.style.height, '');
        assert.equal(timers.length, 0);
    }
});

test('shared CSRF reader matches the complete cookie name and decodes its value', () => {
    const { context } = fixture();
    assert.equal(context.getCsrfToken(), 'a+b=');
    context.document.cookie = 'other_csrf_token=bad';
    assert.equal(context.getCsrfToken(), '');
});

test('mutating panel fetches still attach the shared CSRF token', async () => {
    const { context, requests } = fixture();
    context.window.fetch = context.fetch;
    context.window.location = { origin: 'https://panel.example' };
    context.URL = URL;
    context.Headers = Headers;
    context.Request = Request;
    const patchStart = common.indexOf('(function patchFetchWithCsrf()');
    const patchEnd = common.indexOf('})();', patchStart) + 5;
    vm.runInContext(common.slice(patchStart, patchEnd), context);
    await context.window.fetch('/api/logs/clear', { method: 'POST' });
    assert.equal(requests[0].options.headers.get('X-CSRF-Token'), 'a+b=');
});

test('secureFetch confines requests and redirects to the panel', async () => {
    const { context, requests } = fixture({ response: { status: 200, json: async () => ({ ok: true }) } });
    context.window.location = { origin: 'https://panel.example' };
    context.window.fetch = context.fetch;
    Object.assign(context, { URL, Request });
    vm.runInContext(common.slice(common.indexOf('async function secureFetch('), common.indexOf('function sseRequest(')), context);
    for (const url of ['https://other.example/api', '//other.example/api', 'https://user@panel.example/api']) {
        await assert.rejects(context.secureFetch(url), /same-origin/);
    }
    assert.equal(requests.length, 0);
    await context.secureFetch('/api/status', { mode: 'cors', redirect: 'follow' });
    assert.equal(requests[0].url.url, 'https://panel.example/api/status');
    assert.equal(requests[0].options.mode, 'same-origin');
    assert.equal(requests[0].options.redirect, 'error');
});

test('browser reads authenticated Fernet data from Python and rejects a changed signature', () => {
    const { context } = fixture();
    context.CryptoJS = require('../core/static/vendor/crypto-js.min.js');
    context.WEB_KEY = '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f';
    const token = 'fw1:gAAAAABq_ee1pAlIymOv4G_crpl1swi6iIL4p1MaN2o5RFxwLTRfw2PLMdNcMB8JBc6468VdIRx5cyeiTm9rYEpcMQffnUZz0l6aBIxsK8UX2kyvw5HC-Qz6Pj1hUaBbhPhp39B81vuKRsKuD3-BYYRbQHN8gQkezw==';
    assert.equal(context.decryptData(token), 'Проверка веб-панели: status ✓');
    const bytes = Buffer.from(token.slice(4), 'base64url');
    bytes[bytes.length - 1] ^= 1;
    assert.throws(() => context.decryptData('fw1:' + bytes.toString('base64url')));
    assert.equal(context.decryptData('2001:db8::1'), '2001:db8::1');
    assert.equal(context.decryptData(context.encryptData('Проверка веб-панели: status ✓')), 'Проверка веб-панели: status ✓');
});

test('settings action failures are handled and the expanded button is always restored', async () => {
    const source = fs.readFileSync('core/static/js/settings.js', 'utf8');
    const start = source.indexOf('let settingsBtnTimer = null;');
    const end = source.indexOf('// --- Meta/SEO Modal Logic ---', start);
    for (const fail of [false, true]) {
        const classes = new Set();
        const timers = [], errors = [], messages = [];
        let calls = 0, blurred = false;
        const button = {
            closest: () => null,
            classList: { add: name => classes.add(name), remove: name => classes.delete(name) },
            blur() { blurred = true; }
        };
        const context = vm.createContext({
            window: { I18N: {}, showToast: message => messages.push(message) },
            document: { documentElement: { lang: 'ru' } },
            console: { error: (...args) => errors.push(args) },
            setTimeout: callback => { timers.push(callback); return 1; }, clearTimeout() {}
        });
        vm.runInContext(source.slice(start, end), context);
        await context.handleSettingsBtnClick(button, async () => {
            calls++;
            if (fail) throw new Error('request failed');
        });
        assert.equal(calls, 1);
        assert.equal(errors.length, fail ? 1 : 0);
        assert.equal(messages.length, fail ? 1 : 0);
        assert.equal(classes.has('force-expanded'), true);
        assert.equal(timers.length, 1);
        timers[0]();
        assert.equal(classes.has('force-expanded'), false);
        assert.equal(blurred, true);
    }
});
