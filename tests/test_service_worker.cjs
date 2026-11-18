const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync('core/static/js/sw.js', 'utf8');
const origin = 'https://panel.example';

function fixture({ network, cached, cacheError = false } = {}) {
    const handlers = new Map();
    const calls = { fetch: 0, cache: 0 };
    vm.runInNewContext(source, {
        self: {
            location: { origin },
            addEventListener: (name, handler) => handlers.set(name, handler),
        },
        URL, Response,
        console: { debug() {} },
        fetch: async (request) => {
            calls.fetch++;
            if (network) return network(request);
            throw new TypeError('Network unavailable');
        },
        caches: {
            open: async (name) => {
                calls.cache++;
                assert.equal(name, 'tgbotvpscp-v1');
                if (cacheError) throw new Error('Cache unavailable');
                return { match: async () => cached };
            },
        },
    });
    return {
        calls,
        fetch(url, method = 'GET') {
            let response;
            handlers.get('fetch')({
                request: { url: new URL(url, origin).href, method },
                respondWith(value) { response = value; },
            });
            return response;
        },
    };
}

test('authenticated pages and API requests bypass the service worker, including operation filters', () => {
    const worker = fixture();
    for (const url of ['/', '/operations', '/operations?node_id=0&status=', '/operations?node_id=3&status=failed',
        '/nodes', '/settings', '/login', '/logout', '/terminal', '/api/operations', '/stream/events']) {
        assert.equal(worker.fetch(url), undefined, url);
    }
    assert.deepEqual(worker.calls, { fetch: 0, cache: 0 });
});

test('external assets and non-GET requests are not intercepted', () => {
    const worker = fixture();
    assert.equal(worker.fetch('https://external.example/static/script.js'), undefined);
    assert.equal(worker.fetch('/static/test.js', 'POST'), undefined);
    assert.deepEqual(worker.calls, { fetch: 0, cache: 0 });
});

test('successful asset and manifest responses pass through without touching the cache', async () => {
    const response = new Response('asset');
    const worker = fixture({ network: () => response });
    for (const url of ['/static/css/main.css?v=123', '/site.webmanifest']) {
        assert.equal(await worker.fetch(url), response);
    }
    assert.deepEqual(worker.calls, { fetch: 2, cache: 0 });
});

test('network failure falls back to an existing public asset response', async () => {
    const cached = new Response('cached styles');
    const worker = fixture({ cached });
    assert.equal(await worker.fetch('/static/css/main.css'), cached);
});

test('network failure with no cache returns a Response instead of undefined', async () => {
    const worker = fixture();
    const response = await worker.fetch('/static/js/missing.js');
    assert.ok(response instanceof Response);
    assert.equal(response.type, 'error');
});

test('unavailable cache also returns a Response instead of rejecting respondWith', async () => {
    const worker = fixture({ cacheError: true });
    const response = await worker.fetch('/static/css/main.css');
    assert.ok(response instanceof Response);
    assert.equal(response.type, 'error');
});

test('HTTP errors remain visible and are not replaced by stale cached assets', async () => {
    const response = new Response('Server error', { status: 503 });
    const worker = fixture({ network: () => response, cached: new Response('old asset') });
    assert.equal(await worker.fetch('/static/test.js'), response);
    assert.equal(worker.calls.cache, 0);
});
