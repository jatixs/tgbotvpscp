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
    // parsePageEmojis runs in common.js

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
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

async function fetchNodesList() {
    try {
        const response = await fetch('/api/nodes/list');
        const data = await response.json();
        renderNodesList(data.nodes);
        
        const total = data.nodes.length;
        const activeCount = data.nodes.filter(n => n.status === 'online').length;
        
        const totalEl = document.getElementById('nodesTotal');
        const activeEl = document.getElementById('nodesActive');
        if (totalEl) totalEl.innerText = total;
        if (activeEl) activeEl.innerText = activeCount;
            
    } catch (e) {
        console.error("Error updating nodes list:", e);
    }
}

function renderNodesList(nodes) {
    const container = document.getElementById('nodesList');
    if (!container) return;
    
    if (nodes.length === 0) {
        container.innerHTML = `<div class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">${I18N.web_no_nodes}</div>`;
        return;
    }

    const html = nodes.map(node => {
        let statusColor = "bg-green-500";
        let statusText = "ONLINE";

        if (node.status === 'restarting') {
            statusColor = "bg-yellow-500";
            statusText = "RESTARTING";
        } else if (node.status === 'offline') {
            statusColor = "bg-red-500";
            statusText = "OFFLINE";
        }

        return `
        <div class="bg-gray-50 dark:bg-black/20 hover:bg-gray-100 dark:hover:bg-black/30 transition p-3 rounded-xl border border-gray-100 dark:border-white/5 cursor-pointer flex justify-between items-center group" onclick="openNodeDetails('${escapeHtml(node.token)}', '${statusColor}')">
            <div class="flex items-center gap-3">
                <div class="relative">
                    <div class="w-2.5 h-2.5 rounded-full ${statusColor}"></div>
                    <div class="absolute inset-0 w-2.5 h-2.5 rounded-full ${statusColor} animate-ping opacity-75"></div>
                </div>
                <div>
                    <div class="font-bold text-sm text-gray-900 dark:text-white group-hover:text-blue-500 dark:group-hover:text-blue-400 transition">${escapeHtml(node.name)}</div>
                    <div class="text-[10px] font-mono text-gray-400 dark:text-gray-500">${escapeHtml(node.ip)}</div>
                </div>
            </div>
            <div class="text-right">
                 <div class="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-0.5">${statusText}</div>
                 <div class="text-[10px] text-gray-500 font-mono">CPU: ${Math.round(node.cpu)}%</div>
            </div>
        </div>
        `;
    }).join('');

    if (container.innerHTML !== html) {
        container.innerHTML = html;
    }
}

async function fetchAgentStats() {
    try {
        const response = await fetch('/api/agent/stats');
        const data = await response.json();
        
        if(data.stats) {
            const cpuEl = document.getElementById('stat_cpu');
            if (cpuEl) cpuEl.innerText = Math.round(data.stats.cpu) + "%";
            
            const ramEl = document.getElementById('stat_ram');
            if (ramEl) ramEl.innerText = Math.round(data.stats.ram) + "%";
            
            const diskEl = document.getElementById('stat_disk');
            if (diskEl) diskEl.innerText = Math.round(data.stats.disk) + "%";
            
            const progCpu = document.getElementById('prog_cpu');
            if (progCpu) progCpu.style.width = data.stats.cpu + "%";
            
            const progRam = document.getElementById('prog_ram');
            if (progRam) progRam.style.width = data.stats.ram + "%";
            
            const progDisk = document.getElementById('prog_disk');
            if (progDisk) progDisk.style.width = data.stats.disk + "%";
            
            if (document.getElementById('stat_net_recv')) {
                document.getElementById('stat_net_recv').innerText = formatBytes(data.stats.net_recv);
                document.getElementById('stat_net_sent').innerText = formatBytes(data.stats.net_sent);
                
                const uptimeStr = formatUptime(data.stats.boot_time);
                const uptimeEl = document.getElementById('stat_uptime');
                if(uptimeEl) uptimeEl.innerText = uptimeStr;
                
                // [NEW] Обновление IP агента в бейдже
                const ipEl = document.getElementById('agentIp');
                if(ipEl && data.stats.ip) ipEl.innerText = data.stats.ip;
            }
        }
        renderAgentChart(data.history);
    } catch (e) {
        console.error("Agent stats error:", e);
    }
}

function updateChartsColors() {
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280'; 
    
    [agentChart, chartRes, chartNet].forEach(chart => {
        if (chart) {
            if (chart.options.scales.x) {
                chart.options.scales.x.grid.color = gridColor;
                chart.options.scales.x.ticks.color = tickColor;
            }
            if (chart.options.scales.y) {
                chart.options.scales.y.grid.color = gridColor;
                chart.options.scales.y.ticks.color = tickColor;
            }
            if (chart.options.plugins.legend) {
                 chart.options.plugins.legend.labels.color = tickColor;
            }
            chart.update();
        }
    });
}

function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    
    const labels = [];
    const totalPoints = history.length;
    for(let i=0; i<totalPoints; i++) {
        const secondsAgo = (totalPoints - 1 - i) * 2; 
        labels.push(secondsAgo % 20 === 0 || i === totalPoints-1 ? `-${secondsAgo}s` : "");
    }
    
    const netRx = [];
    const netTx = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1; 
        const dx = Math.max(0, history[i].rx - history[i-1].rx);
        const dy = Math.max(0, history[i].tx - history[i-1].tx);
        netRx.push((dx * 8 / dt / 1024)); 
        netTx.push((dy * 8 / dt / 1024)); 
    }
    
    const labelsSl = labels.slice(1);
    const ctx = document.getElementById('agentChart').getContext('2d');
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';

    const opts = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 5, bottom: 0, left: 0, right: 5 } },
        elements: { point: { radius: 0, hitRadius: 10 } },
        scales: { 
            x: { 
                display: true, 
                grid: { display: true, color: gridColor, borderDash: [4, 4], drawBorder: true, borderColor: gridColor },
                ticks: { color: tickColor, font: {size: 9}, maxRotation: 0, autoSkip: false }
            }, 
            y: { 
                display: true, position: 'right',
                grid: { display: true, color: gridColor, borderDash: [4, 4], drawBorder: true, borderColor: gridColor },
                ticks: { color: tickColor, font: {size: 9}, callback: (val) => formatSpeed(val) }
            } 
        },
        plugins: { 
            legend: { display: true, labels: { color: tickColor, font: {size: 10}, boxWidth: 8, usePointStyle: true } }, 
            tooltip: { 
                enabled: true, mode: 'index', intersect: false,
                backgroundColor: isDark ? 'rgba(17, 24, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
                titleColor: isDark ? '#fff' : '#111827',
                bodyColor: isDark ? '#ccc' : '#4b5563',
                borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                borderWidth: 1,
                callbacks: {
                    title: () => '', 
                    label: (ctx) => (ctx.dataset.label || '') + ': ' + (ctx.parsed.y !== null ? formatSpeed(ctx.parsed.y) : '')
                }
            } 
        } 
    };

    if (agentChart) {
        agentChart.data.labels = labelsSl;
        agentChart.data.datasets[0].data = netRx;
        agentChart.data.datasets[1].data = netTx;
        
        agentChart.options.scales.x.grid.color = gridColor;
        agentChart.options.scales.x.ticks.color = tickColor;
        agentChart.options.scales.y.grid.color = gridColor;
        agentChart.options.scales.y.ticks.color = tickColor;
        agentChart.options.plugins.legend.labels.color = tickColor;
        
        agentChart.update();
    } else {
        agentChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labelsSl,
                datasets: [
                    { label: 'RX (In)', data: netRx, borderColor: '#22c55e', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(34, 197, 94, 0.1)', tension: 0.3 },
                    { label: 'TX (Out)', data: netTx, borderColor: '#3b82f6', borderWidth: 1.5, fill: true, backgroundColor: 'rgba(59, 130, 246, 0.1)', tension: 0.3 }
                ]
            },
            options: opts
        });
    }
}

function formatSpeed(valueInKbps) {
    let val = parseFloat(valueInKbps);
    if (isNaN(val)) return '0 Kbit/s';
    if (val >= 1024 * 1024) return (val / (1024 * 1024)).toFixed(2) + ' Gbit/s';
    if (val >= 1024) return (val / 1024).toFixed(2) + ' Mbit/s';
    return val.toFixed(2) + ' Kbit/s';
}

function formatBytes(bytes, decimals = 2) {
    // Используем переводы из I18N, если они доступны
    const sizes = (typeof I18N !== 'undefined' && I18N.unit_bytes) 
        ? [I18N.unit_bytes, I18N.unit_kb, I18N.unit_mb, I18N.unit_gb, I18N.unit_tb, I18N.unit_pb]
        : ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];

    if (!+bytes) return '0 ' + sizes[0];

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

function formatUptime(bootTime) {
    if (!bootTime) return "...";
    const now = Date.now() / 1000;
    const diff = now - bootTime;
    const days = Math.floor(diff / 86400);
    const hours = Math.floor((diff % 86400) / 3600);
    const minutes = Math.floor((diff % 3600) / 60);

    // Получаем переведенные суффиксы из I18N, либо используем английские по умолчанию
    const dSym = (typeof I18N !== 'undefined' && I18N.web_time_d) ? I18N.web_time_d : 'd';
    const hSym = (typeof I18N !== 'undefined' && I18N.web_time_h) ? I18N.web_time_h : 'h';
    const mSym = (typeof I18N !== 'undefined' && I18N.web_time_m) ? I18N.web_time_m : 'm';
    
    if (days > 0) return `${days}${dSym} ${hours}${hSym}`;
    return `${hours}${hSym} ${minutes}${mSym}`;
}

async function openNodeDetails(token, dotColorClass) {
    const modal = document.getElementById('nodeModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    
    if (chartRes) { chartRes.destroy(); chartRes = null; }
    if (chartNet) { chartNet.destroy(); chartNet = null; }

    await fetchAndRender(token);

    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => fetchAndRender(token), 3000);
}

async function fetchAndRender(token) {
    try {
        const response = await fetch(`/api/node/details?token=${token}`);
        const data = await response.json();
        
        if (data.error) {
            console.error(data.error);
            if (pollInterval) clearInterval(pollInterval);
            return;
        }
        document.getElementById('modalNodeName').innerText = data.name || 'Unknown';
        document.getElementById('modalNodeIp').innerText = data.ip || 'Unknown';
        
        const tokenEl = document.getElementById('modalToken');
        if(tokenEl) tokenEl.innerText = data.token || token;

        renderCharts(data.history);
    } catch (e) {
        console.error("Error render node details:", e);
    }
}

function closeNodeModal() {
    const modal = document.getElementById('nodeModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = 'auto';
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

function renderCharts(history) {
    if (!history || history.length < 2) return; 
    const labels = history.map(h => new Date(h.t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}));
    const cpuData = history.map(h => h.c);
    const ramData = history.map(h => h.r);
    
    const netRxSpeed = [];
    const netTxSpeed = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1; 
        const dx = Math.max(0, history[i].rx - history[i-1].rx);
        const dy = Math.max(0, history[i].tx - history[i-1].tx);
        netRxSpeed.push((dx * 8 / dt / 1024)); 
        netTxSpeed.push((dy * 8 / dt / 1024)); 
    }
    const netLabels = labels.slice(1);

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false,
        animation: false,
        scales: { 
            y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: tickColor, font: {size: 10} } }, 
            x: { display: false } 
        },
        plugins: { 
            legend: { labels: { color: tickColor, font: {size: 11}, boxWidth: 10 } },
            tooltip: { 
                backgroundColor: isDark ? 'rgba(17, 24, 39, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                titleColor: isDark ? '#fff' : '#111827',
                bodyColor: isDark ? '#ccc' : '#4b5563',
                borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                borderWidth: 1 
            }
        }
    }};

    const ctxRes = document.getElementById('nodeResChart').getContext('2d');
    if (chartRes) {
        chartRes.data.labels = labels;
        chartRes.data.datasets[0].data = cpuData;
        chartRes.data.datasets[1].data = ramData;
        chartRes.options.scales.y.grid.color = gridColor;
        chartRes.options.scales.y.ticks.color = tickColor;
        chartRes.options.plugins.legend.labels.color = tickColor;
        chartRes.update();
    } else {
        chartRes = new Chart(ctxRes, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    { label: 'CPU (%)', data: cpuData, borderColor: '#3b82f6', tension: 0.3, borderWidth: 2, pointRadius: 0 },
                    { label: 'RAM (%)', data: ramData, borderColor: '#a855f7', tension: 0.3, borderWidth: 2, pointRadius: 0 }
                ]
            },
            options: { ...commonOptions, scales: { ...commonOptions.scales, y: { ...commonOptions.scales.y, max: 100 } } }
        });
    }

    const ctxNet = document.getElementById('nodeNetChart').getContext('2d');
    const netOptions = JSON.parse(JSON.stringify(commonOptions));
    if (!netOptions.scales) netOptions.scales = {};
    if (!netOptions.scales.y) netOptions.scales.y = {};
    if (!netOptions.scales.y.ticks) netOptions.scales.y.ticks = {};
    netOptions.scales.y.grid.color = gridColor;
    netOptions.scales.y.ticks.color = tickColor;
    netOptions.scales.y.ticks.callback = (val) => formatSpeed(val);
    
    if (chartNet) {
        chartNet.data.labels = netLabels;
        chartNet.data.datasets[0].data = netRxSpeed;
        chartNet.data.datasets[1].data = netTxSpeed;
        chartNet.options.scales.y.grid.color = gridColor;
        chartNet.options.scales.y.ticks.color = tickColor;
        chartNet.options.plugins.legend.labels.color = tickColor;
        chartNet.update();
    } else {
        chartNet = new Chart(ctxNet, {
            type: 'line',
            data: {
                labels: netLabels,
                datasets: [
                    { label: 'RX (In)', data: netRxSpeed, borderColor: '#22c55e', backgroundColor: 'rgba(34, 197, 94, 0.1)', fill: true, tension: 0.3, borderWidth: 2, pointRadius: 0 },
                    { label: 'TX (Out)', data: netTxSpeed, borderColor: '#ef4444', tension: 0.3, borderWidth: 2, pointRadius: 0 }
                ]
            },
            options: netOptions
        });
    }
}

window.switchLogType = function(type) {
    const btnBot = document.getElementById('btnLogBot');
    const btnSys = document.getElementById('btnLogSys');
    
    const activeClasses = ['bg-white', 'dark:bg-gray-700', 'shadow-sm', 'text-gray-900', 'dark:text-white'];
    const inactiveClasses = ['text-gray-500', 'dark:text-gray-400'];

    if (btnBot && btnSys) {
        if(type === 'bot') {
            btnBot.classList.add(...activeClasses);
            btnBot.classList.remove(...inactiveClasses);
            
            btnSys.classList.remove(...activeClasses);
            btnSys.classList.add(...inactiveClasses);
        } else {
            btnSys.classList.add(...activeClasses);
            btnSys.classList.remove(...inactiveClasses);
            
            btnBot.classList.remove(...activeClasses);
            btnBot.classList.add(...inactiveClasses);
        }
    }

    loadLogs(type);

    if (logPollInterval) clearInterval(logPollInterval);
    logPollInterval = setInterval(() => loadLogs(type), 5000);
};

async function loadLogs(type = 'bot') {
    const container = document.getElementById('logsContainer');
    if (!container) return;
    
    if (container.querySelector('.text-gray-500.italic') || container.innerText.includes(I18N.web_loading || "Loading")) {
         container.innerHTML = `<div class="flex items-center justify-center h-full text-gray-500"><span class="animate-pulse">${I18N.web_loading || "Loading..."}</span></div>`;
    }

    let url = '/api/logs';
    if (type === 'sys') {
        url = '/api/logs/system';
    }

    try {
        const response = await fetch(url);
        
        if (response.status === 403) {
            container.innerHTML = `<div class="text-red-400 text-center mt-10">${I18N.web_access_denied}</div>`;
            return;
        }
        
        const data = await response.json();
        
        if (data.error) {
            container.innerHTML = `<div class="text-red-400 p-4 text-xs font-mono">${data.error}</div>`;
        } else {
            const logs = data.logs || [];
            if (logs.length === 0) {
                container.innerHTML = `<div class="text-gray-600 text-center mt-10">${I18N.web_log_empty}</div>`;
                return;
            }

            const coloredLogs = logs.map(line => {
                let cls = "text-gray-500 dark:text-gray-400";
                if (line.includes("INFO")) cls = "text-blue-600 dark:text-blue-300";
                if (line.includes("WARNING")) cls = "text-yellow-600 dark:text-yellow-300";
                if (line.includes("ERROR") || line.includes("CRITICAL") || line.includes("Traceback") || line.includes("FAILED")) cls = "text-red-600 dark:text-red-400 font-bold";
                
                const safeLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return `<div class="${cls} hover:bg-gray-100 dark:hover:bg-white/5 px-1 rounded transition">${safeLine}</div>`;
            }).join('');
            
            const isScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;

            if (container.innerHTML !== coloredLogs) {
                 container.innerHTML = coloredLogs;
                 if (isScrolledToBottom) {
                     container.scrollTop = container.scrollHeight;
                 }
            }
        }
    } catch (e) {
        container.innerHTML = `<div class="text-red-400 text-center mt-10">${I18N.web_conn_error.replace('{error}', e)}</div>`;
    }
}