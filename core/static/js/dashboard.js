let chartRes = null;
let chartNet = null;

async function openNodeDetails(token) {
    const modal = document.getElementById('nodeModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    // Блокируем скролл фона
    document.body.style.overflow = 'hidden';
    
    try {
        const response = await fetch(`/api/node/details?token=${token}`);
        const data = await response.json();
        
        if (data.error) {
            alert(data.error);
            closeModal();
            return;
        }

        document.getElementById('modalTitle').innerText = data.name || 'Unknown';
        renderCharts(data.history);
        
    } catch (e) {
        console.error(e);
        alert("Ошибка загрузки данных");
        closeModal();
    }
}

function closeModal() {
    const modal = document.getElementById('nodeModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    // Разблокируем скролл фона
    document.body.style.overflow = 'auto';
}

function renderCharts(history) {
    const labels = history.map(h => new Date(h.t * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}));
    const cpuData = history.map(h => h.c);
    const ramData = history.map(h => h.r);
    
    const netRxSpeed = [];
    const netTxSpeed = [];
    for(let i=1; i<history.length; i++) {
        const dt = history[i].t - history[i-1].t || 1;
        const dx = Math.max(0, history[i].rx - history[i-1].rx);
        const dy = Math.max(0, history[i].tx - history[i-1].tx);
        netRxSpeed.push(dx / dt / 1024); 
        netTxSpeed.push(dy / dt / 1024); 
    }
    const netLabels = labels.slice(1);

    // Опции для мобильных
    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false, // Позволяет графику занимать всю высоту контейнера
        interaction: { mode: 'index', intersect: false },
        scales: { 
            y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#6b7280', font: {size: 10} } }, 
            x: { display: false } 
        },
        plugins: { legend: { labels: { color: '#9ca3af', font: {size: 11}, boxWidth: 10 } } }
    };

    // Resources
    const ctxRes = document.getElementById('chartResources').getContext('2d');
    if (chartRes) chartRes.destroy();
    
    chartRes = new Chart(ctxRes, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'CPU', data: cpuData, borderColor: '#3b82f6', tension: 0.4, borderWidth: 2, pointRadius: 0 },
                { label: 'RAM', data: ramData, borderColor: '#a855f7', tension: 0.4, borderWidth: 2, pointRadius: 0 }
            ]
        },
        options: { ...chartOptions, scales: { ...chartOptions.scales, y: { ...chartOptions.scales.y, max: 100 } } }
    });

    // Network
    const ctxNet = document.getElementById('chartNetwork').getContext('2d');
    if (chartNet) chartNet.destroy();
    
    chartNet = new Chart(ctxNet, {
        type: 'line',
        data: {
            labels: netLabels,
            datasets: [
                { label: 'RX (In)', data: netRxSpeed, borderColor: '#22c55e', tension: 0.4, borderWidth: 2, fill: true, backgroundColor: 'rgba(34, 197, 94, 0.1)', pointRadius: 0 },
                { label: 'TX (Out)', data: netTxSpeed, borderColor: '#ef4444', tension: 0.4, borderWidth: 2, pointRadius: 0 }
            ]
        },
        options: chartOptions
    });
}