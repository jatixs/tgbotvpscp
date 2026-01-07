/* /core/static/js/dashboard.js */

// --- CONFIGURATION ---
const LOGS_INTERVAL = 5000;  // Логи обновляем раз в 5 сек (Polling)
const SOCKET_RECONNECT_DELAY = 5000;

let socket = null;
let logsTimer = null;

// --- INITIALIZATION ---
document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
});

window.initDashboard = function() {
    clearTimeout(logsTimer);
    if (socket) {
        socket.close();
        socket = null;
    }

    // Инициализация графиков и слушателей
    initCharts();
    setupEventListeners();

    // Запуск WebSocket и поллинга логов
    initSocket();
    pollLogs();
};

function setupEventListeners() {
    const searchInput = document.getElementById('nodeSearch');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => filterNodes(e.target.value));
    }
    
    // Слушаем смену темы для обновления графиков
    window.addEventListener('themeChanged', () => {
        updateChartsTheme();
    });
}

// --- WEBSOCKET LOGIC ---

function initSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/stream`;

    socket = new WebSocket(wsUrl);

    socket.onopen = function() {
        console.log("WS Connected");
    };

    socket.onmessage = function(event) {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'stats_update') {
                updateDashboardFromSocket(msg);
            }
        } catch (e) {
            console.error("WS Parse Error", e);
        }
    };

    socket.onclose = function(event) {
        console.log("WS Closed. Reconnecting...");
        setTimeout(initSocket, SOCKET_RECONNECT_DELAY);
    };
    
    socket.onerror = function(error) {
        console.error("WS Error:", error);
    };
}

// Обновление UI из данных сокета
function updateDashboardFromSocket(data) {
    const d = data.stats;
    const n = data.nodes;

    updateText('stat_uptime', "Live");
    updateText('stat_cpu', d.cpu + '%');
    updateText('stat_ram', d.ram + '%');
    updateText('stat_disk', d.disk + '%');
    
    updateText('stat_net_sent', formatBytes(d.net_sent));
    updateText('stat_net_recv', formatBytes(d.net_recv));
    
    updateText('nodesTotal', n.total);
    updateText('nodesActive', n.active);

    updateProgress('prog_cpu', d.cpu, 'bg-indigo-500');
    updateProgress('prog_ram', d.ram, 'bg-purple-500');
    updateProgress('prog_disk', d.disk, 'bg-green-500');
    
    // Расчет полос трафика
    const rx = parseFloat(d.net_recv || 0);
    const tx = parseFloat(d.net_sent || 0);
    const total = rx + tx;
    if (total > 0) {
        const rxEl = document.getElementById('trafficBarRx');
        const txEl = document.getElementById('trafficBarTx');
        if(rxEl) rxEl.style.width = (rx / total * 100) + '%';
        if(txEl) txEl.style.width = (tx / total * 100) + '%';
    }

    if (window.agentChartInstance) {
        addDataToChart(window.agentChartInstance, d.cpu, d.ram);
    }
}

// --- LOGS POLLING (SMART LOOP) ---

let currentLogType = 'bot';

async function pollLogs() {
    if (document.hidden) {
        logsTimer = setTimeout(pollLogs, LOGS_INTERVAL);
        return;
    }

    try {
        await fetchLogs();
    } catch (e) {
        // console.warn("Logs poll error", e);
    } finally {
        logsTimer = setTimeout(pollLogs, LOGS_INTERVAL);
    }
}

async function fetchLogs() {
    const container = document.getElementById('logsContainer');
    if (!container) return; // Если мы не на дашборде

    const r = await fetch(`/api/logs?type=${currentLogType}`);
    const overlay = document.getElementById('logsOverlay');
    
    if (r.status === 403) {
        if (overlay) overlay.classList.remove('hidden');
        if (container) container.classList.add('blur-sm');
        return;
    } else {
        if (overlay) overlay.classList.add('hidden');
        if (container) container.classList.remove('blur-sm');
    }

    if (!r.ok) return;
    const data = await r.json();
    
    const isScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;
    
    container.innerHTML = data.logs.map(line => {
        let colorClass = 'text-gray-700 dark:text-gray-300';
        if (line.includes('ERROR') || line.includes('CRITICAL')) colorClass = 'text-red-600 dark:text-red-400 font-bold';
        else if (line.includes('WARNING')) colorClass = 'text-yellow-600 dark:text-yellow-400';
        else if (line.includes('INFO')) colorClass = 'text-blue-600 dark:text-blue-400';
        
        return `<div class="whitespace-pre-wrap break-all ${colorClass} hover:bg-black/5 dark:hover:bg-white/5 px-1 rounded">${line}</div>`;
    }).join('');

    if (isScrolledToBottom) {
        container.scrollTop = container.scrollHeight;
    }
}

window.switchLogType = function(type) {
    currentLogType = type;
    const btnBot = document.getElementById('btnLogBot');
    const btnSys = document.getElementById('btnLogSys');
    
    const activeClass = "text-gray-900 dark:text-white bg-white dark:bg-gray-700 shadow-sm";
    const inactiveClass = "text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white";

    if (type === 'bot') {
        btnBot.className = `px-3 py-1.5 rounded-md transition-all font-bold ${activeClass}`;
        btnSys.className = `px-3 py-1.5 rounded-md transition-all ${inactiveClass}`;
    } else {
        btnSys.className = `px-3 py-1.5 rounded-md transition-all font-bold ${activeClass}`;
        btnBot.className = `px-3 py-1.5 rounded-md transition-all ${inactiveClass}`;
    }
    fetchLogs();
};

// --- NODES LIST LOGIC ---
let NODES_DATA = [];

// Список нод загружаем один раз или через WS?
// В текущем WS мы передаем только кол-во. Если нужен список, можно добавить в WS или оставить fetch.
// Для упрощения оставим редкий fetch (или по запросу), т.к. список нод меняется редко.
// Но в исходном коде он был в pollNodes().
// Добавим одноразовую загрузку и обновление по таймеру (реже, 10 сек)

async function fetchNodesList() {
    const r = await fetch('/api/nodes/list');
    if (!r.ok) return;
    NODES_DATA = await r.json();
    renderNodes();
}
// Запускаем отдельно, т.к. это не критично для realtime
setInterval(() => { if(!document.hidden) fetchNodesList(); }, 10000);
fetchNodesList(); 

function renderNodes(filterText = '') {
    const container = document.getElementById('nodesList');
    if (!container) return;
    
    const searchInput = document.getElementById('nodeSearch');
    // Если фильтр не передан, берем из инпута
    if (filterText === '' && searchInput) filterText = searchInput.value;

    const filtered = NODES_DATA.filter(n => 
        n.name.toLowerCase().includes(filterText.toLowerCase()) || 
        (n.ip && n.ip.includes(filterText))
    );

    if (filtered.length === 0) {
        container.innerHTML = `<div class="text-center py-4 text-gray-400 text-xs">Ничего не найдено</div>`;
        return;
    }

    container.innerHTML = filtered.map(node => {
        // Простая проверка онлайна (можно улучшить)
        // В идеале передавать статус с бэка
        const isOnline = node.status === 'online'; 
        const statusColor = isOnline ? 'bg-green-500' : 'bg-red-500';
        const statusPulse = isOnline ? 'animate-pulse' : '';
        
        return `
        <div onclick="openNodeModal('${node.token}')" class="group bg-gray-50 dark:bg-black/20 hover:bg-white dark:hover:bg-white/5 border border-transparent hover:border-gray-200 dark:hover:border-white/10 rounded-xl p-3 cursor-pointer transition-all duration-200">
            <div class="flex justify-between items-center mb-2">
                <div class="flex items-center gap-2">
                    <div class="w-2 h-2 rounded-full ${statusColor} ${statusPulse}"></div>
                    <span class="font-bold text-gray-800 dark:text-gray-200 text-sm">${node.name}</span>
                </div>
                <span class="text-[10px] font-mono text-gray-400">${node.ip || 'Pending...'}</span>
            </div>
            <div class="flex justify-between items-end">
                <div class="flex gap-1">
                    <div class="w-10 h-1 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div class="h-full bg-indigo-500" style="width: ${node.cpu || 0}%"></div>
                    </div>
                    <div class="w-10 h-1 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div class="h-full bg-purple-500" style="width: ${node.ram || 0}%"></div>
                    </div>
                </div>
                <svg class="w-4 h-4 text-gray-300 group-hover:text-blue-500 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
            </div>
        </div>
        `;
    }).join('');
}
window.filterNodes = function(val) { renderNodes(val); };

// --- CHARTS ---
function initCharts() {
    const ctx = document.getElementById('agentChart');
    if (!ctx) return;
    
    if (window.agentChartInstance) {
        window.agentChartInstance.destroy();
    }

    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)';
    const textColor = isDark ? '#9ca3af' : '#6b7280';

    window.agentChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: Array(20).fill(''),
            datasets: [
                {
                    label: 'CPU',
                    data: Array(20).fill(0),
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0
                },
                {
                    label: 'RAM',
                    data: Array(20).fill(0),
                    borderColor: '#a855f7',
                    backgroundColor: 'rgba(168, 85, 247, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: textColor, usePointStyle: true, boxWidth: 6 } },
                tooltip: { 
                    backgroundColor: isDark ? 'rgba(17, 24, 39, 0.9)' : 'rgba(255, 255, 255, 0.9)',
                    titleColor: isDark ? '#fff' : '#111',
                    bodyColor: isDark ? '#ccc' : '#444',
                    borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)',
                    borderWidth: 1,
                    padding: 10,
                    displayColors: true
                }
            },
            scales: {
                x: { display: false },
                y: {
                    min: 0, max: 100,
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { size: 10 } }
                }
            }
        }
    });
}

function updateChartsTheme() {
    if (!window.agentChartInstance) return;
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)';
    const textColor = isDark ? '#9ca3af' : '#6b7280';
    
    window.agentChartInstance.options.scales.y.grid.color = gridColor;
    window.agentChartInstance.options.scales.y.ticks.color = textColor;
    window.agentChartInstance.options.plugins.legend.labels.color = textColor;
    window.agentChartInstance.options.plugins.tooltip.backgroundColor = isDark ? 'rgba(17, 24, 39, 0.9)' : 'rgba(255, 255, 255, 0.9)';
    window.agentChartInstance.options.plugins.tooltip.titleColor = isDark ? '#fff' : '#111';
    window.agentChartInstance.options.plugins.tooltip.bodyColor = isDark ? '#ccc' : '#444';
    window.agentChartInstance.update('none');
}

function addDataToChart(chart, cpu, ram) {
    const labels = chart.data.labels;
    const dataCpu = chart.data.datasets[0].data;
    const dataRam = chart.data.datasets[1].data;

    labels.shift(); labels.push('');
    dataCpu.shift(); dataCpu.push(cpu);
    dataRam.shift(); dataRam.push(ram);

    chart.update('none');
}

// --- UTILS ---
function updateText(id, val) { const el = document.getElementById(id); if(el) el.innerText = val; }
function updateProgress(id, val, colorClass) {
    const el = document.getElementById(id);
    if(el) el.style.width = val + '%';
}
function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

// --- NODE MODAL LOGIC ---
window.openNodeModal = function(token) {
    const modal = document.getElementById('nodeModal');
    if(modal) {
        document.getElementById('modalToken').innerText = token;
        animateModalOpen(modal);
    }
}
window.closeNodeModal = function() {
    const modal = document.getElementById('nodeModal');
    if(modal) animateModalClose(modal);
}