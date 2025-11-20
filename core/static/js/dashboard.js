// Глобальные переменные для графиков и интервала
let chartRes = null;
let chartNet = null;
let pollInterval = null;

// Функция открытия модального окна
async function openNodeDetails(token) {
    const modal = document.getElementById('nodeModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    // Блокируем прокрутку фона
    document.body.style.overflow = 'hidden';
    
    // 1. Сбрасываем старые графики при открытии нового окна, чтобы не видеть старые данные
    if (chartRes) { chartRes.destroy(); chartRes = null; }
    if (chartNet) { chartNet.destroy(); chartNet = null; }

    // 2. Загружаем данные первый раз
    await fetchAndRender(token);

    // 3. Запускаем авто-обновление каждые 3 секунды
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => fetchAndRender(token), 3000);
}

// Функция получения данных и отрисовки
async function fetchAndRender(token) {
    try {
        const response = await fetch(`/api/node/details?token=${token}`);
        const data = await response.json();
        
        if (data.error) {
            console.error(data.error);
            // Если ошибка (например, нода удалена), останавливаем опрос
            if (pollInterval) clearInterval(pollInterval);
            return;
        }

        document.getElementById('modalTitle').innerText = data.name || 'Unknown';
        renderCharts(data.history);
        
    } catch (e) {
        console.error("Ошибка обновления графиков:", e);
    }
}

// Функция закрытия модального окна
function closeModal() {
    const modal = document.getElementById('nodeModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    
    // Разблокируем прокрутку
    document.body.style.overflow = 'auto';
    
    // Останавливаем обновление
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// Логика отрисовки (Chart.js)
function renderCharts(history) {
    if (!history || history.length < 2) return; // Нужно минимум 2 точки для расчета скорости

    // Подготовка данных
    const labels = history.map(h => new Date(h.t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}));
    const cpuData = history.map(h => h.c);
    const ramData = history.map(h => h.r);
    
    // Расчет скорости сети (дельта байтов / дельта времени)
    const netRxSpeed = [];
    const netTxSpeed = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1; // Избегаем деления на 0
        const dx = Math.max(0, history[i].rx - history[i-1].rx);
        const dy = Math.max(0, history[i].tx - history[i-1].tx);
        netRxSpeed.push((dx / dt / 1024).toFixed(2)); // KB/s
        netTxSpeed.push((dy / dt / 1024).toFixed(2)); // KB/s
    }
    // Метки для сети смещены на 1 (так как скорость считается между точками)
    const netLabels = labels.slice(1);

    // Опции графиков (адаптивность и стиль)
    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        animation: false, // Отключаем анимацию при обновлении для плавности
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
            tooltip: { 
                backgroundColor: 'rgba(17, 24, 39, 0.9)', 
                titleColor: '#fff', 
                bodyColor: '#ccc',
                borderColor: 'rgba(255,255,255,0.1)',
                borderWidth: 1
            }
        }
    };

    // --- График Ресурсов (CPU/RAM) ---
    const ctxRes = document.getElementById('chartResources').getContext('2d');
    
    if (chartRes) {
        // Если график уже есть — обновляем данные
        chartRes.data.labels = labels;
        chartRes.data.datasets[0].data = cpuData;
        chartRes.data.datasets[1].data = ramData;
        chartRes.update();
    } else {
        // Если нет — создаем
        chartRes = new Chart(ctxRes, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    { label: 'CPU (%)', data: cpuData, borderColor: '#3b82f6', tension: 0.3, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
                    { label: 'RAM (%)', data: ramData, borderColor: '#a855f7', tension: 0.3, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 }
                ]
            },
            options: { 
                ...commonOptions, 
                scales: { ...commonOptions.scales, y: { ...commonOptions.scales.y, max: 100 } } // CPU/RAM до 100%
            }
        });
    }

    // --- График Сети (RX/TX) ---
    const ctxNet = document.getElementById('chartNetwork').getContext('2d');
    
    if (chartNet) {
        // Обновляем
        chartNet.data.labels = netLabels;
        chartNet.data.datasets[0].data = netRxSpeed;
        chartNet.data.datasets[1].data = netTxSpeed;
        chartNet.update();
    } else {
        // Создаем
        chartNet = new Chart(ctxNet, {
            type: 'line',
            data: {
                labels: netLabels,
                datasets: [
                    { 
                        label: 'RX (Входящий KB/s)', 
                        data: netRxSpeed, 
                        borderColor: '#22c55e', 
                        backgroundColor: 'rgba(34, 197, 94, 0.1)', 
                        fill: true, 
                        tension: 0.3, 
                        borderWidth: 2, 
                        pointRadius: 0 
                    },
                    { 
                        label: 'TX (Исходящий KB/s)', 
                        data: netTxSpeed, 
                        borderColor: '#ef4444', 
                        tension: 0.3, 
                        borderWidth: 2, 
                        pointRadius: 0 
                    }
                ]
            },
            options: commonOptions
        });
    }
}