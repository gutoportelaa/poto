// Servidor do totem e do painel (Bun).
// - Serve as páginas e assets (raiz, /public, /dist, /src) com fallback ao totem.
// - Faz reverse-proxy de /api/* (HTTP e WebSocket) para o backend FastAPI.
//   Assim UMA origem (ex.: um túnel cloudflared) serve páginas + API + WS,
//   que é o que api.ts assume quando não está na porta 5173 local.
const ROOT = import.meta.dir;
const PORT = Number(process.env.POTO_FRONTEND_PORT ?? 5173);
const BACKEND = Number(process.env.POTO_BACKEND_PORT ?? 8000);
const BACKEND_HOST = process.env.POTO_BACKEND_HOST ?? "127.0.0.1";

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

// Encaminha uma requisição HTTP /api/* para o backend, preservando método,
// cabeçalhos, corpo e querystring.
async function proxyHttp(req: Request, url: URL): Promise<Response> {
  const target = `http://${BACKEND_HOST}:${BACKEND}${url.pathname}${url.search}`;
  const headers = new Headers(req.headers);
  headers.delete("host");
  const init: RequestInit = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }
  try {
    return await fetch(target, init);
  } catch (e) {
    return new Response(`proxy backend indisponível: ${e}`, { status: 502 });
  }
}

interface WsData {
  path: string;
  up?: WebSocket;
  fila: (string | ArrayBufferView | ArrayBufferLike)[]; // mensagens antes do upstream abrir
}

Bun.serve<WsData>({
  port: PORT,
  async fetch(req, server) {
    const url = new URL(req.url);

    if (url.pathname.startsWith("/api/")) {
      // Upgrade de WebSocket → vira proxy WS (open() conecta no backend).
      if ((req.headers.get("upgrade") ?? "").toLowerCase() === "websocket") {
        const ok = server.upgrade(req, {
          data: { path: url.pathname + url.search, fila: [] } as WsData,
        });
        return ok ? undefined : new Response("upgrade falhou", { status: 400 });
      }
      return proxyHttp(req, url);
    }

    const res = await resolve(url.pathname);
    if (res) return res;
    // SPA fallback: navegação desconhecida volta ao totem.
    return new Response(Bun.file(ROOT + "/index.html"), {
      headers: { "content-type": "text/html", ...cacheHeaders("/index.html") },
    });
  },
  websocket: {
    open(ws) {
      const alvo = `ws://${BACKEND_HOST}:${BACKEND}${ws.data.path}`;
      const up = new WebSocket(alvo);
      ws.data.up = up;
      up.binaryType = "arraybuffer";
      up.onopen = () => {
        for (const m of ws.data.fila) up.send(m);
        ws.data.fila = [];
      };
      up.onmessage = (e) => ws.send(e.data);
      up.onclose = () => { try { ws.close(); } catch {} };
      up.onerror = () => { try { ws.close(); } catch {} };
    },
    message(ws, msg) {
      const up = ws.data.up;
      if (up && up.readyState === WebSocket.OPEN) up.send(msg);
      else ws.data.fila.push(msg); // ainda conectando → enfileira
    },
    close(ws) {
      try { ws.data.up?.close(); } catch {}
    },
  },
});

console.log(
  `P.O.T.O frontend em http://localhost:${PORT}  (totem: /  ·  painel: /painel)\n` +
    `  proxy /api/* → http://${BACKEND_HOST}:${BACKEND} (HTTP + WebSocket)`,
);
