const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const dashboard = fs.readFileSync('core/static/js/dashboard.js', 'utf8');
const common = fs.readFileSync('core/static/js/common.js', 'utf8');

function fixture() {
    let nextTimer = 0;
    const timers = new Map();
    const sources = [];
    const logs = { style: {}, offsetHeight: 200, innerHTML: '', classList: { remove() {}, add() {} } };
    const services = { innerHTML: '' };
    const elements = new Map([['logsContainer', logs], ['services-container', services]]);
    class EventSource {
        constructor(url) { this.url = url; this.readyState = 0; this.listeners = new Map(); sources.push(this); }
        addEventListener(name, fn) { this.listeners.set(name, fn); }
        close() { this.readyState = 2; }
        emit(name, data) { this.listeners.get(name)?.({ data: JSON.stringify(data) }); }
    }
    const context = vm.createContext({
        console: { error() {}, log() {}, debug() {} }, EventSource, USER_ROLE: 'admins', I18N: {},
        document: { getElementById: id => elements.get(id) || null, addEventListener() {} },
        localStorage: { getItem: () => null, setItem() {} },
        addEventListener() {},
        setTimeout(fn, delay) { const id = ++nextTimer; timers.set(id, { fn, delay }); return id; },
        clearTimeout(id) { timers.delete(id); }, clearInterval() {},
        DOMPurify: { sanitize: html => html }, decryptApiResponse: value => value,
        showModalConfirm: async () => true, showModalAlert() {}, i18n: {},
    });
    context.window = context;
    vm.runInContext(common.slice(common.indexOf('const pendingSSERequests ='), common.indexOf('window.__chartRegistry =')), context);
    vm.runInContext(dashboard, context);
    vm.runInContext(`
        selectLogFilter = () => {};
        renderServiceLogsTab = () => {};
        closeServiceLogsDropdown = () => {};
        setLogLoading = () => {};
        renderServices = () => {};
    `, context);
    return {
        context, sources, elements, timers,
        runTimers(delay) {
            for (const [id, timer] of [...timers]) {
                if (timer.delay !== delay) continue;
                timers.delete(id); timer.fn();
            }
        },
        call(code) { return vm.runInContext(code, context); }
    };
}

test('log click spam opens one stream and an active or connecting stream is reused', () => {
    const f = fixture();
    for (let i = 0; i < 100; i++) f.context.switchLogType('bot');
    assert.equal(f.sources.length, 0);
    f.runTimers(150);
    assert.equal(f.sources.length, 1);
    for (let i = 0; i < 100; i++) f.context.switchLogType('bot');
    f.runTimers(150);
    assert.equal(f.sources.length, 1);
    f.sources[0].readyState = 1;
    f.context.switchLogType('bot');
    f.runTimers(150);
    assert.equal(f.sources.length, 1);
});

test('rapid log switching opens only the final selection and can reopen a closed stream', () => {
    const f = fixture();
    for (let i = 0; i < 50; i++) f.context.switchLogType(i % 2 ? 'sys' : 'bot');
    f.runTimers(150);
    assert.equal(f.sources.length, 1);
    assert.ok(f.sources[0].url.endsWith('type=sys'));
    f.sources[0].close();
    f.context.switchLogType('sys');
    f.runTimers(150);
    assert.equal(f.sources.length, 2);
});

test('same service reads share one pending request and failures release the lock', async () => {
    const f = fixture();
    const first = f.context.sseRequest('/api/services', 'services_list');
    for (let i = 0; i < 50; i++) assert.equal(f.context.sseRequest('/api/services', 'services_list'), first);
    assert.equal(f.sources.length, 1);
    f.sources[0].emit('services_list', { services: [] });
    await first;
    const retry = f.context.sseRequest('/api/services', 'services_list');
    assert.equal(f.sources.length, 2);
    f.sources[1].emit('error', {});
    await assert.rejects(retry, /SSE Error/);
    const third = f.context.sseRequest('/api/services', 'services_list');
    f.sources[2].emit('services_list', {});
    await third;
});

test('service reads time out rather than retaining the spam lock forever', async () => {
    const f = fixture();
    const request = f.context.sseRequest('/api/services', 'services_list');
    f.runTimers(15000);
    await assert.rejects(request, /timed out/);
    assert.equal(f.sources[0].readyState, 2);
    const retry = f.context.sseRequest('/api/services', 'services_list');
    f.sources[1].emit('services_list', {});
    await retry;
});

test('service refresh spam renders once and reuses the live subscription', async () => {
    const f = fixture();
    const first = f.call('loadServices()');
    for (let i = 0; i < 100; i++) assert.equal(f.call('loadServices()'), first);
    assert.equal(f.sources.length, 1);
    f.sources[0].emit('services_list', []);
    await first;
    assert.equal(f.sources.length, 2);
    const refresh = f.call('loadServices()');
    f.sources[2].emit('services_list', []);
    await refresh;
    assert.equal(f.sources.filter(source => source.url === '/api/events/services').length, 1);
});

test('leaving the dashboard closes services and cancels queued log switches and reconnects', () => {
    const f = fixture();
    f.call('initServicesSSE()');
    f.sources[0].onerror(new Error('offline'));
    f.context.switchLogType('bot');
    f.call('cleanupDashboardSources()');
    f.runTimers(150);
    f.runTimers(5000);
    assert.equal(f.sources.length, 1);
    assert.equal(f.sources[0].readyState, 2);
});

test('service controls ignore repeat clicks while confirming and executing', async () => {
    const f = fixture();
    let confirm, finish, requests = 0;
    f.context.showModalConfirm = () => new Promise(resolve => { confirm = resolve; });
    f.context.fetch = async () => { requests++; await new Promise(resolve => { finish = resolve; }); return { json: async () => ({ status: 'ok' }) }; };
    f.call('loadServices = () => {}');
    const first = f.call("controlService('nginx', 'systemd', 'restart')");
    for (let i = 0; i < 50; i++) await f.call("controlService('nginx', 'systemd', 'restart')");
    confirm(true);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests, 1);
    for (let i = 0; i < 50; i++) await f.call("controlService('nginx', 'systemd', 'restart')");
    finish(); await first;
    assert.equal(f.call('pendingServiceControls.size'), 0);
});

test('dashboard cleanup closes an active services stream and ignores its late events', () => {
    const f = fixture();
    let renders = 0;
    f.context.renderServices = () => { renders++; };
    f.call('initServicesSSE()');
    f.call('cleanupDashboardSources()');
    assert.equal(f.sources[0].readyState, 2);
    f.sources[0].emit('services', { services: [] });
    assert.equal(renders, 0);
});

test('cancelled service confirmations release the lock for another attempt', async () => {
    const f = fixture();
    let confirmations = 0;
    f.context.showModalConfirm = async () => { confirmations++; return false; };
    await f.call("controlService('nginx', 'systemd', 'restart')");
    await f.call("controlService('nginx', 'systemd', 'restart')");
    assert.equal(confirmations, 2);
    assert.equal(f.call('pendingServiceControls.size'), 0);
});
