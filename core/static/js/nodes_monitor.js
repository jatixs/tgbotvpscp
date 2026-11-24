/**
 * Nodes Monitor Page JavaScript
 * Real-time monitoring dashboard for all nodes
 */

(() => {
let allNodesData = [];
let currentFilter = 'all';
let currentCpuFilter = 'all';
let currentSort = 'name';
let searchQuery = '';
let selectedNodes = new Set();
window.currentNodeId = null;
let modalResChart = null;
let modalNetChart = null;
let modalResRangeCtl = null;
let modalNetRangeCtl = null;
let nodesMonitorSSESource = null;
let nodeDetailSSESource = null;
let nodeServicesSSESource = null;
let nodeTooltipController = null;
let _lastServicesCache = null; // cached services for stable DOM updates

function getI18n() {
    return (typeof window !== 'undefined' && window.I18N)
        ? window.I18N
        : ((typeof window.I18N !== 'undefined' && typeof window.I18N === 'object') ? window.I18N : {});
}

function t(key, fallbackRu, fallbackEn) {
    const dict = getI18n();
    if (dict && typeof dict[key] === 'string' && dict[key].trim()) {
        return dict[key];
    }
    const isEn = typeof document !== 'undefined' && document.documentElement?.lang === 'en';
    return isEn ? (fallbackEn || fallbackRu || key) : (fallbackRu || fallbackEn || key);
}

function normalizeNode(node) {
    const decryptedName = window.decryptData(node.name) || 'Unknown';
    const decryptedIp = window.decryptData(node.ip) || '-';
    const decryptedPing = window.decryptData(node.ping);

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
        return `${t('web_nodes_monitor_outage_rebooting', 'Текущий простой вызван перезагрузкой', 'Current outage is caused by a reboot')}: ${availability.current_downtime}`;
    }
    return `${t('web_nodes_monitor_outage_pending', 'Причина будет определена после переподключения ноды', 'The reason will be determined after the node reconnects')}: ${availability.current_downtime}`;
}

function initUptimeTooltip() {
    const trigger = document.getElementById('modalUptimeTrigger');
    const popover = document.getElementById('availabilityPopover');
    if (!trigger || !popover || trigger.dataset.tooltipInit) return;
    trigger.dataset.tooltipInit = '1';
    nodeTooltipController?.abort();
    nodeTooltipController = new AbortController();
    function listen(target, event, handler) {
        target.addEventListener(event, handler, { signal: nodeTooltipController.signal });
    }

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

    listen(trigger, 'mouseenter', () => { clearTimeout(leaveTimeout); positionAndShow(); });
    listen(trigger, 'mouseleave', () => { leaveTimeout = setTimeout(hidePopover, 100); });
    listen(popover, 'mouseenter', () => { clearTimeout(leaveTimeout); });
    listen(popover, 'mouseleave', () => { leaveTimeout = setTimeout(hidePopover, 100); });

    listen(trigger, 'click', (e) => {
        if (isVisible()) hidePopover(); else positionAndShow();
        e.stopPropagation();
    });
    listen(trigger, 'keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (isVisible()) hidePopover(); else positionAndShow(); }
        if (e.key === 'Escape') hidePopover();
    });
    listen(document, 'click', (e) => {
        if (!trigger.contains(e.target) && !popover.contains(e.target)) { if (isVisible()) hidePopover(); }
    });
    listen(window, 'resize', () => { if (isVisible()) positionAndShow(); });

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
            selectedNodes = new Set([...selectedNodes].filter(nodeId => allNodesData.some(node => String(node.id) === nodeId)));
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
    if (!document.getElementById('nodesGrid')) return;
    stopNodesMonitorStream();
    
    // Reset state
    // Retain the last snapshot while the live stream reconnects on a return visit.
    currentFilter = 'all';
    currentCpuFilter = 'all';
    currentSort = 'name';
    searchQuery = '';
    selectedNodes.clear();
    window.currentNodeId = null;
    
    // Destroy charts if they exist
    if (modalResChart) {
        modalResChart.destroy();
        modalResChart = null;
        if (window.__chartRegistry) delete window.__chartRegistry['modalResChart'];
    }
    if (modalNetChart) {
        modalNetChart.destroy();
        modalNetChart = null;
        if (window.__chartRegistry) delete window.__chartRegistry['modalNetChart'];
    }
    
    if (allNodesData.length) {
        updateStats();
        renderNodes();
    }

    // Subscribe to node updates
    connectNodesMonitorStream();
    
    // Setup theme
    const curTheme = (typeof window.getResolvedTheme === 'function')
        ? window.getResolvedTheme()
        : ((!localStorage.getItem('theme') || localStorage.getItem('theme') === 'system')
            ? ((window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light')
            : localStorage.getItem('theme'));
    if (typeof window.applyThemeUI === 'function') {
        window.applyThemeUI(curTheme);
    } else if (typeof updateThemeIcons === 'function') {
        updateThemeIcons();
    }

    initUptimeTooltip();
}

// Expose functions to window
window.initNodesMonitor = initNodesMonitor;
window.destroyNodesMonitor = () => {
    nodeTooltipController?.abort();
    stopNodesMonitorStream();
    stopNodeModalStreams();
    if (window.hideAvailabilityPopover) window.hideAvailabilityPopover();
    if (modalResRangeCtl) { modalResRangeCtl.destroy?.(); modalResRangeCtl = null; }
    if (modalNetRangeCtl) { modalNetRangeCtl.destroy?.(); modalNetRangeCtl = null; }
    if (modalResChart) { modalResChart.destroy(); modalResChart = null; }
    if (modalNetChart) { modalNetChart.destroy(); modalNetChart = null; }
};
window.toggleServicesDisplay = toggleServicesDisplay;

// Wire service action buttons rendered inside the modal
document.addEventListener('app:action:node-service-action', (e) => {
    const el = e.detail?.target;
    if (!el) return;
    const nodeId = el.dataset.token;
    const name = el.dataset.name;
    const cmd = el.dataset.cmd;
    const type = el.dataset.type || 'systemd';
    if (!nodeId || !name || !cmd) return;

    const cmdLabels = {
        restart: t('web_service_restart', 'перезапуск', 'restart'),
        stop:    t('web_service_stop',    'остановка', 'stop'),
        start:   t('web_service_start',   'запуск', 'start'),
    };
    const actionLabel = cmdLabels[cmd] || cmd;

    showConfirm(
        t('modal_title_confirm', 'Подтверждение', 'Confirm'),
        t('web_service_confirm', 'Выполнить {action} для {name}?', 'Execute {action} for {name}?')
            .replace('{action}', actionLabel.toLowerCase())
            .replace('{name}', name),
        () => nodeServiceAction(nodeId, name, cmd, type)
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
            case 'ping': {
                const pingA = a.ping != null ? parseFloat(a.ping) : Infinity;
                const pingB = b.ping != null ? parseFloat(b.ping) : Infinity;
                return pingA - pingB;
            }
            case 'name':
            default:
                return a.name.localeCompare(b.name);
        }
    });
    
    if (filtered.length === 0) {
        container.classList.add('nodes-grid-empty');
        window.setSafeHTML(container, `
            <div class="nodes-empty-state text-center text-gray-500 dark:text-gray-400">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto mb-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                ${t('web_no_nodes', 'Ноды не найдены', 'No nodes found')}
            </div>
        `);
        return;
    }
    container.classList.remove('nodes-grid-empty');
    
    const newHtml = filtered.map(node => createNodeCardHtml(node)).join('');
    
    // Try to update in-place to prevent flicker
    const tempContainer = container.cloneNode(false);
    window.setSafeHTML(tempContainer, newHtml);
    
    if (!window.updateDOM(container, tempContainer)) {
        // Fallback if structural changes occurred
        window.setSafeHTML(container, newHtml);
    }
    
    if (typeof window.parsePageEmojis === 'function') {
        window.parsePageEmojis(container);
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
function createNodeCardHtml(node) {
    const isOnline = node.status === 'online';
    const isRestarting = node.status === 'restarting';
    
    let statusClass, statusIconHtml, statusText;
    if (isRestarting) {
        statusClass = 'bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400';
        statusIconHtml = '<i class="icon icon-dot icon-dot-blue icon-xs mr-1"></i>';
        statusText = t('web_node_status_restarting', 'Перезагрузка', 'Restarting');
    } else if (isOnline) {
        statusClass = 'bg-green-100 dark:bg-green-500/20 text-green-600 dark:text-green-400';
        statusIconHtml = '<i class="icon icon-dot icon-dot-green icon-xs mr-1"></i>';
        statusText = t('web_node_status_online', 'В сети', 'Online');
    } else {
        statusClass = 'bg-red-100 dark:bg-red-500/20 text-red-600 dark:text-red-400';
        statusIconHtml = '<i class="icon icon-dot icon-dot-red icon-xs mr-1"></i>';
        statusText = t('web_node_status_offline', 'Не в сети', 'Offline');
    }
    
    const cpu = node.cpu || 0;
    const ram = node.ram || 0;
    const disk = node.disk || 0;
    const uptime = formatUptime(node.uptime || 0);
    const traffic = formatTraffic(node.traffic || {});
    const availability = node.availability || {};
    const lastOutage = availability.last_downtime || '-';
    const totalDowntime = availability.total_downtime || '-';
    
    const nodeId = String(node.id);
    const isSelected = selectedNodes.has(nodeId);
    
    return `
        <div class="node-card bg-white/60 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/10 rounded-2xl overflow-hidden shadow-lg dark:shadow-none hover:scale-[1.02] transition duration-300 ${isSelected ? 'ring-2 ring-blue-500' : ''}" 
             data-token="${nodeId}" data-status="${node.status}" data-name="${node.name.toLowerCase()}">
            
            <!-- Header -->
            <div class="p-4 border-b border-gray-100 dark:border-white/5 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    ${(typeof window.USER_ROLE !== 'undefined' && window.USER_ROLE !== 'users') ? `
                    <input type="checkbox" class="node-checkbox rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500" 
                           ${isSelected ? 'checked' : ''} 
                           data-action="toggle-node-selection" data-token="${nodeId}">
                    ` : ''}
                    <div>
                        <h3 class="font-bold text-gray-900 dark:text-white text-sm">${typeof window.replaceEmojisWithFlagsHTML === 'function' ? window.replaceEmojisWithFlagsHTML(escapeHtml(node.name)) : escapeHtml(node.name)}</h3>
                        <div class="flex items-center gap-1.5">
                            ${window.renderNodeIpBadge(node)}
                            ${node.ping != null ? (node.ping === 'n/a' ? `<span onclick="window.showPingErrorModal(event)" class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold cursor-pointer hover:opacity-80 transition-opacity ${getPingBadgeClass(node.ping)}" title="Click for details">n/a</span>` : `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold ${getPingBadgeClass(node.ping)}">${parseFloat(node.ping)}ms</span>`) : ''}
                        </div>
                    </div>
                </div>
                <span class="px-2 py-1 rounded-lg text-xs font-bold ${statusClass}">
                    ${statusIconHtml} ${statusText}
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
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 font-semibold mt-1 uppercase tracking-wide">${t('web_cpu', 'ЦП', 'CPU')}</span>
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
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 font-semibold mt-1 uppercase tracking-wide">${t('web_ram', 'ОЗУ', 'RAM')}</span>
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
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 font-semibold mt-1 uppercase tracking-wide">${t('web_disk', 'Диск', 'Disk')}</span>
                    </div>
                </div>
                
                <!-- Info Row -->
                <div class="flex justify-between text-xs text-gray-500 dark:text-gray-400 pt-2 mt-2 border-t border-gray-100 dark:border-white/5">
                    <span class="flex items-center gap-1"><i class="icon icon-clock icon-sm bg-current"></i> ${uptime}</span>
                    <span class="flex items-center gap-1"><i class="icon icon-chart-bar icon-sm bg-current"></i> ${traffic}</span>
                </div>
                <div class="mt-2 pt-2 border-t border-gray-100 dark:border-white/5 text-[11px] text-gray-500 dark:text-gray-400 space-y-1">
                    <div class="flex justify-between gap-2">
                        <span>${t('web_nodes_monitor_last_outage', 'Посл. простой', 'Last outage')}</span>
                        <span class="font-mono text-right">${escapeHtml(lastOutage)}</span>
                    </div>
                    <div class="flex justify-between gap-2">
                        <span>${t('web_nodes_monitor_total_downtime', 'Всего простой', 'Total downtime')}</span>
                        <span class="font-mono text-right">${escapeHtml(totalDowntime)}</span>
                    </div>
                </div>
            </div>
            
            <!-- Actions -->
            <div class="px-4 pb-4 mb-3 pt-1 flex gap-2">
                <button data-action="open-node-detail" data-token="${nodeId}" class="flex-1 px-3 py-2 bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 rounded-xl text-xs font-bold hover:bg-blue-200 dark:hover:bg-blue-500/30 transition">
                    ${t('web_node_details', 'Подробнее', 'Node Details')}
                </button>
                ${(typeof window.USER_ROLE !== 'undefined' && window.USER_ROLE !== 'users') ? `
                <button data-action="quick-reboot" data-token="${nodeId}" class="node-reboot-btn px-3 py-2 text-red-600 dark:text-red-400 rounded-xl text-xs font-bold hover:bg-red-200 transition" title="Reboot">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                </button>` : ''}
            </div>
        </div>
    `;
}

// Filtering functions
window.filterNodes = function(query) {
    searchQuery = query;
    renderNodes();
}

// Filter Modal functions
let tempFilterStatus = 'all';
let tempFilterCpu = 'all';
let tempFilterSort = 'name';

window.openFilterModal = function() {
    tempFilterStatus = currentFilter;
    tempFilterCpu = currentCpuFilter;
    tempFilterSort = currentSort;
    updateFilterModalUI();
    const modal = document.getElementById('filterModal');
    if (typeof window.animateModalOpen === 'function') {
        window.animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

window.closeFilterModal = function() {
    const modal = document.getElementById('filterModal');
    if (typeof window.animateModalClose === 'function') {
        window.animateModalClose(modal);
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

window.setFilterStatus = function(status) {
    tempFilterStatus = status;
    updateFilterModalUI();
}

window.setFilterCpu = function(cpu) {
    tempFilterCpu = cpu;
    updateFilterModalUI();
}

window.setFilterSort = function(sort) {
    tempFilterSort = sort;
    updateFilterModalUI();
}

window.resetFilters = function() {
    tempFilterStatus = 'all';
    tempFilterCpu = 'all';
    tempFilterSort = 'name';
    updateFilterModalUI();
}

window.applyFilters = function() {
    currentFilter = tempFilterStatus;
    currentCpuFilter = tempFilterCpu;
    currentSort = tempFilterSort;
    updateFilterBadge();
    renderNodes();
    window.closeFilterModal();
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
window.toggleSelectAll = function(checkbox) {
    if (checkbox.checked) {
        allNodesData.forEach(node => { selectedNodes.add(String(node.id)); });
    } else {
        selectedNodes.clear();
    }
    renderNodes();
}

window.toggleNodeSelection = function(token, checkbox) {
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
window.massCommand = async function(cmd) {
    if (selectedNodes.size === 0) {
        showAlert(t('modal_title_alert', 'Внимание', 'Alert'), t('web_nodes_monitor_select_nodes', 'Пожалуйста, выберите хотя бы одну ноду', 'Please select at least one node'));
        return;
    }
    
    // Get localized command name
    const cmdNames = {
        'reboot': t('web_nodes_monitor_btn_reboot', 'Перезагрузка', 'Reboot'),
        'selftest': t('web_nodes_monitor_btn_selftest', 'Тест системы', 'System Test'),
        'speedtest': t('web_nodes_monitor_btn_speedtest', 'Тест скорости', 'Speedtest'),
        'traffic': t('web_nodes_monitor_btn_traffic', 'Трафик', 'Traffic')
    };
    const cmdName = cmdNames[cmd] || cmd;
    
    const confirmMsg = cmd === 'reboot' 
        ? t('web_nodes_monitor_confirm_mass_reboot', `Перезагрузить выбранные ноды (${selectedNodes.size})?`, `Reboot ${selectedNodes.size} selected nodes?`)
        : t('web_nodes_monitor_confirm_mass_command', `Выполнить {command} на {count} нодах?`, `Execute {command} on {count} nodes?`)
            .replace('{command}', cmdName)
            .replace('{count}', selectedNodes.size);
    
    showConfirm(t('modal_title_confirm', 'Подтверждение', 'Confirm'), confirmMsg, async () => {
        for (const token of selectedNodes) {
            try {
                await sendNodeCommand(token, cmd);
            } catch (e) {
                console.error(`Error executing ${cmd} on node:`, e);
            }
        }
        showAlert(t('modal_title_alert', 'Внимание', 'Alert'), t('web_commands_sent', 'Команды отправлены на все выбранные ноды', 'Commands sent to all selected nodes'));
        connectNodesMonitorStream();
    });
}

// Quick actions
window.quickReboot = async function(nodeId) {
    const node = allNodesData.find(n => String(n.id) === nodeId);
    const name = node ? node.name : 'Node';
    
    showConfirm(
        t('modal_title_confirm', 'Подтверждение', 'Confirm'),
        t('web_reboot_node_confirm', `Перезагрузить ${name}?`, `Reboot ${name}?`).replace('{name}', name),
        async () => {
            await sendNodeCommand(nodeId, 'reboot');
            showAlert(t('modal_title_alert', 'Внимание', 'Alert'), t('web_reboot_sent', 'Команда перезагрузки отправлена', 'Reboot command sent'));
            connectNodesMonitorStream();
        }
    );
}

// Node detail modal
window.openNodeDetail = async function(token) {
    window.currentNodeId = token;
    const modal = document.getElementById('nodeDetailModal');
    
    if (typeof window.animateModalOpen === 'function') {
        window.animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    connectNodeDetailStream(token);
    connectNodeServicesStream(token);
    startModalChartRanges();
}

function startModalChartRanges() {
    if (typeof window.createChartRangeController !== 'function') return;
    if (modalResRangeCtl) modalResRangeCtl.destroy();
    if (modalNetRangeCtl) modalNetRangeCtl.destroy();
    function getSource() { return window.currentNodeId ? { source: 'node', node_id: window.currentNodeId } : null; }
    modalResRangeCtl = window.createChartRangeController({
        key: 'modalResChart',
        mount: '[data-chart-range="modalResChart"]',
        canvasId: 'modalResChart',
        getSource,
        getValues: point => [point.c, point.r],
        render: (series, animate) => updateModalCharts(series, 'res', animate)
    }).start();
    modalNetRangeCtl = window.createChartRangeController({
        key: 'modalNetChart',
        mount: '[data-chart-range="modalNetChart"]',
        canvasId: 'modalNetChart',
        getSource,
        network: true,
        getValues: point => [point.rx, point.tx, point.ping],
        render: (series, animate) => updateModalCharts(series, 'net', animate)
    }).start();
}

function stopModalChartRanges() {
    if (modalResRangeCtl) modalResRangeCtl.stop();
    if (modalNetRangeCtl) modalNetRangeCtl.stop();
}

window.closeNodeDetailModal = function() {
    if (typeof window.collapseChartModal === 'function') window.collapseChartModal();
    const modal = document.getElementById('nodeDetailModal');
    if (typeof window.animateModalClose === 'function') {
        window.animateModalClose(modal);
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    window.currentNodeId = null;
    _lastServicesCache = null; // reset so next node gets a fresh render

    if (typeof window.hideAvailabilityPopover === 'function') window.hideAvailabilityPopover();

    stopNodeModalStreams();
    stopModalChartRanges();
    
    // Destroy charts
    if (modalResChart) {
        modalResChart.destroy();
        modalResChart = null;
        if (window.__chartRegistry) delete window.__chartRegistry['modalResChart'];
    }
    if (modalNetChart) {
        modalNetChart.destroy();
        modalNetChart = null;
        if (window.__chartRegistry) delete window.__chartRegistry['modalNetChart'];
    }
}

function connectNodeDetailStream(token) {
    stopNodeDetailStream();

    nodeDetailSSESource = new EventSource(`/api/events/node?node_id=${encodeURIComponent(token)}`);

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
    const modalTitleEl = document.getElementById('modalNodeTitle');
    window.renderNodeModalTitle(modalTitleEl, window.decryptData(data.name) || 'Unknown');

    const nameContainer = modalTitleEl.parentElement;
    if (nameContainer) {
        const badgeEl = document.getElementById('monitorNodeBillingBadge');
        if (badgeEl) {
            const isSet = data.billing_amount !== null && data.billing_amount !== undefined;
            if (isSet || data.next_payment_date) {
                const daysLeft = window.calculateDaysLeft ? window.calculateDaysLeft(data.next_payment_date) : null;
                const billingIconColor = daysLeft === null ? 'text-gray-400' : daysLeft < 0 ? 'text-red-500 dark:text-red-400' : daysLeft <= 6 ? 'text-yellow-500 dark:text-yellow-400' : 'text-green-500 dark:text-green-400';
                const fragment = window.DOMPurify.sanitize(`
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
                            window.decryptData(data.name) || 'Unknown',
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
    
    window.updateIpBadge(document.getElementById('modalNodeIpContainer'), window.nodeIpBadgeState(data));

    const nodeIdEl = document.getElementById('modalNodeId');
    if (nodeIdEl) nodeIdEl.textContent = String(data.id ?? '-');
    
    // Update ping badge in modal
    const pingBadge = document.getElementById('modalNodePingBadge');
    const stats = data.stats || {};
    const pingValue = window.decryptData(stats.ping);
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
    const statusBadge = document.getElementById('modalNodeStatusBadge');
    const statusDot = document.getElementById('modalNodeStatusDot');
    const statusText = document.getElementById('modalNodeStatus');
    
    if (isRestarting) {
        statusBadge.className = 'flex items-center gap-1 text-blue-600 dark:text-blue-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse';
        statusText.textContent = t('web_node_status_restarting', 'Перезагрузка', 'Restarting');
    } else if (isOnline) {
        statusBadge.className = 'flex items-center gap-1 text-green-600 dark:text-green-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse';
        statusText.textContent = t('web_node_status_online', 'В сети', 'Online');
    } else {
        statusBadge.className = 'flex items-center gap-1 text-red-600 dark:text-red-400';
        statusDot.className = 'w-1.5 h-1.5 rounded-full bg-red-500';
        statusText.textContent = t('web_node_status_offline', 'Не в сети', 'Offline');
    }
    
    document.getElementById('modalUptime').textContent = formatUptime(stats.uptime || 0);
    document.getElementById('modalCpu').textContent = (stats.cpu || 0) + '%';
    document.getElementById('modalRam').textContent = (stats.ram || 0) + '%';
    document.getElementById('modalDisk').textContent = (stats.disk || 0) + '%';

    const availability = data.availability || {};
    const titleEl = document.getElementById('availabilityPopoverTitle');
    if (titleEl) titleEl.textContent = t('web_avail_header', 'Аптайм / Доступность', 'Uptime / Downtime');
    document.getElementById('availabilityLabelCurrentUptime').textContent = t('web_nodes_monitor_current_uptime', 'Текущий аптайм', 'Current uptime');
    document.getElementById('availabilityLabelLastOutage').textContent = t('web_nodes_monitor_last_outage', 'Посл. простой', 'Last outage');
    document.getElementById('availabilityLabelLastReboot').textContent = t('web_nodes_monitor_last_reboot', 'Посл. перезагрузка', 'Last reboot');
    document.getElementById('availabilityLabelTotalUptime').textContent = t('web_nodes_monitor_total_uptime', 'Всего в сети', 'Total uptime');
    document.getElementById('availabilityLabelTotalDowntime').textContent = t('web_nodes_monitor_total_downtime', 'Всего простой', 'Total downtime');
    document.getElementById('availabilityLabelInternetDowntime').textContent = t('web_nodes_monitor_internet_downtime', 'Простой интернета', 'Internet downtime');
    document.getElementById('availabilityLabelPhysicalDowntime').textContent = t('web_nodes_monitor_physical_downtime', 'Физический простой', 'Physical downtime');
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
        if (!isDefault && typeof window.USER_ROLE !== 'undefined' && window.USER_ROLE !== 'users') resetBtn.classList.remove('hidden');
        else resetBtn.classList.add('hidden');
    }
}

function getModalGradient(ctx, color) {
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, color.replace('rgb', 'rgba').replace(')', ', 0.5)'));
    gradient.addColorStop(1, color.replace('rgb', 'rgba').replace(')', ', 0.0)'));
    return gradient;
}

function applyModalResChartData() {
    if (!modalResChart || !modalResChart.__modalState) return;
    const { labels, cpuData, ramData, series, resCtx, tickColor, gridColor } = modalResChart.__modalState;
    modalResChart.data.labels = labels;
    modalResChart.data.datasets[0].data = cpuData;
    modalResChart.data.datasets[1].data = ramData;
    modalResChart.__chartTimeWindow = { min: series.minIndex, max: series.maxIndex };

    modalResChart.data.datasets[0].backgroundColor = getModalGradient(resCtx, 'rgb(59, 130, 246)');
    modalResChart.data.datasets[1].backgroundColor = getModalGradient(resCtx, 'rgb(168, 85, 247)');

    modalResChart.options.scales.x.ticks.color = tickColor;
    modalResChart.options.scales.y.grid.color = gridColor;
    modalResChart.options.scales.y.ticks.color = tickColor;
    modalResChart.options.plugins.legend.labels.color = tickColor;
}

function applyModalNetChartData() {
    if (!modalNetChart || !modalNetChart.__modalState) return;
    const { labels, rxData, txData, series, netCtx, tickColor, gridColor } = modalNetChart.__modalState;
    modalNetChart.data.labels = labels;
    modalNetChart.data.datasets[0].data = rxData;
    modalNetChart.data.datasets[1].data = txData;
    modalNetChart.data.datasets[2].data = series.ping;
    modalNetChart.__chartTimeWindow = { min: series.minIndex, max: series.maxIndex };

    modalNetChart.data.datasets[0].backgroundColor = getModalGradient(netCtx, 'rgb(34, 197, 94)');
    modalNetChart.data.datasets[1].backgroundColor = getModalGradient(netCtx, 'rgb(59, 130, 246)');

    modalNetChart.options.scales.x.ticks.color = tickColor;
    modalNetChart.options.scales.y.grid.color = gridColor;
    modalNetChart.options.scales.y.ticks.color = tickColor;
    modalNetChart.options.scales.ping.ticks.color = tickColor;
}

function updateModalCharts(series, which, animate = true) {
    const canvas = document.getElementById(which === 'res' ? 'modalResChart' : 'modalNetChart');
    if (!canvas) return;
    if (!series || (which === 'net' ? !series.labels.length : series.points.length < 2)) {
        const chart = which === 'res' ? modalResChart : modalNetChart;
        if (chart) {
            chart.data.labels = [];
            chart.data.datasets.forEach(ds => { ds.data = []; });
            chart.update(animate && !document.documentElement.classList.contains('perf-mode') ? undefined : 'none');
        }
        return;
    }

    const labels = series.labels;
    const cpuData = series.cpu;
    const ramData = series.ram;
    const rxData = series.rx;
    const txData = series.tx;
    
    const isDark = document.documentElement.classList.contains('dark');
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const tickColor = isDark ? '#9ca3af' : '#6b7280';
    const isMobile = window.innerWidth < 640;

    const resCtx = canvas.getContext('2d');
    const netCtx = resCtx;

    const interactiveOptions = window.buildInteractiveChartOptions ? window.buildInteractiveChartOptions({}) : {};

    if (which !== 'res') {
        // handled by the network branch below
    } else if (modalResChart) {
        modalResChart.__modalState = { labels, cpuData, ramData, series, resCtx, tickColor, gridColor };
        if (window.updateChartWithLiveData) {
            window.updateChartWithLiveData(modalResChart, applyModalResChartData, 'modalResChart', animate);
        } else {
            applyModalResChartData();
            modalResChart.update(document.documentElement.classList.contains('perf-mode') ? 'none' : undefined);
            if (window.attachChartInteractions) window.attachChartInteractions(modalResChart, 'modalResChart');
        }
    } else {
        modalResChart = new window.Chart(resCtx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: 'CPU (%)', data: cpuData, borderColor: '#3b82f6', borderWidth: 2, backgroundColor: getModalGradient(resCtx, 'rgb(59, 130, 246)'), fill: true },
                    { label: 'RAM (%)', data: ramData, borderColor: '#a855f7', borderWidth: 2, backgroundColor: getModalGradient(resCtx, 'rgb(168, 85, 247)'), fill: true }
                ]
            },
            options: {
                ...interactiveOptions,
                responsive: true,
                maintainAspectRatio: false,
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
                        min: series.minIndex,
                        max: series.maxIndex,
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
        modalResChart.__chartTimeWindow = { min: series.minIndex, max: series.maxIndex };
        window.__chartRegistry = window.__chartRegistry || {};
        window.__chartRegistry['modalResChart'] = modalResChart;
        if (window.attachChartInteractions) window.attachChartInteractions(modalResChart, 'modalResChart');
    }
    
    if (which !== 'net') return;

    if (modalNetChart) {
        modalNetChart.__modalState = { labels, rxData, txData, series, netCtx, tickColor, gridColor };
        if (window.updateChartWithLiveData) {
            window.updateChartWithLiveData(modalNetChart, applyModalNetChartData, 'modalNetChart', animate);
        } else {
            applyModalNetChartData();
            modalNetChart.update(animate && !document.documentElement.classList.contains('perf-mode') ? undefined : 'none');
            if (window.attachChartInteractions) window.attachChartInteractions(modalNetChart, 'modalNetChart');
        }
    } else {
        modalNetChart = new window.Chart(netCtx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    { label: t('web_label_rx', 'ВХ', 'RX'), data: rxData, yAxisID: 'y', borderColor: '#22c55e', borderWidth: 2, backgroundColor: getModalGradient(netCtx, 'rgb(34, 197, 94)'), fill: true },
                    { label: t('web_label_tx', 'ИСХ', 'TX'), data: txData, yAxisID: 'y', borderColor: '#3b82f6', borderWidth: 2, backgroundColor: getModalGradient(netCtx, 'rgb(59, 130, 246)'), fill: true },
                    window.createPingDataset(series.ping)
                ]
            },
            options: {
                ...interactiveOptions,
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    ...(interactiveOptions.plugins || {}),
                    legend: { 
                        display: true, 
                        position: 'top', 
                        labels: { color: tickColor, boxWidth: 10, usePointStyle: true, font: { size: 10 } } 
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(c) { return c.dataset.label + ': ' + (c.dataset.yAxisID === 'ping' ? c.raw + ' ms' : formatSpeed(c.raw)); }
                        }
                    }
                },
                scales: {
                    ping: window.createPingScale(tickColor),
                    x: { 
                        min: series.minIndex,
                        max: series.maxIndex,
                        grid: { display: false },
                        ticks: { display: !isMobile, maxTicksLimit: isMobile ? 3 : 6, color: tickColor }
                    },
                    y: {
                        position: 'right',
                        beginAtZero: true,
                        grid: { color: gridColor },
                        ticks: { 
                            color: tickColor, 
                            font: { size: 10 },
                            callback: function(v) { return formatSpeed(v); }
                        }
                    }
                },
                elements: { line: { tension: 0.35 }, point: { radius: window.networkHistoryPointRadius, hitRadius: 10 } }
            }
        });
        modalNetChart.__chartTimeWindow = { min: series.minIndex, max: series.maxIndex };
        window.__chartRegistry = window.__chartRegistry || {};
        window.__chartRegistry['modalNetChart'] = modalNetChart;
        if (window.attachChartInteractions) window.attachChartInteractions(modalNetChart, 'modalNetChart');
    }
}

function connectNodeServicesStream(token) {
    stopNodeServicesStream();

    const container = document.getElementById('modalServicesContainer');
    if (container) {
        window.setSafeHTML(container, `<div class="text-center py-4 text-gray-400">${t('web_services_loading', 'Загрузка сервисов...', 'Loading services...')}</div>`);
        _lastServicesCache = null; // force full re-render on next data event
    }

    nodeServicesSSESource = new EventSource(`/api/events/node/services?node_id=${encodeURIComponent(token)}`);

    nodeServicesSSESource.addEventListener('node_services', (event) => {
        try {
            const data = JSON.parse(event.data);
            const services = (data.services || []).map((service) => ({
                name: window.decryptData(service.name),
                type: window.decryptData(service.type) || 'systemd',
                status: window.decryptData(service.status),
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
        window.setSafeHTML(container, `<div class="col-span-full text-center py-4 text-gray-400">${t('web_services_empty', 'Нет сервисов', 'No services')}</div>`);
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
                    ? t('web_service_stop', 'Остановить', 'Stop')
                    : t('web_service_start', 'Запустить', 'Start');
                const iconPaths = isRunning
                    ? ['M21 12a9 9 0 11-18 0 9 9 0 0118 0z', 'M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z']
                    : ['M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z', 'M21 12a9 9 0 11-18 0 9 9 0 0118 0z'];

                toggleBtn.dataset.cmd = newCmd;
                toggleBtn.title = newTitle;
                toggleBtn.className = `p-1 ${isRunning ? 'text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20' : 'text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-500/20'} rounded`;
                const svg = toggleBtn.querySelector('svg');
                if (svg) {
                    svg.replaceChildren(...iconPaths.map(data => {
                        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        path.setAttribute('stroke-linecap', 'round');
                        path.setAttribute('stroke-linejoin', 'round');
                        path.setAttribute('stroke-width', '2');
                        path.setAttribute('d', data);
                        return path;
                    }));
                }
            }
        });

        // Update cache statuses
        _lastServicesCache.statuses = displayServices.map(s => s.status);
        return;
    }

    // Structure changed (new services, count changed, or showAll toggled) — full re-render
    _lastServicesCache = { structureKey, showAll, statuses: displayServices.map(s => s.status) };

    window.setSafeHTML(container, displayServices.map(svc => `
            <div class="flex items-center justify-between bg-white/50 dark:bg-black/30 p-2 rounded-lg" data-svc-name="${escapeHtml(svc.name)}">
                <div class="flex items-center gap-2">
                    <span data-svc-dot="true" class="${svc.status === 'running' ? 'text-green-500' : 'text-red-500'}">●</span>
                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">${escapeHtml(svc.name)}</span>
                    ${svc.type === 'docker' ? '<span class="text-xs text-blue-500">🐳</span>' : ''}
                </div>
                ${(window.USER_ROLE_LEVEL || 0) >= 1 ? `
                <div class="flex gap-1">
                    <button data-action="node-service-action" data-token="${escapeHtml(token)}" data-name="${escapeHtml(svc.name)}" data-cmd="restart" data-type="${escapeHtml(svc.type || 'systemd')}" class="p-1 text-yellow-600 dark:text-yellow-400 hover:bg-yellow-100 dark:hover:bg-yellow-500/20 rounded" title="Restart">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    </button>
                    <button data-svc-toggle="true" data-action="node-service-action" data-token="${escapeHtml(token)}" data-name="${escapeHtml(svc.name)}" data-cmd="${svc.status === 'running' ? 'stop' : 'start'}" data-type="${escapeHtml(svc.type || 'systemd')}"
                            class="p-1 ${svc.status === 'running' ? 'text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-500/20' : 'text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-500/20'} rounded"
                            title="${svc.status === 'running' ? t('web_service_stop', 'Остановить', 'Stop') : t('web_service_start', 'Запустить', 'Start')}">
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
                    window.setSafeHTML(btn, `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg> ${t('web_show_less', 'Скрыть', 'Show Less')}`);
                } else {
                    btn.classList.remove('expanded');
                    if (blurOverlay) blurOverlay.style.display = '';
                    window.setSafeHTML(btn, `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 transition-transform duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg> ${t('web_show_more', 'Показать ещё', 'Show More')} (${services.length - INITIAL_SHOW})`);
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
    if (window.currentNodeId) {
        connectNodeServicesStream(window.currentNodeId);
    }
}

window.refreshNodeServices = function() {
    if (window.currentNodeId) {
        connectNodeServicesStream(window.currentNodeId);
    }
}

// Node commands from modal
window.nodeCommand = function(cmd) {
    if (!window.currentNodeId) return;
    
    const node = allNodesData.find(n => String(n.id) === window.currentNodeId);
    const name = node ? node.name : 'Node';
    
    if (cmd === 'reboot') {
        showConfirm(
            t('modal_title_confirm', 'Подтверждение', 'Confirm'),
            t('web_reboot_node_confirm', 'Перезагрузить {name}?', 'Reboot {name}?').replace('{name}', name),
            async () => {
                await sendNodeCommand(window.currentNodeId, cmd);
                showAlert(t('modal_title_alert', 'Внимание', 'Alert'), t('web_command_sent', 'Команда отправлена', 'Command sent'));
                window.closeNodeDetailModal();
                connectNodesMonitorStream();
            }
        );
    } else {
        sendNodeCommand(window.currentNodeId, cmd).then(() => {
            showAlert(t('modal_title_alert', 'Внимание', 'Alert'), t('web_command_sent', 'Команда отправлена', 'Command sent'));
        });
    }
}

async function nodeServiceAction(nodeId, service, action, type = 'systemd') {
    try {
        const response = await fetch('/api/nodes/monitor/service_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ node_id: Number(nodeId), service, action, type })
        });
        
        if (!response.ok) throw new Error('Service action failed');
        
        showAlert(t('modal_title_alert', 'Внимание', 'Alert'), t('web_command_sent', 'Команда отправлена', 'Command sent'));
        setTimeout(() => connectNodeServicesStream(nodeId), 2000);
    } catch (error) {
        showAlert(t('modal_title_error', 'Ошибка', 'Error'), error.message);
    }
}

// Send command to node
async function sendNodeCommand(nodeId, command) {
    const response = await fetch('/api/nodes/monitor/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_id: Number(nodeId), command })
    });
    
    if (!response.ok) {
        throw new Error('Command failed');
    }
    
    return response.json();
}

// Refresh
window.refreshAllNodes = function() {
    connectNodesMonitorStream();
}

// Utility functions
function formatUptime(seconds) {
    if (!seconds || seconds <= 0) return '-';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    
    const parts = [];
    if (d > 0) parts.push(`${d}${t('web_time_d', 'д', 'd')}`);
    if (h > 0) parts.push(`${h}${t('web_time_h', 'ч', 'h')}`);
    parts.push(`${m}${t('web_time_m', 'м', 'm')}`);
    
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
    const sKbps = t('unit_kbps', 'Кбит/с', 'Kbps');
    const sMbps = t('unit_mbps', 'Мбит/с', 'Mbps');
    const sGbps = t('unit_gbps', 'Гбит/с', 'Gbps');
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

    const localizedValue = getI18n()?.[localizedKeyMatch[1]];
    return localizedValue || message;
}

// Modal functions
function showAlert(title, message) {
    const modal = document.getElementById('systemModal');
    document.getElementById('sysModalTitle').textContent = title;
    document.getElementById('sysModalMessage').textContent = resolveLocalizedMessage(message);
    document.getElementById('sysModalCancel').classList.add('hidden');
    document.getElementById('sysModalOk').onclick = () => closeSystemModal(null);
    if (typeof window.animateModalOpen === 'function') {
        window.animateModalOpen(modal, false);
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
    if (typeof window.animateModalOpen === 'function') {
        window.animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function closeSystemModal() {
    const modal = document.getElementById('systemModal');
    if (typeof window.animateModalClose === 'function') {
        window.animateModalClose(modal);
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

// Theme toggle (if not defined in common.js)
if (typeof window.toggleTheme === 'undefined') {
    window.toggleTheme = function() {
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
    const theme = (typeof window.getResolvedTheme === 'function')
        ? window.getResolvedTheme()
        : ((!localStorage.getItem('theme') || localStorage.getItem('theme') === 'system')
            ? ((window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light')
            : localStorage.getItem('theme'));

    if (typeof window.applyThemeUI === 'function') {
        window.applyThemeUI(theme);
        return;
    }
    const isDark = theme === 'dark' || theme === 'amoled';
    document.getElementById('iconMoon')?.classList.toggle('hidden', !isDark || theme === 'amoled');
    document.getElementById('iconAmoled')?.classList.toggle('hidden', theme !== 'amoled');
    document.getElementById('iconSun')?.classList.toggle('hidden', isDark);
    document.getElementById('iconSystem')?.classList.add('hidden');
}
// Global CustomEvent delegation for nodes_monitor.js
document.addEventListener('app:change:toggle-node-selection', e => {
    window.toggleNodeSelection(e.detail.target.getAttribute('data-token'), e.detail.target);
});
document.addEventListener('app:action:open-node-detail', e => {
    window.openNodeDetail(e.detail.target.getAttribute('data-token'));
});
document.addEventListener('app:action:quick-reboot', e => {
    window.quickReboot(e.detail.target.getAttribute('data-token'));
});
// node-service-action is handled by the listener at the top of this file (with confirmation dialog)

window.showPingErrorModal = function(event) {
    if (event) {
        event.stopPropagation();
    }
    const mode = window.GLOBAL_PING_MODE || "http";
    const title = t('web_ping_error_title', 'Ошибка: пинг недоступен', 'Error: ping unavailable');
    const desc = t('web_ping_error_desc', 'Система не смогла измерить сетевую задержку.', 'The system could not measure network latency.');
    const btnText = t('web_ping_how_to_fix_btn', 'Как исправить?', 'How to fix?');
    
    let fixText = "";
    if (mode === "tcp") {
        fixText = t('web_ping_fix_tcp', 'Выбран режим TCP. Проверьте фаервол на исходящий порт 53.', 'TCP mode selected. Check firewall for port 53 out.');
    } else {
        fixText = t('web_ping_fix_http', 'Выбран режим HTTP. Проверьте фаервол на исходящий порт 443.', 'HTTP mode selected. Check firewall for port 443 out.');
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

// Keep the node monitor's private modal closer inside this module.
// common.js owns the global window.closeSystemModal handler because it resolves
// showModalConfirm() promises used by notification clearing and other API actions.
window.showAlert = showAlert;
window.showConfirm = showConfirm;
})();

