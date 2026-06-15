// Painel institucional: chamados em tempo real, ACK e mudança de estado.
import { apiBase } from "./api";

const lista = document.getElementById("lista")!;
const statusEl = document.getElementById("status")!;
const fTipo = document.getElementById("f-tipo") as HTMLSelectElement;
const fStatus = document.getElementById("f-status") as HTMLSelectElement;

const ESTADOS = ["roteado", "notificado", "reconhecido", "em_atendimento", "encerrado", "escalonado", "cancelado"];
const CANAL_NOME: Record<string, string> = {
  csv: "CSV / PREUNI", sala_lilas: "Sala Lilás", sapsi: "SAPSI", ouvidoria: "Ouvidoria",
  samu_192: "SAMU 192", pm_190: "PM 190", central_180: "Central 180",
};
const TIPO_NOME: Record<string, string> = {
  seguranca: "Segurança", mulher: "Mulher", saude: "Saúde", ouvidoria: "Ouvidoria",
};

let chamados: any[] = [];

function quando(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function gravClasse(g: string) {
  return g === "risco_imediato" ? "imediato" : g === "risco_potencial" ? "potencial" : "orientacao";
}

function render() {
  const t = fTipo.value, s = fStatus.value;
  const arr = chamados.filter((c) => (!t || c.tipo_ocorrencia === t) && (!s || c.status === s));
  if (!arr.length) { lista.innerHTML = `<div class="empty">Nenhum chamado.</div>`; return; }
  lista.innerHTML = arr.map((c) => `
    <div class="card ${gravClasse(c.gravidade)}">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <span class="id">${c.chamado_id}</span>
        <span class="when">${quando(c.created_at)}</span>
      </div>
      <div class="chips">
        <span class="chip rust">${TIPO_NOME[c.tipo_ocorrencia] || c.tipo_ocorrencia}</span>
        <span class="chip">${c.gravidade.replace("_", " ")}</span>
        ${c.modo === "discreto" ? `<span class="chip">discreto</span>` : ""}
        <span class="chip">${c.totem_id}</span>
      </div>
      <div style="font-size:14px;color:var(--muted)">
        Canal: <strong>${CANAL_NOME[c.canal_roteado] || c.canal_roteado}</strong> · estado: ${c.status}
      </div>
      <div class="acts">
        <button class="ack" data-ack="${c.chamado_id}">Reconhecer</button>
        <select data-st="${c.chamado_id}">
          ${ESTADOS.map((e) => `<option value="${e}" ${e === c.status ? "selected" : ""}>${e}</option>`).join("")}
        </select>
      </div>
    </div>
  `).join("");

  lista.querySelectorAll<HTMLButtonElement>("[data-ack]").forEach((b) =>
    b.addEventListener("click", () => ack(b.dataset.ack!)),
  );
  lista.querySelectorAll<HTMLSelectElement>("[data-st]").forEach((sel) =>
    sel.addEventListener("change", () => mudarEstado(sel.dataset.st!, sel.value)),
  );
}

async function carregar() {
  try {
    const r = await fetch(`${apiBase()}/chamados`);
    chamados = await r.json();
    render();
  } catch {
    lista.innerHTML = `<div class="empty">Backend indisponível. Inicie a API (porta 8000).</div>`;
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
  if (i >= 0) chamados[i] = c; else chamados.unshift(c);
  render();
}

function conectarWS() {
  const url = apiBase().replace(/^http/, "ws") + "/ws";
  let ws: WebSocket;
  try { ws = new WebSocket(url); } catch { return; }
  ws.onopen = () => { statusEl.className = "status online"; statusEl.innerHTML = `<span class="dot"></span>Tempo real`; };
  ws.onclose = () => {
    statusEl.className = "status offline";
    statusEl.innerHTML = `<span class="dot"></span>Reconectando...`;
    setTimeout(conectarWS, 3000);
  };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.evento === "novo_chamado" || m.evento === "atualizado") upsert(m.dados);
  };
}

fTipo.addEventListener("change", render);
fStatus.addEventListener("change", render);
carregar();
conectarWS();
setInterval(carregar, 20000);
