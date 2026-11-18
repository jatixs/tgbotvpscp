const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync('core/static/js/operations.js', 'utf8');

function fixture({ empty = false } = {}) {
    const connections = [];
    const docEvents = new Map();
    const windowEvents = new Map();
    const fields = {
        '[data-operation-status]': { textContent: 'Queued' },
        '[data-operation-updated]': { textContent: 'old' },
        '[data-operation-output]': { textContent: 'first sample' },
        '[data-operation-result]': { hidden: false, open: true },
    };
    const card = { dataset: { operationId: '8' }, querySelector: name => fields[name] };
    const indicator = { hidden: true, dataset: { connecting: 'connecting', live: 'live', reconnecting: 'retry', expired: 'expired' } };
    const list = {
        dataset: { statusStyles: JSON.stringify({ queued: 'gray', finished: 'green', failed: 'red' }) },
        querySelectorAll: () => empty ? [] : [card],
    };
    class EventSource {
        constructor(url) { this.url = url; this.events = new Map(); this.closed = false; connections.push(this); }
        addEventListener(name, listener) { this.events.set(name, listener); }
        close() { this.closed = true; }
        emit(name, data) { this.events.get(name)?.({ data: typeof data === 'string' ? data : JSON.stringify(data) }); }
    }
    const document = { hidden: false, readyState: 'complete', querySelector: () => ({ querySelectorAll: () => [] }),
        getElementById: id => id === 'operationsList' ? list : indicator,
        addEventListener: (name, callback) => docEvents.set(name, callback) };
    const window = { EventSource, addEventListener: (name, callback) => windowEvents.set(name, callback) };
    vm.runInNewContext(source, {
        window, document, AbortController, decryptData: value => value, decryptApiResponse: value => value.d ? JSON.parse(value.d) : value,
    });
    return { connections, fields, indicator, document, docEvents, windowEvents, window };
}

const update = { id: 8, status: 'finished', status_label: 'Response received', updated_at: 'now', result: 'second sample' };

test('one connection updates the existing card and keeps expanded results open', () => {
    const f = fixture();
    assert.equal(f.connections.length, 1);
    assert.equal(f.connections[0].url, '/api/operations/stream?ids=8');
    f.connections[0].emit('operations', [update]);
    f.connections[0].emit('operations', [{ ...update, result: 'third sample' }]);
    assert.equal(f.connections.length, 1);
    assert.equal(f.fields['[data-operation-output]'].textContent, 'third sample');
    assert.equal(f.fields['[data-operation-result]'].open, true);
    assert.equal(f.fields['[data-operation-status]'].textContent, 'Response received');
    assert.match(f.fields['[data-operation-status]'].className, /green/);
    assert.equal(f.fields['[data-operation-updated]'].textContent, 'now');
});

test('server output is inserted as text and a first result becomes visible', () => {
    const f = fixture();
    f.fields['[data-operation-result]'].hidden = true;
    const output = '<img src=x onerror=alert(1)>';
    f.connections[0].emit('operations', [{ ...update, result: output }]);
    assert.equal(f.fields['[data-operation-output]'].textContent, output);
    assert.equal(f.fields['[data-operation-output]'].innerHTML, undefined);
    assert.equal(f.fields['[data-operation-result]'].hidden, false);
});

test('malformed events and updates for other cards are ignored', () => {
    const f = fixture();
    for (const data of ['not JSON', '{}', [null], [{ ...update, id: 9 }], [{ ...update, status: '__proto__' }]]) {
        f.connections[0].emit('operations', data);
    }
    assert.equal(f.fields['[data-operation-output]'].textContent, 'first sample');
});

test('hidden pages release the stream and restore only one connection when shown', () => {
    const f = fixture();
    f.document.hidden = true;
    f.docEvents.get('visibilitychange')();
    assert.equal(f.connections[0].closed, true);
    f.document.hidden = false;
    f.docEvents.get('visibilitychange')();
    f.windowEvents.get('pageshow')();
    assert.equal(f.connections.length, 2);
    f.connections[0].emit('operations', [update]);
    assert.equal(f.fields['[data-operation-output]'].textContent, 'first sample');
    f.windowEvents.get('pagehide')();
    assert.equal(f.connections[1].closed, true);
});

test('network errors preserve the last result while EventSource reconnects', () => {
    const f = fixture();
    f.connections[0].emit('error');
    assert.equal(f.indicator.textContent, 'retry');
    assert.equal(f.fields['[data-operation-output]'].textContent, 'first sample');
    assert.equal(f.connections.length, 1);
    f.connections[0].emit('open');
    assert.equal(f.indicator.textContent, 'live');
});

test('expired permissions close the connection and prevent background reconnects', () => {
    const f = fixture();
    f.connections[0].emit('session_expired', {});
    assert.equal(f.connections[0].closed, true);
    f.windowEvents.get('pageshow')();
    assert.equal(f.connections.length, 1);
    assert.equal(f.indicator.textContent, 'expired');
});

test('empty history does not open a stream', () => {
    const f = fixture({ empty: true });
    assert.equal(f.connections.length, 0);
    assert.equal(f.indicator.hidden, true);
});

test('encrypted envelopes are decoded and SPA teardown closes the stream', () => {
    const f = fixture();
    f.connections[0].emit('operations', { d: JSON.stringify([update]) });
    assert.equal(f.fields['[data-operation-output]'].textContent, 'second sample');
    f.window.destroyOperations();
    assert.equal(f.connections[0].closed, true);
});
