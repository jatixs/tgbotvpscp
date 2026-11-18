const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync('core/static/js/chart_range.js', 'utf8');

function fixture() {
    const saved = new Map();
    const context = {
        window: { addEventListener() {} },
        document: { addEventListener() {}, removeEventListener() {}, hidden: false },
        localStorage: {
            getItem: key => saved.get(key) ?? null,
            setItem: (key, value) => saved.set(key, value),
            removeItem: key => saved.delete(key),
        },
        URLSearchParams, clearTimeout, setTimeout, console,
        EventSource: class {
            constructor(url) { this.url = url; }
            addEventListener() {}
            close() {}
        },
    };
    vm.runInNewContext(source, context);
    function make(id, opts = {}) {
        return context.window.createChartRangeController({
            key: id ? 'nodeNetChart' : 'agentChart', network: true,
            getSource: () => id ? { source: 'node', node_id: id } : { source: 'agent' },
            ...opts,
        });
    }
    return { context, saved, make };
}

test('restores independent agent and node choices, including first stream request', () => {
    const { make } = fixture();
    for (const [id, name] of [[null, 'docker0'], [1, 'eth0'], [2, 'ens3']]) {
        const original = make(id);
        original.setInterface(name);
        original.destroy();
    }
    for (const [id, name] of [[null, 'docker0'], [1, 'eth0'], [2, 'ens3']]) {
        const restored = make(id).start();
        assert.equal(restored.getInterface(), name);
        const params = new URL(restored.stream.url, 'https://example.test').searchParams;
        assert.equal(params.get('interface'), name);
        assert.equal(params.get('node_id'), id ? String(id) : null);
        restored.destroy();
    }
});

test('reset removes persisted choice and notifies only on change', () => {
    const { make, saved } = fixture();
    const changes = [];
    const ctl = make(1, { onInterfaceChange: value => changes.push(value) });
    ctl.setInterface('eth0');
    ctl.setInterface('eth0');
    ctl.setInterface('');
    assert.deepEqual(changes, ['eth0', '']);
    assert.equal(make(1).getInterface(), '');
    assert.equal(saved.has('chartInterface:nodeNetChart_node_1'), false);
});

test('explicit initial interface wins and invalid values normalize consistently', () => {
    const { make } = fixture();
    make(1).setInterface('eth0');
    assert.equal(make(1, { initialInterface: 'wg0' }).getInterface(), 'wg0');
    for (const value of [null, 123, {}, '']) {
        const ctl = make(1, { initialInterface: value });
        assert.equal(ctl.getInterface(), '');
        ctl.setInterface(value);
        assert.equal(ctl.getInterface(), '');
    }
});

test('disabled localStorage does not break selection or streaming', () => {
    const { context, make } = fixture();
    for (const operation of ['getItem', 'setItem', 'removeItem']) {
        context.localStorage[operation] = () => { throw Error('storage disabled'); };
    }
    const ctl = make(1);
    assert.equal(ctl.getInterface(), '');
    ctl.setInterface('eth0').start();
    assert.equal(new URL(ctl.stream.url, 'https://example.test').searchParams.get('interface'), 'eth0');
    ctl.setInterface('');
    ctl.destroy();
});
