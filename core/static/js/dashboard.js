/* /core/static/js/dashboard.js */

let chartRes = null;
let chartNet = null;
let nodeSSESource = null;
let logSSESource = null;
let servicesSSESource = null;

let agentChart = null;
let allNodesData = [];
let currentNodeToken = null;
let currentRenderList = [];   
let renderedCount = 0; 
const NODES_BATCH_SIZE = 15;

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

window.addEventListener('themeChanged', () => {
    updateChartsColors();
});

function initScrollAnimations() {
    if (window.innerWidth >= 1024) return;
    const observerOptions = {
        root: null,
        rootMargin: '0px',
        threshold: 0.1 
    };

    const observer = new IntersectionObserver((entries, obs) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                obs.unobserve(entry.target); // Анимируем только один раз
            }
        });
    }, observerOptions);

    // ИСПРАВЛЕНИЕ: Выбираем только невидимые блоки, чтобы избежать повторной анимации
    const blocks = document.querySelectorAll('.lazy-block:not(.is-visible)');
    blocks.forEach(block => {
        observer.observe(block);
    });
}

window.initDashboard = function() {
    cleanupDashboardSources();
    
    // Запускаем анимацию блоков
    initScrollAnimations();

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
        
        // Lazy Load для списка узлов (Infinite Scroll)
        const listContainer = document.getElementById('nodesList');
        if (listContainer) {
            listContainer.onscroll = function() {
                if (listContainer.scrollTop + listContainer.clientHeight >= listContainer.scrollHeight - 100) {
                    renderNextNodeBatch();
                }
            };
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
    } catch (err) {
        console.error("Agent stats parse error", err);
    }
};

const handleSSENodesList = (e) => {
    if (!document.getElementById('nodesList')) return;
    try {
        const data = JSON.parse(e.data);
        updateNodesListUI(data);
    } catch (err) {
        console.error("Nodes list parse error", err);
    }
};

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById('agentChart') || document.getElementById('nodesList')) {
        window.initDashboard();
    } else {
        // Даже если нет графиков (например, пустая страница), пробуем запустить анимации
        initScrollAnimations();
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

function getNodeUiParams(node) {
    const statusColor = node.status === 'online' ? "bg-green-500" : (node.status === 'restarting' ? "bg-blue-500" : "bg-red-500");
    const statusText = node.status === 'restarting' ? (typeof I18N !== 'undefined' && I18N.web_status_restart ? I18N.web_status_restart : "RESTART") : node.status.toUpperCase();
    const statusTextClass = node.status === 'online' ? "text-green-500" : (node.status === 'restarting' ? "text-blue-500" : "text-red-500");
    const statusBg = node.status === 'online' ? "bg-green-500/10 text-green-600 dark:text-green-400" : (node.status === 'restarting' ? "bg-blue-500/10 text-blue-600 dark:text-blue-400" : "bg-red-500/10 text-red-600 dark:text-red-400");

    const cpu = Math.round(node.cpu || 0);
    const ram = Math.round(node.ram || 0);
    const disk = Math.round(node.disk || 0);

    const cpuColor = cpu > 80 ? 'text-red-500' : 'text-gray-600 dark:text-gray-300';
    const ramColor = ram > 80 ? 'text-red-500' : 'text-gray-600 dark:text-gray-300';
    const diskColor = disk > 90 ? 'text-red-500' : 'text-gray-600 dark:text-gray-300';
    
    return { statusColor, statusText, statusTextClass, statusBg, cpu, ram, disk, cpuColor, ramColor, diskColor };
}

function updateNodesListUI(data) {
    try {
        allNodesData = data.nodes || [];
        const searchInput = document.getElementById('nodeSearch');
        const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
        
        let newList = [];
        if (query) {
            newList = allNodesData.filter(node => {
                const name = (node.name || "").toLowerCase();
                const ip = (decryptData(node.ip) || "").toLowerCase();
                return name.includes(query) || ip.includes(query);
            });
        } else {
            newList = allNodesData;
        }
        
        const container = document.getElementById('nodesList');
        const currentElements = container ? Array.from(container.children).filter(el => el.hasAttribute('data-token')) : [];
        
        if (currentRenderList.length !== newList.length || (currentElements.length === 0 && newList.length > 0)) {
            currentRenderList = newList;
            renderNodesList();
        } else {
            currentRenderList = newList;
            
            const success = updateVisibleNodes(currentElements, currentRenderList);
            if (!success) {
                renderNodesList();
            }
        }

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

function updateVisibleNodes(elements, dataList) {
    for (let i = 0; i < elements.length; i++) {
        const el = elements[i];
        const token = el.getAttribute('data-token');
        const nodeData = dataList[i];   
        if (!nodeData || nodeData.token !== token) return false;   
        const ui = getNodeUiParams(nodeData);     
        const cpuEl = el.querySelector('[data-ref="cpu-val"]');
        if (cpuEl) {
            cpuEl.innerText = ui.cpu + '%';
            cpuEl.className = `text-xs font-mono font-bold ${ui.cpuColor}`;
        }
        const ramEl = el.querySelector('[data-ref="ram-val"]');
        if (ramEl) {
            ramEl.innerText = ui.ram + '%';
            ramEl.className = `text-xs font-mono font-bold ${ui.ramColor}`;
        }
        const diskEl = el.querySelector('[data-ref="disk-val"]');
        if (diskEl) {
            diskEl.innerText = ui.disk + '%';
            diskEl.className = `text-xs font-mono font-bold ${ui.diskColor}`;
        }
        const stText = el.querySelector('[data-ref="status-text"]');
        if (stText) {
            stText.innerText = ui.statusText;
            stText.className = `text-[10px] font-bold ${ui.statusTextClass} mb-0.5`;
        }
        const stBadge = el.querySelector('[data-ref="status-badge"]');
        if (stBadge) {
            stBadge.innerText = ui.statusText;
            stBadge.className = `sm:hidden px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${ui.statusBg}`;
        }
        
        const stDot = el.querySelector('[data-ref="status-dot"]');
        if (stDot) {
            stDot.className = `w-2.5 h-2.5 rounded-full ${ui.statusColor}`;
        }
        
        const stPing = el.querySelector('[data-ref="status-ping"]');
        if (stPing) {
            if (nodeData.status === 'online') {
                stPing.className = `absolute w-2.5 h-2.5 rounded-full ${ui.statusColor} animate-ping opacity-75`;
                stPing.style.display = 'block';
            } else {
                stPing.style.display = 'none';
            }
        }    
        el.setAttribute('onclick', `openNodeDetails('${escapeHtml(nodeData.token)}', '${ui.statusColor}')`);
    }
    return true; 
}

function filterAndRenderNodes() {
    const searchInput = document.getElementById('nodeSearch');
    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
    
    if (query) {
        currentRenderList = allNodesData.filter(node => {
            const name = (node.name || "").toLowerCase();
            const ip = (decryptData(node.ip) || "").toLowerCase();
            return name.includes(query) || ip.includes(query);
        });
    } else {
        currentRenderList = allNodesData;
    }
    renderNodesList();
}

function renderNodesList() {
    const container = document.getElementById('nodesList');
    if (!container) return;

    if (currentRenderList.length === 0) {
        let emptyText = (typeof I18N !== 'undefined' && I18N.web_no_nodes) ? I18N.web_no_nodes : "No nodes connected";
        const searchInput = document.getElementById('nodeSearch');
        if (searchInput && searchInput.value.trim().length > 0 && allNodesData.length > 0) {
            emptyText = (typeof I18N !== 'undefined' && I18N.web_search_nothing_found) ? I18N.web_search_nothing_found : "Nothing found";
        }
        container.innerHTML = `<div class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">${emptyText}</div>`;
        return;
    }

    container.innerHTML = '';
    renderedCount = 0;
    renderNextNodeBatch();
}

function renderNextNodeBatch() {
    const container = document.getElementById('nodesList');
    if (!container) return;
    
    if (renderedCount >= currentRenderList.length) return;

    const batch = currentRenderList.slice(renderedCount, renderedCount + NODES_BATCH_SIZE);
    
    const lblCpu = (typeof I18N !== 'undefined' && I18N.web_label_cpu) ? I18N.web_label_cpu : "CPU";
    const lblRam = (typeof I18N !== 'undefined' && I18N.web_label_ram) ? I18N.web_label_ram : "RAM";
    const lblDisk = (typeof I18N !== 'undefined' && I18N.web_label_disk) ? I18N.web_label_disk : "DISK";
    const lblStatus = (typeof I18N !== 'undefined' && I18N.web_label_status) ? I18N.web_label_status : "STATUS";

    const html = batch.map(node => {
        const ui = getNodeUiParams(node);
        const displayIp = decryptData(node.ip);

        return `
        <div data-token="${escapeHtml(node.token)}" class="bg-white dark:bg-white/5 hover:bg-gray-50 dark:hover:bg-white/10 transition-all duration-200 rounded-xl border border-gray-100 dark:border-white/5 cursor-pointer shadow-sm hover:shadow-md overflow-hidden group mb-2 animate-fade-in-up" onclick="openNodeDetails('${escapeHtml(node.token)}', '${ui.statusColor}')">
            
            <div class="p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
                
                <div class="flex items-center gap-3 min-w-0">
                    <div class="relative shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-gray-100 dark:bg-black/20">
                        <div data-ref="status-dot" class="w-2.5 h-2.5 rounded-full ${ui.statusColor}"></div>
                        <div data-ref="status-ping" class="absolute w-2.5 h-2.5 rounded-full ${ui.statusColor} animate-ping opacity-75" style="${node.status === 'online' ? '' : 'display:none'}"></div>
                    </div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2">
                            <div data-ref="name" class="font-bold text-sm text-gray-900 dark:text-white truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">${escapeHtml(node.name)}</div>
                            <div data-ref="status-badge" class="sm:hidden px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${ui.statusBg}">${ui.statusText}</div>
                        </div>
                        <div data-ref="ip" class="text-[10px] sm:text-xs font-mono text-gray-400 truncate">${escapeHtml(displayIp)}</div>
                    </div>
                </div>

                <div class="flex items-center justify-between sm:justify-end gap-1 sm:gap-6 mt-1 sm:mt-0 pt-3 sm:pt-0 border-t border-gray-100 dark:border-white/5 sm:border-0">
                    
                    <div class="text-center sm:text-right flex-1 sm:flex-none">
                        <div class="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">${lblCpu}</div>
                        <div data-ref="cpu-val" class="text-xs font-mono font-bold ${ui.cpuColor}">${ui.cpu}%</div>
                    </div>

                    <div class="text-center sm:text-right flex-1 sm:flex-none">
                        <div class="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">${lblRam}</div>
                        <div data-ref="ram-val" class="text-xs font-mono font-bold ${ui.ramColor}">${ui.ram}%</div>
                    </div>

                    <div class="text-center sm:text-right flex-1 sm:flex-none">
                        <div class="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">${lblDisk}</div>
                        <div data-ref="disk-val" class="text-xs font-mono font-bold ${ui.diskColor}">${ui.disk}%</div>
                    </div>

                    <div class="hidden sm:block text-right ml-2 pl-3 border-l border-gray-200 dark:border-white/10 min-w-[70px]">
                        <div data-ref="status-text" class="text-[10px] font-bold ${ui.statusTextClass} mb-0.5">${ui.statusText}</div>
                        <div class="text-[9px] text-gray-300 dark:text-gray-600">${lblStatus}</div>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');

    container.insertAdjacentHTML('beforeend', html);
    renderedCount += batch.length;
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

            let rxSpeed = 0,
                txSpeed = 0;
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
            if (ipEl && data.stats.ip) ipEl.innerText = decryptData(data.stats.ip); 
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
        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }));
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
        interaction: {
            mode: 'index',
            intersect: false
        },
        scales: {
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    color: tickColor,
                    maxTicksLimit: maxTicks,
                    maxRotation: 0
                }
            },
            y: {
                position: 'right',
                grid: {
                    color: gridColor
                },
                ticks: {
                    color: tickColor,
                    callback: (v) => formatSpeed(v)
                },
                beginAtZero: true
            }
        },
        plugins: {
            legend: {
                labels: {
                    color: tickColor,
                    usePointStyle: true
                }
            },
            tooltip: {
                mode: 'index',
                intersect: false,
                callbacks: {
                    label: (c) => c.dataset.label + ': ' + formatSpeed(c.raw)
                }
            }
        },
        elements: {
            line: {
                tension: 0.4
            },
            point: {
                radius: 0,
                hitRadius: 20,
                hoverRadius: 4
            }
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
                datasets: [{
                    label: 'RX',
                    data: netRx,
                    borderColor: '#22c55e',
                    borderWidth: 2,
                    backgroundColor: rxGrad,
                    fill: true
                }, {
                    label: 'TX',
                    data: netTx,
                    borderColor: '#3b82f6',
                    borderWidth: 2,
                    backgroundColor: txGrad,
                    fill: true
                }]
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
        if (loader.parentElement) loader.remove();
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
                        const emptyTitle = (typeof I18N !== 'undefined' && I18N.web_logs_empty_title) ? I18N.web_logs_empty_title : "Logs are empty";
                        const emptyDesc = (typeof I18N !== 'undefined' && I18N.web_logs_empty_desc) ? I18N.web_logs_empty_desc : "No new entries found";

                        const emptyHtml = `
                        <div id="empty-logs-state" class="flex flex-col items-center justify-center h-full min-h-[200px] text-gray-400 dark:text-gray-600 animate-fade-in-up select-none opacity-80">
                            <div class="bg-gray-100 dark:bg-white/5 p-4 rounded-full mb-3">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
                                </svg>
                            </div>
                            <span class="text-sm font-bold text-gray-500 dark:text-gray-400">${escapeHtml(emptyTitle)}</span>
                            <span class="text-[10px] uppercase tracking-wider opacity-60 mt-1">${escapeHtml(emptyDesc)}</span>
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
                container.scrollTo({
                    top: container.scrollHeight,
                    behavior: 'auto'
                });
            } else if (isAtBottom) {
                container.scrollTo({
                    top: container.scrollHeight,
                    behavior: 'smooth'
                });
            }

            if (loader) {
                removeLogLoading();
            }

        } catch (err) {
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
        currentNodeToken = token;
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
        } catch (ex) {}
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
        // ИСПРАВЛЕНИЕ: preventScroll: true
        nameInput.focus({ preventScroll: true });
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
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                token: currentNodeToken,
                name: newName
            })
        });

        if (res.ok) {
            if (window.showToast) {
                const msg = (typeof I18N !== 'undefined' && I18N.web_node_rename_success) ? I18N.web_node_rename_success : "Name updated";
                window.showToast(msg);
            }
        } else {
            const data = await res.json();
            const errorMsg = (typeof I18N !== 'undefined' && I18N.web_node_rename_error) ? I18N.web_node_rename_error : "Error updating name";
            const errTitle = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            if (window.showModalAlert) await window.showModalAlert(data.error || errorMsg, errTitle);
        }
    } catch (e) {
        console.error(e);
        const errTitle = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
        if (window.showModalAlert) await window.showModalAlert(String(e), errTitle);
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

    labels.push(new Date(history[0].t * 1000).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    }));
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
        labels.push(new Date(history[i].t * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        }));
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
        interaction: {
            mode: 'index',
            intersect: false
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: {
                    color: gridColor
                },
                ticks: {
                    color: tickColor,
                    font: {
                        size: 10
                    }
                }
            },
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    display: !isMobile,
                    maxTicksLimit: isMobile ? 3 : 6
                }
            }
        },
        plugins: {
            legend: {
                labels: {
                    color: tickColor,
                    boxWidth: 10,
                    usePointStyle: true
                }
            }
        },
        elements: {
            line: {
                tension: 0.4
            },
            point: {
                radius: 0,
                hitRadius: 10
            }
        }
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
                datasets: [{
                    label: `${lblCpu} (%)`,
                    data: cpuData,
                    borderColor: '#3b82f6',
                    borderWidth: 2,
                    backgroundColor: cpuGrad,
                    fill: true
                }, {
                    label: `${lblRam} (%)`,
                    data: ramData,
                    borderColor: '#a855f7',
                    borderWidth: 2,
                    backgroundColor: ramGrad,
                    fill: true
                }]
            },
            options: {
                ...commonOptions,
                scales: {
                    ...commonOptions.scales,
                    y: {
                        ...commonOptions.scales.y,
                        max: 100
                    }
                }
            }
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
                datasets: [{
                    label: 'RX',
                    data: netRx,
                    borderColor: '#22c55e',
                    borderWidth: 2,
                    backgroundColor: rxGrad,
                    fill: true
                }, {
                    label: 'TX',
                    data: netTx,
                    borderColor: '#ef4444',
                    borderWidth: 2,
                    backgroundColor: txGrad,
                    fill: true
                }]
            },
            options: netOpts
        });
    }
}

window.resetTrafficDashboard = async function() {
    if (!await window.showModalConfirm(I18N.web_traffic_reset_confirm, I18N.modal_title_confirm)) return;

    try {
        const res = await fetch('/api/traffic/reset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        if (res.ok) {
            if (window.showToast) window.showToast(I18N.traffic_reset_done);
        } else {
            const data = await res.json();
            const errorShort = (typeof I18N !== 'undefined' && I18N.web_error_short) ? I18N.web_error_short : "Error";
            await window.showModalAlert(data.error || "Failed", errorShort);
        }
    } catch (e) {
        const errorShort = (typeof I18N !== 'undefined' && I18N.web_conn_error_short) ? I18N.web_conn_error_short : "Conn Error";
        await window.showModalAlert(String(e), errorShort);
    }
};

window.openAddNodeModal = function() {
    const m = document.getElementById('addNodeModal');
    if (m) {
        document.getElementById('nodeResultDash')?.classList.add('hidden');
        const i = document.getElementById('newNodeNameDash');
        if (i) {
            i.value = '';
            if (typeof validateNodeInput === 'function') validateNodeInput();
        }
        animateModalOpen(m, true);
        if (i) {
            setTimeout(() => {
                i.focus({ preventScroll: true });
            }, 150); // Чуть увеличили задержку для надежности на iOS
        }
    }
};

window.animateModalClose = function(modal) {
    if (!modal) return;
    const card = modal.firstElementChild;
    if (card) {
        card.style.opacity = '0';
        card.style.transform = 'scale(0.95)';
    }
    if (typeof handleModalInputClick !== 'undefined') {
        modal.removeEventListener('click', handleModalInputClick);
    }

    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        if (document.body.style.position === 'fixed') {
            const scrollY = Math.abs(parseInt(document.body.style.top || '0'));
            document.body.style.position = '';
            document.body.style.top = '';
            document.body.style.width = '';
            document.body.style.overflow = '';

            // 3. ВАЖНО: Отключаем плавную прокрутку на всем документе перед восстановлением
            const html = document.documentElement;
            const originalBehavior = html.style.scrollBehavior;
            html.style.scrollBehavior = 'auto'; 

            // 4. Мгновенно прыгаем на место
            window.scrollTo(0, scrollY);

            // 5. Возвращаем плавность (если была) через небольшой таймаут
            setTimeout(() => {
                html.style.scrollBehavior = originalBehavior;
            }, 50);
        } else {
            document.body.style.overflow = '';
        }
        modal.style.height = '';
        modal.style.top = '';
        modal.style.paddingBottom = '';
        
        modal.classList.remove('items-start', 'pt-4', 'overflow-y-auto');
        modal.classList.add('items-center');

        if (card) {
            card.classList.add('my-auto');
            card.style.marginBottom = '';
        }
    }, 200);
};

// --- Services Manager ---

// Initialize SSE connection for services
function initServicesSSE() {
    const container = document.getElementById('services-container');
    if (!container) return;
    
    // Close existing connection if any
    if (servicesSSESource) {
        servicesSSESource.close();
        servicesSSESource = null;
    }
    
    servicesSSESource = new EventSource('/api/events/services');
    
    servicesSSESource.addEventListener('services', (e) => {
        try {
            const data = JSON.parse(e.data);
            const encryptedServices = data.services || [];
            
            // Decrypt each service
            const services = encryptedServices.map(svc => ({
                name: decryptData(svc.name),
                type: decryptData(svc.type),
                status: decryptData(svc.status)
            }));
            
            renderServices(services);
        } catch (err) {
            console.error('SSE Services parse error:', err);
        }
    });
    
    servicesSSESource.addEventListener('session_status', (e) => {
        if (e.data === 'expired') {
            servicesSSESource.close();
            window.location.reload();
        }
    });
    
    servicesSSESource.addEventListener('shutdown', () => {
        servicesSSESource.close();
    });
    
    servicesSSESource.onerror = (err) => {
        console.error('SSE Services error:', err);
        // Try to reconnect after 5 seconds
        servicesSSESource.close();
        servicesSSESource = null;
        setTimeout(() => {
            if (document.getElementById('services-container')) {
                initServicesSSE();
            }
        }, 5000);
    };
}

// Load services via fetch (used for initial load and manual refresh)
function loadServices() {
    const container = document.getElementById('services-container');
    if (!container) return;

    fetch('/api/services')
        .then(res => {
            if (res.status === 401) {
                window.location.reload();
                return;
            }
            const contentType = res.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                console.warn('Services API returned non-JSON response');
                return null;
            }
            if (!res.ok) {
                 return res.json().then(errData => {
                     throw new Error(errData.error || 'Server Error ' + res.status);
                 });
            }
            return res.json();
        })
        .then(data => {
            if (!data) {
                container.innerHTML = `<div class="col-span-full text-center text-gray-400 py-4">${window.i18n.services_empty || 'Services not available'}</div>`;
                return;
            }
            if (data.error) {
                 throw new Error(data.error);
            }
            renderServices(data);
            
            // Restart SSE connection after manual refresh
            initServicesSSE();
        })
        .catch(err => {
            console.error('Error loading services:', err);
            container.innerHTML = `<div class="col-span-full text-center text-gray-400 py-4">${window.i18n.services_empty || 'Services not available'}</div>`;
        });
}

function renderServices(services, forceRender = false) {
    const container = document.getElementById('services-container');
    
    // Don't re-render if user is actively searching (unless forceRender is true)
    const searchInput = document.getElementById('servicesSearchInput');
    if (!forceRender && searchInput && searchInput.value.trim()) {
        // Just update data cache - don't re-apply filter to avoid flicker
        window._servicesData = services;
        // Update only status of visible cards without re-rendering
        const cards = container.querySelectorAll('.service-card');
        services.forEach(svc => {
            const card = Array.from(cards).find(c => c.dataset.name === svc.name);
            if (card) {
                const isRunning = svc.status === 'running' || svc.status === 'active';
                const dot = card.querySelector('.rounded-full');
                if (dot) {
                    dot.className = `w-2.5 h-2.5 rounded-full bg-${isRunning ? 'green' : 'red'}-500 shadow-[0_0_6px_rgba(var(--color-${isRunning ? 'green' : 'red'}-500),0.6)] flex-shrink-0`;
                }
            }
        });
        return;
    }
    
    container.innerHTML = '';
    
    // Store services for filtering
    window._servicesData = services;
    
    if (!Array.isArray(services)) {
        console.error("Services is not array:", services);
        return;
    }
    
    if (services.length === 0) {
        container.innerHTML = `<div class="col-span-full text-center text-gray-500 py-4">${window.i18n.services_empty}</div>`;
        return;
    }
    
    const roleLevel = window.USER_ROLE_LEVEL || 0;
    
    services.forEach(item => {
        const isRunning = item.status === 'running' || item.status === 'active';
        const colorClass = isRunning ? 'green' : 'red';
        
        // Buttons Logic based on User Role Level
        // Level 0: View Only (No buttons)
        // Level 1: Start/Restart (Admins)
        // Level 2: All (Main Admin)
        
        let buttonsHtml = '';
        if (roleLevel >= 1) {
            // Show Start only if NOT running
            if (!isRunning) {
                buttonsHtml += `
                    <button onclick="event.stopPropagation(); controlService('${item.name}', '${item.type}', 'start')" class="group w-8 h-8 flex items-center justify-center rounded-lg bg-green-500/20 hover:bg-green-700 transition-all duration-200 hover:scale-110 hover:shadow-lg hover:shadow-green-500/30 active:scale-95" title="${window.i18n.btn_start}">
                         <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-green-500 group-hover:text-white transition-colors" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                    </button>
                `;
            }
            // Show Restart only if running
            if (isRunning) {
                buttonsHtml += `
                    <button onclick="event.stopPropagation(); controlService('${item.name}', '${item.type}', 'restart')" class="group w-8 h-8 flex items-center justify-center rounded-lg bg-blue-500/20 hover:bg-blue-700 transition-all duration-200 hover:scale-110 hover:shadow-lg hover:shadow-blue-500/30 active:scale-95" title="${window.i18n.btn_restart}">
                         <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-blue-500 group-hover:text-white group-hover:animate-spin transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                    </button>
                `;
            }
        }
        if (roleLevel >= 2 && isRunning) {
            // Show Stop only if running
            buttonsHtml += `
                <button onclick="event.stopPropagation(); controlService('${item.name}', '${item.type}', 'stop')" class="group w-8 h-8 flex items-center justify-center rounded-lg bg-red-500/20 hover:bg-red-700 transition-all duration-200 hover:scale-110 hover:shadow-lg hover:shadow-red-500/30 active:scale-95" title="${window.i18n.btn_stop}">
                     <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-red-500 group-hover:text-white transition-colors" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
                </button>
            `;
        }

        // Compact inline card for service - clickable for info
        const card = document.createElement('div');
        card.className = 'service-card w-fit bg-gray-50 dark:bg-black/20 rounded-xl px-4 py-3 flex items-center justify-between gap-3 transition hover:bg-gray-100 dark:hover:bg-white/5 cursor-pointer';
        card.dataset.name = item.name;
        card.dataset.type = item.type;
        card.onclick = () => openServiceInfoModal(item.name, item.type);
        
        card.innerHTML = `
            <div class="flex items-center gap-3 min-w-0">
                <div class="w-2.5 h-2.5 rounded-full bg-${colorClass}-500 shadow-[0_0_6px_rgba(var(--color-${colorClass}-500),0.6)] flex-shrink-0"></div>
                <div class="min-w-0">
                    <h4 class="font-semibold text-sm text-gray-900 dark:text-white leading-tight truncate">${item.name}</h4>
                    <span class="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">${item.type}</span>
                </div>
            </div>
            <div class="flex items-center gap-1.5 flex-shrink-0">
                ${buttonsHtml}
            </div>
        `;
        container.appendChild(card);
    });
}

// --- Services Search Filtering ---

let _globalSearchTimeout = null;
let _globalServicesCache = null;

function filterServices(query) {
    const container = document.getElementById('services-container');
    const cards = container.querySelectorAll('.service-card');
    const q = query.toLowerCase().trim();
    
    // Remove blur from all cards
    cards.forEach(card => {
        card.classList.remove('opacity-30', 'pointer-events-none');
    });
    
    // If empty query, show all managed services and remove global results
    if (!q) {
        cards.forEach(card => card.style.display = '');
        const noResults = container.querySelector('.no-search-results');
        if (noResults) noResults.remove();
        const globalResults = container.querySelectorAll('.global-search-result-card');
        globalResults.forEach(card => card.remove());
        const loadingEl = container.querySelector('.search-loading');
        if (loadingEl) loadingEl.remove();
        return;
    }
    
    // Filter managed services (exclude global search result cards)
    let visibleCount = 0;
    cards.forEach(card => {
        // Skip global search result cards
        if (card.classList.contains('global-search-result-card')) return;
        
        const name = card.dataset.name?.toLowerCase() || '';
        const type = card.dataset.type?.toLowerCase() || '';
        if (name.includes(q) || type.includes(q)) {
            card.style.display = '';
            visibleCount++;
        } else {
            card.style.display = 'none';
        }
    });
    
    // Remove old "no results" message
    const noResults = container.querySelector('.no-search-results');
    if (noResults) noResults.remove();
    
    // Search globally with debounce - only for main admin (level 2) who can add services
    const roleLevel = window.USER_ROLE_LEVEL || 0;
    if (q.length >= 1 && roleLevel >= 2) {
        // Remove old global results
        const oldGlobalResults = container.querySelectorAll('.global-search-result-card');
        oldGlobalResults.forEach(card => card.remove());
        
        // Show loading spinner
        let loadingEl = container.querySelector('.search-loading');
        if (!loadingEl) {
            loadingEl = document.createElement('div');
            loadingEl.className = 'search-loading col-span-full flex items-center justify-center gap-2 py-4 text-gray-400';
            loadingEl.innerHTML = `
                <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>${I18N.web_searching || 'Поиск...'}</span>
            `;
            container.appendChild(loadingEl);
        }
        
        clearTimeout(_globalSearchTimeout);
        _globalSearchTimeout = setTimeout(() => {
            searchGlobalServices(q, visibleCount);
        }, 300);
    } else if (visibleCount === 0 && q) {
        // Show "no results" for non-admins
        const globalResults = container.querySelectorAll('.global-search-result-card');
        globalResults.forEach(card => card.remove());
        const msg = document.createElement('div');
        msg.className = 'no-search-results col-span-full text-center text-gray-400 py-4';
        msg.textContent = I18N.web_services_none_found || 'No services found';
        container.appendChild(msg);
    }
}

async function searchGlobalServices(query, managedMatchCount) {
    const container = document.getElementById('services-container');
    const cards = container.querySelectorAll('.service-card:not(.global-search-result-card)');
    
    // Remove loading spinner
    const loadingEl = container.querySelector('.search-loading');
    if (loadingEl) loadingEl.remove();
    
    // Get managed service names to exclude from results
    const managedNames = new Set();
    cards.forEach(card => {
        if (card.dataset.name) managedNames.add(card.dataset.name.toLowerCase());
    });
    
    try {
        // Use cache or fetch (with search=1 param for read-only access)
        if (!_globalServicesCache) {
            const res = await fetch('/api/services/available?search=1');
            if (!res.ok) return;
            _globalServicesCache = await res.json();
            // Cache expires after 30 seconds
            setTimeout(() => { _globalServicesCache = null; }, 30000);
        }
        
        const q = query.toLowerCase();
        
        // Filter global services that match and are NOT already managed
        const matches = _globalServicesCache.filter(s => {
            const name = s.name.toLowerCase();
            const isMatch = name.includes(q);
            const isNotManaged = !managedNames.has(name);
            return isMatch && isNotManaged && !s.managed;
        }).slice(0, 6); // Limit to 6 results
        
        // Remove previous global results (already handled at the top of this section)
        
        if (matches.length === 0) {
            // Remove blur if no global matches
            cards.forEach(card => {
                card.classList.remove('opacity-30', 'pointer-events-none');
            });
            // No global matches either
            if (managedMatchCount === 0) {
                const existingNoResults = container.querySelector('.no-search-results');
                if (!existingNoResults) {
                    const msg = document.createElement('div');
                    msg.className = 'no-search-results col-span-full text-center text-gray-400 py-4';
                    msg.textContent = I18N.web_services_none_found || 'No services found';
                    container.appendChild(msg);
                }
            }
            return;
        }
        
        // Blur existing managed cards to focus on global results
        cards.forEach(card => {
            if (card.style.display !== 'none') {
                card.classList.add('opacity-30', 'pointer-events-none');
            }
        });
        
        // Remove old global results first
        const oldResults = container.querySelectorAll('.global-search-result-card');
        oldResults.forEach(card => card.remove());
        
        matches.forEach(item => {
            const isRunning = item.status === 'running' || item.status === 'active';
            const colorClass = isRunning ? 'green' : 'red';
            const typeIcon = item.type === 'docker' ? '🐳' : '⚙️';
            const roleLevel = window.USER_ROLE_LEVEL || 0;
            
            // Card in same style as managed services but with Add button
            const card = document.createElement('div');
            card.className = 'global-search-result-card service-card w-fit bg-gray-50 dark:bg-black/20 rounded-xl px-4 py-3 flex items-center justify-between gap-3 transition hover:bg-gray-100 dark:hover:bg-white/5';
            
            // Build add button only for main admin
            let addButtonHtml = '';
            if (roleLevel >= 2) {
                addButtonHtml = `
                    <button onclick="addServiceFromSearch('${item.name}', '${item.type}')" 
                            class="w-8 h-8 flex items-center justify-center rounded-lg bg-green-500/20 hover:bg-green-600 transition-all duration-200 hover:scale-110 active:scale-95"
                            title="${I18N.web_services_btn_add || 'Добавить'}">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-green-500 hover:text-white transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
                        </svg>
                    </button>
                `;
            }
            
            card.innerHTML = `
                <div class="flex items-center gap-3 min-w-0">
                    <div class="w-2.5 h-2.5 rounded-full bg-${colorClass}-500 shadow-[0_0_6px_rgba(var(--color-${colorClass}-500),0.6)] flex-shrink-0"></div>
                    <div class="min-w-0">
                        <h4 class="font-semibold text-sm text-gray-900 dark:text-white leading-tight truncate">${item.name}</h4>
                        <span class="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">${item.type}</span>
                    </div>
                </div>
                <div class="flex items-center gap-1.5 flex-shrink-0">
                    ${addButtonHtml}
                </div>
            `;
            container.appendChild(card);
        });
        
    } catch (err) {
        console.error('Error searching global services:', err);
    }
}

async function addServiceFromSearch(name, type) {
    try {
        const res = await fetch('/api/services/manage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'add', name, type })
        });
        
        if (res.ok) {
            // Clear search field
            const searchInput = document.getElementById('servicesSearchInput');
            if (searchInput) searchInput.value = '';
            
            // Clear global results and caches
            _globalServicesCache = null;
            const container = document.getElementById('services-container');
            const globalResults = container.querySelectorAll('.global-search-result-card');
            globalResults.forEach(card => card.remove());
            
            // Remove blur from managed cards
            container.querySelectorAll('.service-card').forEach(card => {
                card.classList.remove('opacity-30', 'pointer-events-none');
            });
            
            // Force full reload
            loadServices();
        } else {
            const data = await res.json();
            window.showModalAlert((I18N.web_services_error || 'Error') + ': ' + (data.error || 'Unknown'), I18N.modal_title_error);
        }
    } catch (err) {
        console.error('Error adding service:', err);
        window.showModalAlert(I18N.web_services_request_failed || 'Request failed', I18N.modal_title_error);
    }
}

// --- Service Info Modal ---

function openServiceInfoModal(name, type) {
    const modal = document.getElementById('serviceInfoModal');
    const content = document.getElementById('serviceInfoContent');
    const title = document.getElementById('serviceInfoModalTitle');
    
    // Set title to service name
    if (title) title.innerText = name;
    
    // Show loading
    content.innerHTML = `<div class="text-center py-4 text-gray-400">
        <svg class="animate-spin h-6 w-6 mx-auto mb-2 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        ${I18N.web_services_info_loading || 'Loading...'}
    </div>`;
    
    // Open modal with animation
    if (typeof animateModalOpen === 'function') {
        animateModalOpen(modal, false);
    } else {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
    }
    
    // Fetch service info
    fetch(`/api/services/info/${encodeURIComponent(name)}?type=${type}`)
        .then(res => res.json())
        .then(info => {
            renderServiceInfo(info);
        })
        .catch(err => {
            console.error('Error fetching service info:', err);
            content.innerHTML = `<div class="text-center py-4 text-red-500">${err.message}</div>`;
        });
}

function closeServiceInfoModal() {
    const modal = document.getElementById('serviceInfoModal');
    if (typeof animateModalClose === 'function') {
        animateModalClose(modal);
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = '';
    }
}

function renderServiceInfo(info) {
    const content = document.getElementById('serviceInfoContent');
    
    const statusColor = info.status === 'running' ? 'green' : info.status === 'stopped' ? 'red' : 'gray';
    const statusText = info.status === 'running' 
        ? (I18N.web_services_status_running || 'Running')
        : info.status === 'stopped' 
            ? (I18N.web_services_status_stopped || 'Stopped')
            : (I18N.web_services_status_unknown || 'Unknown');
    
    const typeIcon = info.type === 'docker' ? '🐳' : '⚙️';
    const typeLabel = info.type === 'docker' ? 'Docker' : 'Systemd';
    const description = info.description || (I18N.web_services_info_no_desc || 'No description');
    
    // Build info items
    let infoItems = [];
    
    // Status
    infoItems.push(`<div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-${statusColor}-500"></span>
        <span class="text-${statusColor}-600 dark:text-${statusColor}-400 font-medium">${statusText}</span>
    </div>`);
    
    // Type
    infoItems.push(`<div class="flex items-center gap-1.5 text-gray-500 dark:text-gray-400">
        <span>${typeIcon}</span>
        <span class="uppercase text-xs">${typeLabel}</span>
    </div>`);
    
    // Extra info items
    let extraItems = [];
    
    // Docker specific
    if (info.type === 'docker') {
        if (info.image) {
            extraItems.push(`<div class="flex justify-between py-1.5 border-b border-gray-100 dark:border-white/5">
                <span class="text-gray-500 dark:text-gray-400">Image</span>
                <span class="font-mono text-xs truncate max-w-[200px]" title="${info.image}">${info.image}</span>
            </div>`);
        }
        if (info.ports) {
            extraItems.push(`<div class="flex justify-between py-1.5 border-b border-gray-100 dark:border-white/5">
                <span class="text-gray-500 dark:text-gray-400">Ports</span>
                <span class="font-mono text-xs">${info.ports}</span>
            </div>`);
        }
    }
    
    // Systemd specific
    if (info.type === 'systemd') {
        if (info.main_pid) {
            extraItems.push(`<div class="flex justify-between py-1.5 border-b border-gray-100 dark:border-white/5">
                <span class="text-gray-500 dark:text-gray-400">PID</span>
                <span class="font-mono text-xs">${info.main_pid}</span>
            </div>`);
        }
        if (info.memory) {
            extraItems.push(`<div class="flex justify-between py-1.5 border-b border-gray-100 dark:border-white/5">
                <span class="text-gray-500 dark:text-gray-400">Memory</span>
                <span class="font-mono text-xs">${info.memory}</span>
            </div>`);
        }
    }
    
    if (info.uptime) {
        extraItems.push(`<div class="flex justify-between py-1.5">
            <span class="text-gray-500 dark:text-gray-400">Uptime</span>
            <span class="text-xs">${info.uptime}</span>
        </div>`);
    }
    
    content.innerHTML = `
        <div class="space-y-3">
            <!-- Status row -->
            <div class="flex items-center justify-between">
                ${infoItems.join('')}
            </div>
            
            <!-- Description -->
            <p class="text-gray-600 dark:text-gray-300 leading-relaxed">${description}</p>
            
            ${extraItems.length > 0 ? `
            <!-- Extra info -->
            <div class="pt-2 border-t border-gray-100 dark:border-white/5 text-sm">
                ${extraItems.join('')}
            </div>
            ` : ''}
        </div>
    `;
}

async function controlService(name, type, action) {
    const confirmKey = 'web_services_confirm_' + action;
    const confirmMsg = (I18N[confirmKey] || 'Are you sure you want to {action} {name}?').replace('{name}', name).replace('{action}', action);
    
    if (!await window.showModalConfirm(confirmMsg, I18N.modal_title_confirm)) return;
    
    try {
        const res = await fetch('/api/services/' + action, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name: name, type: type })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadServices(); // refresh
        } else {
            window.showModalAlert((I18N.web_services_error || 'Error') + ': ' + (data.error || 'Unknown error'), I18N.modal_title_error || 'Error');
        }
    } catch (err) {
        console.error('Error:', err);
        window.showModalAlert(I18N.web_services_request_failed || 'Request failed', I18N.modal_title_error || 'Error');
    }
}

// --- Services Edit Modal ---

function openServicesEditModal() {
    const modal = document.getElementById('servicesEditModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
    // Clear search inputs
    const searchInputDesktop = document.getElementById('servicesEditSearchInputDesktop');
    const searchInputMobile = document.getElementById('servicesEditSearchInputMobile');
    if (searchInputDesktop) searchInputDesktop.value = '';
    if (searchInputMobile) searchInputMobile.value = '';
    loadAvailableServices();
}

function closeServicesEditModal() {
    const modal = document.getElementById('servicesEditModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = '';
}

async function loadAvailableServices() {
    const container = document.getElementById('servicesEditList');
    container.innerHTML = `
        <div class="flex items-center justify-center gap-2 py-8 text-gray-400">
            <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span>${I18N.web_loading || 'Loading...'}</span>
        </div>`;
    
    try {
        const res = await fetch('/api/services/available');
        const data = await res.json();
        
        if (!res.ok) {
            throw new Error(data.error || 'Error');
        }
        
        renderServicesEditList(data);
    } catch (err) {
        console.error('Error loading available services:', err);
        container.innerHTML = `<div class="text-center py-8 text-red-500">${err.message}</div>`;
    }
}

function renderServicesEditList(services) {
    const container = document.getElementById('servicesEditList');
    
    if (!services || services.length === 0) {
        container.innerHTML = `<div class="text-center py-8 text-gray-400">${I18N.web_services_none_found || 'No services found'}</div>`;
        return;
    }
    
    // Grid: 1 col mobile, 2 cols sm, 3 cols md, 4 cols lg
    let html = '<div id="servicesEditGrid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">';
    
    for (const s of services) {
        const isManaged = s.managed;
        const statusIcon = s.status === 'running' ? '🟢' : '🔴';
        const typeLabel = s.type === 'docker' ? '🐳' : '⚙️';
        const safeId = s.name.replace(/[^a-zA-Z0-9]/g, '_');
        
        html += `
            <div class="service-edit-card flex items-center justify-between p-2.5 bg-gray-50 dark:bg-black/20 rounded-xl gap-2" data-name="${s.name}" data-type="${s.type}">
                <div class="flex items-center gap-2 min-w-0 flex-1">
                    <span class="text-base flex-shrink-0">${typeLabel}</span>
                    <div class="min-w-0 flex-1">
                        <div class="font-medium text-sm text-gray-900 dark:text-white truncate" title="${s.name}">${s.name}</div>
                        <div class="text-[10px] text-gray-500">${statusIcon} ${s.status}</div>
                    </div>
                </div>
                <button id="srv-btn-${safeId}" 
                        data-type="${s.type}"
                        onclick="toggleServiceManaged('${s.name}', '${s.type}', ${isManaged}, this)" 
                        class="srv-manage-btn px-2 py-1 rounded-lg text-xs font-medium transition min-w-[60px] flex items-center justify-center gap-1 flex-shrink-0 ${isManaged 
                            ? 'bg-red-500/20 text-red-600 dark:text-red-400 hover:bg-red-500/30' 
                            : 'bg-green-500/20 text-green-600 dark:text-green-400 hover:bg-green-500/30'}">
                    <span class="btn-text">${isManaged ? (I18N.web_services_btn_remove || 'Remove') : (I18N.web_services_btn_add || 'Add')}</span>
                    <svg class="btn-spinner hidden animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                </button>
            </div>
        `;
    }
    
    html += '</div>';
    container.innerHTML = html;
}

// Filter services in Edit modal
function filterServicesEditList(query) {
    const grid = document.getElementById('servicesEditGrid');
    if (!grid) return;
    
    const cards = grid.querySelectorAll('.service-edit-card');
    const q = (query || '').toLowerCase().trim();
    
    let visibleCount = 0;
    cards.forEach(card => {
        const name = (card.dataset.name || '').toLowerCase();
        const type = (card.dataset.type || '').toLowerCase();
        if (!q || name.includes(q) || type.includes(q)) {
            card.classList.remove('hidden');
            visibleCount++;
        } else {
            card.classList.add('hidden');
        }
    });
    
    // Show "no results" if nothing visible
    let noResults = grid.parentElement.querySelector('.no-search-results-edit');
    if (visibleCount === 0 && q) {
        if (!noResults) {
            const msg = document.createElement('div');
            msg.className = 'no-search-results-edit text-center text-gray-400 py-4';
            msg.textContent = I18N.web_services_none_found || 'No services found';
            grid.parentElement.appendChild(msg);
        }
    } else if (noResults) {
        noResults.remove();
    }
}

function openAgentIpsModal() {
  const m = document.getElementById('agentIpsModal');
  if (!m) return;
  m.classList.remove('hidden');
  m.classList.add('flex');
  loadAgentIpv4();
}

function closeAgentIpsModal() {
  const m = document.getElementById('agentIpsModal');
  if (!m) return;
  m.classList.add('hidden');
  m.classList.remove('flex');
}

async function loadAgentIpv4() {
  const elPrimary = document.getElementById('agentIpsPrimary');
  const elList = document.getElementById('agentIpsList');
  const elEmpty = document.getElementById('agentIpsEmpty');
  const elLoading = document.getElementById('agentIpsLoading');
  const elError = document.getElementById('agentIpsError');
  elError?.classList.add('hidden');
  elEmpty?.classList.add('hidden');
  if (elList) elList.innerHTML = '';
  if (elLoading) elLoading.classList.remove('hidden');

  try {
    const r = await fetch('/api/agent/ipv4', { credentials: 'same-origin' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();

    const primary = data.primary || data.source_ip || data.agent_ip || '-';
    const ips = Array.isArray(data.ips) ? data.ips : Array.isArray(data.ipv4) ? data.ipv4 : [];

    if (elPrimary) elPrimary.textContent = primary;

    const secondary = ips.filter(ip => ip && ip !== primary);

    if (!secondary.length) {
      elEmpty?.classList.remove('hidden');
    } else if (elList) {
      elList.innerHTML = secondary.map(ip => `
        <li class="bg-gray-50 dark:bg-black/20 border border-gray-200 dark:border-white/10 rounded-xl px-3 py-2 font-mono text-xs select-all">
          ${escapeHtml(ip)}
        </li>
      `).join('');
    }
  } catch (e) {
    console.error('Error loading IPs:', e);
    elError?.classList.remove('hidden');
  } finally {
    elLoading?.classList.add('hidden');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const badge = document.getElementById('agentIpBadge');
  if (!badge) return;

  const handler = (e) => {
    e.preventDefault();
    e.stopPropagation();
    openAgentIpsModal();
  };

  badge.addEventListener('click', handler);
  badge.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handler(e);
    }
  });
});


async function toggleServiceManaged(name, type, isCurrentlyManaged, btnElement) {
    const action = isCurrentlyManaged ? 'remove' : 'add';

    // Show spinner on button
    if (btnElement) {
        btnElement.disabled = true;
        btnElement.classList.add('opacity-70', 'cursor-wait');
        const textEl = btnElement.querySelector('.btn-text');
        const spinnerEl = btnElement.querySelector('.btn-spinner');
        if (textEl) textEl.classList.add('hidden');
        if (spinnerEl) spinnerEl.classList.remove('hidden');
    }

    try {
        const res = await fetch('/api/services/manage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, name, type })
        });

        const data = await res.json();

        if (data.status === 'ok') {
            // Update just this item instead of reloading all
            updateServiceItemState(name, !isCurrentlyManaged);
            loadServices();
        } else {
            // Restore button state on error
            restoreButtonState(btnElement, isCurrentlyManaged);
            window.showModalAlert(data.error || 'Error', I18N.modal_title_error || 'Error');
        }
    } catch (err) {
        console.error('Error toggling service:', err);
        restoreButtonState(btnElement, isCurrentlyManaged);
        window.showModalAlert(I18N.web_services_request_failed || 'Request failed', I18N.modal_title_error || 'Error');
    }
}

function restoreButtonState(btnElement, isManaged) {
    if (!btnElement) return;
    btnElement.disabled = false;
    btnElement.classList.remove('opacity-70', 'cursor-wait');
    const textEl = btnElement.querySelector('.btn-text');
    const spinnerEl = btnElement.querySelector('.btn-spinner');
    if (textEl) textEl.classList.remove('hidden');
    if (spinnerEl) spinnerEl.classList.add('hidden');
}

function updateServiceItemState(name, isNowManaged) {
    // Find the button by sanitized name
    const btnId = 'srv-btn-' + name.replace(/[^a-zA-Z0-9]/g, '_');
    const btn = document.getElementById(btnId);
    if (!btn) return;

    // Update button appearance
    btn.disabled = false;
    btn.classList.remove('opacity-70', 'cursor-wait');

    const textEl = btn.querySelector('.btn-text');
    const spinnerEl = btn.querySelector('.btn-spinner');

    if (textEl) {
        textEl.classList.remove('hidden');
        textEl.textContent = isNowManaged
            ? (I18N.web_services_btn_remove || 'Remove')
            : (I18N.web_services_btn_add || 'Add');
    }
    if (spinnerEl) spinnerEl.classList.add('hidden');

    // Update button colors
    if (isNowManaged) {
        btn.classList.remove('bg-green-500/20', 'text-green-600', 'dark:text-green-400', 'hover:bg-green-500/30');
        btn.classList.add('bg-red-500/20', 'text-red-600', 'dark:text-red-400', 'hover:bg-red-500/30');
    } else {
        btn.classList.remove('bg-red-500/20', 'text-red-600', 'dark:text-red-400', 'hover:bg-red-500/30');
        btn.classList.add('bg-green-500/20', 'text-green-600', 'dark:text-green-400', 'hover:bg-green-500/30');
    }

    // Update onclick handler
    btn.onclick = function() { toggleServiceManaged(name, btn.dataset.type || 'systemd', isNowManaged, this); };
}

// Init when DOM loaded
document.addEventListener('DOMContentLoaded', () => {
   // Initial load via fetch, then SSE will be started automatically
   loadServices();
});
