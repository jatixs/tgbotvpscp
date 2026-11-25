/* Keep existing operation cards current without replacing their expanded details. */
(() => {
    function noop() {}
    let cleanup = noop;
    window.destroyOperations = () => cleanup();
    window.initOperations = () => {
        cleanup();
        const lifecycle = new AbortController();
        const signal = lifecycle.signal;
        const main = document.querySelector('main[data-panel-page="operations"]');
        if (!main) return;
        main.querySelectorAll('[data-operation-encrypted]').forEach(element => {
            element.textContent = window.decryptData(element.dataset.operationEncrypted);
        });
        main.querySelectorAll('select').forEach((select, index) => {
            enhanceSelect(select, index, signal);
        });
        cleanup = () => lifecycle.abort();
        const list = document.getElementById('operationsList');
        const indicator = document.getElementById('operationsLiveStatus');
        if (!list || !indicator || !window.EventSource) return;
        const cards = new Map(Array.from(list.querySelectorAll('[data-operation-id]'))
            .map(card => [Number(card.dataset.operationId), card]));
        if (!cards.size) return;
        const styles = JSON.parse(list.dataset.statusStyles || '{}');
        let source = null;
        let expired = false;

        function showStatus(key) {
            indicator.textContent = Reflect.get(indicator.dataset, key) || '';
            indicator.hidden = false;
        }

        function stop() {
            if (source) source.close();
            source = null;
        }

        function start() {
            if (source || expired || document.hidden) return;
            const connection = new window.EventSource(`/api/operations/stream?ids=${Array.from(cards.keys()).slice(0, 50).join(',')}`);
            source = connection;
            showStatus('connecting');
            connection.addEventListener('open', () => {
                if (source === connection) showStatus('live');
            });
            connection.addEventListener('error', () => {
                if (source === connection) showStatus('reconnecting');
            });
            connection.addEventListener('session_expired', () => {
                if (source !== connection) return;
                expired = true;
                stop();
                showStatus('expired');
            });
            connection.addEventListener('operations', event => {
                if (source !== connection) return;
                let updates;
                try { updates = window.decryptApiResponse(JSON.parse(event.data)); } catch { return; }
                if (!Array.isArray(updates)) return;
                for (const update of updates) {
                    if (!update || !Number.isSafeInteger(update.id)) continue;
                    const card = cards.get(update.id);
                    if (!card || typeof update.result !== 'string' || typeof update.status_label !== 'string'
                        || typeof update.updated_at !== 'string' || !Object.hasOwn(styles, update.status)) continue;
                    const badge = card.querySelector('[data-operation-status]');
                    badge.textContent = update.status_label;
                    badge.className = `operation-status px-2 py-1 rounded-lg text-xs font-medium ${styles[update.status]}`;
                    card.querySelector('[data-operation-updated]').textContent = update.updated_at;
                    const output = card.querySelector('[data-operation-output]');
                    if (output.textContent !== update.result) output.textContent = update.result;
                    card.querySelector('[data-operation-result]').hidden = !update.result;
                }
                showStatus('live');
            });
        }

        document.addEventListener('visibilitychange', () => document.hidden ? stop() : start(), { signal });
        window.addEventListener('pagehide', stop, { signal });
        window.addEventListener('pageshow', start, { signal });
        cleanup = () => { stop(); lifecycle.abort(); };
        start();
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', window.initOperations, { once: true });
    else window.initOperations();
})();


function enhanceSelect(select, index, signal) {
    if (select.hidden && select.nextElementSibling?.classList.contains('operation-select')) {
        select.nextElementSibling.remove();
        select.hidden = false;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'operation-select';
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'operation-select-trigger';
    trigger.textContent = select.selectedOptions[0]?.textContent || '';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-label', select.closest('label')?.querySelector('span')?.textContent || select.name);
    const menu = document.createElement('div');
    menu.className = 'operation-select-options custom-scrollbar';
    menu.id = `operation-select-${index}`;
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;
    trigger.setAttribute('aria-controls', menu.id);
    function close() {
        menu.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
    }
    const buttons = Array.from(select.options, option => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'operation-select-option';
        button.textContent = option.textContent;
        button.setAttribute('role', 'option');
        button.setAttribute('aria-selected', String(option.selected));
        button.addEventListener('click', () => {
            const changed = select.value !== option.value;
            select.value = option.value;
            trigger.textContent = option.textContent;
            buttons.forEach(item => {
                item.setAttribute('aria-selected', String(item === button));
            });
            close();
            trigger.focus();
            if (changed) {
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }, { signal });
        menu.appendChild(button);
        return button;
    });
    function open() {
        menu.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        buttons[select.selectedIndex]?.focus();
    }
    trigger.addEventListener('click', () => menu.hidden ? open() : close(), { signal });
    trigger.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); open(); }
    }, { signal });
    menu.addEventListener('keydown', event => {
        const current = buttons.indexOf(document.activeElement);
        if (event.key === 'Escape') { event.preventDefault(); close(); trigger.focus(); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            buttons[(current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
        }
    }, { signal });
    document.addEventListener('click', event => { if (!wrapper.contains(event.target)) close(); }, { signal });
    document.addEventListener('focusin', event => { if (!wrapper.contains(event.target)) close(); }, { signal });
    wrapper.append(trigger, menu);
    select.after(wrapper);
    select.hidden = true;
}
