let chartRes = null;
let chartNet = null;
let pollInterval = null;
let agentChart = null;
let agentPollInterval = null;
let nodesPollInterval = null;
let logPollInterval = null;

window.addEventListener('themeChanged', () => { updateChartsColors(); });

document.addEventListener("DOMContentLoaded", () => {
    if(document.getElementById('agentChart')) {
        fetchAgentStats();
        agentPollInterval = setInterval(fetchAgentStats, 3000);
    }
    if (document.getElementById('nodesList')) {
        fetchNodesList();
        nodesPollInterval = setInterval(fetchNodesList, 3000);
    }
    if (document.getElementById('notifList')) {
        loadNotifications();
        setInterval(loadNotifications, 5000);
        const clearBtn = document.getElementById('notifClearBtn');
        if (clearBtn) clearBtn.addEventListener('click', clearNotifications);
        const notifBtn = document.getElementById('notifBtn');
        if (notifBtn) notifBtn.addEventListener('click', () => {
            const drop = document.getElementById('notifDropdown');
            drop.classList.toggle('hidden');
            if (!drop.classList.contains('hidden')) readNotifications();
        });
    }
    const inputDash = document.getElementById('newNodeNameDash');
    if (inputDash) {
        inputDash.addEventListener('input', validateNodeInput);
        inputDash.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !document.getElementById('btnAddNodeDash').disabled) addNodeDash();
        });
    }
    if (document.getElementById('logsContainer')) switchLogType('bot');
});

function escapeHtml(text) { return text ? text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;") : text; }

async function fetchNodesList() {
    try {
        const response = await fetch('/api/nodes/list');
        const data = await response.json();
        renderNodesList(data.nodes);
        const totalEl = document.getElementById('nodesTotal'), activeEl = document.getElementById('nodesActive');
        if (totalEl) totalEl.innerText = data.nodes.length;
        if (activeEl) activeEl.innerText = data.nodes.filter(n => n.status === 'online').length;
    } catch (e) { console.error("Nodes list error:", e); }
}

function renderNodesList(nodes) {
    const container = document.getElementById('nodesList');
    if (!container) return;
    if (nodes.length === 0) { container.innerHTML = `<div class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">${I18N.web_no_nodes}</div>`; return; }
    const html = nodes.map(node => {
        let sc = "bg-green-500", st = "ONLINE";
        if (node.status === 'restarting') { sc = "bg-yellow-500"; st = "RESTARTING"; }
        else if (node.status === 'offline') { sc = "bg-red-500"; st = "OFFLINE"; }
        return `<div class="bg-gray-50 dark:bg-black/20 hover:bg-gray-100 dark:hover:bg-black/30 transition p-3 rounded-xl border border-gray-100 dark:border-white/5 cursor-pointer flex justify-between items-center group" onclick="openNodeDetails('${escapeHtml(node.token)}', '${sc}')">
            <div class="flex items-center gap-3"><div class="relative"><div class="w-2.5 h-2.5 rounded-full ${sc}"></div><div class="absolute inset-0 w-2.5 h-2.5 rounded-full ${sc} animate-ping opacity-75"></div></div>
            <div><div class="font-bold text-sm text-gray-900 dark:text-white group-hover:text-blue-500 transition">${escapeHtml(node.name)}</div><div class="text-[10px] font-mono text-gray-400">${escapeHtml(node.ip)}</div></div></div>
            <div class="text-right"><div class="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-0.5">${st}</div><div class="text-[10px] text-gray-500 font-mono">CPU: ${Math.round(node.cpu)}%</div></div></div>`;
    }).join('');
    if (container.innerHTML !== html) container.innerHTML = html;
}

async function fetchAgentStats() {
    try {
        const response = await fetch('/api/agent/stats');
        const data = await response.json();
        if(data.stats) {
            ['cpu','ram','disk'].forEach(m => {
                const el = document.getElementById('stat_'+m), pr = document.getElementById('prog_'+m);
                if (el) el.innerText = Math.round(data.stats[m]) + "%";
                if (pr) pr.style.width = data.stats[m] + "%";
            });
            if (document.getElementById('stat_net_recv')) {
                document.getElementById('stat_net_recv').innerText = formatBytes(data.stats.net_recv);
                document.getElementById('stat_net_sent').innerText = formatBytes(data.stats.net_sent);
                const ut = document.getElementById('stat_uptime');
                if(ut) ut.innerText = formatUptime(data.stats.boot_time);
                const ip = document.getElementById('agentIp');
                if(ip && data.stats.ip) ip.innerText = data.stats.ip;
            }
        }
        renderAgentChart(data.history);
    } catch (e) { console.error("Stats error:", e); }
}

function updateChartsColors() {
    const isDark = document.documentElement.classList.contains('dark'), gc = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)', tc = isDark ? '#9ca3af' : '#6b7280';
    [agentChart, chartRes, chartNet].forEach(c => { if (c) {
        if (c.options.scales.x) { c.options.scales.x.grid.color = gc; c.options.scales.x.ticks.color = tc; }
        if (c.options.scales.y) { c.options.scales.y.grid.color = gc; c.options.scales.y.ticks.color = tc; }
        if (c.options.plugins.legend) c.options.plugins.legend.labels.color = tc;
        c.update();
    }});
}

function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    const labels = [], tp = history.length;
    for(let i=0; i<tp; i++) { const sa = (tp - 1 - i) * 2; labels.push(sa % 20 === 0 || i === tp-1 ? `-${sa}s` : ""); }
    const rx = [], tx = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1;
        rx.push(((history[i].rx - history[i-1].rx) * 8 / dt / 1024));
        tx.push(((history[i].tx - history[i-1].tx) * 8 / dt / 1024));
    }
    const ctx = document.getElementById('agentChart').getContext('2d'), isDark = document.documentElement.classList.contains('dark'), gc = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)', tc = isDark ? '#9ca3af' : '#6b7280';
    if (agentChart) {
        agentChart.data.labels = labels.slice(1); agentChart.data.datasets[0].data = rx; agentChart.data.datasets[1].data = tx;
        agentChart.update();
    } else {
        agentChart = new Chart(ctx, { type: 'line', data: { labels: labels.slice(1), datasets: [
            { label: 'RX (In)', data: rx, borderColor: '#22c55e', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(34, 197, 94, 0.1)', tension: 0.3 },
            { label: 'TX (Out)', data: tx, borderColor: '#3b82f6', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(59, 130, 246, 0.1)', tension: 0.3 }
        ]}, options: { responsive: true, maintainAspectRatio: false, animation: false, elements: { point: { radius: 0 } }, scales: { x: { grid: { color: gc }, ticks: { color: tc, font: {size: 9} } }, y: { position: 'right', grid: { color: gc }, ticks: { color: tc, font: {size: 9}, callback: v => formatSpeed(v) } } }, plugins: { legend: { labels: { color: tc, font: {size: 10} } } } } });
    }
}

function formatSpeed(v) { let val = parseFloat(v); if (isNaN(val)) return '0 Kbit/s'; if (val >= 1048576) return (val/1048576).toFixed(2)+' Gbit/s'; if (val >= 1024) return (val/1024).toFixed(2)+' Mbit/s'; return val.toFixed(2)+' Kbit/s'; }

function formatBytes(bytes, decimals = 2) {
    const sizes = (typeof I18N !== 'undefined' && I18N.unit_bytes) ? [I18N.unit_bytes, I18N.unit_kb, I18N.unit_mb, I18N.unit_gb, I18N.unit_tb, I18N.unit_pb] : ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
    if (!+bytes) return '0 ' + sizes[0];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${parseFloat((bytes / Math.pow(1024, i)).toFixed(decimals < 0 ? 0 : decimals))} ${sizes[i]}`;
}

function formatUptime(bt) {
    if (!bt) return "...";
    const d = (Date.now()/1000 - bt), days = Math.floor(d/86400), hours = Math.floor((d%86400)/3600), mins = Math.floor((d%3600)/60);
    const ds = I18N.web_time_d||'d', hs = I18N.web_time_h||'h', ms = I18N.web_time_m||'m';
    return days > 0 ? `${days}${ds} ${hours}${hs}` : `${hours}${hs} ${mins}${ms}`;
}

async function openNodeDetails(token, dotColor) {
    const modal = document.getElementById('nodeModal'); modal.classList.remove('hidden'); modal.classList.add('flex'); document.body.style.overflow = 'hidden';
    if (chartRes) { chartRes.destroy(); chartRes = null; } if (chartNet) { chartNet.destroy(); chartNet = null; }
    await fetchAndRender(token); if (pollInterval) clearInterval(pollInterval); pollInterval = setInterval(() => fetchAndRender(token), 3000);
}

async function fetchAndRender(token) {
    try {
        const r = await fetch(`/api/node/details?token=${token}`), d = await r.json();
        if (d.error) { if (pollInterval) clearInterval(pollInterval); return; }
        document.getElementById('modalNodeName').innerText = d.name || 'Unknown';
        document.getElementById('modalNodeIp').innerText = d.ip || 'Unknown';
        const tok = document.getElementById('modalToken'); if(tok) tok.innerText = d.token || token;
        renderCharts(d.history);
    } catch (e) { console.error("Details error:", e); }
}

function closeNodeModal() {
    const m = document.getElementById('nodeModal'); m.classList.add('hidden'); m.classList.remove('flex'); document.body.style.overflow = 'auto';
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

function renderCharts(history) {
    if (!history || history.length < 2) return;
    const labels = history.map(h => new Date(h.t * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})), cpu = history.map(h => h.c), ram = history.map(h => h.r);
    const rx = [], tx = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1;
        rx.push(((history[i].rx - history[i-1].rx) * 8 / dt / 1024));
        tx.push(((history[i].tx - history[i-1].tx) * 8 / dt / 1024));
    }
    const nl = labels.slice(1), isDark = document.documentElement.classList.contains('dark'), gc = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)', tc = isDark ? '#9ca3af' : '#6b7280';
    const opts = { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false }, scales: { y: { beginAtZero: true, grid: { color: gc }, ticks: { color: tc, font: {size: 10} } }, x: { display: false } }, plugins: { legend: { labels: { color: tc, font: {size: 11}, boxWidth: 10 } } } };
    const ctxRes = document.getElementById('nodeResChart').getContext('2d');
    if (chartRes) { chartRes.data.labels = labels; chartRes.data.datasets[0].data = cpu; chartRes.data.datasets[1].data = ram; chartRes.update(); }
    else chartRes = new Chart(ctxRes, { type: 'line', data: { labels, datasets: [{ label: 'CPU (%)', data: cpu, borderColor: '#3b82f6', tension: 0.3, borderWidth: 2, pointRadius: 0 }, { label: 'RAM (%)', data: ram, borderColor: '#a855f7', tension: 0.3, borderWidth: 2, pointRadius: 0 }] }, options: { ...opts, scales: { ...opts.scales, y: { ...opts.scales.y, max: 100 } } } });
    const ctxNet = document.getElementById('nodeNetChart').getContext('2d');
    if (chartNet) { chartNet.data.labels = nl; chartNet.data.datasets[0].data = rx; chartNet.data.datasets[1].data = tx; chartNet.update(); }
    else chartNet = new Chart(ctxNet, { type: 'line', data: { labels: nl, datasets: [{ label: 'RX (In)', data: rx, borderColor: '#22c55e', backgroundColor: 'rgba(34, 197, 94, 0.1)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: 0 }, { label: 'TX (Out)', data: tx, borderColor: '#ef4444', tension: 0.3, borderWidth: 2, pointRadius: 0 }] }, options: { ...opts, scales: { ...opts.scales, y: { ...opts.scales.y, ticks: { ...opts.scales.y.ticks, callback: v => formatSpeed(v) } } } } });
}

async function loadNotifications() {
    try {
        const r = await fetch('/api/notifications/list'), data = await r.json();
        const list = document.getElementById('notifList'), badge = document.getElementById('notifBadge'), clearBtn = document.getElementById('notifClearBtn');
        if (data.unread_count > 0) { badge.innerText = data.unread_count; badge.classList.remove('hidden'); }
        else badge.classList.add('hidden');
        if (data.notifications && data.notifications.length > 0) {
            clearBtn.classList.remove('hidden');
            list.innerHTML = data.notifications.map(n => `<div class="px-4 py-3 border-b border-gray-100 dark:border-white/5 hover:bg-gray-50 dark:hover:bg-white/5 transition"><div class="text-[10px] text-gray-400 mb-1">${new Date(n.time * 1000).toLocaleTimeString()}</div><div class="text-xs text-gray-700 dark:text-gray-300">${n.text}</div></div>`).join('');
        } else {
            clearBtn.classList.add('hidden');
            list.innerHTML = `<div class="p-8 text-center text-gray-400 text-xs">${I18N.web_no_notifications}</div>`;
        }
    } catch (e) { console.error("Notif error:", e); }
}

async function readNotifications() { await fetch('/api/notifications/read', { method: 'POST' }); document.getElementById('notifBadge').classList.add('hidden'); }

async function clearNotifications() {
    try {
        const res = await fetch('/api/notifications/clear', { method: 'POST' });
        if (res.ok) { await loadNotifications(); if (window.showToast) showToast(I18N.web_notif_cleared || "Уведомления очищены"); }
    } catch (e) { console.error("Clear error:", e); }
}

window.switchLogType = function(t) {
    const bB = document.getElementById('btnLogBot'), bS = document.getElementById('btnLogSys'), ac = ['bg-white','dark:bg-gray-700','shadow-sm','text-gray-900','dark:text-white'], ic = ['text-gray-500','dark:text-gray-400'];
    if (bB && bS) { if(t === 'bot') { bB.classList.add(...ac); bB.classList.remove(...ic); bS.classList.remove(...ac); bS.classList.add(...ic); } else { bS.classList.add(...ac); bS.classList.remove(...ic); bB.classList.remove(...ac); bB.classList.add(...ic); } }
    loadLogs(t); if (logPollInterval) clearInterval(logPollInterval); logPollInterval = setInterval(() => loadLogs(t), 5000);
};

async function loadLogs(type = 'bot') {
    const container = document.getElementById('logsContainer'); if (!container) return;
    let url = (type === 'sys') ? '/api/logs/system' : '/api/logs';
    try {
        const response = await fetch(url); if (response.status === 403) { container.innerHTML = `<div class="text-red-400 text-center mt-10">${I18N.web_access_denied}</div>`; return; }
        const data = await response.json();
        if (data.error) container.innerHTML = `<div class="text-red-400 p-4 text-xs font-mono">${data.error}</div>`;
        else {
            const logs = data.logs || []; if (logs.length === 0) { container.innerHTML = `<div class="text-gray-600 text-center mt-10">${I18N.web_log_empty}</div>`; return; }
            const isScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
            container.innerHTML = logs.map(l => {
                let cls = "text-gray-500 dark:text-gray-400";
                if (l.includes("INFO")) cls = "text-blue-600 dark:text-blue-300";
                else if (l.includes("WARNING")) cls = "text-yellow-600 dark:text-yellow-300";
                else if (l.includes("ERROR") || l.includes("FAILED")) cls = "text-red-600 dark:text-red-400 font-bold";
                return `<div class="${cls} hover:bg-gray-100 dark:hover:bg-white/5 px-1 rounded transition">${l.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>`;
            }).join('');
            if (isScrolledToBottom) container.scrollTop = container.scrollHeight;
        }
    } catch (e) { container.innerHTML = `<div class="text-red-400 text-center mt-10">${I18N.web_conn_error.replace('{error}', e)}</div>`; }
}