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
    
    // ВНИМАНИЕ: Код уведомлений удален отсюда, так как он управляется в common.js
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
        const totalEl = document.getElementById('nodesTotal'), activeEl = document.getElementById('nodesActive');
        if (totalEl) totalEl.innerText = data.nodes.length;
        if (activeEl) activeEl.innerText = data.nodes.filter(n => n.status === 'online').length;
    } catch (e) { console.error(e); }
}

function renderNodesList(nodes) {
    const container = document.getElementById('nodesList');
    if (!container) return;
    if (nodes.length === 0) {
        container.innerHTML = `<div class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">${I18N.web_no_nodes}</div>`;
        return;
    }
    const html = nodes.map(node => {
        let sc = node.status === 'online' ? "bg-green-500" : (node.status === 'restarting' ? "bg-yellow-500" : "bg-red-500");
        return `<div class="bg-gray-50 dark:bg-black/20 hover:bg-gray-100 dark:hover:bg-black/30 transition p-3 rounded-xl border border-gray-100 dark:border-white/5 cursor-pointer flex justify-between items-center group" onclick="openNodeDetails('${escapeHtml(node.token)}')">
            <div class="flex items-center gap-3"><div class="w-2.5 h-2.5 rounded-full ${sc}"></div><div><div class="font-bold text-sm text-gray-900 dark:text-white group-hover:text-blue-500 transition">${escapeHtml(node.name)}</div><div class="text-[10px] text-gray-400">${escapeHtml(node.ip)}</div></div></div>
            <div class="text-right text-[10px] font-bold text-gray-400 uppercase">${node.status}</div></div>`;
    }).join('');
    container.innerHTML = html;
}

async function fetchAgentStats() {
    try {
        const res = await fetch('/api/agent/stats'), data = await res.json();
        if(data.stats) {
            ['cpu','ram','disk'].forEach(m => {
                const el = document.getElementById('stat_'+m), pr = document.getElementById('prog_'+m);
                if(el) el.innerText = Math.round(data.stats[m]) + "%";
                if(pr) pr.style.width = data.stats[m] + "%";
            });
            const ip = document.getElementById('agentIp'); if(ip) ip.innerText = data.stats.ip;
        }
        renderAgentChart(data.history);
    } catch (e) { console.error(e); }
}

function renderAgentChart(history) {
    if (!history || history.length < 2) return;
    const ctx = document.getElementById('agentChart').getContext('2d');
    const isDark = document.documentElement.classList.contains('dark'), gc = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', tc = isDark ? '#9ca3af' : '#6b7280';
    if (!agentChart) {
        agentChart = new Chart(ctx, { type: 'line', data: { labels: history.map(() => ""), datasets: [{ label: 'RX', data: [], borderColor: '#22c55e', fill: true, backgroundColor: 'rgba(34,197,94,0.1)', tension: 0.3 }, { label: 'TX', data: [], borderColor: '#3b82f6', tension: 0.3 }] }, options: { responsive: true, maintainAspectRatio: false, animation: false, scales: { x: { display: false }, y: { grid: { color: gc }, ticks: { color: tc } } } } });
    }
    agentChart.data.datasets[0].data = history.map(h => h.rx / 1024);
    agentChart.data.datasets[1].data = history.map(h => h.tx / 1024);
    agentChart.update();
}

async function openNodeDetails(token) {
    document.getElementById('nodeModal').classList.remove('hidden');
    document.getElementById('nodeModal').classList.add('flex');
    if (pollInterval) clearInterval(pollInterval);
    const update = async () => {
        const res = await fetch(`/api/node/details?token=${token}`), d = await res.json();
        document.getElementById('modalNodeName').innerText = d.name;
        document.getElementById('modalNodeIp').innerText = d.ip;
        document.getElementById('modalToken').innerText = d.token;
        renderCharts(d.history);
    };
    await update();
    pollInterval = setInterval(update, 3000);
}

function closeNodeModal() {
    document.getElementById('nodeModal').classList.add('hidden');
    document.body.style.overflow = 'auto';
    clearInterval(pollInterval);
}

function renderCharts(history) {
    if (!history || history.length < 2) return;
    const isDark = document.documentElement.classList.contains('dark'), gc = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', tc = isDark ? '#9ca3af' : '#6b7280';
    const commonOptions = {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false }, 
        scales: { y: { grid: { color: gc }, ticks: { color: tc } }, x: { display: false } },
        plugins: { legend: { labels: { color: tc } } }
    };
    const ctxRes = document.getElementById('nodeResChart').getContext('2d');
    if (!chartRes) chartRes = new Chart(ctxRes, { type: 'line', data: { labels: history.map(() => ""), datasets: [{ label: 'CPU', data: [], borderColor: '#3b82f6', tension: 0.3 }, { label: 'RAM', data: [], borderColor: '#a855f7', tension: 0.3 }] }, options: commonOptions });
    chartRes.data.datasets[0].data = history.map(h => h.c);
    chartRes.data.datasets[1].data = history.map(h => h.r);
    chartRes.update();
}
// [Логика SwitchLogType и LoadLogs остается такой же]