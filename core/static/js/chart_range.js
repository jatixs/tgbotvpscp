/*
 * Chart time-range selector (3m … 7d) + history stream.
 *
 * Data comes from the SSE endpoint /api/events/metrics (event `metrics_history`): the first
 * message is a full snapshot, later ones are incremental; `data` is AES-encrypted like the
 * other SSE payloads and decrypted with decryptData() from common.js.
 *
 * Usage:
 *   const ctl = createChartRangeController({
 *       key: 'agentChart',                       // localStorage key suffix
 *       mount: '[data-chart-range="agentChart"]',// element that receives the dropdown button
 *       canvasId: 'agentChart',                  // used for zoom reset + empty-state overlay
 *       getSource: () => ({ source: 'agent' }),  // or { source: 'node', node_id }
 *       network: true,                         // use measured network peaks and interface picker
 *       render: (series) => { ... }              // called with normalized series
 *   });
 *   ctl.start(); ctl.stop(); ctl.refresh(); ctl.destroy();
 *
 * series = { range, step, span, points, labels, cpu, ram, disk, rx, tx, isLive }
 * rx/tx are in Kbps (same unit the charts already use), gaps are null-filled.
 */
(function () {
    'use strict';

    const RANGES = [
        { key: '3m', group: 'minutes', amount: 3, seconds: 180 },
        { key: '10m', group: 'minutes', amount: 10, seconds: 600 },
        { key: '30m', group: 'minutes', amount: 30, seconds: 1800 },
        { key: '1h', group: 'hours', amount: 1, seconds: 3600 },
        { key: '3h', group: 'hours', amount: 3, seconds: 3 * 3600 },
        { key: '6h', group: 'hours', amount: 6, seconds: 6 * 3600 },
        { key: '12h', group: 'hours', amount: 12, seconds: 12 * 3600 },
        { key: '1d', group: 'days', amount: 1, seconds: 86400 },
        { key: '3d', group: 'days', amount: 3, seconds: 3 * 86400 },
        { key: '7d', group: 'days', amount: 7, seconds: 7 * 86400 }
    ];
    const GROUPS = ['minutes', 'hours', 'days'];
    const DEFAULT_RANGE = '3m';
    const LIVE_MAX_SECONDS = 3600;
    const RAW_GAP_SECONDS = 25;
    const STREAM_URL = '/api/events/metrics';
    const RECONNECT_DELAY = 5000;

    const CLOCK_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="chart-range-icon"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
    const CHEVRON_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="chart-range-chevron"><path d="M6 9l6 6 6-6"/></svg>';

    function t(key, fallback) {
        return (typeof I18N !== 'undefined' && I18N && I18N[key]) ? I18N[key] : fallback;
    }

    function unitLabel(group) {
        if (group === 'minutes') return t('unit_minute_short', 'm');
        if (group === 'hours') return t('unit_hour_short', 'h');
        return t('unit_day_short', 'd');
    }

    function groupLabel(group) {
        if (group === 'minutes') return t('web_chart_range_minutes', 'Minutes');
        if (group === 'hours') return t('web_chart_range_hours', 'Hours');
        return t('web_chart_range_days', 'Days');
    }

    function rangeLabel(range) {
        return `${range.amount}${unitLabel(range.group)}`;
    }

    function stepLabel(step) {
        if (!step) return '';
        if (step < 60) return `${step}s`;
        if (step < 3600) return `${Math.round(step / 60)}${unitLabel('minutes')}`;
        return `${Math.round(step / 3600)}${unitLabel('hours')}`;
    }

    function findRange(key) {
        return RANGES.find(r => r.key === key) || RANGES.find(r => r.key === DEFAULT_RANGE);
    }

    function formatLabel(ts, span) {
        const date = new Date(ts * 1000);
        if (span <= 3600) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }
        if (span <= 86400) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        return date.toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    }

    function readStored(key) {
        try {
            const value = localStorage.getItem(`chartRange:${key}`);
            return RANGES.some(r => r.key === value) ? value : null;
        } catch {
            return null;
        }
    }

    function writeStored(key, value) {
        try {
            localStorage.setItem(`chartRange:${key}`, value);
        } catch { /* storage disabled */ }
    }

    let openController = null;

    document.addEventListener('click', (e) => {
        if (!openController) return;
        if (openController.pop?.contains(e.target) || openController.button?.contains(e.target) || openController.interfaceButton?.contains(e.target)) return;
        openController.closePopover();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && openController) openController.closePopover();
    });
    window.addEventListener('resize', () => openController?.closePopover());
    window.addEventListener('scroll', (event) => {
        if (!openController?.pop?.contains(event.target)) openController?.closePopover();
    }, true);

    function createChartRangeController(opts) {
        const mount = typeof opts.mount === 'string' ? document.querySelector(opts.mount) : opts.mount;
        const storageKey = opts.key || opts.canvasId || 'chart';
        const ctl = {
            range: findRange(opts.initialRange || readStored(storageKey) || DEFAULT_RANGE),
            points: [],
            step: 0,
            span: 0,
            serverNow: Math.floor(Date.now() / 1000),
            running: false,
            destroyed: false,
            stream: null,
            reconnectTimer: null,
            loading: true,
            pop: null,
            button: null,
            interfaceName: '',
            interfaceButton: null,
            interfaces: [],
            popKind: 'range',
            mount
        };

        /* ---------- UI ---------- */
        function buildButton() {
            if (!mount) return;
            mount.classList.add('chart-range');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'chart-range-btn';
            btn.setAttribute('aria-haspopup', 'listbox');
            btn.setAttribute('aria-expanded', 'false');
            btn.title = t('web_chart_range_title', 'Chart period');

            const liveSpan = document.createElement('span');
            liveSpan.className = 'chart-range-live';
            liveSpan.setAttribute('aria-hidden', 'true');

            const labelSpan = document.createElement('span');
            labelSpan.className = 'chart-range-label';

            const clockWrapper = document.createElement('span');
            clockWrapper.className = 'inline-flex';
            clockWrapper.innerHTML = CLOCK_ICON;

            const chevronWrapper = document.createElement('span');
            chevronWrapper.className = 'inline-flex';
            chevronWrapper.innerHTML = CHEVRON_ICON;

            btn.append(liveSpan, clockWrapper.firstElementChild || clockWrapper, labelSpan, chevronWrapper.firstElementChild || chevronWrapper);
            mount.replaceChildren(btn);
            ctl.button = btn;
            if (opts.network) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'chart-range-btn chart-interface-button';
                button.setAttribute('aria-haspopup', 'listbox');
                button.setAttribute('aria-expanded', 'false');
                const label = document.createElement('span');
                label.className = 'chart-interface-label';
                button.append(label);
                const chevron = document.createElement('span');
                chevron.innerHTML = CHEVRON_ICON;
                button.append(chevron.firstElementChild || chevron);
                button.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (ctl.popKind === 'interface' && ctl.pop?.classList.contains('is-open')) ctl.closePopover();
                    else openPopover('interface');
                });
                ctl.interfaceButton = button;
                syncInterfaces([]);
                mount.prepend(button);
            }
            ctl.button.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (ctl.popKind === 'range' && ctl.pop?.classList.contains('is-open')) ctl.closePopover();
                else openPopover();
            });
            syncButton();
        }

        function syncButton() {
            if (!ctl.button) return;
            ctl.button.title = opts.network && ctl.step ? stepDescription() : t('web_chart_range_title', 'Chart period');
            const label = ctl.button.querySelector('.chart-range-label');
            if (label) label.textContent = rangeLabel(ctl.range);
            ctl.button.classList.toggle('is-live', ctl.range.seconds <= LIVE_MAX_SECONDS);
            if (ctl.pop) {
                ctl.pop.querySelectorAll('[data-range]').forEach(chip => {
                    chip.classList.toggle('is-active', chip.dataset.range === ctl.range.key);
                    chip.setAttribute('aria-selected', chip.dataset.range === ctl.range.key ? 'true' : 'false');
                });
                const foot = ctl.pop.querySelector('.chart-range-foot');
                if (foot) updateFoot(foot);
            }
        }

        function syncInterfaces(interfaces) {
            ctl.interfaces = [...new Set(interfaces)];
            if (!ctl.interfaceButton) return;
            const label = ctl.interfaceName || t('web_chart_all_interfaces', 'All interfaces');
            ctl.interfaceButton.querySelector('.chart-interface-label').textContent = label;
            ctl.interfaceButton.title = t('web_chart_interface', 'Network interface') + ' · ' + label;
            if (ctl.popKind === 'interface' && ctl.pop) fillInterfaceOptions();
        }

        function fillInterfaceOptions() {
            const container = ctl.pop.querySelector('.chart-interface-options');
            const names = ['', ...ctl.interfaces];
            if (ctl.interfaceName && !names.includes(ctl.interfaceName)) names.push(ctl.interfaceName);
            const existing = [...container.children].map(chip => chip.dataset.interface);
            if (existing.length !== names.length || names.some((name, i) => name !== existing[i])) {
                container.replaceChildren(...names.map(name => {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'chart-range-chip';
                    chip.setAttribute('role', 'option');
                    chip.dataset.interface = name;
                    chip.textContent = name || t('web_chart_all_interfaces', 'All interfaces');
                    chip.addEventListener('click', () => {
                        ctl.setInterface(name);
                        ctl.closePopover();
                        ctl.interfaceButton.focus();
                    });
                    return chip;
                }));
            }
            for (const chip of container.children) {
                const active = chip.dataset.interface === ctl.interfaceName;
                chip.classList.toggle('is-active', active);
                chip.setAttribute('aria-selected', String(active));
            }
        }

        function stepDescription() {
            const label = opts.network ? t('web_chart_interval_peak', 'Measured peaks per interval') : t('web_chart_range_step', 'Step');
            return `${label}: ${stepLabel(ctl.step)}`;
        }

        function updateFoot(foot) {
            const isLive = ctl.range.seconds <= LIVE_MAX_SECONDS;
            const stepText = ctl.step ? stepDescription() : '';
            if (isLive) {
                const liveSpan = document.createElement('span');
                liveSpan.className = 'chart-range-foot-live';
                const dot = document.createElement('span');
                dot.className = 'chart-range-live';
                liveSpan.append(dot, document.createTextNode(t('web_chart_range_live', 'Live')));

                if (stepText) {
                    const stepSpan = document.createElement('span');
                    stepSpan.textContent = stepText;
                    foot.replaceChildren(liveSpan, stepSpan);
                } else {
                    foot.replaceChildren(liveSpan);
                }
            } else {
                const textSpan = document.createElement('span');
                textSpan.textContent = stepText || rangeLabel(ctl.range);
                foot.replaceChildren(textSpan);
            }
        }

        function buildPopover() {
            const pop = document.createElement('div');
            pop.className = 'chart-range-pop';
            pop.setAttribute('role', 'listbox');

            const titleDiv = document.createElement('div');
            titleDiv.className = 'chart-range-pop-title';
            titleDiv.textContent = ctl.popKind === 'interface' ? t('web_chart_interface', 'Network interface') : t('web_chart_range_title', 'Chart period');
            pop.appendChild(titleDiv);

            if (ctl.popKind === 'interface') {
                const options = document.createElement('div');
                options.className = 'chart-range-chips chart-interface-options';
                pop.appendChild(options);
                document.body.appendChild(pop);
                ctl.pop = pop;
                fillInterfaceOptions();
                return;
            }

            GROUPS.forEach(group => {
                const groupDiv = document.createElement('div');
                groupDiv.className = 'chart-range-group';

                const labelSpan = document.createElement('span');
                labelSpan.className = 'chart-range-group-label';
                labelSpan.textContent = groupLabel(group);
                groupDiv.appendChild(labelSpan);

                const chipsDiv = document.createElement('div');
                chipsDiv.className = 'chart-range-chips';

                RANGES.filter(r => r.group === group).forEach(r => {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'chart-range-chip';
                    chip.setAttribute('role', 'option');
                    chip.dataset.range = r.key;
                    chip.textContent = rangeLabel(r);
                    chipsDiv.appendChild(chip);
                });

                groupDiv.appendChild(chipsDiv);
                pop.appendChild(groupDiv);
            });

            const footDiv = document.createElement('div');
            footDiv.className = 'chart-range-foot';
            pop.appendChild(footDiv);
            pop.addEventListener('click', (e) => {
                const chip = e.target.closest('.chart-range-chip');
                if (!chip) return;
                e.stopPropagation();
                chip.classList.add('is-pressed');
                setTimeout(() => chip.classList.remove('is-pressed'), 180);
                setRange(chip.dataset.range);
                setTimeout(() => ctl.closePopover(), 120);
            });
            document.body.appendChild(pop);
            ctl.pop = pop;
            syncButton();
        }

        function positionPopover() {
            if (!ctl.pop || !ctl.button) return;
            const button = ctl.popKind === 'interface' ? ctl.interfaceButton : ctl.button;
            const rect = button.getBoundingClientRect();
            const pop = ctl.pop;
            const margin = 8;
            const popWidth = pop.offsetWidth;
            const popHeight = pop.offsetHeight;
            let left = rect.left + (rect.width - popWidth) / 2;
            left = Math.max(margin, Math.min(left, window.innerWidth - popWidth - margin));
            let top = rect.bottom + 6;
            let openUp = false;
            if (top + popHeight > window.innerHeight - margin && rect.top - popHeight - 6 > margin) {
                top = rect.top - popHeight - 6;
                openUp = true;
            }
            pop.style.left = `${Math.round(left)}px`;
            pop.style.top = `${Math.round(top)}px`;
            pop.classList.toggle('is-up', openUp);
        }

        function openPopover(kind = 'range') {
            if (ctl.destroyed) return;
            if (openController && openController !== ctl) openController.closePopover();
            if (ctl.popKind !== kind) {
                ctl.closePopover();
                ctl.pop?.remove();
                ctl.pop = null;
                ctl.popKind = kind;
            }
            if (!ctl.pop) buildPopover();
            syncButton();
            positionPopover();
            requestAnimationFrame(() => ctl.pop?.classList.add('is-open'));
            const button = kind === 'interface' ? ctl.interfaceButton : ctl.button;
            button?.setAttribute('aria-expanded', 'true');
            button?.classList.add('is-open');
            openController = ctl;
        }

        ctl.closePopover = function () {
            if (ctl.pop) ctl.pop.classList.remove('is-open');
            ctl.button?.setAttribute('aria-expanded', 'false');
            ctl.button?.classList.remove('is-open');
            ctl.interfaceButton?.setAttribute('aria-expanded', 'false');
            ctl.interfaceButton?.classList.remove('is-open');
            if (openController === ctl) openController = null;
        };

        /* ---------- data ---------- */
        function sourceParams() {
            const src = typeof opts.getSource === 'function' ? opts.getSource() : { source: 'agent' };
            if (!src || !src.source) return null;
            if (src.source === 'node' && !src.node_id) return null;
            return src;
        }

        function resetChartZoom() {
            const chart = opts.canvasId && window.__chartRegistry ? window.__chartRegistry[opts.canvasId] : null;
            if (!chart) return;
            chart.__liveZoomState = {};
            chart.__chartTimeWindow = null;
            if (chart.options?.scales?.x) {
                delete chart.options.scales.x.min;
                delete chart.options.scales.x.max;
            }
            const mode = document.documentElement.classList.contains('perf-mode') ? 'none' : 'default';
            try { chart.resetZoom?.(mode); } catch { /* plugin missing */ }
        }

        function toggleEmptyState(isEmpty) {
            const canvas = opts.canvasId ? document.getElementById(opts.canvasId) : null;
            const wrapper = canvas?.parentElement;
            if (!wrapper) return;
            let el = wrapper.querySelector('.chart-range-empty');
            if (isEmpty) {
                if (!el) {
                    el = document.createElement('div');
                    el.className = 'chart-range-empty';
                    wrapper.appendChild(el);
                }
                el.textContent = t('web_chart_range_no_data', 'No data for this period yet');
                el.classList.add('is-visible');
            } else if (el) {
                el.classList.remove('is-visible');
            }
        }

        function buildSeries() {
            const pts = ctl.points;
            const span = ctl.range.seconds;
            const step = ctl.step;
            const gap = step ? step * 1.5 : RAW_GAP_SECONDS;
            const series = {
                range: ctl.range.key,
                step,
                span,
                points: pts,
                isLive: span <= LIVE_MAX_SECONDS,
                minIndex: 0,
                maxIndex: -1,
                labels: [], cpu: [], ram: [], disk: [], rx: [], tx: [], ping: []
            };
            const cutoff = ctl.serverNow - span;
            if (opts.network && span >= 3 * 86400) {
                const buckets = new Map(pts.map(point => [Math.floor(point.t / 300), point]));
                for (let timestamp = cutoff; timestamp <= ctl.serverNow; timestamp += 300) {
                    const point = buckets.get(Math.floor(timestamp / 300));
                    series.labels.push(formatLabel(timestamp, span));
                    series.rx.push(point?.rx != null ? point.rx * 8 / 1024 : null);
                    series.tx.push(point?.tx != null ? point.tx * 8 / 1024 : null);
                    series.ping.push(point?.ping ?? null);
                    series.cpu.push(null);
                    series.ram.push(null);
                    series.disk.push(null);
                }
                series.maxIndex = series.labels.length - 1;
                return series;
            }
            let viewportStarted = false;
            for (let i = 0; i < pts.length; i++) {
                const p = pts[i];
                if (i > 0 && p.t - pts[i - 1].t > gap) {
                    series.labels.push('');
                    series.cpu.push(null);
                    series.ram.push(null);
                    series.disk.push(null);
                    series.rx.push(null);
                    series.tx.push(null);
                    series.ping.push(null);
                }
                if (!viewportStarted && p.t >= cutoff) {
                    series.minIndex = series.labels.length;
                    viewportStarted = true;
                }
                series.labels.push(formatLabel(p.t, span));
                series.cpu.push(p.c);
                series.ram.push(p.r);
                series.disk.push(p.d);
                series.rx.push(p.rx != null ? p.rx * 8 / 1024 : null);
                series.tx.push(p.tx != null ? p.tx * 8 / 1024 : null);
                series.ping.push(p.ping ?? null);
            }
            series.maxIndex = series.labels.length - 1;
            return series;
        }

        function emit(animate = true) {
            if (ctl.destroyed) return;
            const hasData = opts.network
                ? ctl.points.some(point => point.rx != null || point.tx != null || point.ping != null)
                : ctl.points.length >= 2;
            toggleEmptyState(!ctl.loading && !hasData);
            if (typeof opts.render === 'function') {
                try {
                    opts.render(buildSeries(), animate);
                } catch (e) {
                    console.error('Chart range render error:', e);
                }
            }
        }

        function mergePoints(payload, incoming, incremental) {
            ctl.step = payload.step || 0;
            ctl.span = payload.span || ctl.range.seconds;
            ctl.serverNow = payload.now || Math.floor(Date.now() / 1000);
            if (incremental && incoming.length) {
                const since = incoming[0].t;
                ctl.points = ctl.points.filter(p => p.t < since).concat(incoming);
            } else if (!incremental) {
                ctl.points = incoming;
            }
            // Keep earlier live points so advancing the viewport does not reassign
            // every existing chart point to a different sample on each tick.
            let cutoff = ctl.serverNow - ctl.span * 3;
            if (opts.network && ctl.span >= 3 * 86400) {
                cutoff = Math.floor((ctl.serverNow - ctl.span) / 300) * 300;
            }
            if (ctl.points.length && ctl.points[0].t < cutoff) {
                ctl.points = ctl.points.filter(p => p.t >= cutoff);
            }
        }

        function pointsEqual(left, right) {
            if (left.length !== right.length) return false;
            for (let i = 0; i < left.length; i++) {
                const a = left[i];
                const b = right[i];
                if (a.t !== b.t || a.c !== b.c || a.r !== b.r || a.d !== b.d || a.rx !== b.rx || a.tx !== b.tx || a.ping !== b.ping) {
                    return false;
                }
            }
            return true;
        }

        function metricValuesChanged(previous, next) {
            if (!previous.length) return next.length > 0;
            const getValues = typeof opts.getValues === 'function'
                ? opts.getValues
                : point => [point.c, point.r, point.d, point.rx, point.tx, point.ping];
            const previousByTime = new Map(previous.map(point => [point.t, point]));
            let preceding = previous[previous.length - 1];

            for (const point of next) {
                const sameTime = previousByTime.get(point.t);
                const comparison = sameTime || (point.t > preceding.t ? preceding : null);
                if (comparison) {
                    const oldValues = getValues(comparison);
                    const newValues = getValues(point);
                    if (oldValues.length !== newValues.length || oldValues.some((value, index) => !Object.is(value, newValues[index]))) {
                        return true;
                    }
                }
                if (point.t > preceding.t) preceding = point;
            }
            return false;
        }

        function decodeHistory(payload) {
            const raw = payload.data;
            if (!raw) return null;
            const text = typeof window.decryptData === 'function' ? window.decryptData(raw)
                : (typeof decryptData === 'function' ? decryptData(raw) : raw);
            try {
                return JSON.parse(text);
            } catch (e) {
                console.debug('Chart range payload decode failed:', e);
                return null;
            }
        }

        function closeStream() {
            clearTimeout(ctl.reconnectTimer);
            ctl.reconnectTimer = null;
            if (ctl.stream) {
                ctl.stream.close();
                ctl.stream = null;
            }
        }

        function openStream() {
            closeStream();
            if (ctl.destroyed || !ctl.running || typeof EventSource === 'undefined') return;
            if (mount && !mount.isConnected) {
                // The page was swapped by the SPA navigation; stop streaming for a dead widget.
                ctl.stop();
                return;
            }
            const src = sourceParams();
            if (!src) return;

            const params = new URLSearchParams({ source: src.source, range: ctl.range.key });
            if (src.node_id) params.set('node_id', String(src.node_id));
            if (opts.network) {
                params.set('metric', 'network');
                if (ctl.interfaceName) params.set('interface', ctl.interfaceName);
            }
            const rangeKey = ctl.range.key;
            const es = new EventSource(`${STREAM_URL}?${params.toString()}`);
            ctl.stream = es;

            es.addEventListener('metrics_history', (event) => {
                if (ctl.stream !== es) return;
                try {
                    const payload = JSON.parse(event.data);
                    if (payload.range !== rangeKey) return;
                    const history = decodeHistory(payload);
                    const points = Array.isArray(history) ? history : history?.points;
                    if (!Array.isArray(points)) return;
                    const wasLoading = ctl.loading;
                    const previousStep = ctl.step;
                    const previousNow = ctl.serverNow;
                    const previousPoints = ctl.points;
                    ctl.loading = false;
                    mergePoints(payload, points, !payload.full);
                    if (Array.isArray(history.interfaces)) syncInterfaces(history.interfaces);
                    if (previousStep !== ctl.step) syncButton();
                    if (wasLoading || !pointsEqual(previousPoints, ctl.points) || (opts.network && ctl.range.seconds >= 3 * 86400 && previousNow !== ctl.serverNow)) {
                        emit(wasLoading || metricValuesChanged(previousPoints, ctl.points));
                    }
                } catch (e) {
                    console.error('Chart range stream parse error:', e);
                }
            });

            es.addEventListener('session_status', (event) => {
                if (event.data === 'expired') {
                    ctl.stop();
                    window.location.assign('/login');
                }
            });

            es.addEventListener('shutdown', () => {
                closeStream();
                scheduleReconnect(15000);
            });

            es.onerror = () => {
                // EventSource retries transient errors itself; a CLOSED state means the server refused the stream.
                if (ctl.stream === es && es.readyState === EventSource.CLOSED) {
                    closeStream();
                    scheduleReconnect(RECONNECT_DELAY);
                }
            };
        }

        function scheduleReconnect(delay) {
            clearTimeout(ctl.reconnectTimer);
            if (!ctl.running || ctl.destroyed) return;
            ctl.reconnectTimer = setTimeout(() => {
                if (ctl.running && !ctl.destroyed && !document.hidden) openStream();
            }, delay);
        }

        function setRange(key) {
            const next = findRange(key);
            if (!next) return;
            const changed = next.key !== ctl.range.key;
            ctl.range = next;
            writeStored(storageKey, next.key);
            if (!changed) return;
            reloadSeries();
            if (typeof opts.onRangeChange === 'function') opts.onRangeChange(next.key);
        }

        function reloadSeries() {
            ctl.points = [];
            ctl.step = 0;
            ctl.loading = true;
            syncButton();
            resetChartZoom();
            emit();
            if (ctl.running) openStream();
        }

        function onVisibility() {
            if (!ctl.running) return;
            // Hidden tabs drop the stream to save server work; it is re-opened with a fresh snapshot.
            if (document.hidden) closeStream();
            else if (!ctl.stream) openStream();
        }

        /* ---------- public API ---------- */
        ctl.start = function () {
            if (ctl.destroyed) return ctl;
            ctl.running = true;
            document.addEventListener('visibilitychange', onVisibility);
            openStream();
            return ctl;
        };

        ctl.stop = function () {
            ctl.running = false;
            closeStream();
            document.removeEventListener('visibilitychange', onVisibility);
            ctl.closePopover();
            return ctl;
        };

        ctl.reset = function () {
            ctl.points = [];
            ctl.step = 0;
            ctl.loading = true;
            if (ctl.running) openStream();
            return ctl;
        };

        ctl.refresh = function () {
            if (ctl.running) openStream();
            return ctl;
        };

        ctl.setRange = function (key) {
            setRange(key);
            return ctl;
        };

        ctl.setInterface = function (name) {
            if (ctl.interfaceName === name) return ctl;
            ctl.interfaceName = name;
            syncInterfaces(ctl.interfaces);
            reloadSeries();
            if (typeof opts.onInterfaceChange === 'function') opts.onInterfaceChange(name);
            return ctl;
        };

        ctl.getInterface = () => ctl.interfaceName;

        ctl.getRange = function () {
            return ctl.range.key;
        };

        ctl.destroy = function () {
            ctl.stop();
            ctl.destroyed = true;
            ctl.pop?.remove();
            ctl.pop = null;
            if (mount) {
                mount.innerHTML = '';
                mount.classList.remove('chart-range');
            }
        };

        buildButton();
        return ctl;
    }

    window.createChartRangeController = createChartRangeController;
    window.networkHistoryPointRadius = ctx => {
        if (!ctx || !ctx.dataset || !Array.isArray(ctx.dataset.data) || typeof ctx.dataIndex !== 'number') {
            return 0;
        }
        const { dataset, dataIndex } = ctx;
        return dataset.data[dataIndex - 1] == null && dataset.data[dataIndex + 1] == null ? 3 : 0;
    };
    window.createPingDataset = data => ({
        label: t('web_label_ping', 'Ping'),
        data,
        yAxisID: 'ping',
        borderColor: '#ef4444',
        backgroundColor: '#ef4444',
        borderWidth: 2,
        fill: false,
        spanGaps: false,
        animations: {
            y: {
                from: ctx => {
                    if (ctx && ctx.type === 'data') {
                        if (ctx.element?.$animations) {
                            return undefined;
                        }
                        const points = ctx.dataset?.data;
                        const scale = ctx.chart?.scales?.[ctx.dataset?.yAxisID || 'ping'];
                        if (points && scale) {
                            for (let i = ctx.dataIndex - 1; i >= 0; i--) {
                                const val = points[i];
                                if (typeof val === 'number' && !isNaN(val)) {
                                    return scale.getPixelForValue(val);
                                }
                            }
                            if (typeof ctx.raw === 'number' && !isNaN(ctx.raw)) {
                                return scale.getPixelForValue(ctx.raw);
                            }
                        }
                    }
                    return undefined;
                }
            }
        }
    });
    window.createPingScale = color => ({
        position: 'left',
        beginAtZero: true,
        title: { display: true, text: 'ms', color },
        ticks: { color },
        grid: { drawOnChartArea: false }
    });
    window.CHART_RANGES = RANGES.map(r => r.key);

    /* ---------- Chart Modal Expansion ---------- */
    let activeExpandedChart = null;

    function createExpandedGradient(color) {
        const fillColor = Chart.helpers.color(color);
        const topColor = fillColor.alpha(0.5).rgbString();
        // Keep the fill visible near zero, where CPU usage often sits.
        const bottomColor = fillColor.alpha(0.25).rgbString();
        let gradient, gradientTop, gradientBottom;

        return ({ chart: { ctx, chartArea } }) => {
            if (!chartArea || chartArea.bottom <= chartArea.top) return bottomColor;
            const { top, bottom } = chartArea;
            if (top !== gradientTop || bottom !== gradientBottom) {
                gradient = ctx.createLinearGradient(0, top, 0, bottom);
                gradient.addColorStop(0, topColor);
                gradient.addColorStop(1, bottomColor);
                gradientTop = top;
                gradientBottom = bottom;
            }
            return gradient;
        };
    }

    function expandChartToModal(canvasId, overlayId) {
        const sourceCanvas = document.getElementById(canvasId);
        if (!sourceCanvas) return;

        const sourceChart = (typeof Chart !== 'undefined' ? Chart.getChart(sourceCanvas) : null)
            || window.__chartRegistry?.[canvasId]
            || window[canvasId];
        if (!sourceChart || !sourceChart.data) return;

        const overlay = overlayId
            ? document.getElementById(overlayId)
            : sourceCanvas.closest('.rounded-2xl')?.querySelector('.chart-expanded-overlay');
        if (!overlay) return;

        if (activeExpandedChart) {
            collapseChartModal();
        }

        const body = overlay.querySelector('.chart-expanded-body');
        if (!body) return;

        const dialog = overlay.closest('.rounded-2xl');
        const originalMinHeight = dialog ? dialog.style.minHeight : '';
        const originalHeight = dialog ? dialog.style.height : '';

        if (dialog) {
            dialog.style.minHeight = '480px';
            if (window.innerWidth >= 640) {
                dialog.style.height = '75vh';
            }
        }

        overlay.classList.add('is-active');
        overlay.classList.remove('hidden');

        // Clean & create fresh canvas element inside expanded body
        body.innerHTML = '<canvas style="display:block;width:100%;height:100%;"></canvas>';
        const expandedCanvas = body.querySelector('canvas');
        const expandedCtx = expandedCanvas.getContext('2d');

        const isDark = document.documentElement.classList.contains('dark');
        const tickColor = isDark ? '#9ca3af' : '#6b7280';

        // Resolve each gradient after the expanded chart has laid out its plot area.
        const datasets = sourceChart.data.datasets.map(ds => {
            const copy = { ...ds };
            if (copy.fill) {
                const color = (typeof copy.borderColor === 'string' && copy.borderColor)
                    || (typeof copy.backgroundColor === 'string' && copy.backgroundColor);
                if (color) {
                    copy.backgroundColor = createExpandedGradient(color);
                }
            }
            return copy;
        });

        const baseOptions = sourceChart.config?.options || sourceChart.options || {};

        // Sanitize scales to avoid passing resolver proxies (which trigger Chart.js warnings)
        const sanitizedScales = {};
        const rawScales = baseOptions.scales || {};
        for (const [key, val] of Object.entries(rawScales)) {
            if (val && typeof val === 'object') {
                const s = { ...val };
                if (s.ticks && typeof s.ticks === 'object') s.ticks = { ...s.ticks };
                if (s.grid && typeof s.grid === 'object') s.grid = { ...s.grid };
                if (s.title && typeof s.title === 'object') s.title = { ...s.title };
                delete s._proxy;
                delete s._context;
                delete s._subProxy;
                delete s._stack;
                delete s._descriptors;
                sanitizedScales[key] = s;
            }
        }

        const options = {
            ...baseOptions,
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: sanitizedScales,
            layout: {
                ...(baseOptions.layout || {}),
                padding: {
                    ...(baseOptions.layout?.padding || {}),
                    top: 6,
                    right: 8
                }
            },
            plugins: {
                ...(baseOptions.plugins || {}),
                legend: {
                    ...(baseOptions.plugins?.legend || {}),
                    display: true,
                    labels: {
                        ...(baseOptions.plugins?.legend?.labels || {}),
                        color: tickColor
                    }
                }
            }
        };

        const expandedChart = new Chart(expandedCtx, {
            type: sourceChart.config.type || 'line',
            data: {
                labels: [...(sourceChart.data.labels || [])],
                datasets
            },
            options
        });

        if (sourceChart.__chartTimeWindow) {
            expandedChart.__chartTimeWindow = { ...sourceChart.__chartTimeWindow };
        }

        activeExpandedChart = {
            canvasId,
            sourceChart,
            expandedChart,
            overlay,
            dialog,
            originalMinHeight,
            originalHeight
        };
        window.__activeExpandedChart = activeExpandedChart;

        if (window.attachChartInteractions) {
            window.attachChartInteractions(expandedChart, expandedCanvas);
        }
    }

    function collapseChartModal(overlayId) {
        if (!activeExpandedChart) {
            if (overlayId) {
                const overlay = document.getElementById(overlayId);
                if (overlay) {
                    overlay.classList.remove('is-active');
                    overlay.classList.add('hidden');
                }
            }
            return;
        }

        const { expandedChart, overlay, dialog, originalMinHeight, originalHeight } = activeExpandedChart;

        if (expandedChart) {
            try {
                expandedChart.destroy();
            } catch (_) {}
        }

        const body = overlay?.querySelector('.chart-expanded-body');
        if (body) {
            body.innerHTML = '';
        }

        if (dialog) {
            dialog.style.minHeight = originalMinHeight;
            dialog.style.height = originalHeight;
        }

        if (overlay) {
            overlay.classList.remove('is-active');
            overlay.classList.add('hidden');
        }

        activeExpandedChart = null;
        window.__activeExpandedChart = null;
    }

    function syncActiveExpandedChart(sourceChart) {
        if (!activeExpandedChart || !activeExpandedChart.expandedChart) return;
        if (activeExpandedChart.sourceChart !== sourceChart) return;
        const exp = activeExpandedChart.expandedChart;
        exp.data.labels = [...(sourceChart.data.labels || [])];
        sourceChart.data.datasets.forEach((ds, i) => {
            if (exp.data.datasets[i]) {
                exp.data.datasets[i].data = [...(ds.data || [])];
            }
        });
        if (sourceChart.__chartTimeWindow) {
            exp.__chartTimeWindow = { ...sourceChart.__chartTimeWindow };
        }
        if (!exp.__liveZoomState?.isZoomed) {
            window.alignChartToLiveWindow?.(exp);
        }
        exp.update('none');
        window.refreshChartZoomState?.(exp);
    }

    window.syncActiveExpandedChart = syncActiveExpandedChart;
    window.expandChartToModal = expandChartToModal;
    window.collapseChartModal = collapseChartModal;

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-expand-chart]');
        if (!btn) return;
        e.preventDefault();
        e.stopPropagation();
        const canvasId = btn.getAttribute('data-expand-chart');
        expandChartToModal(canvasId);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activeExpandedChart) {
            e.preventDefault();
            e.stopPropagation();
            collapseChartModal();
        }
    }, true);
})();
