document.addEventListener('DOMContentLoaded', () => {
    initSSE();
});

function initSSE() {
    const evtSource = new EventSource('/events');

    evtSource.onmessage = (e) => {
    };

    evtSource.addEventListener("system_stats", (e) => {
        const data = JSON.parse(e.data);
        updateText('stat_cpu', data.cpu + '%');
        updateText('stat_ram', data.ram_percent + '%');
        updateText('stat_disk', data.disk_percent + '%');
        updateText('stat_uptime', data.uptime);
        updateWidth('prog_cpu', data.cpu);
        updateWidth('prog_ram', data.ram_percent);
        updateWidth('prog_disk', data.disk_percent);
        
        updateText('stat_net_sent', formatBytes(data.net_sent));
        updateText('stat_net_recv', formatBytes(data.net_recv));
    });
    evtSource.addEventListener("nodes_update", (e) => {
        const nodes = JSON.parse(e.data);
        
        nodes.forEach(node => {
        });
        if (window.renderNodesList && Array.isArray(nodes)) {
        }
    });
}

function updateText(id, val) {
    const el = document.getElementById(id);
    if (el) el.innerText = val;
}

function updateWidth(id, val) {
    const el = document.getElementById(id);
    if (el) el.style.width = val + '%';
}

function formatBytes(bytes, decimals = 2) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}