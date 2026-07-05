/**
 * Nodes Monitor Page JavaScript
 * Real-time monitoring dashboard for all nodes
 */

let allNodesData = [];
let currentFilter = 'all';
let currentCpuFilter = 'all';
let currentSort = 'name';
let searchQuery = '';
let selectedNodes = new Set();
let currentNodeToken = null;
let modalResChart = null;
let modalNetChart = null;
let nodesMonitorSSESource = null;
let nodeDetailSSESource = null;
let nodeServicesSSESource = null;
let _lastServicesCache = null; // cached services for stable DOM updates

function decryptData(text) {
    if (!text) return "";
    if (typeof WEB_KEY === 'undefined' || !WEB_KEY) return text;
    try {
        const decoded = atob(text);
        const bytes = new Uint8Array(decoded.length);
        for (let index = 0; index < decoded.length; index++) {
            const keyChar = WEB_KEY.charCodeAt(index % WEB_KEY.length);
            bytes[index] = decoded.charCodeAt(index) ^ keyChar;
        }
        return new TextDecoder().decode(bytes);
    } catch (error) {
        console.error('Decryption error:', error);
        return text;
    }
}

function normalizeNode(node) {
    const decryptedName = decryptData(node.name) || 'Unknown';
    const decryptedIp = decryptData(node.ip) || '-';
    const decryptedPing = decryptData(node.ping);

    return {
        ...node,
        name: decryptedName,
        ip: decryptedIp,
        ping: decryptedPing !== '' && decryptedPing != null
            ? (decryptedPing === 'n/a' ? 'n/a' : Number(decryptedPing))
            : null,
        availability: node.availability || null,
    };
}

function getAvailabilityNote(availability) {
    if (!availability || !availability.has_ongoing_outage) return '';
    if (availability.ongoing_outage_kind === 'physical') {
        return `${I18N?.web_nodes_monitor_outage_rebooting || 'Current outage is caused by a reboot'}: ${availability.current_downtime}`;
    }
    return `${I18N?.web_nodes_monitor_outage_pending || 'The reason will be determined after the node reconnects'}: ${availability.current_downtime}`;
}

function initUptimeTooltip() {
    const trigger = document.getElementById('modalUptimeTrigger');
    const popover = document.getElementById('availabilityPopover');
    if (!trigger || !popover || trigger.dataset.tooltipInit) return;
    trigger.dataset.tooltipInit = '1';

    let leaveTimeout = null;

    function isVisible() {
        return !popover.classList.contains('hidden');
    }

    function positionAndShow() {
        const rect = trigger.getBoundingClientRect();
        const popW = 288;
        const vpW = window.innerWidth;
        const vpH = window.innerHeight;

        popover.classList.remove('hidden');
        popover.style.opacity = '0';

        let left = rect.left;
        if (left + popW > vpW - 16) left = vpW - popW - 16;
        if (left < 8) left = 8;

        const spaceBelow = vpH - rect.bottom - 8;
        const spaceAbove = rect.top - 8;
        let top;
        if (spaceBelow >= 260 || spaceBelow >= spaceAbove) {
            top = rect.bottom + 8;
        } else {
            top = rect.top - 260;
        }
        popover.style.top = top + 'px';
        popover.style.left = left + 'px';

        trigger.setAttribute('aria-expanded', 'true');
        requestAnimationFrame(() => { popover.style.opacity = '1'; });
    }

    function hidePopover() {
        popover.style.opacity = '0';
        trigger.setAttribute('aria-expanded', 'false');
        setTimeout(() => {
            if (popover.style.opacity === '0') popover.classList.add('hidden');
        }, 150);
    }

    trigger.addEventListener('mouseenter', () => { clearTimeout(leaveTimeout); positionAndShow(); });
    trigger.addEventListener('mouseleave', () => { leaveTimeout = setTimeout(hidePopover, 100); });
    popover.addEventListener('mouseenter', () => { clearTimeout(leaveTimeout); });
    popover.addEventListener('mouseleave', () => { leaveTimeout = setTimeout(hidePopover, 100); });

    trigger.addEventListener('click', (e) => {
        if (isVisible()) hidePopover(); else positionAndShow();
        e.stopPropagation();
    });
    trigger.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (isVisible()) hidePopover(); else positionAndShow(); }
        if (e.key === 'Escape') hidePopover();
    });
    document.addEventListener('click', (e) => {
        if (!trigger.contains(e.target) && !popover.contains(e.target)) { if (isVisible()) hidePopover(); }
    });
    window.addEventListener('resize', () => { if (isVisible()) positionAndShow(); });

    window.hideAvailabilityPopover = hidePopover;
}

function stopNodesMonitorStream() {
    if (nodesMonitorSSESource) {
        nodesMonitorSSESource.close();
        nodesMonitorSSESource = null;
    }
}

function stopNodeDetailStream() {
    if (nodeDetailSSESource) {
        nodeDetailSSESource.close();
        nodeDetailSSESource = null;
    }
}

function stopNodeServicesStream() {
    if (nodeServicesSSESource) {
        nodeServicesSSESource.close();
        nodeServicesSSESource = null;
    }
}

function stopNodeModalStreams() {
    stopNodeDetailStream();
    stopNodeServicesStream();
}

function connectNodesMonitorStream() {
    stopNodesMonitorStream();

    if (typeof EventSource === 'undefined') {
        console.error('EventSource is not supported in this browser');
        return;
    }

    nodesMonitorSSESource = new EventSource('/api/nodes/monitor/list');

    nodesMonitorSSESource.addEventListener('nodes_list', (event) => {
        try {
            const data = JSON.parse(event.data);
            allNodesData = Array.isArray(data.nodes) ? data.nodes.map(normalizeNode) : [];
            selectedNodes = new Set([...selectedNodes].filter(token => allNodesData.some(node => node.token === token)));
            updateStats();
            renderNodes();
        } catch (error) {
            console.error('Error parsing nodes monitor SSE payload:', error);
        }
    });

    nodesMonitorSSESource.addEventListener('session_status', (event) => {
        if (event.data === 'expired') {
            stopNodesMonitorStream();
            window.location.assign('/login');
        }
    });

    nodesMonitorSSESource.addEventListener('shutdown', () => {
        stopNodesMonitorStream();
    });

    nodesMonitorSSESource.onerror = () => {
        if (nodesMonitorSSESource?.readyState === EventSource.CLOSED) {
            stopNodesMonitorStream();
        }
    };
}

// Initialize function for SPA navigation
function initNodesMonitor() {
    stopNodesMonitorStream();
    
    // Reset state
    allNodesData = [];
    currentFilter = 'all';
    currentCpuFilter = 'all';
    currentSort = 'name';
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
    
    // Subscribe to node updates
    connectNodesMonitorStream();
    
    // Setup theme
    if (typeof applyThemeUI === 'function') {
        applyThemeUI(localStorage.getItem('theme') || 'system');
    } else if (typeof updateThemeIcons === 'function') {
        updateThemeIcons();
    }

    initUptimeTooltip();
}

// Expose functions to window
window.initNodesMonitor = initNodesMonitor;
window.toggleServicesDisplay = toggleServicesDisplay;

// Wire service action buttons rendered inside the modal
document.addEventListener('app:action:node-service-action', (e) => {
    const el = e.detail?.target;
    if (!el) return;
    const token = el.dataset.token;
    const name = el.dataset.name;
    const cmd = el.dataset.cmd;
    const type = el.dataset.type || 'systemd';
    if (!token || !name || !cmd) return;

    const cmdLabels = {
        restart: I18N?.web_service_restart || 'restart',
        stop:    I18N?.web_service_stop    || 'stop',
        start:   I18N?.web_service_start   || 'start',
    };
    const actionLabel = cmdLabels[cmd] || cmd;

    showConfirm(
        I18N?.modal_title_confirm || 'Confirm',
        (I18N?.web_service_confirm || 'Execute {action} for {name}?')
            .replace('{action}', actionLabel.toLowerCase())
            .replace('{name}', name),
        () => nodeServiceAction(token, name, cmd, type)
    );
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initNodesMonitor();
});

window.addEventListener('beforeunload', () => {
    stopNodesMonitorStream();
    stopNodeModalStreams();
});

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
    
    // Status filter
    if (currentFilter === 'online') {
        filtered = filtered.filter(n => n.status === 'online');
    } else if (currentFilter === 'offline') {
        filtered = filtered.filter(n => n.status !== 'online' && n.status !== 'restarting');
    } else if (currentFilter === 'restarting') {
        filtered = filtered.filter(n => n.status === 'restarting');
    }
    
    // CPU load filter
    if (currentCpuFilter === 'high') {
        filtered = filtered.filter(n => (n.cpu || 0) > 80);
    } else if (currentCpuFilter === 'medium') {
        filtered = filtered.filter(n => (n.cpu || 0) >= 50 && (n.cpu || 0) <= 80);
    } else if (currentCpuFilter === 'low') {
        filtered = filtered.filter(n => (n.cpu || 0) < 50);
    }
    
    // Search filter
    if (searchQuery) {
        const q = searchQuery.toLowerCase();
        filtered = filtered.filter(n => 
            n.name.toLowerCase().includes(q) || 
            (n.ip && n.ip.toLowerCase().includes(q))
        );
    }
    
    // Sort
    filtered = [...filtered].sort((a, b) => {
        switch (currentSort) {
            case 'cpu':
                return (b.cpu || 0) - (a.cpu || 0);
            case 'ram':
                return (b.ram || 0) - (a.ram || 0);
            case 'ping':
                const pingA = a.ping != null ? parseFloat(a.ping) : Infinity;
                const pingB = b.ping != null ? parseFloat(b.ping) : Infinity;
                return pingA - pingB;
            case 'name':
            default:
                return a.name.localeCompare(b.name);
        }
    });
    
    if (filtered.length === 0) {
        container.innerHTML = DOMPurify.sanitize(`
            <div class="col-span-full text-center py-12 text-gray-500 dark:text-gray-400">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto mb-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                ${I18N?.web_no_nodes || 'No nodes found'}
            </div>
        `);
        return;
    }
    
    const newHtml = filtered.map(node => createNodeCard(node)).join('');
    
    // Try to update in-place to prevent flicker
    const tempContainer = container.cloneNode(false);
    tempContainer.innerHTML = DOMPurify.sanitize(newHtml);
    
    if (!updateDOM(container, tempContainer)) {
        // Fallback if structural changes occurred
        container.innerHTML = DOMPurify.sanitize(newHtml);
    }
}

// Get ping badge CSS classes based on latency value
function getPingBadgeClass(ping) {
    if (ping === 'n/a' || Number.isNaN(Number(ping))) return 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400';
    if (ping < 50) return 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400';
    if (ping < 150) return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400';
    return 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400';
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
    const availability = node.availability || {};
    const lastOutage = availability.last_downtime || '-';
    const totalDowntime = availability.total_downtime || '-';
    
    const isSelected = selectedNodes.has(node.token);
    
    return `
        <div class="node-card bg-white/60 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/10 rounded-2xl overflow-hidden shadow-lg dark:shadow-none hover:scale-[1.02] transition duration-300 ${isSelected ? 'ring-2 ring-blue-500' : ''}" 
             data-token="${node.token}" data-status="${node.status}" data-name="${node.name.toLowerCase()}">
            
            <!-- Header -->
            <div class="p-4 border-b border-gray-100 dark:border-white/5 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    ${(typeof USER_ROLE !== 'undefined' && USER_ROLE !== 'users') ? `
                    <input type="checkbox" class="node-checkbox rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500" 
                           ${isSelected ? 'checked' : ''} 
                           data-action="toggle-node-selection" data-token="${node.token}">
                    ` : ''}
                    <div>
                        <h3 class="font-bold text-gray-900 dark:text-white text-sm">${typeof replaceEmojisWithFlagsHTML === 'function' ? replaceEmojisWithFlagsHTML(escapeHtml(node.name)) : escapeHtml(node.name)}</h3>
                        <div class="flex items-center gap-1.5">
                            <span class="text-xs text-gray-500 dark:text-gray-400">${node.ip || '-'}</span>
                            ${node.ping != null ? (node.ping === 'n/a' ? `<span onclick="window.showPingErrorModal(event)" class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold cursor-pointer hover:opacity-80 transition-opacity ${getPingBadgeClass(node.ping)}" title="Click for details">n/a</span>` : `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold ${getPingBadgeClass(node.ping)}">${parseFloat(node.ping)}ms</span>`) : ''}
                        </div>
                    </div>
                </div>
                <span class="px-2 py-1 rounded-lg text-xs font-bold ${statusClass}">
                    ${statusIcon} ${statusText}
                </span>
            </div>
            
            <!-- Stats -->
            <div class="px-3 py-3">
                <!-- Circular Progress Indicators -->
                <div class="flex justify-between items-center gap-2">
                    <!-- CPU Circle -->
                    <div class="flex flex-col items-center flex-1">
                        <div class="relative w-full" style="max-width: 64px; aspect-ratio: 1;">
                            <svg viewBox="0 0 48 48" class="w-full h-full" style="transform: rotate(-90deg);">
                                <circle cx="24" cy="24" r="20" fill="none" stroke="rgba(99,102,241,0.15)" stroke-width="4"></circle>
                                <circle cx="24" cy="24" r="20" fill="none" stroke="#6366f1" stroke-width="4" 
                                    stroke-dasharray="${(cpu / 100) * 125.6} 125.6" stroke-linecap="round"></circle>
                            </svg>
                            <div class="absolute inset-0 flex items-center justify-center">
                                <span class="text-sm font-bold" style="color: #6366f1;">${cpu}</span>
                            </div>
                        </div>
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 font-semibold mt-1 uppercase tracking-wide">${I18N?.web_cpu || 'CPU'}</span>
                    </div>
                    
                    <!-- RAM Circle -->
                    <div class="flex flex-col items-center flex-1">
                        <div class="relative w-full" style="max-width: 64px; aspect-ratio: 1;">
                            <svg viewBox="0 0 48 48" class="w-full h-full" style="transform: rotate(-90deg);">
                                <circle cx="24" cy="24" r="20" fill="none" stroke="rgba(168,85,247,0.15)" stroke-width="4"></circle>
                                <circle cx="24" cy="24" r="20" fill="none" stroke="#a855f7" stroke-width="4" 
                                    stroke-dasharray="${(ram / 100) * 125.6} 125.6" stroke-linecap="round"></circle>
                            </svg>
                            <div class="absolute inset-0 flex items-center justify-center">
                                <span class="text-sm font-bold" style="color: #a855f7;">${ram}</span>
                            </div>
                        </div>
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 font-semibold mt-1 uppercase tracking-wide">${I18N?.web_ram || 'RAM'}</span>
                    </div>
                    
                    <!-- Disk Circle -->
                    <div class="flex flex-col items-center flex-1">
                        <div class="relative w-full" style="max-width: 64px; aspect-ratio: 1;">
                            <svg viewBox="0 0 48 48" class="w-full h-full" style="transform: rotate(-90deg);">
                                <circle cx="24" cy="24" r="20" fill="none" stroke="rgba(34,197,94,0.15)" stroke-width="4"></circle>
                                <circle cx="24" cy="24" r="20" fill="none" stroke="#22c55e" stroke-width="4" 
                                    stroke-dasharray="${(disk / 100) * 125.6} 125.6" stroke-linecap="round"></circle>
                            </svg>
                            <div class="absolute inset-0 flex items-center justify-center">
                                <span class="text-sm font-bold" style="color: #22c55e;">${disk}</span>
                            </div>
                        </div>
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 font-semibold mt-1 uppercase tracking-wide">${I18N?.web_disk || 'Disk'}</span>
                    </div>
                </div>
                
                <!-- Info Row -->
                <div class="flex justify-between text-xs text-gray-500 dark:text-gray-400 pt-2 mt-2 border-t border-gray-100 dark:border-white/5">
                    <span>⏱ ${uptime}</span>
                    <span>📊 ${traffic}</span>
                </div>
                <div class="mt-2 pt-2 border-t border-gray-100 dark:border-white/5 text-[11px] text-gray-500 dark:text-gray-400 space-y-1">
                    <div class="flex justify-between gap-2">
                        <span>${I18N?.web_nodes_monitor_last_outage || 'Last outage'}</span>
                        <span class="font-mono text-right">${escapeHtml(lastOutage)}</span>
                    </div>
                    <div class="flex justify-between gap-2">
                        <span>${I18N?.web_nodes_monitor_total_downtime || 'Total downtime'}</span>
                        <span class="font-mono text-right">${escapeHtml(totalDowntime)}</span>
                    </div>
                </div>
            </div>
            
            <!-- Actions -->
            <div class="px-4 pb-4 mb-3 pt-1 flex gap-2">
                <button data-action="open-node-detail" data-token="${node.token}" class="flex-1 px-3 py-2 bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 rounded-xl text-xs font-bold hover:bg-blue-200 dark:hover:bg-blue-500/30 transition">
                    ${I18N?.web_node_details || 'Node Details'}
                </button>
                ${(typeof USER_ROLE !== 'undefined' && USER_ROLE !== 'users') ? `
                <button data-action="quick-reboot" data-token="${node.token}" class="node-reboot-btn px-3 py-2 text-red-600 dark:text-red-400 rounded-xl text-xs font-bold hover:bg-red-200 transition" title="Reboot">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                </button>` : ''}
            </div>
        </div>
    `;
}

// Filtering functions
function filterNodes(query) {
    searchQuery = query;
    renderNodes();
}

// Filter Modal functions
let tempFilterStatus = 'all';
let tempFilterCpu = 'all';
let tempFilterSort = 'name';

function openFilterModal() {
    tempFilterStatus = currentFilter;
    tempFilterCpu = currentCpuFilter;
    tempFilterSort = currentSort;
    updateFilterModalUI();
    const modal = document.getElementById('filterModal');
    if (typeof animateModalOpen === 'function') {
        animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function closeFilterModal() {
    const modal = document.getElementById('filterModal');
    if (typeof animateModalClose === 'function') {
        animateModalClose(modal);
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function updateFilterModalUI() {
    // Status buttons
    document.querySelectorAll('.filter-status-btn').forEach(btn => {
        btn.className = 'filter-status-btn px-3 py-2 text-sm font-medium rounded-lg transition focus:outline-none bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 border-2 border-transparent';
    });
    const statusBtn = document.getElementById('fStatus' + tempFilterStatus.charAt(0).toUpperCase() + tempFilterStatus.slice(1));
    if (statusBtn) {
        statusBtn.className = 'filter-status-btn px-3 py-2 text-sm font-medium rounded-lg transition focus:outline-none bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 border-2 border-blue-500';
    }
    
    // CPU buttons
    document.querySelectorAll('.filter-cpu-btn').forEach(btn => {
        btn.className = 'filter-cpu-btn px-3 py-2 text-sm font-medium rounded-lg transition focus:outline-none bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 border-2 border-transparent';
    });
    const cpuBtn = document.getElementById('fCpu' + tempFilterCpu.charAt(0).toUpperCase() + tempFilterCpu.slice(1));
    if (cpuBtn) {
        cpuBtn.className = 'filter-cpu-btn px-3 py-2 text-sm font-medium rounded-lg transition focus:outline-none bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 border-2 border-blue-500';
    }
    
    // Sort buttons
    document.querySelectorAll('.filter-sort-btn').forEach(btn => {
        btn.className = 'filter-sort-btn px-3 py-2 text-sm font-medium rounded-lg transition focus:outline-none bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 border-2 border-transparent';
    });
    const sortBtn = document.getElementById('fSort' + tempFilterSort.charAt(0).toUpperCase() + tempFilterSort.slice(1));
    if (sortBtn) {
        sortBtn.className = 'filter-sort-btn px-3 py-2 text-sm font-medium rounded-lg transition focus:outline-none bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 border-2 border-blue-500';
    }
}

function setFilterStatus(status) {
    tempFilterStatus = status;
    updateFilterModalUI();
}

function setFilterCpu(cpu) {
    tempFilterCpu = cpu;
    updateFilterModalUI();
}

function setFilterSort(sort) {
    tempFilterSort = sort;
    updateFilterModalUI();
}

function resetFilters() {
    tempFilterStatus = 'all';
    tempFilterCpu = 'all';
    tempFilterSort = 'name';
    updateFilterModalUI();
}

function applyFilters() {
    currentFilter = tempFilterStatus;
    currentCpuFilter = tempFilterCpu;
    currentSort = tempFilterSort;
    updateFilterBadge();
    renderNodes();
    closeFilterModal();
}

function updateFilterBadge() {
    const badge = document.getElementById('filterBadge');
    let count = 0;
    if (currentFilter !== 'all') count++;
    if (currentCpuFilter !== 'all') count++;
    if (currentSort !== 'name') count++;
    
    if (count > 0) {
        badge.textContent = count;
        badge.classList.remove('hidden');
        badge.classList.add('flex');
    } else {
        badge.classList.add('hidden');
        badge.classList.remove('flex');
    }
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
        connectNodesMonitorStream();
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
            connectNodesMonitorStream();
        }
    );
}

// Node detail modal
async function openNodeDetail(token) {
    currentNodeToken = token;
    const modal = document.getElementById('nodeDetailModal');
    
    if (typeof animateModalOpen === 'function') {
        animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    connectNodeDetailStream(token);
    connectNodeServicesStream(token);
}

function closeNodeDetailModal() {
    const modal = document.getElementById('nodeDetailModal');
    if (typeof animateModalClose === 'function') {
        animateModalClose(modal);
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    currentNodeToken = null;
    _lastServicesCache = null; // reset so next node gets a fresh render

    if (typeof window.hideAvailabilityPopover === 'function') window.hideAvailabilityPopover();

    stopNodeModalStreams();
    
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

function connectNodeDetailStream(token) {
    stopNodeDetailStream();

    nodeDetailSSESource = new EventSource(`/api/events/node?token=${encodeURIComponent(token)}`);

    nodeDetailSSESource.addEventListener('node_details', (event) => {
        try {
            const data = JSON.parse(event.data);
            updateNodeModal(data);
        } catch (error) {
            console.error('Node detail SSE parse error:', error);
        }
    });

    nodeDetailSSESource.addEventListener('session_status', (event) => {
        if (event.data === 'expired') {
            stopNodeModalStreams();
            window.location.assign('/login');
        }
    });

    nodeDetailSSESource.addEventListener('shutdown', () => {
        stopNodeDetailStream();
    });

    nodeDetailSSESource.onerror = () => {
        if (nodeDetailSSESource?.readyState === EventSource.CLOSED) {
            stopNodeDetailStream();
        }
    };
}

function updateNodeModal(data) {
    const newTitleHtml = typeof replaceEmojisWithFlagsHTML === 'function' ? replaceEmojisWithFlagsHTML(escapeHtml(decryptData(data.name) || 'Unknown')) : escapeHtml(decryptData(data.name) || 'Unknown');
    const modalTitleEl = document.getElementById('modalNodeTitle');
    const tempTitle = modalTitleEl.cloneNode(false);
    tempTitle.innerHTML = DOMPurify.sanitize(newTitleHtml);
    if (!updateDOM(modalTitleEl, tempTitle)) {
        modalTitleEl.innerHTML = DOMPurify.sanitize(newTitleHtml);
    }
    if (typeof parsePageEmojis === 'function') parsePageEmojis(modalTitleEl);
    
    const nameContainer = modalTitleEl.parentElement;
    if (nameContainer) {
        const badgeEl = document.getElementById('monitorNodeBillingBadge');
        if (badgeEl) {
            const isSet = data.billing_amount !== null && data.billing_amount !== undefined;
            if (isSet || data.next_payment_date) {
                const daysLeft = window.calculateDaysLeft ? window.calculateDaysLeft(data.next_payment_date) : null;
                const billingIconColor = daysLeft === null ? 'text-gray-400' : daysLeft < 0 ? 'text-red-500 dark:text-red-400' : daysLeft <= 6 ? 'text-yellow-500 dark:text-yellow-400' : 'text-green-500 dark:text-green-400';
                const fragment = DOMPurify.sanitize(`
                    <button class="flex items-center h-5 px-1.5 rounded hover:bg-black/5 dark:hover:bg-white/10 transition text-gray-500 dark:text-gray-400 text-[10px] gap-1 whitespace-nowrap group">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 ${billingIconColor} transition-colors flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
                        </svg>
                        ${window.getBillingBadgeHtml ? window.getBillingBadgeHtml(daysLeft) : ''}
                    </button>
                `, { RETURN_DOM_FRAGMENT: true });
                badgeEl.textContent = '';
                badgeEl.appendChild(fragment);
                const badgeBtn = badgeEl.querySelector('button');
                if (badgeBtn) {
                    badgeBtn.onclick = () => {
                        window.showBillingModal(
                            decryptData(data.name) || 'Unknown',
                            data.billing_amount !== null && data.billing_amount !== undefined ? data.billing_amount : null,
                            data.currency || '$',
                            data.next_payment_date || null,
                            daysLeft
                        );
                    };
                }
                badgeEl.classList.remove('hidden');
            } else {
                badgeEl.classList.add('hidden');
            }
        }
    }
    
    const newIp = decryptData(data.ip) || '-';
    const ipEl = document.getElementById('modalNodeIp');
    if (ipEl.textContent !== newIp) ipEl.textContent = newIp;
    
    // Update ping badge in modal
    const pingBadge = document.getElementById('modalNodePingBadge');
    const stats = data.stats || {};
    const pingValue = decryptData(stats.ping);
    if (pingValue !== '' && pingValue != null) {
        if (pingValue === 'n/a') {
            pingBadge.className = `inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold cursor-pointer hover:opacity-80 transition-opacity ${getPingBadgeClass(pingValue)}`;
            pingBadge.textContent = 'n/a';
            pingBadge.onclick = window.showPingErrorModal;
            pingBadge.title = "Click for details";
        } else {
            pingBadge.className = `inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold ${getPingBadgeClass(pingValue)}`;
            pingBadge.textContent = parseFloat(pingValue) + 'ms';
            pingBadge.onclick = null;
            pingBadge.title = "";
        }
    } else {
        pingBadge.className = 'hidden';
        pingBadge.textContent = '';
    }
    
    const isRestarting = data.status === 'restarting';
    const isOnline = data.status === 'online';
    const statusIcon = document.getElementById('modalNodeStatusIcon');
    const statusBadge = document.getElementById('modalNodeStatusBadge');
    const statusDot = document.getElementById('modalNodeStatusDot');
    const statusText = document.getElementById('modalNodeStatus');
    
    if (isRestarting) {
        statusIcon.className = 'p-2 bg-blue-100 dark:bg-blue-500/20 rounded-lg text-blue-600 dark:text-blue-400';
        statusBadge.className = 'flex items-center gap-1 text-blue-600 dark:text-blue-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse';
        statusText.textContent = I18N?.web_node_status_restarting || 'Restarting';
    } else if (isOnline) {
        statusIcon.className = 'p-2 bg-green-100 dark:bg-green-500/20 rounded-lg text-green-600 dark:text-green-400';
        statusBadge.className = 'flex items-center gap-1 text-green-600 dark:text-green-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse';
        statusText.textContent = I18N?.web_node_status_online || 'Online';
    } else {
        statusIcon.className = 'p-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-600 dark:text-red-400';
        statusBadge.className = 'flex items-center gap-1 text-red-600 dark:text-red-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-red-500';
        statusText.textContent = I18N?.web_node_status_offline || 'Offline';
    }
    
    document.getElementById('modalUptime').textContent = formatUptime(stats.uptime || 0);
    document.getElementById('modalCpu').textContent = (stats.cpu || 0) + '%';
    document.getElementById('modalRam').textContent = (stats.ram || 0) + '%';
    document.getElementById('modalDisk').textContent = (stats.disk || 0) + '%';

    const availability = data.availability || {};
    const titleEl = document.getElementById('availabilityPopoverTitle');
    if (titleEl) titleEl.textContent = I18N?.web_avail_header || 'Uptime / Downtime';
    document.getElementById('availabilityLabelCurrentUptime').textContent = I18N?.web_nodes_monitor_current_uptime || 'Current uptime';
    document.getElementById('availabilityLabelLastOutage').textContent = I18N?.web_nodes_monitor_last_outage || 'Last outage';
    document.getElementById('availabilityLabelLastReboot').textContent = I18N?.web_nodes_monitor_last_reboot || 'Last reboot';
    document.getElementById('availabilityLabelTotalUptime').textContent = I18N?.web_nodes_monitor_total_uptime || 'Total uptime';
    document.getElementById('availabilityLabelTotalDowntime').textContent = I18N?.web_nodes_monitor_total_downtime || 'Total downtime';
    document.getElementById('availabilityLabelInternetDowntime').textContent = I18N?.web_nodes_monitor_internet_downtime || 'Internet downtime';
    document.getElementById('availabilityLabelPhysicalDowntime').textContent = I18N?.web_nodes_monitor_physical_downtime || 'Physical downtime';
    document.getElementById('modalAvailabilityCurrentUptime').textContent = availability.current_uptime || '-';
    document.getElementById('modalAvailabilityLastOutage').textContent = availability.last_downtime || '-';
    document.getElementById('modalAvailabilityLastReboot').textContent = availability.last_reboot || '-';
    document.getElementById('modalAvailabilityTotalUptime').textContent = availability.total_uptime || '-';
    document.getElementById('modalAvailabilityTotalDowntime').textContent = availability.total_downtime || '-';
    document.getElementById('modalAvailabilityInternetDowntime').textContent = availability.internet_downtime || '-';
    document.getElementById('modalAvailabilityPhysicalDowntime').textContent = availability.physical_downtime || '-';
    document.getElementById('modalAvailabilityNote').textContent = getAvailabilityNote(availability);
    
    // Handle reset button visibility based on whether we are at system defaults
    const isDefault = (availability.total_downtime_secs || 0) === 0;
    const resetBtn = document.getElementById('modalAvailabilityResetBtn');
    if (resetBtn) {
        if (!isDefault && typeof USER_ROLE !== 'undefined' && USER_ROLE !== 'users') resetBtn.classList.remove('hidden');
        else resetBtn.classList.add('hidden');
    }

    // Update charts
    updateModalCharts(data.history || []);
}

function updateModalCharts(history) {
    if (!history || history.length < 2) return;

    const gapThreshold = 25;
    const labels = [];
    const cpuData = [];
    const ramData = [];
    const rxData = [];
    const txData = [];

    labels.push(new Date(history[0].t * 1000).toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    }));
    cpuData.push(history[0].c || 0);
    ramData.push(history[0].r || 0);
    rxData.push(0);
    txData.push(0);

    for (let i = 1; i < history.length; i++) {
        const dt = history[i].t - history[i - 1].t;
        if (dt > gapThreshold) {
            labels.push("");
            cpuData.push(null);
            ramData.push(null);
            rxData.push(null);
            txData.push(null);
        }
        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        }));
        cpuData.push(history[i].c || 0);
        ramData.push(history[i].r || 0);
        
        const dtFixed = Math.max(dt, 1);
        rxData.push((Math.max(0, history[i].rx - history[i - 1].rx) * 8 / dtFixed / 1024));
        txData.push((Math.max(0, history[i].tx - history[i - 1].tx) * 8 / dtFixed / 1024));
    }
    
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    const isMobile = window.innerWidth < 640;

    function getGradient(ctx, color) {
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, color.replace('rgb', 'rgba').replace(')', ', 0.5)'));
        gradient.addColorStop(1, color.replace('rgb', 'rgba').replace(')', ', 0.0)'));
        return gradient;
    }

    const resCtx = document.getElementById('modalResChart').getContext('2d');
    const netCtx = document.getElementById('modalNetChart').getContext('2d');

    const interactiveOptions = window.buildInteractiveChartOptions ? window.buildInteractiveChartOptions({}) : {};

    if (modalResChart) {
        const applyModalResChartData = () => {
            modalResChart.data.labels = labels;
            modalResChart.data.datasets[0].data = cpuData;
            modalResChart.data.datasets[1].data = ramData;

            modalResChart.data.datasets[0].backgroundColor = getGradient(resCtx, 'rgb(59, 130, 246)');
            modalResChart.data.datasets[1].backgroundColor = getGradient(resCtx, 'rgb(168, 85, 247)');

            modalResChart.options.scales.x.ticks.color = tickColor;
            modalResChart.options.scales.y.grid.color = gridColor;
            modalResChart.options.scales.y.ticks.color = tickColor;
            modalResChart.options.plugins.legend.labels.color = tickColor;
        };

        if (window.updateChartWithLiveData) {
            window.updateChartWithLiveData(modalResChart, applyModalResChartData, 'modalResChart');
        } else {
            applyModalResChartData();
            modalResChart.update('none');
            if (window.attachChartInteractions) window.attachChartInteractions(modalResChart, 'modalResChart');
        }
    } else {
        modalResChart = new Chart(resCtx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'CPU (%)', data: cpuData, borderColor: '#3b82f6', borderWidth: 2, backgroundColor: getGradient(resCtx, 'rgb(59, 130, 246)'), fill: true },
                    { label: 'RAM (%)', data: ramData, borderColor: '#a855f7', borderWidth: 2, backgroundColor: getGradient(resCtx, 'rgb(168, 85, 247)'), fill: true }
                ]
            },
            options: {
                ...interactiveOptions,
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    ...(interactiveOptions.plugins || {}),
                    legend: { 
                        display: true, 
                        position: 'top', 
                        labels: { color: tickColor, boxWidth: 10, usePointStyle: true, font: { size: 10 } } 
                    } 
                },
                scales: {
                    x: { 
                        grid: { display: false },
                        ticks: { display: !isMobile, maxTicksLimit: isMobile ? 3 : 6, color: tickColor }
                    },
                    y: { 
                        beginAtZero: true, max: 100,
                        grid: { color: gridColor },
                        ticks: { color: tickColor, font: { size: 10 } }
                    }
                },
                elements: { line: { tension: 0.4 }, point: { radius: 0, hitRadius: 10 } }
            }
        });
        if (window.attachChartInteractions) window.attachChartInteractions(modalResChart, 'modalResChart');
    }
    
    if (modalNetChart) {
        const applyModalNetChartData = () => {
            modalNetChart.data.labels = labels;
            modalNetChart.data.datasets[0].data = rxData;
            modalNetChart.data.datasets[1].data = txData;

            modalNetChart.data.datasets[0].backgroundColor = getGradient(netCtx, 'rgb(34, 197, 94)');
            modalNetChart.data.datasets[1].backgroundColor = getGradient(netCtx, 'rgb(239, 68, 68)');

            modalNetChart.options.scales.x.ticks.color = tickColor;
            modalNetChart.options.scales.y.grid.color = gridColor;
            modalNetChart.options.scales.y.ticks.color = tickColor;
            modalNetChart.options.plugins.legend.labels.color = tickColor;
        };

        if (window.updateChartWithLiveData) {
            window.updateChartWithLiveData(modalNetChart, applyModalNetChartData, 'modalNetChart');
        } else {
            applyModalNetChartData();
            modalNetChart.update('none');
            if (window.attachChartInteractions) window.attachChartInteractions(modalNetChart, 'modalNetChart');
        }
    } else {
        modalNetChart = new Chart(netCtx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'RX', data: rxData, borderColor: '#22c55e', borderWidth: 2, backgroundColor: getGradient(netCtx, 'rgb(34, 197, 94)'), fill: true },
                    { label: 'TX', data: txData, borderColor: '#ef4444', borderWidth: 2, backgroundColor: getGradient(netCtx, 'rgb(239, 68, 68)'), fill: true }
                ]
            },
            options: {
                ...interactiveOptions,
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    ...(interactiveOptions.plugins || {}),
                    legend: { 
                        display: true, 
                        position: 'top', 
                        labels: { color: tickColor, boxWidth: 10, usePointStyle: true, font: { size: 10 } } 
                    } 
                },
                scales: {
                    x: { 
                        grid: { display: false },
                        ticks: { display: !isMobile, maxTicksLimit: isMobile ? 3 : 6, color: tickColor }
                    },
                    y: { 
                        beginAtZero: true,
                        grid: { color: gridColor },
                        ticks: { 
                            color: tickColor, 
                            font: { size: 10 },
                            callback: function(v) { return formatSpeed(v); }
                        }
                    }
                },
                elements: { line: { tension: 0.4 }, point: { radius: 0, hitRadius: 10 } }
            }
        });
        if (window.attachChartInteractions) window.attachChartInteractions(modalNetChart, 'modalNetChart');
    }
}

function connectNodeServicesStream(token) {
    stopNodeServicesStream();

    const container = document.getElementById('modalServicesContainer');
    if (container) {
        container.innerHTML = DOMPurify.sanitize(`<div class="text-center py-4 text-gray-400">${I18N?.web_services_loading || I18N?.web_loading || 'Loading'}</div>`);
        _lastServicesCache = null; // force full re-render on next data event
    }

    nodeServicesSSESource = new EventSource(`/api/events/node/services?token=${encodeURIComponent(token)}`);

    nodeServicesSSESource.addEventListener('node_services', (event) => {
        try {
            const data = JSON.parse(event.data);
            const services = (data.services || []).map((service) => ({
                name: decryptData(service.name),
                type: decryptData(service.type) || 'systemd',
                status: decryptData(service.status),
            }));
            renderNodeServices(token, services);
        } catch (error) {
            console.error('Node services SSE parse error:', error);
        }
    });

    nodeServicesSSESource.addEventListener('session_status', (event) => {
        if (event.data === 'expired') {
            stopNodeModalStreams();
            window.location.assign('/login');
        }
    });

    nodeServicesSSESource.addEventListener('shutdown', () => {
        stopNodeServicesStream();
    });

    nodeServicesSSESource.onerror = () => {
        if (nodeServicesSSESource?.readyState === EventSource.CLOSED) {
            stopNodeServicesStream();
        }
    };
}

function renderNodeServices(token, services) {
    const container = document.getElementById('modalServicesContainer');
    const btnContainer = document.getElementById('modalServicesToggle');

    if (services.length === 0) {
        _lastServicesCache = null;
        container.innerHTML = DOMPurify.sanitize(`<div class="col-span-full text-center py-4 text-gray-400">${I18N?.web_services_empty || 'No services'}</div>`);
        if (btnContainer) btnContainer.classList.add('hidden');
        return;
    }

    const INITIAL_SHOW = 4;
    const showAll = container.dataset.showAll === 'true';
    const displayServices = showAll ? services : services.slice(0, INITIAL_SHOW);

    // Build a structural key: names + types must match for in-place update
    const structureKey = displayServices.map(s => `${s.name}|${s.type}`).join(',');
    const prevCache = _lastServicesCache;
    const prevStructureKey = prevCache ? prevCache.structureKey : null;
    const prevShowAll = prevCache ? prevCache.showAll : null;

    if (structureKey === prevStructureKey && showAll === prevShowAll) {
        // Structure unchanged — only patch status indicators and start/stop button in-place
        const rows = container.querySelectorAll('[data-svc-name]');
        rows.forEach(row => {
            const svcName = row.dataset.svcName;
            const svc = displayServices.find(s => s.name === svcName);
            if (!svc) return;

            const dot = row.querySelector('[data-svc-dot]');
            if (dot) {
                dot.className = svc.status === 'running' ? 'text-green-500' : 'text-red-500';
            }

            const toggleBtn = row.querySelector('[data-svc-toggle="true"]');
            if (toggleBtn) {
                const isRunning = svc.status === 'running';
                const newCmd = isRunning ? 'stop' : 'start';
                // Localized titles for the toggle button
                const newTitle = isRunning
                    ? (I18N?.web_service_stop || 'Stop')
                    : (I18N?.web_service_start || 'Start');
                // Hardcoded SVG paths — no user input, safe to set without DOMPurify
                // (DOMPurify strips SVG stroke-* attributes in HTML context)
                const iconStop = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />';
                const iconStart = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />';

                toggleBtn.dataset.cmd = newCmd;
                toggleBtn.title = newTitle;
                toggleBtn.className = `p-1 ${isRunning ? 'text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20' : 'text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-500/20'} rounded`;
                const svg = toggleBtn.querySelector('svg');
                // Direct innerHTML assignment — safe for hardcoded SVG paths
                if (svg) svg.innerHTML = isRunning ? iconStop : iconStart;
            }
        });

        // Update cache statuses
        _lastServicesCache.statuses = displayServices.map(s => s.status);
        return;
    }

    // Structure changed (new services, count changed, or showAll toggled) — full re-render
    _lastServicesCache = { structureKey, showAll, statuses: displayServices.map(s => s.status) };

    container.innerHTML = DOMPurify.sanitize(displayServices.map(svc => `
            <div class="flex items-center justify-between bg-white/50 dark:bg-black/30 p-2 rounded-lg" data-svc-name="${escapeHtml(svc.name)}">
                <div class="flex items-center gap-2">
                    <span data-svc-dot="true" class="${svc.status === 'running' ? 'text-green-500' : 'text-red-500'}">●</span>
                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${escapeHtml(svc.name)}</span>
                    ${svc.type === 'docker' ? '<span class="text-xs text-blue-500">🐳</span>' : ''}
                </div>
                ${(window.USER_ROLE_LEVEL || 0) >= 1 ? `
                <div class="flex gap-1">
                    <button data-action="node-service-action" data-token="${token}" data-name="${svc.name}" data-cmd="restart" data-type="${svc.type || 'systemd'}" class="p-1 text-yellow-600 dark:text-yellow-400 hover:bg-yellow-100 dark:hover:bg-yellow-500/20 rounded" title="Restart">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    </button>
                    <button data-svc-toggle="true" data-action="node-service-action" data-token="${token}" data-name="${svc.name}" data-cmd="${svc.status === 'running' ? 'stop' : 'start'}" data-type="${svc.type || 'systemd'}" 
                            class="p-1 ${svc.status === 'running' ? 'text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20' : 'text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-500/20'} rounded"
                            title="${svc.status === 'running' ? (I18N?.web_service_stop || 'Stop') : (I18N?.web_service_start || 'Start')}">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            ${svc.status === 'running' 
                                ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />'
                                : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
                            }
                        </svg>
                    </button>
                </div>
                ` : ''}
            </div>
        `).join(''));

    if (btnContainer) {
        if (services.length > INITIAL_SHOW) {
            btnContainer.classList.remove('hidden');
            const btn = btnContainer.querySelector('button');
            const blurOverlay = btnContainer.querySelector('.services-blur-overlay');
            if (btn) {
                if (showAll) {
                    btn.classList.add('expanded');
                    if (blurOverlay) blurOverlay.style.display = 'none';
                    btn.innerHTML = DOMPurify.sanitize(`<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg> ${I18N?.web_show_less || 'Show Less'}`);
                } else {
                    btn.classList.remove('expanded');
                    if (blurOverlay) blurOverlay.style.display = '';
                    btn.innerHTML = DOMPurify.sanitize(`<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg> ${I18N?.web_show_more || 'Show More'} (${services.length - INITIAL_SHOW})`);
                }
            }
        } else {
            btnContainer.classList.add('hidden');
        }
    }
}

function toggleServicesDisplay() {
    const container = document.getElementById('modalServicesContainer');
    const isShowingAll = container.dataset.showAll === 'true';
    container.dataset.showAll = !isShowingAll;
    if (currentNodeToken) {
        connectNodeServicesStream(currentNodeToken);
    }
}

function refreshNodeServices() {
    if (currentNodeToken) {
        connectNodeServicesStream(currentNodeToken);
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
                connectNodesMonitorStream();
            }
        );
    } else {
        sendNodeCommand(currentNodeToken, cmd).then(() => {
            showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_command_sent || 'Command sent');
        });
    }
}

async function nodeServiceAction(token, service, action, type = 'systemd') {
    try {
        const response = await fetch('/api/nodes/monitor/service_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, service, action, type })
        });
        
        if (!response.ok) throw new Error('Service action failed');
        
        showAlert(I18N?.modal_title_alert || 'Alert', I18N?.web_command_sent || 'Command sent');
        setTimeout(() => connectNodeServicesStream(token), 2000);
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
    connectNodesMonitorStream();
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

function formatSpeed(v) {
    const sKbps = (typeof I18N !== 'undefined' && I18N.unit_kbps) ? I18N.unit_kbps : 'Kbps';
    const sMbps = (typeof I18N !== 'undefined' && I18N.unit_mbps) ? I18N.unit_mbps : 'Mbps';
    const sGbps = (typeof I18N !== 'undefined' && I18N.unit_gbps) ? I18N.unit_gbps : 'Gbps';
    if (v === null || v === undefined) return '0 ' + sKbps;
    return v >= 1024 * 1024 ? (v / 1048576).toFixed(2) + ' ' + sGbps : (v >= 1024 ? (v / 1024).toFixed(2) + ' ' + sMbps : v.toFixed(2) + ' ' + sKbps);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function resolveLocalizedMessage(message) {
    if (typeof message !== 'string') return message;

    const localizedKeyMatch = message.match(/^\[([a-z0-9_]+)\]$/i);
    if (!localizedKeyMatch) return message;

    const localizedValue = I18N?.[localizedKeyMatch[1]];
    return localizedValue || message;
}

// Modal functions
function showAlert(title, message) {
    const modal = document.getElementById('systemModal');
    document.getElementById('sysModalTitle').textContent = title;
    document.getElementById('sysModalMessage').textContent = resolveLocalizedMessage(message);
    document.getElementById('sysModalCancel').classList.add('hidden');
    document.getElementById('sysModalOk').onclick = () => closeSystemModal(null);
    if (typeof animateModalOpen === 'function') {
        animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function showConfirm(title, message, onConfirm) {
    const modal = document.getElementById('systemModal');
    document.getElementById('sysModalTitle').textContent = title;
    document.getElementById('sysModalMessage').textContent = resolveLocalizedMessage(message);
    document.getElementById('sysModalCancel').classList.remove('hidden');
    document.getElementById('sysModalCancel').onclick = () => closeSystemModal(null);
    document.getElementById('sysModalOk').onclick = () => {
        closeSystemModal(null);
        if (onConfirm) onConfirm();
    };
    if (typeof animateModalOpen === 'function') {
        animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function closeSystemModal() {
    const modal = document.getElementById('systemModal');
    if (typeof animateModalClose === 'function') {
        animateModalClose(modal);
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
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
// Global CustomEvent delegation for nodes_monitor.js
document.addEventListener('app:change:toggle-node-selection', e => {
    toggleNodeSelection(e.detail.target.getAttribute('data-token'), e.detail.target);
});
document.addEventListener('app:action:open-node-detail', e => {
    openNodeDetail(e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:quick-reboot', e => {
    quickReboot(e.detail.target.getAttribute('data-token'));
});
// node-service-action is handled by the listener at the top of this file (with confirmation dialog)

window.showPingErrorModal = function(event) {
    if (event) {
        event.stopPropagation();
    }
    const mode = window.GLOBAL_PING_MODE || "http";
    const title = (typeof I18N !== 'undefined' && I18N.web_ping_error_title) ? I18N.web_ping_error_title : "Error: ping unavailable";
    const desc = (typeof I18N !== 'undefined' && I18N.web_ping_error_desc) ? I18N.web_ping_error_desc : "The system could not measure network latency.";
    const btnText = (typeof I18N !== 'undefined' && I18N.web_ping_how_to_fix_btn) ? I18N.web_ping_how_to_fix_btn : "How to fix?";
    
    let fixText = "";
    if (mode === "tcp") {
        fixText = (typeof I18N !== 'undefined' && I18N.web_ping_fix_tcp) ? I18N.web_ping_fix_tcp : "TCP mode selected. Check firewall for port 53 out.";
    } else {
        fixText = (typeof I18N !== 'undefined' && I18N.web_ping_fix_http) ? I18N.web_ping_fix_http : "HTTP mode selected. Check firewall for port 443 out.";
    }

    const htmlContent = `
        <div class="text-sm text-gray-700 dark:text-gray-300 mb-4">${desc}</div>
        <details class="group bg-gray-50 dark:bg-black/20 rounded-lg border border-gray-200 dark:border-white/10 overflow-hidden">
            <summary class="px-4 py-3 cursor-pointer font-medium text-sm text-gray-900 dark:text-white flex items-center justify-between select-none">
                ${btnText}
                <svg class="w-4 h-4 transform transition-transform group-open:rotate-180 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                </svg>
            </summary>
            <div class="px-4 pb-4 pt-1 text-sm text-gray-600 dark:text-gray-400 border-t border-gray-100 dark:border-white/5">
                ${fixText}
            </div>
        </details>
    `;

    if (window.showModalAlert) {
        window.showModalAlert(htmlContent, title);
    } else {
        alert(title + "\\n\\n" + desc);
    }
};
