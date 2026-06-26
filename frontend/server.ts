// Servidor estático simples (Bun) para o totem e o painel.
// Serve raiz, /public, /dist e /src. Faz fallback para index.html.
const ROOT = import.meta.dir;
const PORT = Number(process.env.POTO_FRONTEND_PORT ?? 5173);

function cacheHeaders(pathname: string): Record<string, string> {
  // Dev/local: nunca cachear shell — evita UI congelada no navegador.
  if (
    pathname.endsWith(".html") ||
    pathname.startsWith("/dist/") ||
    pathname.startsWith("/src/") ||
    pathname === "/sw.js"
  ) {
    return { "Cache-Control": "no-store, must-revalidate" };
  }
  return {};
}

async function resolve(pathname: string): Promise<Response | null> {
  let p = pathname;
  if (p === "/") p = "/index.html";
  if (p === "/painel") p = "/painel.html";
  for (const base of ["/public", "/dist", "", "/src"]) {
    const file = Bun.file(ROOT + base + p);
    if (await file.exists()) {
      return new Response(file, { headers: cacheHeaders(p) });
    }
  }
  return null;
}

Bun.serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const res = await resolve(url.pathname);
    if (res) return res;
    // SPA fallback: navegação desconhecida volta ao totem.
    return new Response(Bun.file(ROOT + "/index.html"), {
      headers: { "content-type": "text/html", ...cacheHeaders("/index.html") },
    });
  },
});

console.log(`P.O.T.O frontend em http://localhost:${PORT}  (totem: /  ·  painel: /painel)`);
