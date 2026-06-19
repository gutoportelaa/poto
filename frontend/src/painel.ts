// Central — fila limpa, ações claras.
import { apiBase } from "./api";
import { assistir, type SessaoRTC } from "./video";
import { SYM, sym } from "./icons";

const videoAtivo = new Set<string>();
const lista = document.getElementById("lista")!;
const statusEl = document.getElementById("status")!;
const fTipo = document.getElementById("f-tipo") as HTMLSelectElement;
const fStatus = document.getElementById("f-status") as HTMLSelectElement;

const ESTADOS = ["roteado", "notificado", "reconhecido", "em_atendimento", "encerrado", "escalonado", "cancelado"];
const CANAL: Record<string, string> = {
  csv: "CSV", sala_lilas: "Sala Lilás", sapsi: "SAPSI", ouvidoria: "Ouvidoria",
  samu_192: "SAMU", pm_190: "PM", central_180: "180",
};
const TIPO: Record<string, string> = {
  seguranca: "Segurança", mulher: "Mulher", saude: "Saúde", ouvidoria: "Ouvidoria",
};
const STATUS: Record<string, string> = {
  roteado: "Roteado", notificado: "Aguardando", reconhecido: "Reconhecido",
  em_atendimento: "Em atendimento", encerrado: "Encerrado", escalonado: "Escalonado",
  cancelado: "Cancelado", falha_notificacao: "Falha envio",
};
const SLA_SEG: Record<string, number> = { risco_imediato: 120, risco_potencial: 600 };

let chamados: any[] = [];

function quando(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function gravClasse(g: string) {
  return g === "risco_imediato" ? "imediato" : g === "risco_potencial" ? "potencial" : "orientacao";
}

function slaRestante(c: any): string | null {
  if (c.status !== "notificado" || c.acked_at) return null;
  const sla = SLA_SEG[c.gravidade];
  if (!sla) return null;
  const ref = new Date(c.updated_at || c.created_at).getTime();
  const rest = sla - Math.floor((Date.now() - ref) / 1000);
  if (rest <= 0) return "SLA expirado";
  const m = Math.floor(rest / 60);
  const s = rest % 60;
  return `Responder em ${m}:${String(s).padStart(2, "0")}`;
}

function render() {
  const t = fTipo.value;
  const s = fStatus.value;
  const arr = chamados.filter((c) => {
    if (t && c.tipo_ocorrencia !== t) return false;
    if (!s) return c.status !== "encerrado" && c.status !== "cancelado";
    return c.status === s;
  });

  if (!arr.length) {
    lista.innerHTML = `<div class="empty">Nenhum chamado${s || t ? " com estes filtros" : " ativo"}.</div>`;
    return;
  }

  lista.innerHTML = arr.map((c) => {
    const sla = slaRestante(c);
    const urgente = sla === "SLA expirado";
    const live = videoAtivo.has(c.chamado_id);
    const meta = [
      TIPO[c.tipo_ocorrencia] || c.tipo_ocorrencia,
      CANAL[c.canal_roteado] || c.canal_roteado,
      STATUS[c.status] || c.status,
      c.modo === "discreto" ? "discreto" : null,
    ].filter(Boolean).join(" · ");

    return `
      <article class="card ${gravClasse(c.gravidade)}${urgente ? " sla-urgente" : ""}">
        <div class="card-head">
          <span class="card-id">${c.chamado_id}</span>
          <span class="card-meta">${meta}${live ? ` · <span class="badge live">vídeo</span>` : ""}</span>
        </div>
        <time class="card-when">${quando(c.created_at)}</time>
        ${sla ? `<div class="card-sla">${sla}</div>` : ""}
        <div class="card-actions">
          ${c.status === "notificado" || c.status === "roteado" ? `
            <button class="btn-ack" type="button" data-ack="${c.chamado_id}">Reconhecer</button>` : ""}
          ${live || c.status !== "encerrado" ? `
            <button class="btn-ghost" type="button" data-video="${c.chamado_id}">
              ${sym(SYM.video, "sm")}${live ? "Ver vídeo" : "Vídeo"}
            </button>` : ""}
          <select data-st="${c.chamado_id}" aria-label="Estado">
            ${ESTADOS.map((e) => `<option value="${e}" ${e === c.status ? "selected" : ""}>${STATUS[e] || e}</option>`).join("")}
          </select>
        </div>
      </article>`;
  }).join("");

  lista.querySelectorAll<HTMLButtonElement>("[data-ack]").forEach((b) =>
    b.addEventListener("click", () => ack(b.dataset.ack!)),
  );
  lista.querySelectorAll<HTMLSelectElement>("[data-st]").forEach((sel) =>
    sel.addEventListener("change", () => mudarEstado(sel.dataset.st!, sel.value)),
  );
  lista.querySelectorAll<HTMLButtonElement>("[data-video]").forEach((b) =>
    b.addEventListener("click", () => abrirVideo(b.dataset.video!)),
  );
}

function abrirVideo(chamadoId: string) {
  let sessao: SessaoRTC | null = null;
  const ov = document.createElement("div");
  ov.className = "vmodal";
  ov.innerHTML = `
    <div class="vbox">
      <div class="vhead">
        <span>${chamadoId}</span>
        <button class="vclose" type="button" aria-label="Fechar">${sym(SYM.close, "sm")}</button>
      </div>
      <video class="vstream" autoplay playsinline></video>
      <div class="vstatus">Aguardando totem…</div>
    </div>`;
  document.body.appendChild(ov);
  const vid = ov.querySelector(".vstream") as HTMLVideoElement;
  const st = ov.querySelector(".vstatus") as HTMLElement;
  const fechar = () => { sessao?.encerrar(); ov.remove(); };
  ov.querySelector(".vclose")!.addEventListener("click", fechar);
  ov.addEventListener("click", (e) => { if (e.target === ov) fechar(); });

  assistir(chamadoId, vid, {
    onStream: () => { st.textContent = "Recebendo vídeo."; },
    onEstado: (e) => {
      if (e === "connected") st.textContent = "Conectado.";
      else if (e === "failed") st.textContent = "Falha na conexão.";
    },
  }).then((s) => { sessao = s; });
}

async function carregar() {
  try {
    chamados = await fetch(`${apiBase()}/chamados`).then((r) => r.json());
    render();
  } catch {
    lista.innerHTML = `<div class="empty">API indisponível (porta 8000).</div>`;
  }
}

async function ack(id: string) {
  await fetch(`${apiBase()}/chamados/${id}/ack`, { method: "POST" });
}

async function mudarEstado(id: string, status: string) {
  await fetch(`${apiBase()}/chamados/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status }),
  });
}

function upsert(c: any) {
  const i = chamados.findIndex((x) => x.chamado_id === c.chamado_id);
  if (i >= 0) chamados[i] = c;
  else chamados.unshift(c);
  render();
}

function conectarWS() {
  const url = apiBase().replace(/^http/, "ws") + "/ws";
  let ws: WebSocket;
  try { ws = new WebSocket(url); } catch { return; }
  ws.onopen = () => {
    statusEl.className = "status online";
    statusEl.innerHTML = `<span class="dot"></span>Tempo real`;
  };
  ws.onclose = () => {
    statusEl.className = "status offline";
    statusEl.innerHTML = `<span class="dot"></span>Reconectando`;
    setTimeout(conectarWS, 3000);
  };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.evento === "novo_chamado" || m.evento === "atualizado") upsert(m.dados);
    else if (m.evento === "video_ativo" && m.dados?.chamado_id) {
      videoAtivo.add(m.dados.chamado_id);
      render();
    }
  };
}

fTipo.addEventListener("change", render);
fStatus.addEventListener("change", render);
carregar();
conectarWS();
setInterval(carregar, 20_000);
setInterval(render, 1000);
