/* Shared visual privacy mode, loaded in the head before page content. */
(() => {
    const storageKey = 'screenshotMode';
    const root = document.documentElement;
    const sensitive = [
        '[data-sensitive]', '.ip-copy-text', '[data-ref="name"]',
        '[data-token][data-status] h3', '[data-operation-encrypted]',
        '#agentIp', '#agentIpsPrimary', '#agentIpsList', '#modalNodeName', '#modalNodeTitle',
        '#vncNodeSelectModal button[onclick*="openVncTerminal"]',
        '#notifDetailNodeName', '#newNodeTokenDash', '#newNodeCmdDash',
        '#usersTableBody td:nth-child(-n+2)', '#nodesTableBody td:nth-child(-n+3)',
        '#sessionsModalContent', '#logsContainer', '#notifList',
        '#terminal-container', '.xterm', 'iframe',
        '#sysModalMessage', '#connError', '.app-toast:not([data-screenshot-safe])', 'pre',
        'input:not([type]):not(:placeholder-shown)', 'input[type="text"]:not(:placeholder-shown)', 'input[type="password"]',
        'input[type="email"]', 'input[type="url"]', 'input[type="tel"]',
        'input[type="search"]:not(:placeholder-shown)', 'textarea', 'select[name="node_id"]'
    ];
    const style = document.createElement('style');
    style.textContent = `
        ${sensitive.map(selector => `html.screenshot-transition ${selector}`).join(',')} {
            transition: filter 240ms ease !important;
        }
        ${sensitive.map(selector => `html.screenshot-mode ${selector}`).join(',')} {
            filter: blur(9px) !important;
            user-select: none !important;
        }
        .screenshot-toggle { display:inline-flex; align-items:center; gap:7px; padding:6px;
            font-size:12px; font-weight:600; cursor:pointer; border-radius:8px; outline:none; }
        .screenshot-toggle:focus { outline:none; }
        .screenshot-toggle.screenshot-toggle-menu { display:flex; width:100%;
            align-items:center; justify-content:space-between; padding:8px 16px; border-radius:0;
            font-size:14px; font-weight:500; text-align:left; transition:background-color 150ms ease; }
        .screenshot-toggle-track { position:relative; width:44px; height:24px; border-radius:9999px;
            background-color:#e5e7eb; flex-shrink:0; cursor:pointer; box-sizing:border-box;
            transition:background-color 150ms cubic-bezier(0.4, 0, 0.2, 1); }
        html.dark .screenshot-toggle-track,
        .dark .screenshot-toggle-track { background-color:#374151; }
        .screenshot-toggle-track::after { content:''; position:absolute; top:2px; left:2px;
            width:20px; height:20px; border-radius:9999px; background-color:#ffffff;
            border:1px solid #d1d5db; box-sizing:border-box; transform:translateX(0);
            transition:all 150ms cubic-bezier(0.4, 0, 0.2, 1); }
        html.dark .screenshot-toggle-track::after,
        .dark .screenshot-toggle-track::after { border-color:#4b5563; }
        .screenshot-toggle[aria-checked="true"] .screenshot-toggle-track { background-color:#22c55e; }
        html.dark .screenshot-toggle[aria-checked="true"] .screenshot-toggle-track,
        .dark .screenshot-toggle[aria-checked="true"] .screenshot-toggle-track { background-color:#22c55e; }
        .screenshot-toggle[aria-checked="true"] .screenshot-toggle-track::after { transform:translateX(20px); border-color:#ffffff; }
        .screenshot-toggle.is-control-pressed .screenshot-toggle-track::after,
        .screenshot-toggle-track.is-control-pressed::after {
            scale: 1.15;
        }
        @media (pointer: coarse), (hover: none) {
            .screenshot-toggle:active .screenshot-toggle-track::after,
            .screenshot-toggle-track:active::after {
                scale: 1.15;
            }
        }
        .screenshot-toggle-icon { flex-shrink:0; transition:color 150ms cubic-bezier(0.4, 0, 0.2, 1); }
        .screenshot-toggle[aria-checked="true"] .screenshot-toggle-icon { color:#22c55e; }
        @media(prefers-reduced-motion:reduce) {
            .screenshot-toggle-track, .screenshot-toggle-track::after, .screenshot-toggle-icon {
                transition:none;
            }
            .screenshot-toggle.is-control-pressed .screenshot-toggle-track::after,
            .screenshot-toggle-track.is-control-pressed::after,
            .screenshot-toggle:active .screenshot-toggle-track::after,
            .screenshot-toggle-track:active::after {
                scale:none;
            }
        }
    `;
    document.head.appendChild(style);

    let transitionTimer;
    function apply(enabled, animate = false) {
        if (animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            clearTimeout(transitionTimer);
            root.classList.add('screenshot-transition');
            transitionTimer = setTimeout(() => root.classList.remove('screenshot-transition'), 260);
        }
        root.classList.toggle('screenshot-mode', enabled);
        document.querySelectorAll('[data-screenshot-toggle]').forEach(button => {
            button.setAttribute('aria-checked', String(enabled));
        });
    }
    try { apply(localStorage.getItem(storageKey) === 'true'); } catch { apply(false); }

    document.addEventListener('click', event => {
        const toggle = event.target.closest('[data-screenshot-toggle]');
        if (!toggle) return;
        const enabled = !root.classList.contains('screenshot-mode');
        apply(enabled, true);
        try { localStorage.setItem(storageKey, String(enabled)); } catch { /* Session-only mode. */ }
        const message = enabled
            ? toggle.dataset.enabledMessage
            : toggle.dataset.disabledMessage;
        window.showToast(message, { screenshotSafe: true });
    });
    window.addEventListener('storage', event => {
        if (event.key === storageKey || event.key === null) apply(event.newValue === 'true', true);
    });
    // Delegation and observation also cover headers replaced by panel navigation.
    const sync = () => {
        document.querySelectorAll('[data-screenshot-toggle]').forEach(button => {
            button.setAttribute('aria-checked', String(root.classList.contains('screenshot-mode')));
        });
    };
    document.addEventListener('DOMContentLoaded', () => {
        sync();
        new MutationObserver(sync).observe(document.body, { childList:true, subtree:true });
    });
})();
