/* Meelad Fest service worker — offline-tolerant shell for judges.
 *
 * Strategy:
 *  - Static assets (compiled CSS, vendored JS, fonts, icons): cache-first,
 *      refreshed in the background (stale-while-revalidate).
 *  - Navigations (HTML pages): network-first; fall back to the cache, then
 *      to a themed offline page so a judge in a dead-signal hall still sees
 *      the app instead of the browser's dinosaur.
 *  - Non-GET requests (mark saves etc.) are never touched — the page itself
 *      queues them in localStorage and replays on reconnect.
 */
const VERSION = 'meelad-v7';
const STATIC_CACHE = VERSION + '-static';
const PAGE_CACHE = VERSION + '-pages';

const PRECACHE = [
  '/static/program/css/app.min.css',
  '/static/program/js/alpine.min.js',
  '/static/program/js/qrcode.min.js',
  '/static/program/js/_ajax_forms.js',
  '/static/program/js/_pager.js',
  '/static/fonts/noto-sans-malayalam-400.woff2',
  '/static/images/icons/icon-192.png',
  '/static/images/icons/icon-512.png',
  '/static/images/icons/favicon-32.png',
  '/static/manifest.webmanifest',
  '/offline/',
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(function (cache) { return cache.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k.indexOf(VERSION) !== 0; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  const req = event.request;
  if (req.method !== 'GET') return; // POSTs are the page's job (offline queue)

  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // never touch other hosts

  // Same-origin static assets — stale-while-revalidate. match() ignores the
  // query string so "?v=7" requests hit the precached plain-path asset
  // (cache.addAll stores /static/... without the version query); otherwise a
  // cache miss sends the request to the network alone and a dead/restarting
  // server fails the <script> load, leaving pages without the pager engine.
  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(function (cache) {
        return cache.match(req, { ignoreSearch: true }).then(function (cached) {
          const fresh = fetch(req).then(function (resp) {
            if (resp && resp.status === 200) cache.put(req, resp.clone());
            return resp;
          }).catch(function () { return cached; });
          return cached || fresh;
        });
      })
    );
    return;
  }

  // Navigations — network-first with cached/offline fallbacks.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).then(function (resp) {
        const copy = resp.clone();
        caches.open(PAGE_CACHE).then(function (cache) { cache.put(req, copy); });
        return resp;
      }).catch(function () {
        return caches.match(req).then(function (cached) {
          return cached || caches.match('/offline/');
        });
      })
    );
  }
});
