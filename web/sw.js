// The phone keeps a copy of Jarvis's page. Opened while Jarvis is restarting (or the PC is waking up), the phone shows
// that copy instead of a blank screen, and the page reloads itself as soon as Jarvis answers again.
const SHELL = 'jarvis-page';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;  // only the page itself; Jarvis's live data always goes to Jarvis
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(SHELL).then(c => c.put('/', copy)); return r; }
    return r.status >= 500 ? caches.match('/').then(c => c || r) : r;  // Tailscale says Jarvis is down: the copy
  }).catch(() => caches.match('/').then(c => c || Response.error())));
});
