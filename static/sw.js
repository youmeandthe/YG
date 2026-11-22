const CACHE = 'stardew-hub-v2';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll([
    '/', '/manifest.webmanifest', '/icon.svg',
  ])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.delete('stardew-hub-v1').then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin ||
      url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).catch(async error => {
    const cache = await caches.open(CACHE);
    const offline = await cache.match(event.request, { ignoreSearch: url.pathname === '/' });
    if (offline) return offline;
    throw error;
  }));
});
