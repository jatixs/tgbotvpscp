const assert = require('node:assert/strict');
const { test } = require('node:test');

test('pushQuickStatHistory preserves consecutive steady load values and caps at max', () => {
    const quickStatsHistory = { cpu: [], ram: [], disk: [] };
    const QUICK_STATS_HISTORY_MAX = 30;

    function pushQuickStatHistory(key, value) {
        if (typeof value !== 'number' || Number.isNaN(value)) return;
        const hist = quickStatsHistory[key];
        hist.push(value);
        if (hist.length > QUICK_STATS_HISTORY_MAX) hist.shift();
    }

    // Server at steady 100% CPU
    for (let i = 0; i < 35; i++) {
        pushQuickStatHistory('cpu', 100);
    }
    assert.equal(quickStatsHistory.cpu.length, 30);
    assert.ok(quickStatsHistory.cpu.every(v => v === 100));

    // Disk at constant 20%
    for (let i = 0; i < 5; i++) {
        pushQuickStatHistory('disk', 20);
    }
    assert.equal(quickStatsHistory.disk.length, 5);
    assert.ok(quickStatsHistory.disk.every(v => v === 20));
});

test('getQuickStatColor reflects peak and warn thresholds', () => {
    const quickStatsHistory = { cpu: [100], ram: [82], disk: [20] };
    const SYS_CONFIG = { cpu_threshold: 90, ram_threshold: 80, disk_threshold: 95 };

    function getQuickStatColor(key, defaultRgb) {
        const hist = quickStatsHistory[key];
        const val = hist && hist.length ? hist[hist.length - 1] : 0;
        if (typeof SYS_CONFIG !== 'undefined') {
            const threshold = (key === 'cpu' ? SYS_CONFIG.cpu_threshold : key === 'ram' ? SYS_CONFIG.ram_threshold : SYS_CONFIG.disk_threshold) || 90;
            const isPeak = val >= Math.max(threshold, 95) || val >= threshold + 5;
            const isWarn = val >= threshold;
            if (isPeak) return 'rgb(239, 68, 68)';
            if (isWarn) return 'rgb(249, 115, 22)';
        }
        return defaultRgb;
    }

    assert.equal(getQuickStatColor('cpu', 'rgb(99, 102, 241)'), 'rgb(239, 68, 68)'); // 100 >= 95 -> Peak (red)
    assert.equal(getQuickStatColor('ram', 'rgb(168, 85, 247)'), 'rgb(249, 115, 22)'); // 82 >= 80 -> Warn (orange)
    assert.equal(getQuickStatColor('disk', 'rgb(34, 197, 94)'), 'rgb(34, 197, 94)');  // 20 < 95 -> Default (green)
});

test('renderNodeModalTraffic calculates interface-specific vs total traffic', () => {
    const sampleData = {
        stats: {
            net_rx: 869000000000,
            net_tx: 857000000000,
            interface_counters: {
                eth0: [100000000, 200000000],
                wg0: [5000000, 10000000]
            }
        }
    };

    function resolveTraffic(data, selectedInterface) {
        const stats = data.stats;
        let rx = stats.net_rx;
        let tx = stats.net_tx;

        if (selectedInterface) {
            const counters = stats.interfaces?.[selectedInterface] || stats.interface_counters?.[selectedInterface];
            if (Array.isArray(counters)) {
                rx = counters[0];
                tx = counters[1];
            } else if (counters && typeof counters === 'object') {
                rx = counters.bytes_recv ?? counters.rx;
                tx = counters.bytes_sent ?? counters.tx;
            } else {
                rx = undefined;
                tx = undefined;
            }
        }
        return { rx, tx };
    }

    // All interfaces
    assert.deepEqual(resolveTraffic(sampleData, ''), { rx: 869000000000, tx: 857000000000 });

    // eth0 interface
    assert.deepEqual(resolveTraffic(sampleData, 'eth0'), { rx: 100000000, tx: 200000000 });

    // wg0 interface
    assert.deepEqual(resolveTraffic(sampleData, 'wg0'), { rx: 5000000, tx: 10000000 });

    // Unknown interface
    assert.deepEqual(resolveTraffic(sampleData, 'unknown0'), { rx: undefined, tx: undefined });
});
