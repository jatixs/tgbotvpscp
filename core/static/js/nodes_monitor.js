/**
 * Nodes Monitor Page JavaScript
 * Real-time monitoring dashboard for all nodes
 */

let allNodesData = [];
let currentFilter = 'all';
let searchQuery = '';
let selectedNodes = new Set();
let currentNodeToken = null;
let modalResChart = null;
let modalNetChart = null;
let updateInterval = null;
let modalUpdateInterval = null;

// Initialize function for SPA navigation
function initNodesMonitor() {
    // Clear previous interval if exists
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
    }
    
    // Reset state
    allNodesData = [];
    currentFilter = 'all';
    searchQuery = '';
    selectedNodes.clear();
    currentNodeToken = null;
    
    // Destroy charts if they exist
    if (modalResChart) {
        modalResChart.destroy();
        modalResChart = null;
    }
    if (modalNetChart) {
        modalNetChart.destroy();
        modalNetChart = null;
    }
    
    // Load nodes
    loadNodes();
    
    // Start auto-refresh
    updateInterval = setInterval(loadNodes, 10000);
    
    // Setup theme
    if (typeof applyThemeUI === 'function') {
        applyThemeUI(localStorage.getItem('theme') || 'system');
    } else if (typeof updateThemeIcons === 'function') {
        updateThemeIcons();
    }
}

// Expose functions to window
window.initNodesMonitor = initNodesMonitor;
window.toggleServicesDisplay = toggleServicesDisplay;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initNodesMonitor();
});

// Load all nodes data
async function loadNodes() {
    try {
        const response = await fetch('/api/nodes/monitor/list');
        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            throw new Error('Failed to load nodes');
        }
        const data = await response.json();
        allNodesData = data.nodes || [];
        updateStats();
        renderNodes();
    } catch (error) {
        console.error('Error loading nodes:', error);
    }
}

// Update stats counters
function updateStats() {
    const total = allNodesData.length;
    const online = allNodesData.filter(n => n.status === 'online').length;
    const offline = total - online;
    
    document.getElementById('nodesTotal').textContent = total;
    document.getElementById('nodesOnline').textContent = online;
    document.getElementById('nodesOffline').textContent = offline;
}

// Render nodes grid
function renderNodes() {
    const container = document.getElementById('nodesGrid');
    if (!container) return;
    
    // Filter nodes
    let filtered = allNodesData;
    
    if (currentFilter === 'online') {
        filtered = filtered.filter(n => n.status === 'online');
    } else if (currentFilter === 'offline') {
        filtered = filtered.filter(n => n.status !== 'online');
    }
    
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        filtered = filtered.filter(n => 
            n.name.toLowerCase().includes(q) || 
            (n.ip && n.ip.toLowerCase().includes(q))
        );
    }
    
    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="col-span-full text-center py-12 text-gray-500 dark:text-gray-400">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto mb-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                ${I18N?.web_no_nodes || 'No nodes found'}
            </div>
        `;
        return;
    }
    
    container.innerHTML = filtered.map(node => createNodeCard(node)).join('');
}

// Create node card HTML
function createNodeCard(node) {
    const isOnline = node.status === 'online';
    const isRestarting = node.status === 'restarting';
    
    let statusClass, statusIcon, statusText;
    if (isRestarting) {
        statusClass = 'bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400';
        statusIcon = '🔵';
        statusText = I18N?.web_node_status_restarting || 'Restarting';
    } else if (isOnline) {
        statusClass = 'bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400';
        statusIcon = '🟢';
        statusText = I18N?.web_node_status_online || 'Online';
    } else {
        statusClass = 'bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-400';
        statusIcon = '🔴';
        statusText = I18N?.web_node_status_offline || 'Offline';
    }
    
    const cpu = node.cpu || 0;
    const ram = node.ram || 0;
    const disk = node.disk || 0;
    const uptime = formatUptime(node.uptime || 0);
    const traffic = formatTraffic(node.traffic || {});
    
    const isSelected = selectedNodes.has(node.token);
    
    return `
        <div class="node-card bg-white/60 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/10 rounded-2xl overflow-hidden shadow-lg dark:shadow-none hover:scale-[1.02] transition duration-300 ${isSelected ? 'ring-2 ring-blue-500' : ''}" 
             data-token="${node.token}" data-status="${node.status}" data-name="${node.name.toLowerCase()}">
            
            <!-- Header -->
            <div class="p-4 border-b border-gray-100 dark:border-white/5 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    <input type="checkbox" class="node-checkbox rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500" 
                           ${isSelected ? 'checked' : ''} 
                           onchange="toggleNodeSelection('${node.token}', this)">
                    <div>
                        <h3 class="font-bold text-gray-900 dark:text-white text-sm">${escapeHtml(node.name)}</h3>
                        <span class="text-xs text-gray-500 dark:text-gray-400">${node.ip || '-'}</span>
                    </div>
                </div>
                <span class="px-2 py-1 rounded-lg text-xs font-bold ${statusClass}">
                    ${statusIcon} ${statusText}
                </span>
            </div>
            
            <!-- Stats -->
            <div class="p-4 space-y-3">
                <!-- CPU -->
                <div>
                    <div class="flex justify-between text-xs mb-1">
                        <span class="text-gray-500 dark:text-gray-400 font-bold">${I18N?.web_cpu || 'CPU'}</span>
                        <span class="font-mono font-bold text-indigo-600 dark:text-indigo-400">${cpu}%</span>
                    </div>
                    <div class="w-full bg-gray-200 dark:bg-gray-700 h-1.5 rounded-full overflow-hidden">
                        <div class="bg-indigo-500 h-1.5 rounded-full transition-all duration-500" style="width: ${cpu}%"></div>
                    </div>
                </div>
                
                <!-- RAM -->
                <div>
                    <div class="flex justify-between text-xs mb-1">
                        <span class="text-gray-500 dark:text-gray-400 font-bold">${I18N?.web_ram || 'RAM'}</span>
                        <span class="font-mono font-bold text-purple-600 dark:text-purple-400">${ram}%</span>
                    </div>
                    <div class="w-full bg-gray-200 dark:bg-gray-700 h-1.5 rounded-full overflow-hidden">
                        <div class="bg-purple-500 h-1.5 rounded-full transition-all duration-500" style="width: ${ram}%"></div>
                    </div>
                </div>
                
                <!-- Disk -->
                <div>
                    <div class="flex justify-between text-xs mb-1">
                        <span class="text-gray-500 dark:text-gray-400 font-bold">${I18N?.web_disk || 'Disk'}</span>
                        <span class="font-mono font-bold text-green-600 dark:text-green-400">${disk}%</span>
                    </div>
                    <div class="w-full bg-gray-200 dark:bg-gray-700 h-1.5 rounded-full overflow-hidden">
                        <div class="bg-green-500 h-1.5 rounded-full transition-all duration-500" style="width: ${disk}%"></div>
                    </div>
                </div>
                
                <!-- Info Row -->
                <div class="flex justify-between text-xs text-gray-500 dark:text-gray-400 pt-2 border-t border-gray-100 dark:border-white/5">
                    <span>⏱ ${uptime}</span>
                    <span>📊 ${traffic}</span>
                </div>
            </div>
            
            <!-- Actions -->
            <div class="px-4 pb-4 mb-3 pt-1 flex gap-2">
                <button onclick="openNodeDetail('${node.token}')" class="flex-1 px-3 py-2 bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 rounded-xl text-xs font-bold hover:bg-blue-200 dark:hover:bg-blue-500/30 transition">
                    ${I18N?.web_node_details || 'Node Details'}
                </button>
                <button onclick="quickReboot('${node.token}')" class="node-reboot-btn px-3 py-2 text-red-600 dark:text-red-400 rounded-xl text-xs font-bold hover:bg-red-200 transition" title="Reboot">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                </button>
            </div>
        </div>
    `;
}

// Filtering functions
function filterNodes(query) {
    searchQuery = query;
    renderNodes();
}

function filterByStatus(status) {
    currentFilter = status;
    
    // Update button styles
    ['filterAll', 'filterOnline', 'filterOffline'].forEach(id => {
        const btn = document.getElementById(id);
        btn.className = 'px-3 py-1.5 text-xs font-bold rounded-lg transition bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400';
    });
    
    const activeBtn = document.getElementById('filter' + status.charAt(0).toUpperCase() + status.slice(1));
    if (status === 'all') {
        activeBtn.className = 'px-3 py-1.5 text-xs font-bold rounded-lg transition bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400';
    } else if (status === 'online') {
        activeBtn.className = 'px-3 py-1.5 text-xs font-bold rounded-lg transition bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400';
    } else {
        activeBtn.className = 'px-3 py-1.5 text-xs font-bold rounded-lg transition bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-400';
    }
    
    renderNodes();
}

// Selection functions
function toggleSelectAll(checkbox) {
    if (checkbox.checked) {
        allNodesData.forEach(node => selectedNodes.add(node.token));
    } else {
        selectedNodes.clear();
    }
    renderNodes();
}

function toggleNodeSelection(token, checkbox) {
    if (checkbox.checked) {
        selectedNodes.add(token);
    } else {
        selectedNodes.delete(token);
    }
    
    // Update select all checkbox
    const selectAll = document.getElementById('selectAllNodes');
    selectAll.checked = selectedNodes.size === allNodesData.length;
    selectAll.indeterminate = selectedNodes.size > 0 && selectedNodes.size < allNodesData.length;
}

// Mass commands
async function massCommand(cmd) {
    if (selectedNodes.size === 0) {
        showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_nodes_monitor_select_nodes || 'Please select at least one node');
        return;
    }
    
    // Get localized command name
    const cmdNames = {
        'reboot': I18N?.web_nodes_monitor_btn_reboot || 'Reboot',
        'selftest': I18N?.web_nodes_monitor_btn_selftest || 'System Test',
        'speedtest': I18N?.web_nodes_monitor_btn_speedtest || 'Speedtest',
        'traffic': I18N?.web_nodes_monitor_btn_traffic || 'Traffic'
    };
    const cmdName = cmdNames[cmd] || cmd;
    
    const confirmMsg = cmd === 'reboot' 
        ? (I18N?.web_nodes_monitor_confirm_mass_reboot || `Reboot ${selectedNodes.size} selected nodes?`)
        : (I18N?.web_nodes_monitor_confirm_mass_command || `Execute {command} on {count} nodes?`)
            .replace('{command}', cmdName)
            .replace('{count}', selectedNodes.size);
    
    showConfirm(I18N?.modal_title_confirm || 'Confirm', confirmMsg, async () => {
        for (const token of selectedNodes) {
            try {
                await sendNodeCommand(token, cmd);
            } catch (e) {
                console.error(`Error executing ${cmd} on node:`, e);
            }
        }
        showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_commands_sent || 'Commands sent to all selected nodes');
        loadNodes();
    });
}

// Quick actions
async function quickReboot(token) {
    const node = allNodesData.find(n => n.token === token);
    const name = node ? node.name : 'Node';
    
    showConfirm(
        I18N?.modal_title_confirm || 'Confirm',
        (I18N?.web_reboot_node_confirm || 'Reboot {name}?').replace('{name}', name),
        async () => {
            await sendNodeCommand(token, 'reboot');
            showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_reboot_sent || 'Reboot command sent');
            loadNodes();
        }
    );
}

// Node detail modal
async function openNodeDetail(token) {
    currentNodeToken = token;
    const modal = document.getElementById('nodeDetailModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    // Load node details
    await loadNodeDetails(token);
    
    // Start auto-refresh for modal (every 5 seconds)
    if (modalUpdateInterval) clearInterval(modalUpdateInterval);
    modalUpdateInterval = setInterval(() => {
        if (currentNodeToken) {
            loadNodeDetails(currentNodeToken);
        }
    }, 5000);
}

function closeNodeDetailModal() {
    document.getElementById('nodeDetailModal').classList.add('hidden');
    document.getElementById('nodeDetailModal').classList.remove('flex');
    currentNodeToken = null;
    
    // Stop modal auto-refresh
    if (modalUpdateInterval) {
        clearInterval(modalUpdateInterval);
        modalUpdateInterval = null;
    }
    
    // Destroy charts
    if (modalResChart) {
        modalResChart.destroy();
        modalResChart = null;
    }
    if (modalNetChart) {
        modalNetChart.destroy();
        modalNetChart = null;
    }
}

async function loadNodeDetails(token) {
    try {
        const response = await fetch(`/api/nodes/monitor/detail?token=${encodeURIComponent(token)}`);
        if (!response.ok) throw new Error('Failed to load node details');
        
        const data = await response.json();
        updateNodeModal(data);
        loadNodeServices(token);
    } catch (error) {
        console.error('Error loading node details:', error);
    }
}

function updateNodeModal(data) {
    document.getElementById('modalNodeTitle').textContent = data.name || 'Unknown';
    document.getElementById('modalNodeIp').textContent = data.ip || '-';
    
    const isOnline = data.status === 'online';
    const statusIcon = document.getElementById('modalNodeStatusIcon');
    const statusBadge = document.getElementById('modalNodeStatusBadge');
    const statusDot = document.getElementById('modalNodeStatusDot');
    const statusText = document.getElementById('modalNodeStatus');
    
    if (isOnline) {
        statusIcon.className = 'p-2 bg-green-100 dark:bg-green-500/20 rounded-lg text-green-600 dark:text-green-400';
        statusBadge.className = 'flex items-center gap-1 text-green-600 dark:text-green-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse';
        statusText.textContent = I18N?.web_node_status_online || 'Online';
    } else {
        statusIcon.className = 'p-2 bg-red-100 dark:bg-red-500/20 rounded-lg text-red-600 dark:text-red-400';
        statusBadge.className = 'flex items-center gap-1 text-red-600 dark:text-red-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-red-500';
        statusText.textContent = I18N?.web_node_status_offline || 'Offline';
    }
    
    const stats = data.stats || {};
    document.getElementById('modalUptime').textContent = formatUptime(stats.uptime || 0);
    document.getElementById('modalCpu').textContent = (stats.cpu || 0) + '%';
    document.getElementById('modalRam').textContent = (stats.ram || 0) + '%';
    document.getElementById('modalDisk').textContent = (stats.disk || 0) + '%';
    
    // Update charts
    updateModalCharts(data.history || []);
}

function updateModalCharts(history) {
    const labels = history.map((_, i) => i);
    const cpuData = history.map(h => h.c || 0);
    const ramData = history.map(h => h.r || 0);
    const rxData = history.map(h => (h.rx || 0) / 1024 / 1024);
    const txData = history.map(h => (h.tx || 0) / 1024 / 1024);
    
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    
    // Gradient function
    function getGradient(ctx, color) {
        const gradient = ctx.createLinearGradient(0, 0, 0, 160);
        gradient.addColorStop(0, color.replace('rgb', 'rgba').replace(')', ', 0.3)'));
        gradient.addColorStop(1, color.replace('rgb', 'rgba').replace(')', ', 0.01)'));
        return gradient;
    }
    
    const commonOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { 
            legend: { 
                display: true, 
                position: 'top', 
                labels: { 
                    color: tickColor,
                    boxWidth: 10, 
                    usePointStyle: true,
                    font: { size: 10 } 
                } 
            } 
        },
        scales: {
            x: { display: false },
            y: { 
                beginAtZero: true, 
                max: 100,
                grid: { color: gridColor },
                ticks: { color: tickColor, font: { size: 10 } }
            }
        },
        elements: {
            line: { tension: 0.4 },
            point: { radius: 0, hitRadius: 10 }
        }
    };
    
    // Resources chart
    const resCtx = document.getElementById('modalResChart').getContext('2d');
    if (modalResChart) modalResChart.destroy();
    
    const cpuGrad = getGradient(resCtx, 'rgb(59, 130, 246)');
    const ramGrad = getGradient(resCtx, 'rgb(168, 85, 247)');
    
    modalResChart = new Chart(resCtx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                { label: 'CPU (%)', data: cpuData, borderColor: '#3b82f6', borderWidth: 2, backgroundColor: cpuGrad, fill: true },
                { label: 'RAM (%)', data: ramData, borderColor: '#a855f7', borderWidth: 2, backgroundColor: ramGrad, fill: true }
            ]
        },
        options: commonOptions
    });
    
    // Network chart
    const netCtx = document.getElementById('modalNetChart').getContext('2d');
    if (modalNetChart) modalNetChart.destroy();
    
    const rxGrad = getGradient(netCtx, 'rgb(34, 197, 94)');
    const txGrad = getGradient(netCtx, 'rgb(239, 68, 68)');
    
    modalNetChart = new Chart(netCtx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                { label: 'RX (MB)', data: rxData, borderColor: '#22c55e', borderWidth: 2, backgroundColor: rxGrad, fill: true },
                { label: 'TX (MB)', data: txData, borderColor: '#ef4444', borderWidth: 2, backgroundColor: txGrad, fill: true }
            ]
        },
        options: { 
            ...commonOptions, 
            scales: { 
                x: { display: false }, 
                y: { 
                    beginAtZero: true, 
                    grid: { color: gridColor },
                    ticks: { color: tickColor, font: { size: 10 } } 
                }
            } 
        }
    });
}

async function loadNodeServices(token) {
    const container = document.getElementById('modalServicesContainer');
    const btnContainer = document.getElementById('modalServicesToggle');
    try {
        const response = await fetch(`/api/nodes/monitor/services?token=${encodeURIComponent(token)}`);
        if (!response.ok) throw new Error('Failed to load services');
        
        const data = await response.json();
        const services = data.services || [];
        
        if (services.length === 0) {
            container.innerHTML = `<div class="col-span-full text-center py-4 text-gray-400">${I18N?.web_services_empty || 'No services'}</div>`;
            if (btnContainer) btnContainer.classList.add('hidden');
            return;
        }
        
        const INITIAL_SHOW = 4;
        const showAll = container.dataset.showAll === 'true';
        const displayServices = showAll ? services : services.slice(0, INITIAL_SHOW);
        
        container.innerHTML = displayServices.map(svc => `
            <div class="flex items-center justify-between bg-white/50 dark:bg-black/30 p-2 rounded-lg">
                <div class="flex items-center gap-2">
                    <span class="${svc.status === 'running' ? 'text-green-500' : 'text-red-500'}">●</span>
                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${escapeHtml(svc.name)}</span>
                </div>
                <div class="flex gap-1">
                    <button onclick="nodeServiceAction('${token}', '${svc.name}', 'restart')" class="p-1 text-yellow-600 dark:text-yellow-400 hover:bg-yellow-100 dark:hover:bg-yellow-500/20 rounded" title="Restart">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    </button>
                    <button onclick="nodeServiceAction('${token}', '${svc.name}', '${svc.status === 'running' ? 'stop' : 'start'}')" 
                            class="p-1 ${svc.status === 'running' ? 'text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20' : 'text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-500/20'} rounded"
                            title="${svc.status === 'running' ? 'Stop' : 'Start'}">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            ${svc.status === 'running' 
                                ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />'
                                : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
                            }
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
        
        // Show/hide toggle button
        if (btnContainer) {
            if (services.length > INITIAL_SHOW) {
                btnContainer.classList.remove('hidden');
                const btn = btnContainer.querySelector('button');
                const blurOverlay = btnContainer.querySelector('.services-blur-overlay');
                if (btn) {
                    if (showAll) {
                        btn.classList.add('expanded');
                        if (blurOverlay) blurOverlay.style.display = 'none';
                        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" /></svg> ${I18N?.web_show_less || 'Show Less'}`;
                    } else {
                        btn.classList.remove('expanded');
                        if (blurOverlay) blurOverlay.style.display = '';
                        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg> ${I18N?.web_show_more || 'Show More'} (${services.length - INITIAL_SHOW})`;
                    }
                }
            } else {
                btnContainer.classList.add('hidden');
            }
        }
    } catch (error) {
        container.innerHTML = `<div class="col-span-full text-center py-4 text-red-400">${I18N?.web_error || 'Error'}</div>`;
        if (btnContainer) btnContainer.classList.add('hidden');
    }
}

function toggleServicesDisplay() {
    const container = document.getElementById('modalServicesContainer');
    const isShowingAll = container.dataset.showAll === 'true';
    container.dataset.showAll = !isShowingAll;
    loadNodeServices(currentNodeToken);
}

function refreshNodeServices() {
    if (currentNodeToken) {
        loadNodeServices(currentNodeToken);
    }
}

// Node commands from modal
function nodeCommand(cmd) {
    if (!currentNodeToken) return;
    
    const node = allNodesData.find(n => n.token === currentNodeToken);
    const name = node ? node.name : 'Node';
    
    if (cmd === 'reboot') {
        showConfirm(
            I18N?.modal_title_confirm || 'Confirm',
            (I18N?.web_reboot_node_confirm || 'Reboot {name}?').replace('{name}', name),
            async () => {
                await sendNodeCommand(currentNodeToken, cmd);
                showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_command_sent || 'Command sent');
                closeNodeDetailModal();
                loadNodes();
            }
        );
    } else {
        sendNodeCommand(currentNodeToken, cmd).then(() => {
            showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_command_sent || 'Command sent');
        });
    }
}

async function nodeServiceAction(token, service, action) {
    try {
        const response = await fetch('/api/nodes/monitor/service_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, service, action })
        });
        
        if (!response.ok) throw new Error('Service action failed');
        
        showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_command_sent || 'Command sent');
        setTimeout(() => loadNodeServices(token), 2000);
    } catch (error) {
        showAlert(I18N?.modal_title_error || 'Error', error.message);
    }
}

// Send command to node
async function sendNodeCommand(token, command) {
    const response = await fetch('/api/nodes/monitor/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, command })
    });
    
    if (!response.ok) {
        throw new Error('Command failed');
    }
    
    return response.json();
}

// Refresh
function refreshAllNodes() {
    loadNodes();
}

// Utility functions
function formatUptime(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    
    const parts = [];
    if (d > 0) parts.push(`${d}${I18N?.web_time_d || 'd'}`);
    if (h > 0) parts.push(`${h}${I18N?.web_time_h || 'h'}`);
    parts.push(`${m}${I18N?.web_time_m || 'm'}`);
    
    return parts.join(' ');
}

function formatTraffic(traffic) {
    const rx = traffic.rx || 0;
    const tx = traffic.tx || 0;
    return `↓${formatBytes(rx)} ↑${formatBytes(tx)}`;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Modal functions
function showAlert(title, message) {
    const modal = document.getElementById('systemModal');
    document.getElementById('sysModalTitle').textContent = title;
    document.getElementById('sysModalMessage').textContent = message;
    document.getElementById('sysModalCancel').classList.add('hidden');
    document.getElementById('sysModalOk').onclick = () => closeSystemModal(null);
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function showConfirm(title, message, onConfirm) {
    const modal = document.getElementById('systemModal');
    document.getElementById('sysModalTitle').textContent = title;
    document.getElementById('sysModalMessage').textContent = message;
    document.getElementById('sysModalCancel').classList.remove('hidden');
    document.getElementById('sysModalCancel').onclick = () => closeSystemModal(null);
    document.getElementById('sysModalOk').onclick = () => {
        closeSystemModal(null);
        if (onConfirm) onConfirm();
    };
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeSystemModal() {
    document.getElementById('systemModal').classList.add('hidden');
    document.getElementById('systemModal').classList.remove('flex');
}

// Theme toggle (if not defined in common.js)
if (typeof toggleTheme === 'undefined') {
    function toggleTheme() {
        const html = document.documentElement;
        const current = html.classList.contains('dark') ? 'dark' : 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        
        if (next === 'dark') {
            html.classList.add('dark');
        } else {
            html.classList.remove('dark');
        }
        
        localStorage.setItem('theme', next);
        updateThemeIcons();
    }
}

function updateThemeIcons() {
    const theme = localStorage.getItem('theme') || 'system';
    if (typeof applyThemeUI === 'function') {
        applyThemeUI(theme);
        return;
    }
    const isDark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.getElementById('iconMoon')?.classList.toggle('hidden', !isDark || theme === 'system');
    document.getElementById('iconSun')?.classList.toggle('hidden', isDark || theme === 'system');
    document.getElementById('iconSystem')?.classList.toggle('hidden', theme !== 'system');
}
