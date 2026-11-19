const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync('core/static/js/panel_navigation.js', 'utf8');

function getPageKey(path) {
    const clean = path.replace(/\/+$/, '') || '/';
    if (clean === '/') return 'dashboard';
    if (clean === '/nodes') return 'nodes';
    if (clean === '/operations') return 'operations';
    if (clean === '/settings') return 'settings';
    return 'unknown';
}

function createFixture({ initialPath = '/nodes', enableViewTransitions = false, navigationDelay = 0 } = {}) {
    let assignedUrl = null;
    let pushedUrl = null;
    let fetchedUrl = null;
    const docListeners = new Map();
    const winListeners = new Map();
    const actions = [];
    const initKey = getPageKey(initialPath);

    const document = {
        readyState: 'complete',
        title: initKey.charAt(0).toUpperCase() + initKey.slice(1),
        documentElement: { lang: 'ru', dataset: {} },
        body: {
            className: initKey + '-page',
            style: { overflow: '' },
            appendChild(el) { actions.push('append:' + el.id); }
        },
        addEventListener(event, fn) {
            docListeners.set(event, fn);
        },
        getElementById(id) {
            if (['dashboardPageModals', 'nodesPageModals', 'settingsPageModals'].includes(id)) {
                return { remove() { actions.push('remove:' + id); } };
            }
            return null;
        },
        querySelector(selector) {
            if (selector === 'main') {
                return {
                    setAttribute(name, val) { actions.push(`main.set:${name}=${val}`); },
                    removeAttribute(name) { actions.push(`main.remove:${name}`); },
                    classList: {
                        add(c) { actions.push('main.class.add:' + c); },
                        remove(c) { actions.push('main.class.remove:' + c); }
                    },
                    replaceWith(newNode) { actions.push('main.replaceWith'); },
                    style: {},
                    offsetWidth: 100
                };
            }
            if (selector === 'nav') {
                return { replaceWith() { actions.push('nav.replaceWith'); } };
            }
            if (selector === 'main[data-panel-page]') {
                return { dataset: { panelPage: initKey } };
            }
            return null;
        },
        importNode(node) { return node; }
    };

    if (enableViewTransitions) {
        document.startViewTransition = fn => {
            actions.push('startViewTransition:navigating=' + document.documentElement.dataset.panelNavigating);
            fn();
            return { finished: Promise.resolve() };
        };
    }

    const window = {
        location: {
            href: 'http://localhost:8080' + initialPath,
            pathname: initialPath,
            origin: 'http://localhost:8080',
            search: '',
            assign(url) {
                assignedUrl = url;
            }
        },
        history: {
            state: null,
            pushState(state, title, url) {
                pushedUrl = url;
            },
            replaceState(state, title, url) {}
        },
        addEventListener(event, fn) {
            winListeners.set(event, fn);
        },
        scrollTo() {},
        applyPanelBootstrap() { actions.push('applyPanelBootstrap'); },
        initDashboard() { actions.push('initDashboard'); },
        initNodesMonitor() { actions.push('initNodesMonitor'); },
        initOperations() { actions.push('initOperations'); },
        initSettings() { actions.push('initSettings'); },
        destroyDashboard() { actions.push('destroyDashboard'); },
        destroyNodesMonitor() { actions.push('destroyNodesMonitor'); },
        destroyOperations() { actions.push('destroyOperations'); },
        destroySettings() { actions.push('destroySettings'); },
        fetch: async (url, options) => {
            fetchedUrl = url;
            const path = url.split('?')[0];
            const targetPage = getPageKey(path);
            const modalId = targetPage === 'dashboard' ? 'dashboardPageModals'
                : (targetPage === 'nodes' ? 'nodesPageModals'
                : (targetPage === 'settings' ? 'settingsPageModals' : null));
            return {
                ok: true,
                url: 'http://localhost:8080' + url,
                text: async () => `<!DOCTYPE html><html><head><title>${targetPage}</title></head><body>
                    <nav></nav>
                    <main data-panel-page="${targetPage}"></main>
                    ${modalId ? `<div id="${modalId}"></div>` : ''}
                </body></html>`
            };
        },
        secureFetch: async (url, options) => {
            fetchedUrl = url;
            const path = url.split('?')[0];
            const targetPage = getPageKey(path);
            const modalId = targetPage === 'dashboard' ? 'dashboardPageModals'
                : (targetPage === 'nodes' ? 'nodesPageModals'
                : (targetPage === 'settings' ? 'settingsPageModals' : null));
            return {
                ok: true,
                url: 'http://localhost:8080' + url,
                text: async () => `<!DOCTYPE html><html><head><title>${targetPage}</title></head><body>
                    <nav></nav>
                    <main data-panel-page="${targetPage}"></main>
                    ${modalId ? `<div id="${modalId}"></div>` : ''}
                </body></html>`
            };
        },
        DOMParser: class {
            parseFromString(html) {
                const match = html.match(/data-panel-page="([^"]+)"/);
                const targetPage = match ? match[1] : 'unknown';
                const modalId = targetPage === 'dashboard' ? 'dashboardPageModals'
                    : (targetPage === 'nodes' ? 'nodesPageModals'
                    : (targetPage === 'settings' ? 'settingsPageModals' : null));
                return {
                    title: targetPage.charAt(0).toUpperCase() + targetPage.slice(1),
                    documentElement: { lang: 'ru', dataset: {} },
                    body: { className: targetPage + '-page' },
                    getElementById(id) {
                        if (id === modalId) return { id: modalId, querySelectorAll: () => [] };
                        return null;
                    },
                    querySelector(sel) {
                        if (sel === 'main[data-panel-page]') {
                            return {
                                dataset: { panelPage: targetPage },
                                querySelectorAll: () => []
                            };
                        }
                        if (sel === 'nav') {
                            return { querySelectorAll: () => [] };
                        }
                        return null;
                    }
                };
            }
        }
    };

    const context = {
        console,
        window,
        document,
        location: window.location,
        fetch: window.fetch,
        secureFetch: window.secureFetch,
        DOMParser: window.DOMParser,
        AbortController,
        URL,
        URLSearchParams,
        setTimeout: (fn, delay, ...args) => setTimeout(fn, delay === 120 ? navigationDelay : delay, ...args),
        clearTimeout
    };

    vm.runInNewContext(source, context);

    return {
        window,
        document,
        docListeners,
        winListeners,
        actions,
        getAssignedUrl: () => assignedUrl,
        getPushedUrl: () => pushedUrl,
        getFetchedUrl: () => fetchedUrl
    };
}

test('navigation from /nodes to /operations runs SPA transition without page reload', async () => {
    const f = createFixture({ initialPath: '/nodes' });
    assert.equal(typeof f.window.operationNavigationHandles, 'function');
    assert.equal(f.window.operationNavigationHandles('/operations'), true);

    const clickListener = f.docListeners.get('click');
    let defaultPrevented = false;
    let propagationStopped = false;
    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/operations', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => { defaultPrevented = true; },
        stopImmediatePropagation: () => { propagationStopped = true; }
    });

    await new Promise(r => setTimeout(r, 20));

    assert.equal(defaultPrevented, true);
    assert.equal(propagationStopped, true);
    assert.equal(f.getAssignedUrl(), null, 'Should not trigger window.location.assign');
    assert.equal(f.getFetchedUrl(), '/operations');
    assert.equal(f.getPushedUrl(), '/operations');
    assert.ok(f.actions.includes('destroyNodesMonitor'));
    assert.ok(f.actions.includes('main.replaceWith'));
    assert.ok(f.actions.includes('initOperations'));
    assert.ok(f.actions.includes('main.class.add:panel-page-enter'));
});

test('pagination and filters on /operations stay within SPA without full reload', async () => {
    const f = createFixture({ initialPath: '/operations' });
    assert.equal(f.window.operationNavigationHandles('/operations?page=2'), true);

    const clickListener = f.docListeners.get('click');
    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/operations?page=2&status=finished&junk=malicious', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });

    await new Promise(r => setTimeout(r, 20));

    assert.equal(f.getAssignedUrl(), null, 'Pagination must not trigger full page reload');
    assert.equal(f.getFetchedUrl(), '/operations?page=2&status=finished');
    assert.equal(f.getPushedUrl(), '/operations?page=2&status=finished');
    assert.ok(f.actions.includes('main.class.add:panel-page-enter'));
});

test('navigation from /operations back to /nodes restores modals and monitor state', async () => {
    const f = createFixture({ initialPath: '/operations' });
    assert.equal(f.window.operationNavigationHandles('/nodes'), true);

    const clickListener = f.docListeners.get('click');
    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/nodes', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });

    await new Promise(r => setTimeout(r, 20));

    assert.equal(f.getAssignedUrl(), null, 'Back to /nodes must not trigger reload');
    assert.equal(f.getFetchedUrl(), '/nodes');
    assert.equal(f.getPushedUrl(), '/nodes');
    assert.ok(f.actions.includes('destroyOperations'));
    assert.ok(f.actions.includes('append:nodesPageModals'));
    assert.ok(f.actions.includes('initNodesMonitor'));
});

test('navigation from /nodes to dashboard (/) and /settings works seamlessly across entire panel', async () => {
    const f = createFixture({ initialPath: '/nodes' });
    assert.equal(f.window.panelNavigationHandles('/'), true);
    assert.equal(f.window.panelNavigationHandles('/settings'), true);

    const clickListener = f.docListeners.get('click');
    // Navigate to / (dashboard)
    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });
    await new Promise(r => setTimeout(r, 20));

    assert.equal(f.getAssignedUrl(), null);
    assert.equal(f.getFetchedUrl(), '/');
    assert.equal(f.getPushedUrl(), '/');
    assert.ok(f.actions.includes('destroyNodesMonitor'));
    assert.ok(f.actions.includes('append:dashboardPageModals'));
    assert.ok(f.actions.includes('initDashboard'));

    // Now update location and navigate to /settings
    f.window.location.pathname = '/';
    f.window.location.href = 'http://localhost:8080/';

    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/settings', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });
    await new Promise(r => setTimeout(r, 20));

    assert.equal(f.getAssignedUrl(), null);
    assert.equal(f.getFetchedUrl(), '/settings');
    assert.equal(f.getPushedUrl(), '/settings');
    assert.ok(f.actions.includes('destroyDashboard'));
    assert.ok(f.actions.includes('append:settingsPageModals'));
    assert.ok(f.actions.includes('initSettings'));
});

test('view transitions API when available executes without double CSS animation jerk', async () => {
    const f = createFixture({ initialPath: '/', enableViewTransitions: true });
    const clickListener = f.docListeners.get('click');

    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/settings', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });
    await new Promise(r => setTimeout(r, 20));

    assert.ok(f.actions.includes('startViewTransition:navigating=true'), 'Should flag documentElement with data-panel-navigating during transition');
    assert.equal(f.document.documentElement.dataset.panelNavigating, undefined, 'Should cleanup data-panel-navigating after transition');
    assert.ok(f.actions.includes('initSettings'));
    assert.equal(f.actions.includes('main.class.add:panel-page-enter'), false, 'Should not add panel-page-enter when View Transitions API handled transition');
});

test('popstate history navigation preserves smooth SPA transitions', async () => {
    const f = createFixture({ initialPath: '/operations' });
    f.window.location.pathname = '/nodes';
    f.window.location.href = 'http://localhost:8080/nodes';

    const popListener = f.winListeners.get('popstate');
    assert.equal(typeof popListener, 'function');
    popListener({
        state: { panelRoute: true },
        stopImmediatePropagation: () => {}
    });

    await new Promise(r => setTimeout(r, 20));

    assert.equal(f.getAssignedUrl(), null, 'Popstate must not reload the browser');
    assert.equal(f.getFetchedUrl(), '/nodes');
    assert.ok(f.actions.includes('initNodesMonitor'));
});

test('perf-mode bypasses view transitions and suppresses animation classes', async () => {
    const f = createFixture({ initialPath: '/nodes', enableViewTransitions: true });
    f.document.documentElement.classList = {
        contains(c) { return c === 'perf-mode'; }
    };

    const clickListener = f.docListeners.get('click');
    assert.equal(typeof clickListener, 'function');

    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/settings', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });
    await new Promise(r => setTimeout(r, 20));

    assert.equal(f.actions.some(a => a.startsWith('startViewTransition')), false, 'Should skip startViewTransition in perf-mode');
    assert.equal(f.actions.includes('main.class.add:panel-page-enter'), false, 'Should not add enter animation in perf-mode');
    assert.ok(f.actions.includes('initSettings'));
});

test('cancelNodeRename and node rename functions handle token and modal calls safely', () => {
    const settingsCode = fs.readFileSync('core/static/js/settings.js', 'utf8');
    const dashboardCode = fs.readFileSync('core/static/js/dashboard.js', 'utf8');

    const sandbox = {
        window: {},
        document: {
            getElementById(id) {
                if (id === 'edit_name_token123') return { classList: { add() {}, remove() {} } };
                if (id === 'nodeNameContainer' || id === 'nodeNameInputContainer') {
                    return { classList: { add() {}, remove() {} } };
                }
                return null;
            },
            addEventListener() {}
        },
        localStorage: { getItem() { return null; }, setItem() {} },
        location: { href: 'http://localhost/' },
        addEventListener() {}
    };
    sandbox.window = sandbox;

    // Run settings first then dashboard
    vm.runInNewContext(settingsCode + '\n' + dashboardCode, sandbox);

    // Call without token (dashboard modal style)
    assert.doesNotThrow(() => {
        sandbox.cancelNodeRename();
    });

    // Call with token (settings style)
    assert.doesNotThrow(() => {
        sandbox.cancelNodeRename('token123');
    });

    // Call with undefined or null token when element does not exist
    assert.doesNotThrow(() => {
        sandbox.cancelNodeRename('non_existent_token');
    });
});

test('view transitions are skipped cleanly when document is hidden', async () => {
    let startTransitionCalled = false;
    const f = createFixture({ initialPath: '/settings' });
    f.document.hidden = true;
    f.document.startViewTransition = fn => {
        startTransitionCalled = true;
        fn();
        return { finished: Promise.resolve() };
    };

    const clickListener = f.docListeners.get('click');
    clickListener({
        target: { closest: sel => sel === 'a' ? { href: 'http://localhost:8080/', target: '_self', hasAttribute: () => false } : null },
        button: 0,
        preventDefault: () => {},
        stopImmediatePropagation: () => {}
    });

    await new Promise(r => setTimeout(r, 20));

    assert.equal(startTransitionCalled, false, 'startViewTransition should not be called when document is hidden');
    assert.ok(f.actions.includes('main.replaceWith'), 'DOM was still updated directly');
});

test('settings navigation preserves only the allowed monitoring return route', async () => {
    for (const [value, expected] of [
        ['/nodes', '/settings?return_to=%2Fnodes'],
        ['https://example.com', '/settings'],
        ['//example.com', '/settings'],
    ]) {
        const f = createFixture({ initialPath: '/nodes' });
        f.docListeners.get('click')({
            target: { closest: () => ({
                href: 'http://localhost:8080/settings?return_to=' + encodeURIComponent(value),
                target: '_self', hasAttribute: () => false
            }) },
            button: 0,
            preventDefault() {},
            stopImmediatePropagation() {}
        });
        await new Promise(r => setTimeout(r, 20));
        assert.equal(f.getFetchedUrl(), expected);
        assert.equal(f.getPushedUrl(), expected);
        assert.equal(f.getAssignedUrl(), null);
        assert.ok(f.actions.includes('initSettings'));
    }
});

test('old content stays intact during a slow request and initialization runs inside the transition', async () => {
    const f = createFixture();
    const request = f.window.secureFetch;
    let releaseRequest;
    f.window.secureFetch = async (...args) => {
        await new Promise(resolve => { releaseRequest = resolve; });
        return request(...args);
    };
    let updateFrame, finish;
    f.document.startViewTransition = callback => {
        f.actions.push('capture-old-frame');
        const updateCallbackDone = new Promise(resolve => {
            updateFrame = () => { callback(); resolve(); };
        });
        return { updateCallbackDone, finished: new Promise(resolve => { finish = resolve; }) };
    };
    f.docListeners.get('click')({
        target: { closest: () => ({ href: 'http://localhost:8080/settings', hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    assert.equal(f.actions.includes('destroyNodesMonitor'), false);
    assert.equal(f.actions.includes('main.replaceWith'), false);
    await new Promise(resolve => setTimeout(resolve, 0));
    releaseRequest();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.ok(f.actions.includes('capture-old-frame'));
    assert.equal(f.actions.includes('destroyNodesMonitor'), false, 'Capture the populated charts before destroying them');
    updateFrame();
    assert.ok(f.actions.includes('initSettings'), 'Initialize before the browser captures the new frame');
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.document.documentElement.dataset.panelNavigating, 'true', 'Styles persist beyond DOM replacement');
    finish();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.document.documentElement.dataset.panelNavigating, undefined);
    assert.equal(f.getAssignedUrl(), null);
});

test('a superseded response cannot replace the newer page even if transport ignores abort', async () => {
    const f = createFixture();
    const request = f.window.secureFetch;
    let releaseOld;
    f.window.secureFetch = async (...args) => {
        if (args[0] === '/settings') await new Promise(resolve => { releaseOld = resolve; });
        return request(...args);
    };
    const click = href => f.docListeners.get('click')({
        target: { closest: () => ({ href, hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    click('http://localhost:8080/settings');
    await new Promise(resolve => setTimeout(resolve, 0));
    click('http://localhost:8080/operations');
    await new Promise(resolve => setTimeout(resolve, 0));
    releaseOld();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.getPushedUrl(), '/operations');
    assert.ok(f.actions.includes('initOperations'));
    assert.equal(f.actions.includes('initSettings'), false);
    assert.equal(f.getAssignedUrl(), null);
});

test('reduced motion skips native and fallback page animations', async () => {
    const f = createFixture({ enableViewTransitions: true });
    f.window.matchMedia = () => ({ matches: true });
    f.docListeners.get('click')({
        target: { closest: () => ({ href: 'http://localhost:8080/settings', hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.actions.some(action => action.startsWith('startViewTransition')), false);
    assert.equal(f.actions.includes('main.class.add:panel-page-enter'), false);
    assert.ok(f.actions.includes('initSettings'));
});

test('a failed native transition still initializes the page and uses the CSS fallback', async () => {
    const f = createFixture();
    f.document.startViewTransition = () => { throw new Error('Snapshot unavailable'); };
    f.docListeners.get('click')({
        target: { closest: () => ({ href: 'http://localhost:8080/settings', hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.ok(f.actions.includes('initSettings'));
    assert.ok(f.actions.includes('main.class.add:panel-page-enter'));
    assert.equal(f.document.documentElement.dataset.panelNavigating, undefined);
    assert.equal(f.getAssignedUrl(), null);
});

test('gateway failures keep every current page visible and never trigger a document reload', async () => {
    for (const path of ['/nodes', '/settings', '/operations', '/']) {
        const f = createFixture({ initialPath: path });
        const messages = [];
        let attempts = 0;
        f.window.showToast = message => messages.push(message);
        f.window.secureFetch = async (url, options) => {
            attempts++;
            assert.equal(options.cache, 'no-store');
            return { ok: false, status: 503 };
        };
        const target = path === '/settings' ? '/nodes' : '/settings';
        f.docListeners.get('click')({
            target: { closest: () => ({ href: 'http://localhost:8080' + target, hasAttribute: () => false }) },
            button: 0, preventDefault() {}, stopImmediatePropagation() {}
        });
        await new Promise(resolve => setTimeout(resolve, 0));
        assert.equal(attempts, 2);
        assert.equal(messages.length, 1);
        assert.equal(f.getAssignedUrl(), null);
        assert.equal(f.getPushedUrl(), null);
        assert.equal(f.actions.includes('main.replaceWith'), false);
        assert.equal(f.actions.includes('destroyNodesMonitor'), false);
        assert.ok(f.actions.includes('main.remove:aria-busy'));
    }
});

test('a transient 503 retries once and then completes normal navigation', async () => {
    const f = createFixture();
    const request = f.window.secureFetch;
    let attempts = 0;
    f.window.secureFetch = (...args) => ++attempts === 1
        ? Promise.resolve({ status: 503, ok: false }) : request(...args);
    f.docListeners.get('click')({
        target: { closest: () => ({ href: 'http://localhost:8080/settings', hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(attempts, 2);
    assert.ok(f.actions.includes('initSettings'));
    assert.equal(f.getAssignedUrl(), null);
});

test('Retry-After prevents an immediate retry against an unavailable server', async () => {
    const f = createFixture();
    let attempts = 0;
    f.window.secureFetch = async () => {
        attempts++;
        return { status: 503, ok: false, headers: { get: () => '30' } };
    };
    f.docListeners.get('click')({
        target: { closest: () => ({ href: 'http://localhost:8080/settings', hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(attempts, 1);
    assert.equal(f.getAssignedUrl(), null);
});

test('click bursts request only the final page and reuse an in-flight navigation', async () => {
    const f = createFixture({ navigationDelay: 30 });
    const request = f.window.secureFetch;
    let calls = 0, release;
    f.window.secureFetch = async (...args) => {
        calls++;
        await new Promise(resolve => { release = resolve; });
        return request(...args);
    };
    const click = path => f.docListeners.get('click')({
        target: { closest: () => ({ href: 'http://localhost:8080' + path, hasAttribute: () => false }) },
        button: 0, preventDefault() {}, stopImmediatePropagation() {}
    });
    for (let i = 0; i < 50; i++) click(i % 2 ? '/settings' : '/operations');
    assert.equal(calls, 0);
    await new Promise(resolve => setTimeout(resolve, 45));
    assert.equal(calls, 1);
    for (let i = 0; i < 50; i++) click('/settings');
    await new Promise(resolve => setTimeout(resolve, 45));
    assert.equal(calls, 1, 'Do not abort or duplicate an identical pending navigation');
    release();
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(f.getPushedUrl(), '/settings');
    assert.equal(f.actions.filter(action => action === 'initSettings').length, 1);
});
