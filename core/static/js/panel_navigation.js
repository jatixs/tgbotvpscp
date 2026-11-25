/* Navigation between dashboard, server monitoring, operations history, and settings. Bundles load once. */
(() => {
    const ALLOWED_ROUTES = new Map([
        ['/', '/'],
        ['/nodes', '/nodes'],
        ['/operations', '/operations'],
        ['/settings', '/settings']
    ]);
    const pages = new Set(ALLOWED_ROUTES.keys());
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
    let pendingTarget = null;
    let navigationTimer = null;
    let activeTransition = null;

    function scheduleNavigation(href) {
        clearTimeout(navigationTimer);
        navigationTimer = setTimeout(() => {
            navigationTimer = null;
            navigate(href);
        }, 120);
    }

    function normalizePath(pathname) {
        if (!pathname) return '';
        const trimmed = pathname.replace(/\/+$/, '');
        return trimmed || '/';
    }

    function sanitizeQueryParams(searchParams) {
        const clean = new URLSearchParams();
        for (const [key, val] of searchParams.entries()) {
            if (key === 'return_to' && val === '/nodes') {
                clean.set(key, val);
            } else if (key === 'node_id' && /^\d+$/.test(val)) {
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
        const expectedPage = Reflect.get(pageKeyMap, normPath);
        if (history && currentDomPage === expectedPage && url.search === location.search) {
            if (pending) {
                pending.abort();
                pending = null;
                pendingTarget = null;
                document.querySelector('main')?.removeAttribute('aria-busy');
            }
            if (url.hash) return;
            window.scrollTo({ top: 0, behavior: 'smooth' });
            return;
        }

        const baseRoute = ALLOWED_ROUTES.get(normPath) || null;
        if (!baseRoute) return;
        const safeQuery = sanitizeQueryParams(url.searchParams);
        const targetUrl = baseRoute + safeQuery;

        if (pending && pendingTarget === targetUrl) return;
        if (pending) pending.abort();
        const controller = new AbortController();
        pending = controller;
        pendingTarget = targetUrl;
        const mainEl = document.querySelector('main');
        if (mainEl) mainEl.setAttribute('aria-busy', 'true');

        function finishTransition(transition) {
            if (activeTransition !== transition) return;
            activeTransition = null;
            if (document.documentElement?.dataset) delete document.documentElement.dataset.panelNavigating;
        }

        try {
            const options = {
                credentials: 'same-origin',
                cache: 'no-store',
                signal: controller.signal,
            };
            const requestClient = (typeof window !== 'undefined' && typeof window.secureFetch === 'function')
                ? window.secureFetch
                : (typeof window.secureFetch === 'function' ? window.secureFetch : null);
            if (!requestClient) throw new Error('Secure transport unavailable');
            let response = await requestClient(targetUrl, options);
            // A transient gateway failure must not send the user to an error document.
            if ([502, 503, 504].includes(response.status) && !controller.signal.aborted) {
                const retryAfter = response.headers?.get('Retry-After');
                if (!retryAfter) {
                    response = await requestClient(targetUrl, options);
                }
            }
            if ([502, 503, 504].includes(response.status)) {
                if (!controller.signal.aborted) {
                    const message = document.documentElement.lang === 'ru'
                        ? 'Сервер временно недоступен. Попробуйте перейти ещё раз позже.'
                        : 'The server is temporarily unavailable. Please try again later.';
                    window.showToast?.(message);
                }
                return;
            }

            if (!response.ok) throw new Error('Navigation unavailable');
            const responsePath = normalizePath(new URL(response.url, location.href).pathname);
            if (responsePath !== normPath) throw new Error('Navigation unavailable');

            const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
            const main = doc.querySelector('main[data-panel-page]');
            const nav = doc.querySelector('nav');
            const expectedPage = Reflect.get(pageKeyMap, normPath);
            if (!main || !nav || main.dataset.panelPage !== expectedPage) throw new Error('Unexpected page');
            if (controller.signal.aborted) return;

            const targetModalId = expectedPage ? Reflect.get(modalIdMap, expectedPage) : undefined;
            const sections = [main, nav, targetModalId ? doc.getElementById(targetModalId) : null].filter(Boolean);
            sections.forEach(section => {
                section.querySelectorAll?.('script')?.forEach(script => {
                    script.remove();
                });
            });

            const updateDOM = function updateDOM() {
                // A newer request may supersede us while the browser captures the old frame.
                if (controller.signal.aborted) return;
                window.destroyDashboard?.();
                window.destroyNodesMonitor?.();
                window.destroyOperations?.();
                window.destroySettings?.();
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
                if (history) window.history.pushState({ panelRoute: true }, '', targetUrl);
                window.applyPanelBootstrap?.();
                if (typeof window.applyThemeUI === 'function') {
                    const curTheme = typeof window.getResolvedTheme === 'function' ? window.getResolvedTheme() : (localStorage.getItem('theme') || 'dark');
                    window.applyThemeUI(curTheme);
                }
                // Rebind shared header controls before page-specific initialization.
                // A settings/dashboard error must not leave the replaced nav inert.
                if (typeof window.initNotifications === 'function') window.initNotifications();
                if (typeof window.renderHeaderBilling === 'function') window.renderHeaderBilling();

                if (expectedPage === 'dashboard') {
                    window.initDashboard?.();
                } else if (expectedPage === 'nodes') {
                    window.initNodesMonitor?.();
                } else if (expectedPage === 'operations') {
                    window.initOperations?.();
                } else if (expectedPage === 'settings') {
                    window.initSettings?.();
                }
                if (typeof window.initNodeModalScaling === 'function') window.initNodeModalScaling();
                if (typeof window.initHapticsToggle === 'function') window.initHapticsToggle();
                if (typeof window.initGlobalLazyLoad === 'function') window.initGlobalLazyLoad();
                if (typeof window.parsePageEmojis === 'function') window.parsePageEmojis();
            };

            const isPerfMode = Boolean(document.documentElement?.classList?.contains?.('perf-mode'))
                || Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);
            const isDocumentHidden = typeof document !== 'undefined' && Boolean(document.hidden);

            activeTransition?.skipTransition?.();
            let hasViewTransitions = false;
            let domUpdated = false;

            if (!isPerfMode && !isDocumentHidden && typeof document.startViewTransition === 'function') {
                hasViewTransitions = true;
                if (document.documentElement?.dataset) {
                    document.documentElement.dataset.panelNavigating = 'true';
                }
                try {
                    const transition = document.startViewTransition(() => {
                        domUpdated = true;
                        updateDOM();
                    });
                    activeTransition = transition;
                    if (transition && typeof transition.ready?.catch === 'function') {
                        transition.ready.catch(() => {});
                    }
                    if (transition && typeof transition.finished?.catch === 'function') {
                        transition.finished.catch(() => {});
                    }
                    // Keep navigation styles until the visual animation has actually finished.
                    const onTransitionEnd = finishTransition.bind(null, transition);
                    Promise.resolve(transition.finished).then(onTransitionEnd, onTransitionEnd);
                    await (transition.updateCallbackDone || transition.finished || Promise.resolve());
                } catch {
                    if (!domUpdated) {
                        hasViewTransitions = false;
                        updateDOM();
                    }
                    if (!activeTransition && document.documentElement?.dataset) delete document.documentElement.dataset.panelNavigating;
                }
            } else {
                updateDOM();
            }

            if (controller.signal.aborted) return;
            const newMain = document.querySelector('main');
            if (newMain && !hasViewTransitions && !isPerfMode) {
                newMain.classList.remove('panel-page-enter');
                void newMain.offsetWidth;
                newMain.classList.add('panel-page-enter');
            }
        } catch (error) {
            if (!controller.signal.aborted && error.name !== 'AbortError') {
                console.error('[Panel Navigation]', error);
                window.location.assign(url.href);
            }
        } finally {
            if (pending === controller) {
                pending = null;
                pendingTarget = null;
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
        scheduleNavigation(link.href);
    }, true);

    document.addEventListener('submit', event => {
        const form = event.target;
        if (form.matches('form.operations-filters') && normalizePath(location.pathname) === '/operations') {
            event.preventDefault();
            event.stopImmediatePropagation();
            const params = new URLSearchParams(new FormData(form)).toString();
            scheduleNavigation('/operations' + (params ? ('?' + params) : ''));
        }
    }, true);

    window.addEventListener('popstate', event => {
        if (event.state?.panelRoute && pages.has(normalizePath(location.pathname)) && document.querySelector('main[data-panel-page]')) {
            event.stopImmediatePropagation();
            clearTimeout(navigationTimer);
            navigate(location.href, { history: false });
        }
    }, true);

    if (pages.has(normalizePath(location.pathname))) {
        window.history.replaceState({ ...window.history.state, panelRoute: true }, '', location.href);
    }
})();
