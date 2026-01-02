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
    // График агента
    if(document.getElementById('agentChart')) {
        fetchAgentStats();
        agentPollInterval = setInterval(fetchAgentStats, 3000);
    }
    
    // Список нод
    if (document.getElementById('nodesList')) {
        fetchNodesList();
        nodesPollInterval = setInterval(fetchNodesList, 3000);
    }

    // Логи
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
            chart.options.scales.x.grid.color = 'transparent'; // Скрываем сетку X
            chart.options.scales.x.ticks.color = tickColor;
            chart.options.scales.y.grid.color = gridColor; 
            chart.options.scales.y.ticks.color = tickColor;
            if (chart.options.plugins.legend) chart.options.plugins.legend.labels.color = tickColor;
            chart.update();
        }
    });
}

// Хелпер для создания градиента
function getGradient(ctx, colorBase) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    // Преобразуем rgb(r, g, b) в rgba(r, g, b, alpha)
    gradient.addColorStop(0, colorBase.replace(')', ', 0.5)').replace('rgb', 'rgba'));
    gradient.addColorStop(1, colorBase.replace(')', ', 0.0)').replace('rgb', 'rgba'));
    return gradient;
}

function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    const ctx = document.getElementById('agentChart').getContext('2d');
    
    const labels = [];
    const netRx = [];
    const netTx = [];
    // Если разрыв больше 10 секунд -> считаем даунтаймом (агент шлет данные каждые 2-3 сек)
    const gapThreshold = 10; 

    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t;
        
        // Обнаружение разрыва (Downtime)
        if (dt > gapThreshold) {
            labels.push(""); // Пустая метка
            netRx.push(null); // Разрыв линии
            netTx.push(null);
        }

        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}));
        netRx.push((Math.max(0, history[i].rx - history[i-1].rx) * 8 / dt / 1024));
        netTx.push((Math.max(0, history[i].tx - history[i-1].tx) * 8 / dt / 1024));
    }

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';

    const opts = {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        scales: { 
            x: { grid: { display: false }, ticks: { color: tickColor, maxTicksLimit: 8, maxRotation: 0 } },
            y: { position: 'right', grid: { color: gridColor }, ticks: { color: tickColor, callback: (v) => formatSpeed(v) }, beginAtZero: true }
        },
        plugins: { 
            legend: { labels: { color: tickColor, usePointStyle: true } },
            tooltip: {
                mode: 'index', intersect: false,
                callbacks: { label: (c) => c.dataset.label + ': ' + formatSpeed(c.raw) }
            }
        },
        elements: {
            line: { tension: 0.4 }, // Сглаживание
            point: { radius: 0, hitRadius: 20, hoverRadius: 4 }
        }
    };

    if (agentChart) {
        agentChart.data.labels = labels; 
        agentChart.data.datasets[0].data = netRx; 
        agentChart.data.datasets[1].data = netTx; 
        agentChart.update();
    } else {
        // Создаем градиенты
        const rxGrad = getGradient(ctx, 'rgb(34, 197, 94)');
        const txGrad = getGradient(ctx, 'rgb(59, 130, 246)');

        agentChart = new Chart(ctx, { 
            type: 'line', 
            data: { 
                labels, 
                datasets: [
                    { label: 'RX', data: netRx, borderColor: '#22c55e', borderWidth: 2, backgroundColor: rxGrad, fill: true }, 
                    { label: 'TX', data: netTx, borderColor: '#3b82f6', borderWidth: 2, backgroundColor: txGrad, fill: true }
                ] 
            }, 
            options: opts 
        });
    }
}

function formatSpeed(v) { 
    if (v === null || v === undefined) return '0 Kbps';
    return v >= 1024 * 1024 ? (v / 1048576).toFixed(2) + ' Gbps' : (v >= 1024 ? (v / 1024).toFixed(2) + ' Mbps' : v.toFixed(2) + ' Kbps'); 
}

function formatBytes(b) {
    const s = [
        (typeof I18N !== 'undefined' && I18N.unit_bytes) ? I18N.unit_bytes : 'B',
        (typeof I18N !== 'undefined' && I18N.unit_kb) ? I18N.unit_kb : 'KB',
        (typeof I18N !== 'undefined' && I18N.unit_mb) ? I18N.unit_mb : 'MB',
        (typeof I18N !== 'undefined' && I18N.unit_gb) ? I18N.unit_gb : 'GB',
        (typeof I18N !== 'undefined' && I18N.unit_tb) ? I18N.unit_tb : 'TB',
        (typeof I18N !== 'undefined' && I18N.unit_pb) ? I18N.unit_pb : 'PB'
    ];
    if (!+b) return '0 ' + s[0];
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return `${parseFloat((b / Math.pow(1024, i)).toFixed(2))} ${s[i]}`;
}

function formatUptime(bt) {
    if (!bt) return "...";
    const now = Date.now() / 1000;
    const seconds = Math.floor(now - bt);
    
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);

    const unitD = (typeof I18N !== 'undefined' && I18N.web_time_d) ? I18N.web_time_d : 'd';
    const unitH = (typeof I18N !== 'undefined' && I18N.web_time_h) ? I18N.web_time_h : 'h';
    const unitM = (typeof I18N !== 'undefined' && I18N.web_time_m) ? I18N.web_time_m : 'm';

    if (d > 0) return `${d}${unitD} ${h}${unitH}`;
    if (h > 0) return `${h}${unitH} ${m}${unitM}`;
    return `${m}${unitM}`;
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
        
        // Last Seen logic
        const lastSeen = data.last_seen || 0;
        const now = Math.floor(Date.now() / 1000);
        const diff = now - lastSeen;
        const lsEl = document.getElementById('modalNodeLastSeen');
        if (lsEl) {
            lsEl.innerText = diff < 60 ? "Online" : `Last seen: ${new Date(lastSeen * 1000).toLocaleString()}`;
            lsEl.className = diff < 60 ? "text-green-500 font-bold text-xs" : "text-red-500 font-bold text-xs";
        }

        renderCharts(data.history);
    } catch (e) { console.error("Node detail error:", e); }
}

function closeNodeModal() {
    document.getElementById('nodeModal').classList.replace('flex', 'hidden');
    document.body.style.overflow = 'auto';
    if (pollInterval) clearInterval(pollInterval);
}

function renderCharts(history) {
    if (!history || history.length < 2) return; 
    
    const ctxRes = document.getElementById('nodeResChart').getContext('2d');
    const ctxNet = document.getElementById('nodeNetChart').getContext('2d');

    // Для нод интервал обновления больше, ставим порог 25 сек для даунтайма
    const gapThreshold = 25; 

    const labels = [];
    const cpuData = [];
    const ramData = [];
    const netRx = [];
    const netTx = [];

    // Инициализация первой точки
    labels.push(new Date(history[0].t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}));
    cpuData.push(history[0].c);
    ramData.push(history[0].r);
    netRx.push(0);
    netTx.push(0);

    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t;
        
        // Обнаружение разрыва (Downtime) для Ноды
        if (dt > gapThreshold) {
            labels.push("");
            cpuData.push(null);
            ramData.push(null);
            netRx.push(null);
            netTx.push(null);
        }

        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}));
        cpuData.push(history[i].c);
        ramData.push(history[i].r);
        netRx.push((Math.max(0, history[i].rx - history[i-1].rx) * 8 / dt / 1024));
        netTx.push((Math.max(0, history[i].tx - history[i-1].tx) * 8 / dt / 1024));
    }

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';

    const commonOptions = {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false }, 
        scales: { 
            y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: tickColor, font: {size: 10} } }, 
            x: { grid: { display: false }, ticks: { display: false } } 
        },
        plugins: { legend: { labels: { color: tickColor, boxWidth: 10, usePointStyle: true } } },
        elements: { line: { tension: 0.4 }, point: { radius: 0, hitRadius: 10 } }
    };

    // Resources Chart (Node)
    if (chartRes) {
        chartRes.data.labels = labels; 
        chartRes.data.datasets[0].data = cpuData; 
        chartRes.data.datasets[1].data = ramData; 
        chartRes.update();
    } else {
        const cpuGrad = getGradient(ctxRes, 'rgb(59, 130, 246)');
        const ramGrad = getGradient(ctxRes, 'rgb(168, 85, 247)');

        chartRes = new Chart(ctxRes, { 
            type: 'line', 
            data: { 
                labels, 
                datasets: [
                    { label: 'CPU (%)', data: cpuData, borderColor: '#3b82f6', borderWidth: 2, backgroundColor: cpuGrad, fill: true }, 
                    { label: 'RAM (%)', data: ramData, borderColor: '#a855f7', borderWidth: 2, backgroundColor: ramGrad, fill: true }
                ] 
            }, 
            options: { ...commonOptions, scales: { ...commonOptions.scales, y: { ...commonOptions.scales.y, max: 100 } } } 
        });
    }

    // Network Chart (Node)
    if (chartNet) {
        chartNet.data.labels = labels; 
        chartNet.data.datasets[0].data = netRx; 
        chartNet.data.datasets[1].data = netTx; 
        chartNet.update();
    } else {
        const netOpts = JSON.parse(JSON.stringify(commonOptions)); 
        netOpts.scales.y.ticks.callback = (v) => formatSpeed(v);
        
        const rxGrad = getGradient(ctxNet, 'rgb(34, 197, 94)');
        const txGrad = getGradient(ctxNet, 'rgb(239, 68, 68)');

        chartNet = new Chart(ctxNet, { 
            type: 'line', 
            data: { 
                labels, 
                datasets: [
                    { label: 'RX', data: netRx, borderColor: '#22c55e', borderWidth: 2, backgroundColor: rxGrad, fill: true }, 
                    { label: 'TX', data: netTx, borderColor: '#ef4444', borderWidth: 2, backgroundColor: txGrad, fill: true } 
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