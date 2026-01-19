/* /core/static/js/dashboard.js */

let chartRes = null;
let chartNet = null;
let nodeSSESource = null; 
let logSSESource = null;  

let agentChart = null;
let allNodesData = [];
let currentNodeToken = null; 

// --- CRYPTO FUNCTIONS (XOR + Base64) ---
// WEB_KEY is injected in dashboard.html by server

function decryptData(text) {
    if (!text) return "";
    if (typeof WEB_KEY === 'undefined' || !WEB_KEY) return text;
    try {
        const decoded = atob(text);
        let result = "";
        for (let i = 0; i < decoded.length; i++) {
            const keyChar = WEB_KEY[i % WEB_KEY.length];
            result += String.fromCharCode(decoded.charCodeAt(i) ^ keyChar.charCodeAt(0));
        }
        return result;
    } catch (e) {
        console.error("Decryption error:", e);
        return text;
    }
}

function encryptData(text) {
    if (!text) return "";
    if (typeof WEB_KEY === 'undefined' || !WEB_KEY) return text;
    try {
        let result = "";
        for (let i = 0; i < text.length; i++) {
            const keyChar = WEB_KEY[i % WEB_KEY.length];
            result += String.fromCharCode(text.charCodeAt(i) ^ keyChar.charCodeAt(0));
        }
        return btoa(result);
    } catch (e) {
        console.error("Encryption error:", e);
        return text;
    }
}
// ----------------------------------------

window.addEventListener('themeChanged', () => {
    updateChartsColors();
});

window.initDashboard = function() {
    cleanupDashboardSources();
    if (window.sseSource) {
        window.sseSource.removeEventListener('agent_stats', handleSSEAgentStats);
        window.sseSource.removeEventListener('nodes_list', handleSSENodesList);
        
        window.sseSource.addEventListener('agent_stats', handleSSEAgentStats);
        window.sseSource.addEventListener('nodes_list', handleSSENodesList);
    }

    if (document.getElementById('nodesList')) {
        const searchInput = document.getElementById('nodeSearch');
        if (searchInput) {
            const newSearch = searchInput.cloneNode(true);
            searchInput.parentNode.replaceChild(newSearch, searchInput);
            newSearch.addEventListener('input', () => {
                filterAndRenderNodes();
            });
        }
    }
    if (document.getElementById('logsContainer')) {
        switchLogType('bot');
    }
};

function cleanupDashboardSources() {
    if (nodeSSESource) {
        nodeSSESource.close();
        nodeSSESource = null;
    }
    if (logSSESource) {
        logSSESource.close();
        logSSESource = null;
    }
    if (window.nodesPollInterval) clearInterval(window.nodesPollInterval);
    if (window.agentPollInterval) clearInterval(window.agentPollInterval);
}
const handleSSEAgentStats = (e) => {
    if (!document.getElementById('agentChart')) return;
    try {
        const data = JSON.parse(e.data);
        updateAgentStatsUI(data);
    } catch (err) { console.error("Agent stats parse error", err); }
};

const handleSSENodesList = (e) => {
    if (!document.getElementById('nodesList')) return;
    try {
        const data = JSON.parse(e.data);
        updateNodesListUI(data);
    } catch (err) { console.error("Nodes list parse error", err); }
};

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById('agentChart') || document.getElementById('nodesList')) {
        window.initDashboard();
    }
});
function escapeHtml(text) {
    if (!text) return text;
    return text.replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatProcessList(procList, title, colorClass = "text-gray-500") {
    if (!procList || procList.length === 0) return '';

    const rows = procList.map(procStr => {
        const match = procStr.match(/^(.*)\s\((.*)\)$/);
        let name = procStr;
        let value = "";
        
        if (match) {
            name = match[1];
            value = match[2];
        }

        return `
        <div class="flex justify-between items-center py-1.5 border-b border-gray-500/10 last:border-0 group">
            <div class="flex items-center gap-2 overflow-hidden">
                <div class="w-1 h-1 rounded-full bg-gray-300 dark:bg-gray-600 group-hover:bg-blue-400 transition-colors"></div>
                <span class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
            </div>
            <span class="text-[10px] font-mono font-bold bg-gray-100 dark:bg-white/10 px-1.5 py-0.5 rounded ml-2 text-gray-600 dark:text-gray-300 whitespace-nowrap">${escapeHtml(value)}</span>
        </div>`;
    }).join('');

    return `
        <div class="min-w-[180px]">
            <div class="text-[10px] uppercase tracking-wider font-bold mb-2 pb-1 border-b border-gray-500/20 ${colorClass}">
                ${title}
            </div>
            <div class="flex flex-col">
                ${rows}
            </div>
        </div>
    `;
}

function formatInterfaceList(interfaces, type, title, colorClass = "text-gray-500") {
    if (!interfaces) return '';

    const keys = Object.keys(interfaces).sort();

    const rows = keys.map(name => {
        const val = type === 'rx' ? interfaces[name].bytes_recv : interfaces[name].bytes_sent;
        const hoverColor = colorClass.replace('text-', 'bg-');
        
        return `
        <div class="flex justify-between items-center py-1.5 border-b border-gray-500/10 last:border-0 group">
            <div class="flex items-center gap-2 overflow-hidden">
                <div class="w-1 h-1 rounded-full bg-gray-300 dark:bg-gray-600 group-hover:${hoverColor} transition-colors"></div>
                <span class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
            </div>
            <span class="text-[10px] font-mono font-bold bg-gray-100 dark:bg-white/10 px-1.5 py-0.5 rounded ml-2 text-gray-600 dark:text-gray-300 whitespace-nowrap">${formatBytes(val)}</span>
        </div>`;
    }).join('');

    return `
        <div class="min-w-[180px]">
            <div class="text-[10px] uppercase tracking-wider font-bold mb-2 pb-1 border-b border-gray-500/20 ${colorClass}">
                ${title}
            </div>
            <div class="flex flex-col max-h-[200px] overflow-y-auto custom-scrollbar">
                ${rows}
            </div>
        </div>
    `;
}

function updateNodesListUI(data) {
    try {
        allNodesData = data.nodes || [];
        filterAndRenderNodes();

        if (document.getElementById('nodesTotal')) {
            document.getElementById('nodesTotal').innerText = allNodesData.length;
        }
        if (document.getElementById('nodesActive')) {
            document.getElementById('nodesActive').innerText = allNodesData.filter(n => n.status === 'online').length;
        }
    } catch (e) {
        console.error("Nodes UI update error:", e);
    }
}

function filterAndRenderNodes() {
    const searchInput = document.getElementById('nodeSearch');
    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
    let filteredNodes = allNodesData;

    if (query) {
        filteredNodes = allNodesData.filter(node => {
            const name = (node.name || "").toLowerCase();
            // Decrypt IP for search
            const ip = (decryptData(node.ip) || "").toLowerCase();
            return name.includes(query) || ip.includes(query);
        });
    }
    renderNodesList(filteredNodes);
}

function renderNodesList(nodes) {
    const container = document.getElementById('nodesList');
    if (!container) return;

    if (nodes.length === 0) {
        let emptyText = (typeof I18N !== 'undefined' && I18N.web_no_nodes) ? I18N.web_no_nodes : "No nodes connected";
        const searchInput = document.getElementById('nodeSearch');
        if (searchInput && searchInput.value.trim().length > 0 && allNodesData.length > 0) {
            emptyText = (typeof I18N !== 'undefined' && I18N.web_search_nothing_found) ? I18N.web_search_nothing_found : "Nothing found";
        }
        container.innerHTML = `<div class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">${emptyText}</div>`;
        return;
    }

    const lblCpu = (typeof I18N !== 'undefined' && I18N.web_label_cpu) ? I18N.web_label_cpu : "CPU";
    const lblRam = (typeof I18N !== 'undefined' && I18N.web_label_ram) ? I18N.web_label_ram : "RAM";
    const lblDisk = (typeof I18N !== 'undefined' && I18N.web_label_disk) ? I18N.web_label_disk : "DISK";
    const lblStatus = (typeof I18N !== 'undefined' && I18N.web_label_status) ? I18N.web_label_status : "STATUS";

    const html = nodes.map(node => {
        let statusColor = node.status === 'online' ? "bg-green-500" : (node.status === 'restarting' ? "bg-blue-500" : "bg-red-500");
        let statusText = node.status === 'restarting' ? (typeof I18N !== 'undefined' && I18N.web_status_restart ? I18N.web_status_restart : "RESTART") : node.status.toUpperCase();
        let statusTextClass = node.status === 'online' ? "text-green-500" : (node.status === 'restarting' ? "text-blue-500" : "text-red-500");
        let statusBg = node.status === 'online' ? "bg-green-500/10 text-green-600 dark:text-green-400" : (node.status === 'restarting' ? "bg-blue-500/10 text-blue-600 dark:text-blue-400" : "bg-red-500/10 text-red-600 dark:text-red-400");
        
        const cpu = Math.round(node.cpu || 0);
        const ram = Math.round(node.ram || 0);
        const disk = Math.round(node.disk || 0);

        const cpuColor = cpu > 80 ? 'text-red-500' : 'text-gray-600 dark:text-gray-300';
        const ramColor = ram > 80 ? 'text-red-500' : 'text-gray-600 dark:text-gray-300';
        const diskColor = disk > 90 ? 'text-red-500' : 'text-gray-600 dark:text-gray-300';

        // Decrypt IP for display
        const displayIp = decryptData(node.ip);

        return `
        <div class="bg-white dark:bg-white/5 hover:bg-gray-50 dark:hover:bg-white/10 transition-all duration-200 rounded-xl border border-gray-100 dark:border-white/5 cursor-pointer shadow-sm hover:shadow-md overflow-hidden group mb-2" onclick="openNodeDetails('${escapeHtml(node.token)}', '${statusColor}')">
            
            <div class="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
                
                <div class="flex items-center gap-3 min-w-0">
                    <div class="relative shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-gray-100 dark:bg-black/20">
                        <div class="w-2.5 h-2.5 rounded-full ${statusColor}"></div>
                        ${node.status === 'online' ? `<div class="absolute w-2.5 h-2.5 rounded-full ${statusColor} animate-ping opacity-75"></div>` : ''}
                    </div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2">
                            <div class="font-bold text-sm text-gray-900 dark:text-white truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">${escapeHtml(node.name)}</div>
                            <div class="sm:hidden px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${statusBg}">${statusText}</div>
                        </div>
                        <div class="text-[10px] sm:text-xs font-mono text-gray-400 truncate">${escapeHtml(displayIp)}</div>
                    </div>
                </div>

                <div class="flex items-center justify-between sm:justify-end gap-1 sm:gap-6 mt-1 sm:mt-0 pt-3 sm:pt-0 border-t border-gray-100 dark:border-white/5 sm:border-0">
                    
                    <div class="text-center sm:text-right flex-1 sm:flex-none">
                        <div class="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">${lblCpu}</div>
                        <div class="text-xs font-mono font-bold ${cpuColor}">${cpu}%</div>
                    </div>

                    <div class="text-center sm:text-right flex-1 sm:flex-none">
                        <div class="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">${lblRam}</div>
                        <div class="text-xs font-mono font-bold ${ramColor}">${ram}%</div>
                    </div>

                    <div class="text-center sm:text-right flex-1 sm:flex-none">
                        <div class="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">${lblDisk}</div>
                        <div class="text-xs font-mono font-bold ${diskColor}">${disk}%</div>
                    </div>

                    <div class="hidden sm:block text-right ml-2 pl-3 border-l border-gray-200 dark:border-white/10 min-w-[70px]">
                        <div class="text-[10px] font-bold ${statusTextClass} mb-0.5">${statusText}</div>
                        <div class="text-[9px] text-gray-300 dark:text-gray-600">${lblStatus}</div>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');

    container.innerHTML = html;
}

function updateAgentStatsUI(data) {
    try {
        const freeIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 inline mb-0.5 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;

        if (data.stats) {
            const cpuEl = document.getElementById('stat_cpu');
            const progCpu = document.getElementById('prog_cpu');
            if (cpuEl) {
                let html = `${Math.round(data.stats.cpu)}%`;
                if (data.stats.cpu_freq) {
                    html += ` <span class="text-xs font-normal opacity-60">/ ${formatHz(data.stats.cpu_freq)}</span>`;
                }
                cpuEl.innerHTML = html;
                const hintCpu = document.getElementById('hint-cpu');
                if (hintCpu) {
                    const title = (typeof I18N !== 'undefined' && I18N.web_top_cpu) ? I18N.web_top_cpu : "Top CPU Consumers";
                    hintCpu.innerHTML = formatProcessList(data.stats.process_cpu, title, "text-blue-500");
                }
            }
            if (progCpu) progCpu.style.width = data.stats.cpu + "%";

            const ramEl = document.getElementById('stat_ram');
            const progRam = document.getElementById('prog_ram');
            if (ramEl) {
                let html = `${Math.round(data.stats.ram)}%`;
                if (data.stats.ram_free) {
                    html += ` <span class="text-xs font-normal opacity-60">/ ${formatBytes(data.stats.ram_free)} ${freeIcon}</span>`;
                }
                ramEl.innerHTML = html;
                const hintRam = document.getElementById('hint-ram');
                if (hintRam) {
                    const title = (typeof I18N !== 'undefined' && I18N.web_top_ram) ? I18N.web_top_ram : "Top Memory Consumers";
                    hintRam.innerHTML = formatProcessList(data.stats.process_ram, title, "text-purple-500");
                }
            }
            if (progRam) progRam.style.width = data.stats.ram + "%";

            const diskEl = document.getElementById('stat_disk');
            const progDisk = document.getElementById('prog_disk');
            if (diskEl) {
                let html = `${Math.round(data.stats.disk)}%`;
                if (data.stats.disk_free) {
                    html += ` <span class="text-xs font-normal opacity-60">/ ${formatBytes(data.stats.disk_free)} ${freeIcon}</span>`;
                }
                diskEl.innerHTML = html;
                const hintDisk = document.getElementById('hint-disk');
                if (hintDisk) {
                    const title = (typeof I18N !== 'undefined' && I18N.web_top_disk) ? I18N.web_top_disk : "Top I/O Usage";
                    hintDisk.innerHTML = formatProcessList(data.stats.process_disk, title, "text-emerald-500");
                }
            }
            if (progDisk) progDisk.style.width = data.stats.disk + "%";

            let rxSpeed = 0, txSpeed = 0;
            if (data.history && data.history.length >= 2) {
                const last = data.history[data.history.length - 1];
                const prev = data.history[data.history.length - 2];
                const dt = last.t - prev.t;
                if (dt > 0) {
                    rxSpeed = Math.max(0, (last.rx - prev.rx) * 8 / dt / 1024);
                    txSpeed = Math.max(0, (last.tx - prev.tx) * 8 / dt / 1024);
                }
            }

            const speedStyle = "text-xs text-gray-400 font-normal ml-2 pl-2 border-l border-gray-300 dark:border-white/20";
            const rxEl = document.getElementById('stat_net_recv');
            if (rxEl) rxEl.innerHTML = `${formatBytes(data.stats.net_recv)} <span class="${speedStyle}">${formatSpeed(rxSpeed)}</span>`;

            const txEl = document.getElementById('stat_net_sent');
            if (txEl) txEl.innerHTML = `${formatBytes(data.stats.net_sent)} <span class="${speedStyle}">${formatSpeed(txSpeed)}</span>`;

            if (data.stats.interfaces) {
                 const hintRx = document.getElementById('hint-rx');
                 if (hintRx) {
                     const title = (typeof I18N !== 'undefined' && I18N.web_hint_traffic_in) ? I18N.web_hint_traffic_in : "Inbound Traffic";
                     hintRx.innerHTML = formatInterfaceList(data.stats.interfaces, 'rx', title, "text-cyan-500");
                 }
                 const hintTx = document.getElementById('hint-tx');
                 if (hintTx) {
                     const title = (typeof I18N !== 'undefined' && I18N.web_hint_traffic_out) ? I18N.web_hint_traffic_out : "Outbound Traffic";
                     hintTx.innerHTML = formatInterfaceList(data.stats.interfaces, 'tx', title, "text-orange-500");
                 }
            }

            const rxTotal = data.stats.net_recv || 0;
            const txTotal = data.stats.net_sent || 0;
            const totalNet = rxTotal + txTotal;
            if (totalNet > 0) {
                const rxPercent = (rxTotal / totalNet) * 100;
                const txPercent = 100 - rxPercent;
                const barRx = document.getElementById('trafficBarRx');
                const barTx = document.getElementById('trafficBarTx');
                if (barRx) barRx.style.width = rxPercent + '%';
                if (barTx) barTx.style.width = txPercent + '%';
            }

            const uptimeEl = document.getElementById('stat_uptime');
            if (uptimeEl) uptimeEl.innerText = formatUptime(data.stats.boot_time);

            const ipEl = document.getElementById('agentIp');
            if (ipEl && data.stats.ip) ipEl.innerText = decryptData(data.stats.ip); // Decrypt Agent IP
        }
        renderAgentChart(data.history);
    } catch (e) {
        console.error("Agent stats UI error:", e);
    }
}
function updateChartsColors() {
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    [agentChart, chartRes, chartNet].forEach(chart => {
        if (chart) {
            chart.options.scales.x.grid.color = 'transparent';
            chart.options.scales.x.ticks.color = tickColor;
            chart.options.scales.y.grid.color = gridColor;
            chart.options.scales.y.ticks.color = tickColor;
            if (chart.options.plugins.legend) chart.options.plugins.legend.labels.color = tickColor;
            chart.update();
        }
    });
}

function getGradient(ctx, colorBase) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
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
    const gapThreshold = 10;

    for (let i = 1; i < history.length; i++) {
        const dt = history[i].t - history[i - 1].t;
        if (dt > gapThreshold) {
            labels.push("");
            netRx.push(null);
            netTx.push(null);
        }
        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        netRx.push((Math.max(0, history[i].rx - history[i - 1].rx) * 8 / dt / 1024));
        netTx.push((Math.max(0, history[i].tx - history[i - 1].tx) * 8 / dt / 1024));
    }

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    const isMobile = window.innerWidth < 640;
    const maxTicks = isMobile ? 4 : 8;

    const opts = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
            x: {
                grid: { display: false },
                ticks: { color: tickColor, maxTicksLimit: maxTicks, maxRotation: 0 }
            },
            y: {
                position: 'right',
                grid: { color: gridColor },
                ticks: { color: tickColor, callback: (v) => formatSpeed(v) },
                beginAtZero: true
            }
        },
        plugins: {
            legend: { labels: { color: tickColor, usePointStyle: true } },
            tooltip: { mode: 'index', intersect: false, callbacks: { label: (c) => c.dataset.label + ': ' + formatSpeed(c.raw) } }
        },
        elements: {
            line: { tension: 0.4 },
            point: { radius: 0, hitRadius: 20, hoverRadius: 4 }
        }
    };

    if (agentChart) {
        agentChart.data.labels = labels;
        agentChart.data.datasets[0].data = netRx;
        agentChart.data.datasets[1].data = netTx;
        agentChart.options = opts;
        agentChart.update();
    } else {
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

function formatHz(mhz) {
    if (!mhz) return '';
    if (mhz >= 1000) return (mhz / 1000).toFixed(2) + ' GHz';
    return mhz.toFixed(0) + ' MHz';
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
function setLogLoading() {
    const container = document.getElementById('logsContainer');
    if (!container) return;
    container.classList.add('overflow-hidden');
    if (!container.classList.contains('relative')) container.classList.add('relative');

    const loadingText = (typeof I18N !== 'undefined' && I18N.web_log_connecting) ? I18N.web_log_connecting : "Connecting...";
    const existing = document.getElementById('log-loader');
    if (existing) existing.remove();

    const loader = document.createElement('div');
    loader.id = 'log-loader';
    loader.className = 'absolute inset-0 z-50 flex flex-col items-center justify-center bg-white/90 dark:bg-gray-900/90 backdrop-blur-sm transition-opacity duration-300 opacity-0';
    
    loader.innerHTML = `
        <svg class="animate-spin h-10 w-10 text-blue-600 dark:text-blue-400 mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium text-gray-600 dark:text-gray-300 animate-pulse">${escapeHtml(loadingText)}</span>
    `;
    
    container.appendChild(loader);    
    void loader.offsetWidth;
    loader.classList.remove('opacity-0');
}

function removeLogLoading() {
    const loader = document.getElementById('log-loader');
    if (!loader) return;
    
    loader.classList.add('opacity-0');
    setTimeout(() => {
        if(loader.parentElement) loader.remove();
    }, 300);
}

window.switchLogType = function(type) {
    ['btnLogBot', 'btnLogSys'].forEach(id => {
        const el = document.getElementById(id);
        const isActive = (id === 'btnLogBot' && type === 'bot') || (id === 'btnLogSys' && type === 'sys');
        el.classList.toggle('bg-white', isActive);
        el.classList.toggle('dark:bg-gray-700', isActive);
        el.classList.toggle('text-gray-900', isActive);
        el.classList.toggle('text-gray-500', !isActive);
    });
    if (logSSESource) {
        logSSESource.close();
        logSSESource = null;
    }

    const container = document.getElementById('logsContainer');
    const overlay = document.getElementById('logsOverlay');
    if (typeof USER_ROLE !== 'undefined' && USER_ROLE !== 'admins') {
        if (overlay) overlay.classList.remove('hidden');
        if (!container.innerHTML.includes('blur')) {
            container.innerHTML = generateDummyLogs();
            container.scrollTop = 0;
        }
        return;
    }
    container.innerHTML = '';
    
    const oldEmpty = document.getElementById('empty-logs-state');
    if (oldEmpty) oldEmpty.remove();

    setLogLoading();
    logSSESource = new EventSource(`/api/events/logs?type=${type}`);

    logSSESource.addEventListener('logs', (e) => {
        if (overlay) overlay.classList.add('hidden');
        
        try {
            const data = JSON.parse(e.data);
            const logs = data.logs || [];
            const container = document.getElementById('logsContainer');

            // --- EMPTY LOGS HANDLING ---
            if (logs.length === 0) {
                 if (document.getElementById('log-loader')) {
                    container.classList.remove('overflow-hidden');
                    removeLogLoading();
                    
                    if (!document.getElementById('empty-logs-state')) {
                        const emptyHtml = `
                        <div id="empty-logs-state" class="flex flex-col items-center justify-center h-full min-h-[200px] text-gray-400 dark:text-gray-600 animate-fade-in-up select-none opacity-80">
                            <div class="bg-gray-100 dark:bg-white/5 p-4 rounded-full mb-3">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
                                </svg>
                            </div>
                            <span class="text-sm font-bold text-gray-500 dark:text-gray-400">В логах тишина</span>
                            <span class="text-[10px] uppercase tracking-wider opacity-60 mt-1">Новых записей не найдено</span>
                        </div>`;
                        container.insertAdjacentHTML('beforeend', emptyHtml);
                    }
                 }
                 return;
            }

            const emptyState = document.getElementById('empty-logs-state');
            if (emptyState) {
                emptyState.remove();
            }
            // ---------------------------

            const html = logs.map(line => {
                let cls = "text-gray-500";
                if (line.includes("INFO")) cls = "text-blue-400";
                else if (line.includes("WARNING")) cls = "text-yellow-400";
                else if (line.includes("ERROR") || line.includes("CRITICAL")) cls = "text-red-500 font-bold";
                return `<div class="${cls} font-mono text-xs break-all py-[1px]">${escapeHtml(line)}</div>`;
            }).join('');

            const loader = document.getElementById('log-loader');
            const isInitialLoad = loader && !loader.classList.contains('opacity-0');
            const isAtBottom = (container.scrollHeight - container.scrollTop) <= (container.clientHeight + 5);
            
            container.insertAdjacentHTML('beforeend', html);
            
            if (container.children.length > 1000) {
                 while (container.children.length > 1000) {
                     const first = container.firstChild;
                     if (first && first.id !== 'log-loader' && first.id !== 'empty-logs-state') {
                         first.remove();
                     } else {
                         if (container.children[1]) container.children[1].remove();
                         else break;
                     }
                 }
            }
            
            container.classList.remove('overflow-hidden');
            if (isInitialLoad) {
                container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
            } else if (isAtBottom) {
                container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
            }

            if (loader) {
                removeLogLoading();
            }

        } catch(err) {
            console.error("Logs parse error", err);
            container.classList.remove('overflow-hidden');
            removeLogLoading();
        }
    });

    logSSESource.onerror = () => {
        if (overlay) overlay.classList.add('hidden');
    };
};
function setModalLoading() {
    const modal = document.getElementById('nodeModal');
    if (!modal) return;
    
    const fields = ['modalNodeName', 'modalNodeIp', 'modalToken', 'modalNodeUptime', 'modalNodeRam', 'modalNodeDisk', 'modalNodeTraffic'];
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerText = '...';
    });
    const lastSeen = document.getElementById('modalNodeLastSeen');
    if (lastSeen) {
        lastSeen.innerText = '...';
        lastSeen.className = 'text-gray-400 text-xs';
    }
    const card = modal.firstElementChild;
    if (!card) return;    
    if (!card.classList.contains('relative')) card.classList.add('relative');    
    const existing = document.getElementById('node-modal-loader');
    if (existing) existing.remove();

    const loadingText = (typeof I18N !== 'undefined' && I18N.web_node_modal_loading) ? I18N.web_node_modal_loading : "Loading node data...";

    const loader = document.createElement('div');
    loader.id = 'node-modal-loader';
    loader.className = 'absolute inset-0 z-50 flex flex-col items-center justify-center bg-white/60 dark:bg-gray-900/60 backdrop-blur-md rounded-2xl transition-opacity duration-300 opacity-0';
    loader.innerHTML = `
        <svg class="animate-spin h-10 w-10 text-blue-600 dark:text-blue-400 mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium text-gray-600 dark:text-gray-300 animate-pulse">${escapeHtml(loadingText)}</span>
    `;
    
    card.appendChild(loader);    
    void loader.offsetWidth;
    loader.classList.remove('opacity-0');
}

function removeModalLoading() {
    const loader = document.getElementById('node-modal-loader');
    if (!loader) return;
    
    loader.classList.add('opacity-0');
    setTimeout(() => {
        if (loader.parentElement) loader.remove();
    }, 300);
}

async function openNodeDetails(token, color) {
    const modal = document.getElementById('nodeModal');
    if (modal) {
        setModalLoading();
        animateModalOpen(modal); 
        currentNodeToken = token; // Contains Encrypted Token from renderNodesList
        cancelNodeRename();
    }

    if (chartRes) chartRes.destroy();
    if (chartNet) chartNet.destroy();
    chartRes = null;
    chartNet = null;
    if (nodeSSESource) {
        nodeSSESource.close();
        nodeSSESource = null;
    }
    // Token is already encrypted, send as is
    nodeSSESource = new EventSource(`/api/events/node?token=${token}`);
    
    nodeSSESource.addEventListener('node_details', (e) => {
        try {
            const data = JSON.parse(e.data);
            updateNodeDetailsUI(data);
        } catch (err) {
            console.error("Node details parse error", err);
        }
    });
    
    nodeSSESource.addEventListener('error', (e) => {
         try {
             if (e.data) {
                 const errData = JSON.parse(e.data);
                 if (errData.error) {
                     console.warn("Node SSE Error:", errData.error);
                 }
             }
         } catch(ex) {}
    });
}

function updateNodeDetailsUI(data) {
    if (data.error) return;
    removeModalLoading();
    const inputContainer = document.getElementById('nodeNameInputContainer');
    if (inputContainer && inputContainer.classList.contains('hidden')) {
        document.getElementById('modalNodeName').innerText = data.name;
    }
    
    document.getElementById('modalNodeIp').innerText = decryptData(data.ip);
    document.getElementById('modalToken').innerText = decryptData(data.token);

    const stats = data.stats || {};
    
    if (stats.uptime) {
        const bootTimestamp = (Date.now() / 1000) - stats.uptime;
        document.getElementById('modalNodeUptime').innerText = formatUptime(bootTimestamp);
    } else {
        document.getElementById('modalNodeUptime').innerText = "-";
    }

    if (stats.ram_total) {
        const ramUsed = stats.ram_total - (stats.ram_free || 0);
        document.getElementById('modalNodeRam').innerText = `${formatBytes(ramUsed)} / ${formatBytes(stats.ram_total)}`;
    } else {
        document.getElementById('modalNodeRam').innerText = "-";
    }

    if (stats.disk_total) {
        const diskUsed = stats.disk_total - (stats.disk_free || 0);
        document.getElementById('modalNodeDisk').innerText = `${formatBytes(diskUsed)} / ${formatBytes(stats.disk_total)}`;
    } else {
        document.getElementById('modalNodeDisk').innerText = "-";
    }

    if (stats.net_rx !== undefined) {
        document.getElementById('modalNodeTraffic').innerText = `⬇${formatBytes(stats.net_rx)} ⬆${formatBytes(stats.net_tx)}`;
    } else {
        document.getElementById('modalNodeTraffic').innerText = "-";
    }

    const lastSeen = data.last_seen || 0;
    const now = Math.floor(Date.now() / 1000);
    const diff = now - lastSeen;
    const lsEl = document.getElementById('modalNodeLastSeen');

    const statusOnline = (typeof I18N !== 'undefined' && I18N.web_node_status_online) ? I18N.web_node_status_online : "Online";
    const statusLastSeen = (typeof I18N !== 'undefined' && I18N.web_node_last_seen) ? I18N.web_node_last_seen : "Last seen: ";

    if (lsEl) {
        lsEl.innerText = diff < 60 ? statusOnline : `${statusLastSeen}${new Date(lastSeen * 1000).toLocaleString()}`;
        lsEl.className = diff < 60 ? "text-green-500 font-bold text-xs" : "text-red-500 font-bold text-xs";
    }
    renderCharts(data.history);
}

function closeNodeModal() {
    const modal = document.getElementById('nodeModal');
    if (modal) {
        animateModalClose(modal);
    }
    removeModalLoading();
    if (nodeSSESource) {
        nodeSSESource.close();
        nodeSSESource = null;
    }
}

window.startNodeRename = function() {
    const nameDisplay = document.getElementById('nodeNameContainer');
    const nameInputContainer = document.getElementById('nodeNameInputContainer');
    const nameInput = document.getElementById('modalNodeNameInput');
    const currentName = document.getElementById('modalNodeName').innerText;

    if (nameDisplay && nameInputContainer && nameInput) {
        nameDisplay.classList.add('hidden');
        nameInputContainer.classList.remove('hidden');
        nameInput.value = currentName;
        nameInput.focus();
    }
};

window.cancelNodeRename = function() {
    const nameDisplay = document.getElementById('nodeNameContainer');
    const nameInputContainer = document.getElementById('nodeNameInputContainer');

    if (nameDisplay && nameInputContainer) {
        nameDisplay.classList.remove('hidden');
        nameInputContainer.classList.add('hidden');
    }
};

window.saveNodeRename = async function() {
    const nameInput = document.getElementById('modalNodeNameInput');
    const newName = nameInput.value.trim();
    if (!newName || !currentNodeToken) return;
    document.getElementById('modalNodeName').innerText = newName;
    cancelNodeRename();

    try {
        const res = await fetch('/api/nodes/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: currentNodeToken, name: newName }) // Token is already encrypted
        });
        
        if (res.ok) {
            if (window.showToast) {
                const msg = (typeof I18N !== 'undefined' && I18N.web_node_rename_success) ? I18N.web_node_rename_success : "Name updated";
                window.showToast(msg);
            }
        } else {
            const data = await res.json();
            const errorMsg = (typeof I18N !== 'undefined' && I18N.web_node_rename_error) ? I18N.web_node_rename_error : "Error updating name";
            if (window.showModalAlert) await window.showModalAlert(data.error || errorMsg, "Error");
        }
    } catch (e) {
        console.error(e);
        if (window.showModalAlert) await window.showModalAlert(String(e), "Error");
    }
};

window.handleRenameKeydown = function(event) {
    if (event.key === 'Enter') {
        saveNodeRename();
    } else if (event.key === 'Escape') {
        cancelNodeRename();
    }
};

function renderCharts(history) {
    if (!history || history.length < 2) return;

    const ctxRes = document.getElementById('nodeResChart').getContext('2d');
    const ctxNet = document.getElementById('nodeNetChart').getContext('2d');
    const gapThreshold = 25;

    const labels = [];
    const cpuData = [];
    const ramData = [];
    const netRx = [];
    const netTx = [];

    labels.push(new Date(history[0].t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    cpuData.push(history[0].c);
    ramData.push(history[0].r);
    netRx.push(0);
    netTx.push(0);

    for (let i = 1; i < history.length; i++) {
        const dt = history[i].t - history[i - 1].t;
        if (dt > gapThreshold) {
            labels.push("");
            cpuData.push(null);
            ramData.push(null);
            netRx.push(null);
            netTx.push(null);
        }
        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        cpuData.push(history[i].c);
        ramData.push(history[i].r);
        netRx.push((Math.max(0, history[i].rx - history[i - 1].rx) * 8 / dt / 1024));
        netTx.push((Math.max(0, history[i].tx - history[i - 1].tx) * 8 / dt / 1024));
    }

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    const isMobile = window.innerWidth < 640;

    const lblCpu = (typeof I18N !== 'undefined' && I18N.web_label_cpu) ? I18N.web_label_cpu : "CPU";
    const lblRam = (typeof I18N !== 'undefined' && I18N.web_label_ram) ? I18N.web_label_ram : "RAM";

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
            y: { beginAtZero: true, grid: { color: gridColor }, ticks: { color: tickColor, font: { size: 10 } } },
            x: { grid: { display: false }, ticks: { display: !isMobile, maxTicksLimit: isMobile ? 3 : 6 } }
        },
        plugins: { legend: { labels: { color: tickColor, boxWidth: 10, usePointStyle: true } } },
        elements: { line: { tension: 0.4 }, point: { radius: 0, hitRadius: 10 } }
    };

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
                    { label: `${lblCpu} (%)`, data: cpuData, borderColor: '#3b82f6', borderWidth: 2, backgroundColor: cpuGrad, fill: true },
                    { label: `${lblRam} (%)`, data: ramData, borderColor: '#a855f7', borderWidth: 2, backgroundColor: ramGrad, fill: true }
                ]
            },
            options: { ...commonOptions, scales: { ...commonOptions.scales, y: { ...commonOptions.scales.y, max: 100 } } }
        });
    }

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