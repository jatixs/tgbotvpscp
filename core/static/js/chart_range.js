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
        } catch (e) {
            return null;
        }
    }

    function writeStored(key, value) {
        try {
            localStorage.setItem(`chartRange:${key}`, value);
        } catch (e) { /* storage disabled */ }
    }

    let openController = null;

    document.addEventListener('click', (e) => {
        if (!openController) return;
        if (openController.pop?.contains(e.target) || openController.button?.contains(e.target)) return;
        openController.closePopover();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && openController) openController.closePopover();
    });
    window.addEventListener('resize', () => openController?.closePopover());
    window.addEventListener('scroll', () => openController?.closePopover(), true);

    function createChartRangeController(opts) {
        const mount = typeof opts.mount === 'string' ? document.querySelector(opts.mount) : opts.mount;
        const storageKey = opts.key || opts.canvasId || 'chart';
        const ctl = {
            range: findRange(opts.initialRange || readStored(storageKey) || DEFAULT_RANGE),
            points: [],
            step: 0,
            span: 0,
            serverNow: 0,
            running: false,
            destroyed: false,
            stream: null,
            reconnectTimer: null,
            loading: true,
            pop: null,
            button: null,
            mount
        };

        /* ---------- UI ---------- */
        function buildButton() {
            if (!mount) return;
            mount.classList.add('chart-range');
            mount.innerHTML = `
                <button type="button" class="chart-range-btn" aria-haspopup="listbox" aria-expanded="false" title="${t('web_chart_range_title', 'Chart period')}">
                    <span class="chart-range-live" aria-hidden="true"></span>
                    ${CLOCK_ICON}
                    <span class="chart-range-label"></span>
                    ${CHEVRON_ICON}
                </button>`;
            ctl.button = mount.querySelector('.chart-range-btn');
            ctl.button.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (ctl.pop?.classList.contains('is-open')) ctl.closePopover();
                else openPopover();
            });
            syncButton();
        }

        function syncButton() {
            if (!ctl.button) return;
            const label = ctl.button.querySelector('.chart-range-label');
            if (label) label.textContent = rangeLabel(ctl.range);
            ctl.button.classList.toggle('is-live', ctl.range.seconds <= LIVE_MAX_SECONDS);
            if (ctl.pop) {
                ctl.pop.querySelectorAll('.chart-range-chip').forEach(chip => {
                    chip.classList.toggle('is-active', chip.dataset.range === ctl.range.key);
                    chip.setAttribute('aria-selected', chip.dataset.range === ctl.range.key ? 'true' : 'false');
                });
                const foot = ctl.pop.querySelector('.chart-range-foot');
                if (foot) foot.innerHTML = footHtml();
            }
        }

        function footHtml() {
            const isLive = ctl.range.seconds <= LIVE_MAX_SECONDS;
            const stepText = ctl.step ? `${t('web_chart_range_step', 'Step')}: ${stepLabel(ctl.step)}` : '';
            if (isLive) {
                return `<span class="chart-range-foot-live"><span class="chart-range-live"></span>${t('web_chart_range_live', 'Live')}</span>${stepText ? `<span>${stepText}</span>` : ''}`;
            }
            return `<span>${stepText || rangeLabel(ctl.range)}</span>`;
        }

        function buildPopover() {
            const pop = document.createElement('div');
            pop.className = 'chart-range-pop';
            pop.setAttribute('role', 'listbox');
            const groups = GROUPS.map(group => {
                const chips = RANGES.filter(r => r.group === group).map(r =>
                    `<button type="button" class="chart-range-chip" role="option" data-range="${r.key}">${rangeLabel(r)}</button>`
                ).join('');
                return `<div class="chart-range-group"><span class="chart-range-group-label">${groupLabel(group)}</span><div class="chart-range-chips">${chips}</div></div>`;
            }).join('');
            pop.innerHTML = `<div class="chart-range-pop-title">${t('web_chart_range_title', 'Chart period')}</div>${groups}<div class="chart-range-foot"></div>`;
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
            const rect = ctl.button.getBoundingClientRect();
            const pop = ctl.pop;
            const margin = 8;
            const popRect = pop.getBoundingClientRect();
            let left = rect.right - popRect.width;
            left = Math.max(margin, Math.min(left, window.innerWidth - popRect.width - margin));
            let top = rect.bottom + 6;
            let openUp = false;
            if (top + popRect.height > window.innerHeight - margin && rect.top - popRect.height - 6 > margin) {
                top = rect.top - popRect.height - 6;
                openUp = true;
            }
            pop.style.left = `${Math.round(left)}px`;
            pop.style.top = `${Math.round(top)}px`;
            pop.classList.toggle('is-up', openUp);
        }

        function openPopover() {
            if (ctl.destroyed) return;
            if (openController && openController !== ctl) openController.closePopover();
            if (!ctl.pop) buildPopover();
            syncButton();
            positionPopover();
            requestAnimationFrame(() => ctl.pop?.classList.add('is-open'));
            ctl.button?.setAttribute('aria-expanded', 'true');
            ctl.button?.classList.add('is-open');
            openController = ctl;
        }

        ctl.closePopover = function () {
            if (ctl.pop) ctl.pop.classList.remove('is-open');
            ctl.button?.setAttribute('aria-expanded', 'false');
            ctl.button?.classList.remove('is-open');
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
            if (chart.options?.scales?.x) {
                delete chart.options.scales.x.min;
                delete chart.options.scales.x.max;
            }
            const mode = document.documentElement.classList.contains('perf-mode') ? 'none' : 'default';
            try { chart.resetZoom?.(mode); } catch (e) { /* plugin missing */ }
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
                labels: [], cpu: [], ram: [], disk: [], rx: [], tx: []
            };
            for (let i = 0; i < pts.length; i++) {
                const p = pts[i];
                if (i > 0 && p.t - pts[i - 1].t > gap) {
                    series.labels.push('');
                    series.cpu.push(null);
                    series.ram.push(null);
                    series.disk.push(null);
                    series.rx.push(null);
                    series.tx.push(null);
                }
                series.labels.push(formatLabel(p.t, span));
                series.cpu.push(p.c);
                series.ram.push(p.r);
                series.disk.push(p.d);
                series.rx.push(p.rx * 8 / 1024);
                series.tx.push(p.tx * 8 / 1024);
            }
            return series;
        }

        function emit(animate = true) {
            if (ctl.destroyed) return;
            toggleEmptyState(!ctl.loading && ctl.points.length < 2);
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
            const cutoff = ctl.serverNow - ctl.span;
            if (ctl.points.length && ctl.points[0].t < cutoff) {
                ctl.points = ctl.points.filter(p => p.t >= cutoff);
            }
        }

        function pointsEqual(left, right) {
            if (left.length !== right.length) return false;
            for (let i = 0; i < left.length; i++) {
                const a = left[i];
                const b = right[i];
                if (a.t !== b.t || a.c !== b.c || a.r !== b.r || a.d !== b.d || a.rx !== b.rx || a.tx !== b.tx) {
                    return false;
                }
            }
            return true;
        }

        function metricValuesChanged(previous, next) {
            if (!previous.length) return next.length > 0;
            const getValues = typeof opts.getValues === 'function'
                ? opts.getValues
                : point => [point.c, point.r, point.d, point.rx, point.tx];
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

        function decodePoints(payload) {
            const raw = payload.data;
            if (!raw) return [];
            const text = typeof window.decryptData === 'function' ? window.decryptData(raw)
                : (typeof decryptData === 'function' ? decryptData(raw) : raw);
            try {
                const parsed = JSON.parse(text);
                return Array.isArray(parsed) ? parsed : [];
            } catch (e) {
                console.debug('Chart range payload decode failed:', e);
                return [];
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
            const rangeKey = ctl.range.key;
            const es = new EventSource(`${STREAM_URL}?${params.toString()}`);
            ctl.stream = es;

            es.addEventListener('metrics_history', (event) => {
                if (ctl.stream !== es) return;
                try {
                    const payload = JSON.parse(event.data);
                    if (payload.range !== rangeKey) return;
                    const wasLoading = ctl.loading;
                    const previousPoints = ctl.points;
                    ctl.loading = false;
                    mergePoints(payload, decodePoints(payload), !payload.full);
                    if (wasLoading || !pointsEqual(previousPoints, ctl.points)) {
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
            syncButton();
            if (!changed) return;
            ctl.points = [];
            ctl.step = 0;
            ctl.loading = true;
            resetChartZoom();
            if (typeof opts.onRangeChange === 'function') opts.onRangeChange(next.key);
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
    window.CHART_RANGES = RANGES.map(r => r.key);
})();
