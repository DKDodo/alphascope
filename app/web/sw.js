// PWA service worker: caches the static app shell (HTML/CSS/JS/icons) so
// the dashboard opens instantly from the home-screen icon, even on a slow
// connection. Deliberately never caches /api/* -- this is a live trading
// dashboard, a stale cached price/signal/portfolio response would be
// actively misleading rather than just inconvenient.
//
// Bump CACHE_NAME whenever a shell asset changes so clients pick up the
// new version instead of serving a stale cached one indefinitely.
const CACHE_NAME = "alphascope-shell-v1";
const SHELL_ASSETS = [
  "/",
  "/style.css",
  "/app.js",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) {
    return; // let the browser handle live data / mutations normally
  }

  // Stale-while-revalidate: serve the cached shell instantly, and update
  // the cache in the background so the *next* load has the latest version.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
