let chartRes = null;
let chartNet = null;
let pollInterval = null;

let chartAgent = null;
let agentPollInterval = null;
let nodesPollInterval = null;

// --- ЛОГИКА ТЕМЫ ---
const themes = ['dark', 'light', 'system'];
let currentTheme = localStorage.getItem('theme') || 'system';

function initTheme() {
    applyTheme(currentTheme);
}

function toggleTheme() {
    const idx = themes.indexOf(currentTheme);
    const nextIdx = (idx + 1) % themes.length;
    currentTheme = themes[nextIdx];
    localStorage.setItem('theme', currentTheme);
    applyTheme(currentTheme);
}

function applyTheme(theme) {
    const html = document.documentElement;
    const iconMoon = document.getElementById('iconMoon');
    const iconSun = document.getElementById('iconSun');
    const iconSystem = document.getElementById('iconSystem');
    
    // Сброс иконок
    [iconMoon, iconSun, iconSystem].forEach(el => el.classList.add('hidden'));

    if (theme === 'dark') {
        html.classList.add('dark');
        iconMoon.classList.remove('hidden');
    } else if (theme === 'light') {
        html.classList.remove('dark');
        iconSun.classList.remove('hidden');
    } else {
        // System
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            html.classList.add('dark');
        } else {
            html.classList.remove('dark');
        }
        iconSystem.classList.remove('hidden');
    }
    
    updateChartsColors();
}

function updateChartsColors() {
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#6b7280' : '#9ca3af';
    
    [chartAgent, chartRes, chartNet].forEach(chart => {
        if (chart) {
            if (chart.options.scales.x) {
                chart.options.scales.x.grid.color = gridColor;
                chart.options.scales.x.ticks.color = tickColor;
            }
            if (chart.options.scales.y) {
                chart.options.scales.y.grid.color = gridColor;
                chart.options.scales.y.ticks.color = tickColor;
            }
            chart.update();
        }
    });
}

// --- ЛОГИКА ЯЗЫКА ---
async function setLanguage(lang) {
    try {
        const res = await fetch('/api/settings/language', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lang: lang})
        });
        if (res.ok) {
            window.location.reload();
        }
    } catch (e) {
        console.error("Lang switch failed", e);
    }
}

function formatSpeed(valueInKbps) {
    let val = parseFloat(valueInKbps);
    if (isNaN(val)) return '0 Kbit/s';

    if (val >= 1024 * 1024) { 
        return (val / (1024 * 1024)).toFixed(2) + ' Gbit/s';
    }
    if (val >= 1024) { 
        return (val / 1024).toFixed(2) + ' Mbit/s';
    }
    return val.toFixed(2) + ' Kbit/s';
}

function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
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
    
    if (days > 0) return `${days}d ${hours}h`;
    return `${hours}h ${minutes}m`;
}

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    
    if(document.getElementById('chartAgent')) {
        fetchAgentStats();
        agentPollInterval = setInterval(fetchAgentStats, 3000);
    }
    
    if (document.getElementById('nodesGrid')) {
        fetchNodesList();
        nodesPollInterval = setInterval(fetchNodesList, 3000);
    }
});

async function fetchNodesList() {
    try {
        const response = await fetch('/api/nodes/list');
        const data = await response.json();
        renderNodesGrid(data.nodes);
        
        const activeCount = data.nodes.filter(n => n.status === 'online').length;
        if (document.getElementById('statTotalNodes')) 
            document.getElementById('statTotalNodes').innerText = data.nodes.length;
        if (document.getElementById('statActiveNodes')) 
            document.getElementById('statActiveNodes').innerText = activeCount;
            
    } catch (e) {
        console.error("Ошибка обновления списка нод:", e);
    }
}

function renderNodesGrid(nodes) {
    const container = document.getElementById('nodesGrid');
    if (!container) return;
    
    if (nodes.length === 0) {
        container.innerHTML = '<div class="col-span-full text-center text-gray-500 py-10">Нет подключенных нод</div>';
        return;
    }

    const html = nodes.map(node => {
        let statusColor = "text-green-500";
        let statusText = "ONLINE";
        let bgClass = "bg-green-500/10 border-green-500/30";
        let dotColor = "bg-green-500";

        if (node.status === 'restarting') {
            statusColor = "text-yellow-500";
            statusText = "RESTARTING";
            bgClass = "bg-yellow-500/10 border-yellow-500/30";
            dotColor = "bg-yellow-500";
        } else if (node.status === 'offline') {
            statusColor = "text-red-500";
            statusText = "OFFLINE";
            bgClass = "bg-red-500/10 border-red-500/30";
            dotColor = "bg-red-500";
        }

        return `
        <div class="bg-white dark:bg-black/20 hover:shadow-md dark:hover:bg-black/30 transition duration-200 rounded-xl p-4 border border-gray-200 dark:border-white/5 cursor-pointer shadow-sm" onclick="openNodeDetails('${node.token}', '${dotColor}')">
            <div class="flex justify-between items-start">
                <div>
                    <div class="font-bold text-gray-800 dark:text-gray-200">${node.name}</div>
                    <div class="text-[10px] font-mono text-gray-500 mt-1">${node.token.substring(0, 8)}...</div>
                </div>
                <div class="px-2 py-1 rounded text-[10px] font-bold ${statusColor} ${bgClass}">${statusText}</div>
            </div>
            
            <div class="mt-4 pt-4 border-t border-gray-100 dark:border-white/5 grid grid-cols-3 gap-2">
                <div class="bg-gray-50 dark:bg-white/5 rounded-lg p-2 text-center border border-gray-100 dark:border-white/5">
                    <div class="text-[10px] text-gray-500 uppercase font-bold">CPU</div>
                    <div class="text-sm font-bold text-gray-900 dark:text-white">${Math.round(node.cpu)}%</div>
                </div>
                <div class="bg-gray-50 dark:bg-white/5 rounded-lg p-2 text-center border border-gray-100 dark:border-white/5">
                    <div class="text-[10px] text-gray-500 uppercase font-bold">RAM</div>
                    <div class="text-sm font-bold text-gray-900 dark:text-white">${Math.round(node.ram)}%</div>
                </div>
                <div class="bg-gray-50 dark:bg-white/5 rounded-lg p-2 text-center border border-gray-100 dark:border-white/5">
                    <div class="text-[10px] text-gray-500 uppercase font-bold">IP</div>
                    <div class="text-xs font-bold text-gray-900 dark:text-white truncate" title="${node.ip}">${node.ip}</div>
                </div>
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
            document.getElementById('agentCpu').innerText = Math.round(data.stats.cpu) + "%";
            document.getElementById('agentRam').innerText = Math.round(data.stats.ram) + "%";
            document.getElementById('agentDisk').innerText = Math.round(data.stats.disk) + "%";
            document.getElementById('agentIp').innerText = data.stats.ip || "Unknown";
            
            if (document.getElementById('trafficRxTotal')) {
                document.getElementById('trafficRxTotal').innerText = formatBytes(data.stats.net_recv);
                document.getElementById('trafficTxTotal').innerText = formatBytes(data.stats.net_sent);
                document.getElementById('agentUptime').innerText = formatUptime(data.stats.boot_time);
            }
        }
        
        renderAgentChart(data.history);
        
    } catch (e) {
        console.error("Ошибка получения данных агента:", e);
    }
}

function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    
    const labels = [];
    const totalPoints = history.length;
    for(let i=0; i<totalPoints; i++) {
        const secondsAgo = (totalPoints - 1 - i) * 2; 
        if (secondsAgo % 20 === 0 || i === totalPoints-1) {
             labels.push(`-${secondsAgo}s`);
        } else {
             labels.push("");
        }
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

    const ctx = document.getElementById('chartAgent').getContext('2d');
    
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#6b7280' : '#9ca3af';

    const opts = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: {
            padding: { top: 5, bottom: 0, left: 0, right: 5 } 
        },
        elements: { point: { radius: 0, hitRadius: 10 } },
        scales: { 
            x: { 
                display: true, 
                grid: { 
                    display: true, 
                    color: gridColor, 
                    borderDash: [4, 4],
                    drawBorder: true,
                    borderColor: gridColor
                },
                ticks: { color: tickColor, font: {size: 9}, maxRotation: 0, autoSkip: false }
            }, 
            y: { 
                display: true, 
                position: 'right',
                grid: { 
                    display: true, 
                    color: gridColor, 
                    borderDash: [4, 4],
                    drawBorder: true,
                    borderColor: gridColor
                },
                ticks: { 
                    color: tickColor, 
                    font: {size: 9},
                    callback: function(value) { return formatSpeed(value); }
                }
            } 
        },
        plugins: { 
            legend: { 
                display: true, 
                labels: { color: tickColor, font: {size: 10}, boxWidth: 8, usePointStyle: true }
            }, 
            tooltip: { 
                enabled: true,
                mode: 'index',
                intersect: false,
                backgroundColor: isDark ? 'rgba(17, 24, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
                titleColor: isDark ? '#fff' : '#111827',
                bodyColor: isDark ? '#ccc' : '#4b5563',
                borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                borderWidth: 1,
                callbacks: {
                    title: () => '', 
                    label: function(context) {
                        let label = context.dataset.label || '';
                        if (label) label += ': ';
                        if (context.parsed.y !== null) {
                            label += formatSpeed(context.parsed.y);
                        }
                        return label;
                    }
                }
            } 
        } 
    };

    if (chartAgent) {
        chartAgent.data.labels = labelsSl;
        chartAgent.data.datasets[0].data = netRx;
        chartAgent.data.datasets[1].data = netTx;
        
        // Update colors dynamically
        if (chartAgent.options.scales.x) {
            chartAgent.options.scales.x.grid.color = gridColor;
            chartAgent.options.scales.x.ticks.color = tickColor;
        }
        if (chartAgent.options.scales.y) {
            chartAgent.options.scales.y.grid.color = gridColor;
            chartAgent.options.scales.y.ticks.color = tickColor;
        }
        
        chartAgent.update();
    } else {
        chartAgent = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labelsSl,
                datasets: [
                    { 
                        label: 'RX (In)', 
                        data: netRx, 
                        borderColor: '#22c55e', 
                        borderWidth: 1.5, 
                        fill: true, 
                        backgroundColor: 'rgba(34, 197, 94, 0.1)', 
                        tension: 0.3 
                    },
                    { 
                        label: 'TX (Out)', 
                        data: netTx, 
                        borderColor: '#3b82f6', 
                        borderWidth: 1.5, 
                        fill: true, 
                        backgroundColor: 'rgba(59, 130, 246, 0.1)', 
                        tension: 0.3 
                    }
                ]
            },
            options: opts
        });
    }
}

async function openNodeDetails(token, dotColorClass) {
    const modal = document.getElementById('nodeModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    
    updateModalDot(dotColorClass);

    if (chartRes) { chartRes.destroy(); chartRes = null; }
    if (chartNet) { chartNet.destroy(); chartNet = null; }

    await fetchAndRender(token);

    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => fetchAndRender(token), 3000);
}

function updateModalDot(colorClass) {
    const dot = document.getElementById('modalStatusDot');
    if (dot) {
        if(colorClass) {
             dot.className = dot.className.replace(/bg-\w+-500/g, "");
             const newColor = colorClass.replace("bg-", "").trim() ? colorClass : "bg-gray-500";
             dot.classList.add("h-3", "w-3", "rounded-full", "animate-pulse");
             dot.classList.add(newColor);
        }
    }
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

        document.getElementById('modalTitle').innerText = data.name || 'Unknown';
        
        const now = Date.now() / 1000;
        const lastSeen = data.last_seen || 0;
        const isRestarting = data.is_restarting;
        const isOnline = (now - lastSeen < 25); 

        let newColor = "bg-red-500"; 
        if (isRestarting) newColor = "bg-yellow-500"; 
        else if (isOnline) newColor = "bg-green-500"; 

        updateModalDot(newColor);

        const stats = data.stats || {};
        document.getElementById('modalCpu').innerText = (stats.cpu !== undefined ? stats.cpu : 0) + '%';
        document.getElementById('modalRam').innerText = (stats.ram !== undefined ? stats.ram : 0) + '%';
        document.getElementById('modalIp').innerText = data.ip || 'Unknown';
        
        const tokenEl = document.getElementById('modalToken');
        if(tokenEl) {
            tokenEl.innerText = data.token || token;
        }

        renderCharts(data.history);
        
    } catch (e) {
        console.error("Ошибка обновления графиков:", e);
    }
}

function closeModal() {
    const modal = document.getElementById('nodeModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = 'auto';
    
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

function copyToken(element) {
    const tokenEl = document.getElementById('modalToken');
    const tokenText = tokenEl.innerText;
    
    if (!tokenText || tokenText === '...') return;

    const showToast = () => {
        const toast = document.getElementById('copyToast');
        if (toast) {
            toast.classList.remove('translate-y-full');
            setTimeout(() => {
                toast.classList.add('translate-y-full');
            }, 2000);
        }
    };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tokenText).then(showToast).catch(err => {
            console.warn('Clipboard API failed, trying fallback...', err);
            fallbackCopyTextToClipboard(tokenText, showToast);
        });
    } else {
        fallbackCopyTextToClipboard(tokenText, showToast);
    }
}

function fallbackCopyTextToClipboard(text, onSuccess) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        const successful = document.execCommand('copy');
        if (successful && onSuccess) onSuccess();
    } catch (err) {
        console.error('Fallback error', err);
    }
    document.body.removeChild(textArea);
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
    const tickColor = isDark ? '#6b7280' : '#9ca3af';

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        animation: false,
        scales: { 
            y: { 
                beginAtZero: true, 
                grid: { color: gridColor }, 
                ticks: { color: tickColor, font: {size: 10} } 
            }, 
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
    };

    const ctxRes = document.getElementById('chartResources').getContext('2d');
    if (chartRes) {
        chartRes.data.labels = labels;
        chartRes.data.datasets[0].data = cpuData;
        chartRes.data.datasets[1].data = ramData;
        
        // Update colors
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

    const ctxNet = document.getElementById('chartNetwork').getContext('2d');
    
    const netOptions = JSON.parse(JSON.stringify(commonOptions));
    // Re-apply functions lost in JSON parse
    if (!netOptions.scales) netOptions.scales = {};
    if (!netOptions.scales.y) netOptions.scales.y = {};
    if (!netOptions.scales.y.ticks) netOptions.scales.y.ticks = {};
    
    netOptions.scales.y.grid.color = gridColor;
    netOptions.scales.y.ticks.color = tickColor;
    netOptions.plugins.legend.labels.color = tickColor;

    netOptions.scales.y.ticks.callback = function(value) { return formatSpeed(value); };
    
    if (chartNet) {
        chartNet.data.labels = netLabels;
        chartNet.data.datasets[0].data = netRxSpeed;
        chartNet.data.datasets[1].data = netTxSpeed;
        
        // Update colors
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

function openLogsModal() {
    const modal = document.getElementById('logsModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    fetchLogs();
}

function closeLogsModal() {
    const modal = document.getElementById('logsModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = 'auto';
}

async function fetchLogs() {
    const contentDiv = document.getElementById('logsContent');
    contentDiv.innerHTML = '<div class="flex items-center justify-center h-full text-gray-500"><span class="animate-pulse">Загрузка логов...</span></div>';
    try {
        const response = await fetch('/api/logs');
        if (response.status === 403) {
            contentDiv.innerHTML = '<div class="text-red-400 text-center">Доступ запрещен</div>';
            return;
        }
        const data = await response.json();
        if (data.error) {
            contentDiv.innerHTML = `<div class="text-red-400">Ошибка: ${data.error}</div>`;
        } else {
            const coloredLogs = data.logs.map(line => {
                let cls = "text-gray-500 dark:text-gray-400";
                if (line.includes("INFO")) cls = "text-blue-600 dark:text-blue-300";
                if (line.includes("WARNING")) cls = "text-yellow-600 dark:text-yellow-300";
                if (line.includes("ERROR") || line.includes("CRITICAL") || line.includes("Traceback")) cls = "text-red-600 dark:text-red-400 font-bold";
                const safeLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return `<div class="${cls} hover:bg-gray-100 dark:hover:bg-white/5 px-1 rounded">${safeLine}</div>`;
            }).join('');
            contentDiv.innerHTML = coloredLogs || '<div class="text-gray-600 text-center">Лог пуст</div>';
            contentDiv.scrollTop = contentDiv.scrollHeight;
        }
    } catch (e) {
        contentDiv.innerHTML = `<div class="text-red-400">Ошибка соединения: ${e}</div>`;
    }
}