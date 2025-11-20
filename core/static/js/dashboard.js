// Глобальные переменные для графиков и интервала
let chartRes = null;
let chartNet = null;
let pollInterval = null;

// --- УПРАВЛЕНИЕ НОДАМИ ---

async function openNodeDetails(token) {
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

        document.getElementById('modalTitle').innerText = data.name || 'Unknown';
        
        // Заполняем статистику
        const stats = data.stats || {};
        document.getElementById('modalCpu').innerText = (stats.cpu !== undefined ? stats.cpu : 0) + '%';
        document.getElementById('modalRam').innerText = (stats.ram !== undefined ? stats.ram : 0) + '%';
        document.getElementById('modalIp').innerText = data.ip || 'Unknown';
        
        // Обновляем токен для копирования
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

// --- ФУНКЦИЯ КОПИРОВАНИЯ (С FALLBACK ДЛЯ HTTP) ---
function copyToken(element) {
    const tokenEl = document.getElementById('modalToken');
    const tokenText = tokenEl.innerText;
    
    if (!tokenText || tokenText === '...') return;

    // Функция показа уведомления "Скопировано"
    const showToast = () => {
        const toast = document.getElementById('copyToast');
        if (toast) {
            toast.classList.remove('translate-y-full');
            setTimeout(() => {
                toast.classList.add('translate-y-full');
            }, 2000);
        }
    };

    // Попытка копирования через Clipboard API (требует HTTPS или localhost)
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(tokenText).then(showToast).catch(err => {
            console.warn('Clipboard API failed, trying fallback...', err);
            fallbackCopyTextToClipboard(tokenText, showToast);
        });
    } else {
        // Fallback для HTTP
        fallbackCopyTextToClipboard(tokenText, showToast);
    }
}

function fallbackCopyTextToClipboard(text, onSuccess) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    
    // Стили, чтобы элемент не был виден пользователю, но был в DOM
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
        console.error('Fallback: Oops, unable to copy', err);
    }
    
    document.body.removeChild(textArea);
}
// -----------------------------------------------------

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
        netRxSpeed.push((dx / dt / 1024).toFixed(2)); 
        netTxSpeed.push((dy / dt / 1024).toFixed(2)); 
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
            options: commonOptions
        });
    }
}

// --- УПРАВЛЕНИЕ ЛОГАМИ ---

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
            // Форматирование логов цветом
            const coloredLogs = data.logs.map(line => {
                let cls = "text-gray-400";
                if (line.includes("INFO")) cls = "text-blue-300";
                if (line.includes("WARNING")) cls = "text-yellow-300";
                if (line.includes("ERROR") || line.includes("CRITICAL") || line.includes("Traceback")) cls = "text-red-400 font-bold";
                
                // Экранирование HTML
                const safeLine = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return `<div class="${cls} hover:bg-white/5 px-1 rounded">${safeLine}</div>`;
            }).join('');
            
            contentDiv.innerHTML = coloredLogs || '<div class="text-gray-600 text-center">Лог пуст</div>';
            
            // Автоскролл вниз
            contentDiv.scrollTop = contentDiv.scrollHeight;
        }
    } catch (e) {
        contentDiv.innerHTML = `<div class="text-red-400">Ошибка соединения: ${e}</div>`;
    }
}