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

function createFixture({ initialPath = '/nodes', enableViewTransitions = false } = {}) {
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
        DOMParser: window.DOMParser,
        AbortController,
        URL,
        URLSearchParams,
        setTimeout,
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
