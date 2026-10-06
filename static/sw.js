const CACHE_NAME = 'gravitynas-v2';
const ASSETS = [
    '/static/style.css',
    '/static/app.js',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css'
];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener('fetch', (e) => {
    if (e.request.method !== 'GET') return;
    
    // Stratégie : Cache First pour les assets statiques, Network First pour le reste
    const url = new URL(e.request.url);
    if (url.pathname.startsWith('/static/') || url.hostname.includes('cdnjs')) {
        e.respondWith(
            fetch(e.request).then(response => {
                const copy = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(e.request, copy));
                return response;
            }).catch(() => caches.match(e.request))
        );
    } else {
        e.respondWith(fetch(e.request));
    }
});
