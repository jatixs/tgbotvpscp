// Глобальные переменные
let chartRes = null;
let chartNet = null;
let pollInterval = null;

// Для агента
let chartAgent = null;
let agentPollInterval = null;

// Функция форматирования скорости (динамические единицы)
function formatSpeed(valueInKbps) {
    // Проверка на валидность
    let val = parseFloat(valueInKbps);
    if (isNaN(val)) return '0 Kbit/s';

    if (val >= 1024 * 1024) { // > 1 Gbps
        return (val / (1024 * 1024)).toFixed(2) + ' Gbit/s';
    }
    if (val >= 1024) { // > 1 Mbps
        return (val / 1024).toFixed(2) + ' Mbit/s';
    }
    return val.toFixed(2) + ' Kbit/s';
}

// Запуск мониторинга агента при загрузке страницы
document.addEventListener("DOMContentLoaded", () => {
    if(document.getElementById('chartAgent')) {
        fetchAgentStats();
        agentPollInterval = setInterval(fetchAgentStats, 3000);
    }
});

// --- УПРАВЛЕНИЕ АГЕНТОМ (Dashboard Header) ---
async function fetchAgentStats() {
    try {
        const response = await fetch('/api/agent/stats');
        const data = await response.json();
        
        if(data.stats) {
            document.getElementById('agentCpu').innerText = Math.round(data.stats.cpu) + "%";
            document.getElementById('agentRam').innerText = Math.round(data.stats.ram) + "%";
            document.getElementById('agentDisk').innerText = Math.round(data.stats.disk) + "%";
            document.getElementById('agentIp').innerText = data.stats.ip || "Unknown";
        }
        
        renderAgentChart(data.history);
        
    } catch (e) {
        console.error("Ошибка получения данных агента:", e);
    }
}

function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    
    // Формируем метки времени (секунды назад)
    const labels = [];
    const totalPoints = history.length;
    for(let i=0; i<totalPoints; i++) {
        const secondsAgo = (totalPoints - 1 - i) * 2; 
        // Показываем метку каждые 10 точек
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
        
        // Переводим Байты -> Биты, делим на 1024 -> Кбиты
        // (bytes * 8) / 1024 = Kbps
        netRx.push((dx * 8 / dt / 1024)); 
        netTx.push((dy * 8 / dt / 1024)); 
    }
    
    const labelsSl = labels.slice(1);

    const ctx = document.getElementById('chartAgent').getContext('2d');
    
    const opts = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: {
            padding: { top: 10, bottom: 5, left: 0, right: 10 } // Отступы
        },
        elements: { point: { radius: 0, hitRadius: 10 } },
        scales: { 
            x: { 
                display: true, 
                grid: { display: false, drawBorder: false },
                ticks: { color: '#6b7280', font: {size: 9}, maxRotation: 0, autoSkip: false }
            }, 
            y: { 
                display: true, 
                position: 'right',
                grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                ticks: { 
                    color: '#6b7280', 
                    font: {size: 9},
                    callback: function(value) { return formatSpeed(value); }
                }
            } 
        },
        plugins: { 
            legend: { 
                display: true, 
                labels: { color: '#9ca3af', font: {size: 10}, boxWidth: 8, usePointStyle: true }
            }, 
            tooltip: { 
                enabled: true,
                mode: 'index',
                intersect: false,
                backgroundColor: 'rgba(17, 24, 39, 0.9)',
                titleColor: '#fff',
                bodyColor: '#ccc',
                borderColor: 'rgba(255,255,255,0.1)',
                borderWidth: 1,
                callbacks: {
                    title: () => '', // Скрываем заголовок
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
        chartAgent.update();
    } else {
        chartAgent = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labelsSl,
                datasets: [
                    { label: 'RX (In)', data: netRx, borderColor: '#22c55e', borderWidth: 1.5, fill: false, tension: 0.3 },
                    { label: 'TX (Out)', data: netTx, borderColor: '#3b82f6', borderWidth: 1.5, fill: false, tension: 0.3 }
                ]
            },
            options: opts
        });
    }
}


// --- УПРАВЛЕНИЕ НОДАМИ ---

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
             // Удаляем старые цвета bg-*
             dot.className = dot.className.replace(/bg-\w+-500/g, "");
             // Добавляем базовые классы + новый цвет
             // Очищаем от пробелов и добавляем новый цвет
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
        
        // Обновляем точку
        const now = Date.now() / 1000;
        const lastSeen = data.last_seen || 0;
        const isRestarting = data.is_restarting;
        const isOnline = (now - lastSeen < 25); 

        let newColor = "bg-red-500"; 
        if (isRestarting) newColor = "bg-yellow-500"; 
        else if (isOnline) newColor = "bg-green-500"; 

        updateModalDot(newColor);

        // Статистика
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
        // Переводим в Kbit/s
        netRxSpeed.push((dx * 8 / dt / 1024)); 
        netTxSpeed.push((dy * 8 / dt / 1024)); 
    }
    const netLabels = labels.slice(1);

    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        animation: false,
        scales: { 
            y: { 
                beginAtZero: true, 
                grid: { color: 'rgba(255,255,255,0.05)' }, 
                ticks: { color: '#6b7280', font: {size: 10} } 
            }, 
            x: { display: false } 
        },
        plugins: { 
            legend: { labels: { color: '#9ca3af', font: {size: 11}, boxWidth: 10 } },
            tooltip: { backgroundColor: 'rgba(17, 24, 39, 0.9)', titleColor: '#fff', bodyColor: '#ccc', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1 }
        }
    };

    const ctxRes = document.getElementById('chartResources').getContext('2d');
    if (chartRes) {
        chartRes.data.labels = labels;
        chartRes.data.datasets[0].data = cpuData;
        chartRes.data.datasets[1].data = ramData;
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
    
    // Опции для графика сети с форматированием
    const netOptions = JSON.parse(JSON.stringify(commonOptions));
    // Безопасное создание вложенных объектов, если их нет
    if (!netOptions.scales) netOptions.scales = {};
    if (!netOptions.scales.y) netOptions.scales.y = {};
    if (!netOptions.scales.y.ticks) netOptions.scales.y.ticks = {};
    if (!netOptions.plugins) netOptions.plugins = {};
    if (!netOptions.plugins.tooltip) netOptions.plugins.tooltip = {};
    if (!netOptions.plugins.tooltip.callbacks) netOptions.plugins.tooltip.callbacks = {};

    netOptions.scales.y.ticks.callback = function(value) { return formatSpeed(value); };
    netOptions.plugins.tooltip.callbacks.label = function(context) {
        let label = context.dataset.label || '';
        if (label) label += ': ';
        if (context.parsed.y !== null) {
            label += formatSpeed(context.parsed.y);
        }
        return label;
    };

    if (chartNet) {
        chartNet.data.labels = netLabels;
        chartNet.data.datasets[0].data = netRxSpeed;
        chartNet.data.datasets[1].data = netTxSpeed;
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
                let cls = "text-gray-400";
                if (line.includes("INFO")) cls = "text-blue-300";
                if (line.includes("WARNING")) cls = "text-yellow-300";
                if (line.includes("ERROR") || line.includes("CRITICAL") || line.includes("Traceback")) cls = "text-red-400 font-bold";
                const safeLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return `<div class="${cls} hover:bg-white/5 px-1 rounded">${safeLine}</div>`;
            }).join('');
            contentDiv.innerHTML = coloredLogs || '<div class="text-gray-600 text-center">Лог пуст</div>';
            contentDiv.scrollTop = contentDiv.scrollHeight;
        }
    } catch (e) {
        contentDiv.innerHTML = `<div class="text-red-400">Ошибка соединения: ${e}</div>`;
    }
}
