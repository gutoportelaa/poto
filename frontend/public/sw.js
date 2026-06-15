// Service worker do P.O.T.O — habilita a ABORDAGEM OFFLINE.
// Estratégia: cache-first para o app shell (funciona sem rede);
// nunca cacheia chamadas /api (o envio offline é tratado pela fila local em api.ts).
const CACHE = "poto-shell-v1";
const SHELL = [
  "/",
  "/index.html",
  "/painel.html",
  "/src/styles.css",
  "/dist/totem.js",
  "/dist/painel.js",
  "/poto-logo-3.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.includes("/api/")) return; // API sempre via rede (fila cuida do offline)

  e.respondWith(
    caches.match(e.request).then((hit) => {
      if (hit) return hit;
      return fetch(e.request)
        .then((res) => {
          if (res.ok && e.request.method === "GET") {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return res;
        })
        .catch(() => {
          if (e.request.mode === "navigate") return caches.match("/index.html");
          return new Response("", { status: 504 });
        });
    })
  );
});
