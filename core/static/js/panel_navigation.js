/* Navigation between dashboard, server monitoring, operations history, and settings. Bundles load once. */
(() => {
    const pages = new Set(['/', '/nodes', '/operations', '/settings']);
    const pageKeyMap = {
        '/': 'dashboard',
        '/nodes': 'nodes',
        '/operations': 'operations',
        '/settings': 'settings'
    };
    const modalIdMap = {
        dashboard: 'dashboardPageModals',
        nodes: 'nodesPageModals',
        settings: 'settingsPageModals'
    };
    const allModalIds = Object.values(modalIdMap);
    let pending = null;

    function normalizePath(pathname) {
        if (!pathname) return '';
        const trimmed = pathname.replace(/\/+$/, '');
        return trimmed || '/';
    }

    function sanitizeQueryParams(searchParams) {
        const clean = new URLSearchParams();
        for (const [key, val] of searchParams.entries()) {
            if (key === 'node_id' && /^\d+$/.test(val)) {
                clean.set(key, val);
            } else if (key === 'status' && /^[a-z_]{1,20}$/.test(val)) {
                clean.set(key, val);
            } else if (key === 'per_page' && /^(10|25|50|100)$/.test(val)) {
                clean.set(key, val);
            } else if ((key === 'page' || key === 'before') && /^\d+$/.test(val)) {
                clean.set(key, val);
            } else if (key === 'tab' && /^[a-zA-Z0-9_-]{1,32}$/.test(val)) {
                clean.set(key, val);
            }
        }
        const searchStr = clean.toString();
        return searchStr ? ('?' + searchStr) : '';
    }

    window.panelNavigationHandles = window.operationNavigationHandles = href => {
        try {
            const url = new URL(href, location.href);
            return url.origin === location.origin && pages.has(normalizePath(location.pathname)) && pages.has(normalizePath(url.pathname));
        } catch {
            return false;
        }
    };

    async function navigate(href, { history = true } = {}) {
        const url = new URL(href, location.href);
        const normPath = normalizePath(url.pathname);
        if (url.origin !== location.origin || !pages.has(normPath)) return;
        const currentMain = document.querySelector('main[data-panel-page]');
        const currentDomPage = currentMain ? currentMain.dataset.panelPage : null;
        const expectedPage = pageKeyMap[normPath];
        if (history && currentDomPage === expectedPage && url.search === location.search) {
            if (url.hash) return;
            window.scrollTo({ top: 0, behavior: 'smooth' });
            return;
        }

        const safeQuery = sanitizeQueryParams(url.searchParams);
        const targetUrl = (normPath === '/' ? '/' : normPath) + safeQuery;

        if (pending) pending.abort();
        const controller = new AbortController();
        pending = controller;
        const mainEl = document.querySelector('main');
        if (mainEl) mainEl.setAttribute('aria-busy', 'true');

        try {
            const options = {
                credentials: 'same-origin',
                cache: 'no-store',
                signal: controller.signal,
            };
            const response = await fetch(targetUrl, options);

            if (!response.ok) throw new Error('Navigation unavailable');
            const responsePath = normalizePath(new URL(response.url, location.href).pathname);
            if (responsePath !== normPath) throw new Error('Navigation unavailable');

            const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
            const main = doc.querySelector('main[data-panel-page]');
            const nav = doc.querySelector('nav');
            const expectedPage = pageKeyMap[normPath];
            if (!main || !nav || main.dataset.panelPage !== expectedPage) throw new Error('Unexpected page');
            if (controller.signal.aborted) return;

            window.destroyDashboard?.();
            window.destroyNodesMonitor?.();
            window.destroyOperations?.();
            window.destroySettings?.();

            const targetModalId = modalIdMap[expectedPage];
            const sections = [main, nav, targetModalId ? doc.getElementById(targetModalId) : null].filter(Boolean);
            sections.forEach(section => {
                section.querySelectorAll?.('script')?.forEach(script => {
                    script.remove();
                });
            });

            function updateDOM() {
                window.scrollTo(0, 0);
                document.querySelector('main')?.replaceWith(document.importNode(main, true));
                document.querySelector('nav')?.replaceWith(document.importNode(nav, true));
                allModalIds.forEach(id => {
                    document.getElementById(id)?.remove();
                });
                if (targetModalId) {
                    const modals = doc.getElementById(targetModalId);
                    if (modals) document.body.appendChild(document.importNode(modals, true));
                }
                document.title = doc.title;
                if (doc.documentElement?.lang) document.documentElement.lang = doc.documentElement.lang;
                if (doc.body) document.body.className = doc.body.className;
                document.body.style.overflow = '';
            }

            let hasViewTransitions = false;
            if (typeof document.startViewTransition === 'function') {
                hasViewTransitions = true;
                if (document.documentElement?.dataset) {
                    document.documentElement.dataset.panelNavigating = 'true';
                }
                try {
                    await document.startViewTransition(() => updateDOM()).finished;
                } catch {
                } finally {
                    if (document.documentElement?.dataset) {
                        delete document.documentElement.dataset.panelNavigating;
                    }
                }
            } else {
                updateDOM();
            }

            if (history) window.history.pushState({ panelRoute: true }, '', targetUrl);
            window.applyPanelBootstrap?.();
            if (expectedPage === 'dashboard') {
                window.initDashboard?.();
            } else if (expectedPage === 'nodes') {
                window.initNodesMonitor?.();
            } else if (expectedPage === 'operations') {
                window.initOperations?.();
            } else if (expectedPage === 'settings') {
                window.initSettings?.();
            }
            if (typeof initNotifications === 'function') initNotifications();
            if (typeof renderHeaderBilling === 'function') renderHeaderBilling();
            if (typeof initNodeModalScaling === 'function') initNodeModalScaling();
            if (typeof initHapticsToggle === 'function') initHapticsToggle();
            if (typeof initGlobalLazyLoad === 'function') initGlobalLazyLoad();
            if (typeof parsePageEmojis === 'function') parsePageEmojis();

            const newMain = document.querySelector('main');
            if (newMain && !hasViewTransitions) {
                newMain.classList.remove('panel-page-enter');
                void newMain.offsetWidth;
                newMain.classList.add('panel-page-enter');
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('[Panel Navigation]', error);
                window.location.assign(url.href);
            }
        } finally {
            if (pending === controller) {
                pending = null;
                document.querySelector('main')?.removeAttribute('aria-busy');
            }
        }
    }

    document.addEventListener('click', event => {
        const link = event.target.closest('a');
        if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
            || link.hasAttribute('download') || (link.target && link.target !== '_self')
            || !window.panelNavigationHandles(link.href)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        navigate(link.href);
    }, true);

    document.addEventListener('submit', event => {
        const form = event.target;
        if (form.matches('form.operations-filters') && normalizePath(location.pathname) === '/operations') {
            event.preventDefault();
            event.stopImmediatePropagation();
            const params = new URLSearchParams(new FormData(form)).toString();
            navigate('/operations' + (params ? ('?' + params) : ''));
        }
    }, true);

    window.addEventListener('popstate', event => {
        if (event.state?.panelRoute && pages.has(normalizePath(location.pathname)) && document.querySelector('main[data-panel-page]')) {
            event.stopImmediatePropagation();
            navigate(location.href, { history: false });
        }
    }, true);

    if (pages.has(normalizePath(location.pathname))) {
        window.history.replaceState({ ...window.history.state, panelRoute: true }, '', location.href);
    }
})();
