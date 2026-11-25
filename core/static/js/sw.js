/**
 * Service Worker for PWA and Web Push notifications.
 * Handles background push events, offline asset caching, and notification clicks.
 */

const CACHE_NAME = 'tgbotvpscp-v1';
const PRECACHE_ASSETS = [
    '/site.webmanifest',
    '/static/css/main.css',
    '/static/css/style.css',
    '/static/css/icons.css',
    '/static/favicons/favicon-32x32.png',
    '/static/favicons/android-chrome-192x192.png'
];

// --- INSTALL & ACTIVATE ---
self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_ASSETS).catch((err) => {
                // Non-critical if some icons aren't generated yet
                console.debug('[SW] Precache notice:', err);
            });
        })
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => {
            return self.clients.claim();
        })
    );
});

// --- FETCH (Network first for public assets only) ---
self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);

    // Authenticated pages (including /operations) and APIs belong to the network.
    // Never serve a cached personal page after a session change or network failure.
    if (
        url.origin !== self.location.origin ||
        (url.pathname !== '/site.webmanifest' && !url.pathname.startsWith('/static/'))
    ) {
        return;
    }

    event.respondWith(
        fetch(request).catch(async () => {
            try {
                const cache = await caches.open(CACHE_NAME);
                const cached = await cache.match(request);
                if (cached) return cached;
            } catch (err) {
                console.debug('[SW] Cache unavailable:', err);
            }
            // Cache misses resolve to undefined, which is invalid for respondWith().
            return Response.error();
        })
    );
});

// --- PUSH NOTIFICATIONS ---
self.addEventListener('push', (event) => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch {
            payload = {
                title: 'VPS Control Panel',
                body: event.data.text()
            };
        }
    }

    const title = payload.title || 'VPS Control Panel';
    const options = {
        body: payload.body || 'New notification',
        icon: payload.icon || '/static/favicons/android-chrome-192x192.png',
        badge: payload.badge || '/static/favicons/favicon-32x32.png',
        tag: payload.tag || ('vps-alert-' + Date.now()),
        data: payload.data || { url: '/' },
        vibrate: [200, 100, 200],
        renotify: true
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// --- NOTIFICATION CLICK ---
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    const targetUrl = (event.notification.data && event.notification.data.url)
        ? event.notification.data.url
        : '/';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
            // Check if there is already a window open
            for (const client of windowClients) {
                if ('focus' in client) {
                    if (targetUrl !== '/' && 'navigate' in client) {
                        client.navigate(targetUrl);
                    }
                    return client.focus();
                }
            }
            // If no active window is found, open a new one
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }
        })
    );
});
