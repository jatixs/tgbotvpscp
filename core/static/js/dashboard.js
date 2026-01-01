let chartRes = null;
let chartNet = null;
let pollInterval = null;

let agentChart = null;
let agentPollInterval = null;
let nodesPollInterval = null;
let logPollInterval = null;

window.addEventListener('themeChanged', () => {
    updateChartsColors();
});

document.addEventListener("DOMContentLoaded", () => {
    if(document.getElementById('agentChart')) {
        fetchAgentStats();
        agentPollInterval = setInterval(fetchAgentStats, 3000);
    }
    
    if (document.getElementById('nodesList')) {
        fetchNodesList();
        nodesPollInterval = setInterval(fetchNodesList, 3000);
    }

    const inputDash = document.getElementById('newNodeNameDash');
    if (inputDash) {
        inputDash.addEventListener('input', validateNodeInput);
        inputDash.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !document.getElementById('btnAddNodeDash').disabled) {
                addNodeDash();
            }
        });
    }

    if (document.getElementById('logsContainer')) {
        switchLogType('bot');
    }
});

function escapeHtml(text) {
    if (!text) return text;
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

async function fetchNodesList() {
    try {
        const response = await fetch('/api/nodes/list');
        const data = await response.json();
        renderNodesList(data.nodes);
        const totalCount = data.nodes.length;
        const activeCount = data.nodes.filter(n => n.status === 'online').length;
        if (document.getElementById('nodesTotal')) document.getElementById('nodesTotal').innerText = totalCount;
        if (document.getElementById('nodesActive')) document.getElementById('nodesActive').innerText = activeCount;
    } catch (e) { console.error("Nodes list error:", e); }
}

function renderNodesList(nodes) {
    const container = document.getElementById('nodesList');
    if (!container) return;
    if (nodes.length === 0) {
        container.innerHTML = `<div class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">${I18N.web_no_nodes}</div>`;
        return;
    }
    const html = nodes.map(node => {
        let statusColor = node.status === 'online' ? "bg-green-500" : (node.status === 'restarting' ? "bg-yellow-500" : "bg-red-500");
        let statusText = node.status.toUpperCase();
        return `
        <div class="bg-gray-50 dark:bg-black/20 hover:bg-gray-100 dark:hover:bg-black/30 transition p-3 rounded-xl border border-gray-100 dark:border-white/5 cursor-pointer flex justify-between items-center group" onclick="openNodeDetails('${escapeHtml(node.token)}', '${statusColor}')">
            <div class="flex items-center gap-3">
                <div class="relative"><div class="w-2.5 h-2.5 rounded-full ${statusColor}"></div><div class="absolute inset-0 w-2.5 h-2.5 rounded-full ${statusColor} animate-ping opacity-75"></div></div>
                <div><div class="font-bold text-sm text-gray-900 dark:text-white group-hover:text-blue-500 transition">${escapeHtml(node.name)}</div><div class="text-[10px] font-mono text-gray-400">${escapeHtml(node.ip)}</div></div>
            </div>
            <div class="text-right"><div class="text-[10px] font-bold text-gray-400 mb-0.5">${statusText}</div><div class="text-[10px] text-gray-500 font-mono">CPU: ${Math.round(node.cpu)}%</div></div>
        </div>`;
    }).join('');
    if (container.innerHTML !== html) container.innerHTML = html;
}

async function fetchAgentStats() {
    try {
        const response = await fetch('/api/agent/stats');
        const data = await response.json();
        if(data.stats) {
            ['cpu', 'ram', 'disk'].forEach(m => {
                const el = document.getElementById('stat_'+m);
                const prog = document.getElementById('prog_'+m);
                if (el) el.innerText = Math.round(data.stats[m]) + "%";
                if (prog) prog.style.width = data.stats[m] + "%";
            });
            if (document.getElementById('stat_net_recv')) {
                document.getElementById('stat_net_recv').innerText = formatBytes(data.stats.net_recv);
                document.getElementById('stat_net_sent').innerText = formatBytes(data.stats.net_sent);
                const uptimeEl = document.getElementById('stat_uptime');
                if(uptimeEl) uptimeEl.innerText = formatUptime(data.stats.boot_time);
                const ipEl = document.getElementById('agentIp');
                if(ipEl && data.stats.ip) ipEl.innerText = data.stats.ip;
            }
        }
        renderAgentChart(data.history);
    } catch (e) { console.error("Agent stats error:", e); }
}

function updateChartsColors() {
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280'; 
    [agentChart, chartRes, chartNet].forEach(chart => {
        if (chart) {
            chart.options.scales.x.grid.color = gridColor; chart.options.scales.x.ticks.color = tickColor;
            chart.options.scales.y.grid.color = gridColor; chart.options.scales.y.ticks.color = tickColor;
            if (chart.options.plugins.legend) chart.options.plugins.legend.labels.color = tickColor;
            chart.update();
        }
    });
}

// --- ГРАФИК АГЕНТА (ИСПРАВЛЕНО) ---
function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    const labels = history.slice(1).map((_, i) => `-${(history.length - 2 - i) * 2}s`);
    const netRx = [], netTx = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1;
        netRx.push((Math.max(0, history[i].rx - history[i-1].rx) * 8 / dt / 1024));
        netTx.push((Math.max(0, history[i].tx - history[i-1].tx) * 8 / dt / 1024));
    }
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    const opts = {
        responsive: true, maintainAspectRatio: false, animation: false,
        scales: { 
            x: { grid: { color: gridColor }, ticks: { color: tickColor, font: {size: 9} } },
            y: { position: 'right', grid: { color: gridColor }, ticks: { color: tickColor, callback: (v) => formatSpeed(v) } }
        },
        plugins: { legend: { labels: { color: tickColor, usePointStyle: true } } }
    };
    if (agentChart) {
        agentChart.data.labels = labels; agentChart.data.datasets[0].data = netRx; agentChart.data.datasets[1].data = netTx; agentChart.update();
    } else {
        const ctx = document.getElementById('agentChart').getContext('2d');
        agentChart = new Chart(ctx, { 
            type: 'line', 
            data: { 
                labels, 
                datasets: [
                    { 
                        label: 'RX', data: netRx, borderColor: '#22c55e', fill: true, backgroundColor: 'rgba(34,197,94,0.1)', tension: 0.3,
                        pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 10 // ИСПРАВЛЕНО: Скрыты точки
                    }, 
                    { 
                        label: 'TX', data: netTx, borderColor: '#3b82f6', fill: true, backgroundColor: 'rgba(59,130,246,0.1)', tension: 0.3,
                        pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 10 // ИСПРАВЛЕНО: Скрыты точки
                    }
                ] 
            }, 
            options: opts 
        });
    }
}

function formatSpeed(v) { return v >= 1024 * 1024 ? (v / 1048576).toFixed(2) + ' Gbps' : (v >= 1024 ? (v / 1024).toFixed(2) + ' Mbps' : v.toFixed(2) + ' Kbps'); }

function formatBytes(b) {
    const s = ['B', 'KB', 'MB', 'GB', 'TB'];
    if (!+b) return '0 ' + s[0];
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return `${parseFloat((b / Math.pow(1024, i)).toFixed(2))} ${s[i]}`;
}

function formatUptime(bt) {
    if (!bt) return "...";
    const d = Math.floor((Date.now() / 1000 - bt) / 86400);
    const h = Math.floor(((Date.now() / 1000 - bt) % 86400) / 3600);
    return d > 0 ? `${d}d ${h}h` : `${h}h`;
}

async function openNodeDetails(token, color) {
    const modal = document.getElementById('nodeModal');
    modal.classList.replace('hidden', 'flex');
    document.body.style.overflow = 'hidden';
    if (chartRes) chartRes.destroy(); if (chartNet) chartNet.destroy();
    chartRes = null; chartNet = null;
    await fetchAndRender(token);
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => fetchAndRender(token), 3000);
}

async function fetchAndRender(token) {
    try {
        const res = await fetch(`/api/node/details?token=${token}`);
        const data = await res.json();
        if (data.error) { clearInterval(pollInterval); return; }
        document.getElementById('modalNodeName').innerText = data.name;
        document.getElementById('modalNodeIp').innerText = data.ip;
        document.getElementById('modalToken').innerText = data.token;
        renderCharts(data.history);
    } catch (e) { console.error("Node detail error:", e); }
}

function closeNodeModal() {
    document.getElementById('nodeModal').classList.replace('flex', 'hidden');
    document.body.style.overflow = 'auto';
    if (pollInterval) clearInterval(pollInterval);
}

// --- ГРАФИКИ НОДЫ В МОДАЛКЕ (ИСПРАВЛЕНО) ---
function renderCharts(history) {
    if (!history || history.length < 2) return; 
    const labels = history.map(h => new Date(h.t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}));
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';

    const commonOptions = {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false }, 
        scales: { 
            y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: tickColor, font: {size: 10} } }, 
            x: { display: false } 
        },
        plugins: { legend: { labels: { color: tickColor, boxWidth: 10 } } }
    };

    if (chartRes) {
        chartRes.data.labels = labels; chartRes.data.datasets[0].data = history.map(h => h.c); chartRes.data.datasets[1].data = history.map(h => h.r); chartRes.update();
    } else {
        chartRes = new Chart(document.getElementById('nodeResChart').getContext('2d'), { 
            type: 'line', 
            data: { 
                labels, 
                datasets: [
                    { label: 'CPU (%)', data: history.map(h => h.c), borderColor: '#3b82f6', pointRadius: 0, pointHoverRadius: 5 }, // ИСПРАВЛЕНО
                    { label: 'RAM (%)', data: history.map(h => h.r), borderColor: '#a855f7', pointRadius: 0, pointHoverRadius: 5 }  // ИСПРАВЛЕНО
                ] 
            }, 
            options: { ...commonOptions, scales: { ...commonOptions.scales, y: { ...commonOptions.scales.y, max: 100 } } } 
        });
    }

    const netRxSpeed = [], netTxSpeed = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1;
        netRxSpeed.push((Math.max(0, history[i].rx - history[i-1].rx) * 8 / dt / 1024));
        netTxSpeed.push((Math.max(0, history[i].tx - history[i-1].tx) * 8 / dt / 1024));
    }
    if (chartNet) {
        chartNet.data.labels = labels.slice(1); chartNet.data.datasets[0].data = netRxSpeed; chartNet.data.datasets[1].data = netTxSpeed; chartNet.update();
    } else {
        const netOpts = JSON.parse(JSON.stringify(commonOptions)); netOpts.scales.y.ticks.callback = (v) => formatSpeed(v);
        chartNet = new Chart(document.getElementById('nodeNetChart').getContext('2d'), { 
            type: 'line', 
            data: { 
                labels: labels.slice(1), 
                datasets: [
                    { label: 'RX', data: netRxSpeed, borderColor: '#22c55e', fill: true, backgroundColor: 'rgba(34,197,94,0.1)', pointRadius: 0, pointHoverRadius: 5 }, // ИСПРАВЛЕНО
                    { label: 'TX', data: netTxSpeed, borderColor: '#ef4444', pointRadius: 0, pointHoverRadius: 5 } // ИСПРАВЛЕНО
                ] 
            }, 
            options: netOpts 
        });
    }
}

window.switchLogType = function(type) {
    ['btnLogBot', 'btnLogSys'].forEach(id => {
        const el = document.getElementById(id);
        const isActive = (id === 'btnLogBot' && type === 'bot') || (id === 'btnLogSys' && type === 'sys');
        el.classList.toggle('bg-white', isActive); el.classList.toggle('dark:bg-gray-700', isActive); el.classList.toggle('text-gray-900', isActive); el.classList.toggle('text-gray-500', !isActive);
    });
    loadLogs(type);
    if (logPollInterval) clearInterval(logPollInterval);
    logPollInterval = setInterval(() => loadLogs(type), 5000);
};

async function loadLogs(type = 'bot') {
    const container = document.getElementById('logsContainer');
    const url = type === 'sys' ? '/api/logs/system' : '/api/logs';
    try {
        const res = await fetch(url);
        if (res.status === 403) { container.innerHTML = `<div class="text-red-400 text-center mt-10">${I18N.web_access_denied}</div>`; return; }
        const data = await res.json();
        if (data.error) container.innerHTML = `<div class="text-red-400 p-4 font-mono">${data.error}</div>`;
        else {
            const logs = data.logs || [];
            if (logs.length === 0) { container.innerHTML = `<div class="text-gray-600 text-center mt-10">${I18N.web_log_empty}</div>`; return; }
            const html = logs.map(line => {
                let cls = "text-gray-500";
                if (line.includes("INFO")) cls = "text-blue-400"; else if (line.includes("WARNING")) cls = "text-yellow-400"; else if (line.includes("ERROR") || line.includes("CRITICAL")) cls = "text-red-500 font-bold";
                return `<div class="${cls}">${escapeHtml(line)}</div>`;
            }).join('');
            const isBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
            if (container.innerHTML !== html) { container.innerHTML = html; if (isBottom) container.scrollTop = container.scrollHeight; }
        }
    } catch (e) { container.innerHTML = `<div class="text-red-400 text-center mt-10">Conn error</div>`; }
}