/* Service worker: la página se abre sin conexión con los últimos datos descargados. */
const VERSION = 'v5';
const SHELL = `lluvia-shell-${VERSION}`;
const DATOS = `lluvia-datos-${VERSION}`;
const ES_DATO = u => u.hostname === 'raw.githubusercontent.com' && u.pathname.includes('/lluvia-es-datos/');
const ES_LIBRERIA = u => ['cdnjs.cloudflare.com', 'fonts.googleapis.com', 'fonts.gstatic.com'].includes(u.hostname);

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(['./', 'manifest.json', 'icon-192.png', 'icon-512.png'])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => ![SHELL, DATOS].includes(k)).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function redPrimero(req, cache) {
  const clave = req.url.split('?')[0];
  try {
    const r = await fetch(req);
    if (r.ok) cache.put(clave, r.clone());
    return r;
  } catch (err) {
    const c = await cache.match(clave);
    if (c) return c;
    throw err;
  }
}

async function cachePrimero(req, cache) {
  const c = await cache.match(req, {ignoreSearch: true});
  const red = fetch(req).then(r => { if (r.ok || r.type === 'opaque') cache.put(req, r.clone()); return r; }).catch(() => null);
  return c || (await red) || Response.error();
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const u = new URL(req.url);
  if (ES_DATO(u)) e.respondWith(caches.open(DATOS).then(c => redPrimero(req, c)));
  else if (u.origin === location.origin) e.respondWith(caches.open(SHELL).then(c => redPrimero(req, c)));
  else if (ES_LIBRERIA(u)) e.respondWith(caches.open(SHELL).then(c => cachePrimero(req, c)));
});
