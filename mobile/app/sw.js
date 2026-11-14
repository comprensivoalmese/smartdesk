/* SmartDesk mobile: tiene in memoria l'app (non i dati) per aprirla subito e renderla installabile. */
const VERSIONE = 'smartdesk-1';
const FILE = ['./', 'index.html', 'app.js', 'config.js', 'finto.js', 'style.css', 'mobile.css', 'icona.svg', 'manifest.webmanifest'];
self.addEventListener('install', e => { e.waitUntil(caches.open(VERSIONE).then(c => c.addAll(FILE)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== VERSIONE).map(x => caches.delete(x)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return; // Argo e Apps Script sempre dalla rete
  // prima la rete (così gli aggiornamenti arrivano subito), poi la copia salvata
  e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(VERSIONE).then(x => x.put(e.request, c)); return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match('index.html'))));
});
