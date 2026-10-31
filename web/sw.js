const CACHE = "locdiary-v2";
const SHELL = ["./", "app.js", "manifest.webmanifest", "icons/icon-192.png",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"];

self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE && k !== TILES).map(k => caches.delete(k))))));

const TILES = "locdiary-tiles";
async function tile(req) { // ko'rilgan xarita bo'laklari oflayn ham ko'rinsin
  const c = await caches.open(TILES), hit = await c.match(req);
  if (hit) return hit;
  const r = await fetch(req);
  if (r.ok) { c.put(req, r.clone()); c.keys().then(ks => ks.length > 3000 && c.delete(ks[0])); }
  return r;
}

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method === "GET" && url.host === "tile.openstreetmap.org") { e.respondWith(tile(e.request)); return; }
  if (e.request.method !== "GET" || url.pathname.includes("/api/") || url.origin !== location.origin && url.host !== "unpkg.com") return; // API doim tarmoqdan
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && (url.origin === location.origin || url.host === "unpkg.com")) {
      const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy));
    }
    return r;
  }).catch(() => caches.match(e.request)));
});
