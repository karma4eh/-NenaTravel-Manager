// Service Worker para Viajes Nena PWA
const CACHE_NAME = 'viajes-nena-v1';
const ASSETS_TO_CACHE = [
  '/static/core/chart.min.js',
  '/static/core/manifest.json',
  '/static/core/icon-192.png',
  '/static/core/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Solo interceptamos GET para estaticos; las peticiones dinamicas de Django van directas a la red
  if (event.request.method === 'GET' && event.request.url.includes('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cachedResponse) => {
        return cachedResponse || fetch(event.request);
      })
    );
  }
});
