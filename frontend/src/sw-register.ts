/** Registra SW só fora de localhost; em dev limpa caches antigos. */
export function initServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;

  const dev = location.hostname === "localhost" || location.hostname === "127.0.0.1";

  if (dev) {
    navigator.serviceWorker.getRegistrations().then((regs) => {
      for (const r of regs) r.unregister();
    });
    if ("caches" in window) {
      caches.keys().then((keys) => {
        for (const k of keys) caches.delete(k);
      });
    }
    return;
  }

  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
