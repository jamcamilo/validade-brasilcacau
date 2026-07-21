const CACHE = 'validade-v1';
const SHELL = ['/static/style.css', '/static/app.js', '/static/manifest.json'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
