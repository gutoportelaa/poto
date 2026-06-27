// Central NOC — fila densa, auditoria e ações claras.
import { apiBase } from "./api";
import { assistir, type SessaoRTC } from "./video";
import { SYM, sym } from "./icons";

const videoAtivo = new Set<string>();
const lista = document.getElementById("lista")!;
const statusEl = document.getElementById("status")!;
const gfiltersEl = document.getElementById("gfilters")!;
const buscaEl = document.getElementById("busca") as HTMLInputElement;
const drawerEl = document.getElementById("drawer")!;
const totensLista = document.getElementById("totens-lista")!;
const totensResumo = document.getElementById("totens-resumo")!;

const ESTADOS = ["roteado", "notificado", "alerta_ativo", "reconhecido", "em_atendimento", "encerrado", "escalonado", "cancelado"];
const CANAL: Record<string, string> = {
  csv: "CSV / PREUNI", sala_lilas: "Sala Lilás", sapsi: "SAPSI", ouvidoria: "Ouvidoria",
  samu_192: "SAMU", pm_190: "Polícia Militar", bombeiros_193: "Bombeiros", central_180: "Central 180",
};
const TIPO: Record<string, string> = {
  seguranca: "Segurança", mulher: "Atendimento à Mulher", saude: "Saúde", ouvidoria: "Ouvidoria",
};
const STATUS: Record<string, string> = {
  roteado: "Roteado", notificado: "Aguardando", alerta_ativo: "Alerta ativo", reconhecido: "Reconhecido",
  em_atendimento: "Em atendimento", encerrado: "Encerrado", escalonado: "Escalonado",
  cancelado: "Cancelado", falha_notificacao: "Falha no envio",
};
// Autoridades do estado oferecidas para escalonamento manual (DESIGN.md §13.2 / P3).
const CANAIS_ESTADO = ["pm_190", "samu_192", "bombeiros_193", "central_180"];
const GRAV = {
  risco_imediato: { rotulo: "Imediato", badge: "U1 Crítico", classe: "imediato", rank: 0 },
  risco_potencial: { rotulo: "Potencial", badge: "U2 Potencial", classe: "potencial", rank: 1 },
  orientacao: { rotulo: "Orientação", badge: "U3 Info", classe: "orientacao", rank: 2 },
} as const;
type GravKey = keyof typeof GRAV;
const SLA_SEG: Record<string, number> = { risco_imediato: 120, risco_potencial: 600 };

let chamados: any[] = [];
let gravFiltro: GravKey | "" = "";
let busca = "";
// Status das ligações ao vivo (Twilio): chamado_id -> canal -> {nome, rotulo, status}.
const ligacoes = new Map<string, Map<string, { nome: string; rotulo: string; status: string }>>();

// Twilio CallStatus -> classe visual do chip de ligação.
function classeLigacao(status: string): string {
  if (status === "in-progress") return "atendida";
  if (["ringing", "initiated", "queued"].includes(status)) return "tocando";
  if (status === "completed") return "encerrada";
  return "falhou"; // busy | failed | no-answer | canceled
}
function ligacoesCard(id: string): string {
  const m = ligacoes.get(id);
  if (!m || !m.size) return "";
  return `<div class="noc-ligs">${[...m.values()].map((l) =>
    `<span class="noc-lig ${classeLigacao(l.status)}">${sym("call", "xs")}${l.nome} · <b>${l.rotulo}</b></span>`,
  ).join("")}</div>`;
}
let totens: any[] = [];
type View = "painel" | "totens" | "incidentes" | "analises";
let view: View = "painel";
const TOTEM_OFFLINE_SEG = 45; // espelha POTO_TOTEM_OFFLINE_SEG (liveness no cliente)
let incBusca = "";

const PENDENTES = new Set(["roteado", "notificado", "alerta_ativo"]);
const ENCERRADOS = new Set(["encerrado", "cancelado"]);

function gravInfo(g: string) {
  return GRAV[g as GravKey] || GRAV.orientacao;
}
function horario(iso: string): string {
  return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function quando(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function fmtDur(seg: number): string {
  if (seg < 60) return `${seg.toFixed(seg < 10 ? 1 : 0)}s`;
  const m = Math.floor(seg / 60);
  const s = Math.round(seg % 60);
  if (m < 60) return `${m}m${String(s).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h${String(m % 60).padStart(2, "0")}m`;
}
function tituloCard(c: any): string {
  if (c.origem_acionamento === "panico") return "Botão de pânico acionado";
  return TIPO[c.tipo_ocorrencia] || c.tipo_ocorrencia;
}
function contextoCard(c: any): string {
  return c.triagem?.mensagem_acolhimento || c.observacao || `Encaminhado para ${CANAL[c.canal_roteado] || c.canal_roteado}.`;
}
function slaRestante(c: any): string | null {
  if (!PENDENTES.has(c.status) || c.acked_at) return null;
  const sla = SLA_SEG[c.gravidade];
  if (!sla) return null;
  const rest = sla - Math.floor((Date.now() - new Date(c.updated_at || c.created_at).getTime()) / 1000);
  if (rest <= 0) return "SLA expirado";
  return `Responder em ${Math.floor(rest / 60)}:${String(rest % 60).padStart(2, "0")}`;
}

function aplicarBuscaGravidade(): any[] {
  const q = busca.trim().toLowerCase();
  return chamados.filter((c) => {
    if (gravFiltro && c.gravidade !== gravFiltro) return false;
    if (q) {
      const alvo = `${c.chamado_id} ${c.totem_id} ${c.canal_roteado} ${TIPO[c.tipo_ocorrencia] || ""}`.toLowerCase();
      if (!alvo.includes(q)) return false;
    }
    return true;
  });
}

function renderFiltros() {
  const base = chamados.filter((c) => {
    const q = busca.trim().toLowerCase();
    if (!q) return true;
    return `${c.chamado_id} ${c.totem_id} ${c.canal_roteado}`.toLowerCase().includes(q);
  });
  const cont = (g: GravKey) => base.filter((c) => c.gravidade === g).length;
  const pill = (key: GravKey | "", rotulo: string, n: number, cls: string) => `
    <button type="button" class="gpill ${cls}${gravFiltro === key ? " on" : ""}" data-grav="${key}" aria-pressed="${gravFiltro === key}">
      <span class="gdot"></span>${rotulo}${n >= 0 ? ` <span class="gnum">${n}</span>` : ""}
    </button>`;
  gfiltersEl.innerHTML =
    pill("", "Todos", base.length, "todos") +
    pill("risco_imediato", "Imediato", cont("risco_imediato"), "imediato") +
    pill("risco_potencial", "Potencial", cont("risco_potencial"), "potencial") +
    pill("orientacao", "Orientação", cont("orientacao"), "orientacao");
  gfiltersEl.querySelectorAll<HTMLButtonElement>("[data-grav]").forEach((b) =>
    b.addEventListener("click", () => {
      gravFiltro = (b.dataset.grav as GravKey) || "";
      renderFiltros();
      render();
    }),
  );
}

function render() {
  const arr = aplicarBuscaGravidade().sort((a, b) =>
    (gravInfo(a.gravidade).rank - gravInfo(b.gravidade).rank) ||
    (new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
  );

  if (!arr.length) {
    lista.innerHTML = `<div class="empty">Nenhum chamado${busca || gravFiltro ? " com estes filtros" : ""}.</div>`;
    return;
  }

  lista.innerHTML = arr.map((c) => {
    const g = gravInfo(c.gravidade);
    const live = videoAtivo.has(c.chamado_id);
    const ativo = !ENCERRADOS.has(c.status);
    const critico = c.gravidade === "risco_imediato" && ativo;
    const sla = slaRestante(c);
    const pend = PENDENTES.has(c.status);
    const statChip = live
      ? `<span class="noc-stat live">${sym("videocam", "xs")}Câmera ativa</span>`
      : `<span class="noc-stat">${STATUS[c.status] || c.status}</span>`;
    return `
      <article class="noc-card ${g.classe}${critico ? " pulse-crit" : ""}" data-card="${c.chamado_id}">
        <header class="noc-card-top">
          <div>
            <div class="noc-card-tags">
              <span class="ubadge ${g.classe}">${g.badge}</span>
              <span class="noc-id ${g.classe}">${c.chamado_id}</span>
            </div>
            <h3 class="noc-card-title">${tituloCard(c)}</h3>
          </div>
          <span class="noc-time">${sym("schedule", "xs")}${horario(c.created_at)}</span>
        </header>
        <div class="noc-card-body">
          <div class="noc-line">${sym("location_on", "xs")}<span>${c.totem_id}</span></div>
          <div class="noc-line ctx">${sym("forum", "xs")}<p>${contextoCard(c)}</p></div>
          ${sla ? `<div class="noc-sla${sla === "SLA expirado" ? " exp" : ""}">${sla}</div>` : ""}
          ${ligacoesCard(c.chamado_id)}
        </div>
        <footer class="noc-card-foot">
          ${statChip}
          <div class="noc-card-acts">
            ${pend ? `<button class="btn-ack" type="button" data-ack="${c.chamado_id}">${sym("shield_person", "xs")}Reconhecer</button>` : ""}
            <button class="btn-ghost" type="button" data-det="${c.chamado_id}">Detalhes ${sym("chevron_right", "xs")}</button>
          </div>
        </footer>
      </article>`;
  }).join("");

  lista.querySelectorAll<HTMLButtonElement>("[data-ack]").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); ack(b.dataset.ack!); }),
  );
  lista.querySelectorAll<HTMLElement>("[data-det]").forEach((b) =>
    b.addEventListener("click", () => abrirDrawer(b.dataset.det!)),
  );
  lista.querySelectorAll<HTMLElement>("[data-card]").forEach((el) =>
    el.addEventListener("click", () => abrirDrawer(el.dataset.card!)),
  );
}

// ---- Drawer de detalhe / auditoria ----------------------------------------
async function abrirDrawer(id: string) {
  drawerEl.innerHTML = `<div class="dover"><aside class="dpanel"><div class="dload">Carregando auditoria…</div></aside></div>`;
  const over = drawerEl.querySelector(".dover")!;
  over.addEventListener("click", (e) => { if (e.target === over) fecharDrawer(); });
  document.addEventListener("keydown", escFecha);
  try {
    const a = await fetch(`${apiBase()}/chamados/${id}/auditoria`).then((r) => r.json());
    renderDrawer(a);
  } catch {
    drawerEl.querySelector(".dpanel")!.innerHTML = `<div class="dload">Falha ao carregar auditoria.</div>`;
  }
}
function escFecha(e: KeyboardEvent) { if (e.key === "Escape") fecharDrawer(); }
function fecharDrawer() { drawerEl.innerHTML = ""; document.removeEventListener("keydown", escFecha); }

function renderDrawer(a: any) {
  const g = gravInfo(a.gravidade);
  const live = videoAtivo.has(a.chamado_id);
  const linha = (a.linha_do_tempo || []).map((ev: any) => {
    if (ev.tipo === "estado") {
      const rotulo = `${ev.de ? STATUS[ev.de] || ev.de : "início"} → ${STATUS[ev.para] || ev.para}`;
      return `<li class="tl estado${ev.em_curso ? " agora" : ""}">
        <span class="sym sym-xs" aria-hidden="true">history</span>
        <div><div class="tl-main">${rotulo}</div>
        <div class="tl-sub">${ev.em_curso ? "em curso há " : ""}${fmtDur(ev.duracao_segundos)}${ev.em_curso ? "" : " neste estado"}</div></div>
      </li>`;
    }
    const esc = ev.tipo === "escalonamento";
    return `<li class="tl contato">
      <span class="sym sym-xs ${ev.sucesso ? "ok" : "fail"}" aria-hidden="true">${ev.sucesso ? "call_made" : "error"}</span>
      <div><div class="tl-main">${ev.nome} <span class="tl-canal">· ${ev.canal}</span>${esc ? ` <span class="ubadge mini">escalonamento</span>` : ""}</div>
      <div class="tl-sub">${ev.destino} · ${ev.sucesso ? "enviado" : "falhou"}${ev.detalhe ? ` · ${ev.detalhe}` : ""}</div></div>
    </li>`;
  }).join("");

  const podeEscalonar = !ENCERRADOS.has(a.status_atual);
  const escBtns = podeEscalonar ? CANAIS_ESTADO.map((c) =>
    `<button type="button" class="esc-btn" data-esc="${c}">${sym("emergency", "xs")}${CANAL[c]}</button>`,
  ).join("") : "";

  drawerEl.querySelector(".dpanel")!.innerHTML = `
    <header class="dhead ${g.classe}">
      <div class="dhead-top">
        <span class="ubadge ${g.classe}">${g.badge}</span>
        ${a.emergencia ? `<span class="selo-emerg">${sym("priority_high", "xs")}Emergência</span>` : ""}
        <button class="dclose" type="button" aria-label="Fechar">${sym(SYM.close, "sm")}</button>
      </div>
      <div class="dproto">${a.chamado_id}</div>
      <div class="dsub">${tituloCard(a)} · ${a.totem_id}</div>
    </header>
    <div class="dbody">
      <div class="dtempos">
        <div><span class="dt-num">${fmtDur(a.tempo_total_segundos || 0)}</span><span class="dt-lab">em aberto</span></div>
        <div><span class="dt-num">${a.tempo_ate_ack_segundos != null ? fmtDur(a.tempo_ate_ack_segundos) : "—"}</span><span class="dt-lab">até reconhecer</span></div>
        <div><span class="dt-num">${a.total_contatos_acionados}</span><span class="dt-lab">contatos acionados</span></div>
      </div>

      <div class="drow">
        <label class="dlabel">Estado</label>
        <select id="d-estado" aria-label="Alterar estado">
          ${ESTADOS.map((e) => `<option value="${e}" ${e === a.status_atual ? "selected" : ""}>${STATUS[e] || e}</option>`).join("")}
        </select>
        ${live || podeEscalonar ? `<button class="btn-ghost" type="button" id="d-video">${sym("videocam", "xs")}Vídeo</button>` : ""}
      </div>

      ${podeEscalonar ? `
      <div class="desc">
        <div class="dlabel">Escalonar autoridade do estado</div>
        <div class="esc-grid">${escBtns}</div>
      </div>` : ""}

      <div class="dlabel">Linha do tempo (auditoria)</div>
      <ul class="timeline">${linha}</ul>
    </div>`;

  const panel = drawerEl.querySelector(".dpanel")!;
  panel.querySelector(".dclose")!.addEventListener("click", fecharDrawer);
  (panel.querySelector("#d-estado") as HTMLSelectElement)?.addEventListener("change", (e) =>
    mudarEstado(a.chamado_id, (e.target as HTMLSelectElement).value),
  );
  panel.querySelector("#d-video")?.addEventListener("click", () => abrirVideo(a.chamado_id));
  panel.querySelectorAll<HTMLButtonElement>("[data-esc]").forEach((b) =>
    b.addEventListener("click", () => escalonar(a.chamado_id, b.dataset.esc!, b)),
  );
}

// ---- Vídeo ------------------------------------------------------------------
async function abrirVideo(chamadoId: string) {
  let sessao: SessaoRTC | null = null;
  // A central também envia A/V (mic obrigatório, câmera melhor-esforço) — chamada
  // bidirecional. Se não houver mic/câmera, cai para só assistir (mão única).
  let local: MediaStream | undefined;
  try {
    local = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
  } catch {
    try { local = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { local = undefined; }
  }
  const ov = document.createElement("div");
  ov.className = "vmodal";
  ov.innerHTML = `
    <div class="vbox">
      <div class="vhead"><span>${chamadoId}</span>
        <button class="vclose" type="button" aria-label="Fechar">${sym(SYM.close, "sm")}</button></div>
      <video class="vstream" autoplay playsinline></video>
      <video class="vpip" autoplay muted playsinline></video>
      <div class="vstatus">Conectando…</div>
    </div>`;
  document.body.appendChild(ov);
  const vid = ov.querySelector(".vstream") as HTMLVideoElement;
  const pip = ov.querySelector(".vpip") as HTMLVideoElement;
  const st = ov.querySelector(".vstatus") as HTMLElement;
  if (local) pip.srcObject = local; else pip.hidden = true;
  const fechar = () => {
    sessao?.encerrar();
    local?.getTracks().forEach((t) => t.stop());
    ov.remove();
  };
  ov.querySelector(".vclose")!.addEventListener("click", fechar);
  ov.addEventListener("click", (e) => { if (e.target === ov) fechar(); });
  assistir(chamadoId, vid, {
    onStream: () => { st.textContent = "Em chamada."; },
    onEstado: (e) => { st.textContent = e === "connected" ? "Em chamada." : e === "failed" ? "Falha na conexão." : st.textContent; },
  }, local).then((s) => { sessao = s; });
}

// ---- API --------------------------------------------------------------------
async function carregar() {
  try {
    chamados = await fetch(`${apiBase()}/chamados`).then((r) => r.json());
    renderFiltros();
    render();
  } catch {
    lista.innerHTML = `<div class="empty">API indisponível (porta 8000).</div>`;
  }
}
async function ack(id: string) {
  // Atualiza direto da resposta (não depende do WS chegar) — feedback imediato.
  try {
    // Corpo mínimo de propósito: um POST sem corpo atravessa o túnel cloudflared
    // como chunked-vazio e é rejeitado (400) antes de chegar ao backend.
    const r = await fetch(`${apiBase()}/chamados/${id}/ack`, {
      method: "POST", headers: { "content-type": "application/json" }, body: "{}",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    upsert(await r.json());
  } catch {
    statusEl.className = "status offline";
    statusEl.innerHTML = `<span class="dot"></span>Falha ao reconhecer`;
  }
}
async function mudarEstado(id: string, status: string) {
  await fetch(`${apiBase()}/chamados/${id}`, {
    method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ status }),
  });
}
async function escalonar(id: string, canal: string, btn: HTMLButtonElement) {
  btn.disabled = true;
  try {
    const r = await fetch(`${apiBase()}/chamados/${id}/escalonar`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ canal }),
    }).then((x) => x.json());
    btn.classList.add(r.sucesso ? "done" : "fail");
    btn.innerHTML = `${sym(r.sucesso ? "check" : "error", "xs")}${CANAL[canal]}`;
    const a = await fetch(`${apiBase()}/chamados/${id}/auditoria`).then((x) => x.json());
    renderDrawer(a); // reflete o novo contato na linha do tempo
  } catch {
    btn.disabled = false;
    btn.classList.add("fail");
  }
}

function upsert(c: any) {
  const i = chamados.findIndex((x) => x.chamado_id === c.chamado_id);
  if (i >= 0) chamados[i] = c; else chamados.unshift(c);
  renderFiltros();
  render();
  if (view === "incidentes") renderIncidentes();
}

// Batida ao vivo: mescla a telemetria no totem e marca a hora da última batida.
function upsertTotem(hb: any) {
  const i = totens.findIndex((t) => t.totem_id === hb.totem_id);
  const base = i >= 0 ? totens[i] : { totem_id: hb.totem_id, chamados_total: 0, ultimo_chamado: null };
  const novo = {
    ...base,
    online: hb.online !== false,
    bateria: hb.bateria ?? base.bateria ?? null,
    conectividade: hb.conectividade ?? base.conectividade ?? null,
    tamper: !!hb.tamper,
    ultimo_heartbeat: new Date().toISOString(),
  };
  if (i >= 0) totens[i] = novo; else totens.push(novo);
  if (view === "totens") renderTotens();
}

function conectarWS() {
  const url = apiBase().replace(/^http/, "ws") + "/ws";
  let ws: WebSocket;
  try { ws = new WebSocket(url); } catch { return; }
  ws.onopen = () => { statusEl.className = "status online"; statusEl.innerHTML = `<span class="dot"></span>Tempo real`; };
  ws.onclose = () => {
    statusEl.className = "status offline";
    statusEl.innerHTML = `<span class="dot"></span>Reconectando`;
    setTimeout(conectarWS, 3000);
  };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.evento === "novo_chamado" || m.evento === "atualizado") upsert(m.dados);
    else if (m.evento === "video_ativo" && m.dados?.chamado_id) {
      videoAtivo.add(m.dados.chamado_id); render();
      bannerChamadaAoVivo(m.dados.chamado_id, m.dados.totem_id);
    }
    else if (m.evento === "heartbeat" && m.dados?.totem_id) upsertTotem(m.dados);
    else if (m.evento === "ligacao" && m.dados?.chamado_id) {
      const id = m.dados.chamado_id as string;
      if (!ligacoes.has(id)) ligacoes.set(id, new Map());
      ligacoes.get(id)!.set(m.dados.canal || m.dados.canal_nome, {
        nome: m.dados.canal_nome || m.dados.canal,
        rotulo: m.dados.rotulo || m.dados.status,
        status: m.dados.status,
      });
      render();
    }
  };
}

// ---- Frota de totens (status em tempo real da Raspberry) -------------------
function segDesde(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
}
function vistoLabel(t: any): string {
  const s = segDesde(t.ultimo_heartbeat);
  if (s == null) return "sem heartbeat";
  return `visto há ${fmtDur(s)}`;
}
function totemOnline(t: any): boolean {
  // Liveness no cliente: online se houve batida recente (independe do refetch).
  const s = segDesde(t.ultimo_heartbeat);
  return s != null && s <= TOTEM_OFFLINE_SEG;
}
function bateriaIcon(n: number | null): string {
  if (n == null) return "battery_unknown";
  if (n >= 80) return "battery_full";
  if (n >= 50) return "battery_5_bar";
  if (n >= 20) return "battery_3_bar";
  return "battery_1_bar";
}

async function carregarTotens() {
  try {
    totens = await fetch(`${apiBase()}/totens`).then((r) => r.json());
    renderTotens();
  } catch {
    totensLista.innerHTML = `<div class="empty">API indisponível (porta 8000).</div>`;
  }
}

function renderTotens() {
  if (!totens.length) {
    totensLista.innerHTML = `<div class="empty">Nenhum totem registrado ainda.</div>`;
    totensResumo.textContent = "";
    return;
  }
  const online = totens.filter(totemOnline).length;
  const tamper = totens.filter((t) => t.tamper).length;
  totensResumo.innerHTML =
    `<span class="rdot ok"></span>${online} online · ` +
    `<span class="rdot off"></span>${totens.length - online} offline` +
    (tamper ? ` · <span class="rdot crit"></span>${tamper} violação` : "");

  totensLista.innerHTML = totens
    .slice()
    .sort((a, b) => Number(b.tamper) - Number(a.tamper) || Number(totemOnline(a)) - Number(totemOnline(b)) || a.totem_id.localeCompare(b.totem_id))
    .map((t) => {
      const on = totemOnline(t);
      const bat = t.bateria;
      const batLow = bat != null && bat <= 20;
      return `
      <article class="tcard ${on ? "on" : "off"}${t.tamper ? " tamper" : ""}">
        <header class="tcard-top">
          <div>
            <span class="tstatus ${on ? "on" : "off"}"><span class="gdot"></span>${on ? "Online" : "Offline"}</span>
            <h3 class="tcard-id">${t.totem_id}</h3>
          </div>
          <span class="sym sym-md tdev ${on ? "on" : ""}">${on ? "cast_connected" : "cast"}</span>
        </header>
        <div class="tgrid">
          <div class="tmetric${batLow ? " warn" : ""}">${sym(bateriaIcon(bat), "sm")}<span>${bat != null ? bat + "%" : "—"}</span><small>bateria</small></div>
          <div class="tmetric">${sym("wifi", "sm")}<span>${t.conectividade || "—"}</span><small>conexão</small></div>
          <div class="tmetric${t.tamper ? " crit" : ""}">${sym(t.tamper ? "lock_open" : "lock", "sm")}<span>${t.tamper ? "Violado" : "OK"}</span><small>tamper</small></div>
        </div>
        <footer class="tcard-foot">
          <span class="noc-stat">${sym("schedule", "xs")}${vistoLabel(t)}</span>
          <span class="noc-stat">${sym("inbox", "xs")}${t.chamados_total} ${t.chamados_total === 1 ? "chamado" : "chamados"}</span>
        </footer>
      </article>`;
    }).join("");
}

// ---- Incidentes (registro / auditoria) -------------------------------------
const incTabela = document.getElementById("inc-tabela")!;
const incBuscaEl = document.getElementById("inc-busca") as HTMLInputElement;
const incGravEl = document.getElementById("inc-grav") as HTMLSelectElement;
const incStatusEl = document.getElementById("inc-status") as HTMLSelectElement;

function incFiltrados(): any[] {
  const q = incBusca.trim().toLowerCase();
  const fg = incGravEl.value;
  const fs = incStatusEl.value;
  return chamados.filter((c) => {
    if (fg && c.gravidade !== fg) return false;
    if (fs === "abertos") { if (ENCERRADOS.has(c.status)) return false; }
    else if (fs && c.status !== fs) return false;
    if (q && !`${c.chamado_id} ${c.totem_id} ${c.canal_roteado} ${TIPO[c.tipo_ocorrencia] || ""}`.toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
}

function renderIncidentes() {
  const arr = incFiltrados();
  if (!arr.length) { incTabela.innerHTML = `<div class="empty">Nenhum incidente com estes filtros.</div>`; return; }
  const linhas = arr.map((c) => {
    const g = gravInfo(c.gravidade);
    return `<tr data-det="${c.chamado_id}">
      <td><span class="ubadge ${g.classe}">${g.badge}</span></td>
      <td class="mono">${c.chamado_id}${c.emergencia ? ` <span class="sym sym-xs emerg" title="Emergência">priority_high</span>` : ""}</td>
      <td>${tituloCard(c)}</td>
      <td>${c.totem_id}</td>
      <td><span class="st-dot ${ENCERRADOS.has(c.status) ? "off" : "on"}"></span>${STATUS[c.status] || c.status}</td>
      <td class="mono">${quando(c.created_at)}</td>
      <td><button class="btn-ghost mini" type="button">Auditoria ${sym("chevron_right", "xs")}</button></td>
    </tr>`;
  }).join("");
  incTabela.innerHTML = `<table class="inc-table"><thead><tr>
      <th>Triagem</th><th>Protocolo</th><th>Ocorrência</th><th>Totem</th><th>Estado</th><th>Aberto em</th><th></th>
    </tr></thead><tbody>${linhas}</tbody></table>
    <div class="inc-rodape">${arr.length} de ${chamados.length} chamados</div>`;
  incTabela.querySelectorAll<HTMLElement>("[data-det]").forEach((tr) =>
    tr.addEventListener("click", () => abrirDrawer(tr.dataset.det!)),
  );
}

function exportarCSV() {
  const arr = incFiltrados();
  const cols = ["chamado_id", "gravidade", "tipo_ocorrencia", "totem_id", "canal_roteado", "status", "origem_acionamento", "created_at", "acked_at"];
  const esc = (v: any) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [cols.join(","), ...arr.map((c) => cols.map((k) => esc(c[k])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = `poto-incidentes-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

// ---- Análises (métricas) ---------------------------------------------------
const anCorpo = document.getElementById("an-corpo")!;
const anResumo = document.getElementById("an-resumo")!;

function barras(dados: { rotulo: string; n: number; cls?: string }[]): string {
  const max = Math.max(1, ...dados.map((d) => d.n));
  return `<div class="bars">${dados.map((d) => `
    <div class="bar-row"><span class="bar-lab">${d.rotulo}</span>
      <span class="bar-track"><span class="bar-fill ${d.cls || ""}" style="width:${Math.round(100 * d.n / max)}%"></span></span>
      <span class="bar-num">${d.n}</span></div>`).join("")}</div>`;
}

async function carregarAnalises() {
  anCorpo.innerHTML = `<div class="empty">Carregando métricas…</div>`;
  let m: any;
  try { m = await fetch(`${apiBase()}/metricas`).then((r) => r.json()); }
  catch { anCorpo.innerHTML = `<div class="empty">API indisponível.</div>`; return; }

  anResumo.textContent = `${m.total} chamados · ${m.abertos} em aberto`;
  const ack = m.tempo_medio_ack_segundos != null ? fmtDur(m.tempo_medio_ack_segundos) : "—";
  const sla = m.sla_cumprido_pct != null ? `${m.sla_cumprido_pct}%` : "—";
  const kpi = (num: string, lab: string, cls = "") => `<div class="kpi ${cls}"><span class="kpi-num">${num}</span><span class="kpi-lab">${lab}</span></div>`;

  const grav = [
    { rotulo: "Imediato", n: m.por_gravidade.risco_imediato || 0, cls: "imediato" },
    { rotulo: "Potencial", n: m.por_gravidade.risco_potencial || 0, cls: "potencial" },
    { rotulo: "Orientação", n: m.por_gravidade.orientacao || 0, cls: "orientacao" },
  ];
  const tipos = Object.entries(m.por_tipo || {}).map(([k, n]) => ({ rotulo: TIPO[k] || k, n: n as number }));
  const dias = (m.volume_por_dia || []).map((d: any) => ({ rotulo: d.dia.slice(5), n: d.total }));
  const totens = (m.top_totens || []).map((t: any) => ({ rotulo: t.totem_id, n: t.total }));

  anCorpo.innerHTML = `
    <div class="kpis">
      ${kpi(m.total, "Total de chamados")}
      ${kpi(String(m.emergencias), "Emergências", "imediato")}
      ${kpi(ack, "Tempo médio até ACK")}
      ${kpi(sla, "SLA cumprido")}
      ${kpi(`${m.taxa_escalonamento_pct}%`, "Taxa de escalonamento")}
      ${kpi(String(m.contatos_acionados), "Contatos acionados")}
    </div>
    <div class="an-grid">
      <section class="an-card"><h3>Por gravidade</h3>${barras(grav)}</section>
      <section class="an-card"><h3>Por tipo de ocorrência</h3>${barras(tipos)}</section>
      <section class="an-card"><h3>Volume por dia (7d)</h3>${barras(dias)}</section>
      <section class="an-card"><h3>Totens mais acionados</h3>${barras(totens)}</section>
    </div>`;
}

// ---- Troca de view ---------------------------------------------------------
function trocarView(alvo: View) {
  view = alvo;
  for (const v of ["painel", "totens", "incidentes", "analises"] as View[]) {
    document.getElementById(`view-${v}`)!.toggleAttribute("hidden", v !== alvo);
  }
  document.querySelectorAll<HTMLAnchorElement>("[data-view]").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === alvo),
  );
  if (alvo === "totens") carregarTotens();
  else if (alvo === "incidentes") renderIncidentes();
  else if (alvo === "analises") carregarAnalises();
}

buscaEl.addEventListener("input", () => { busca = buscaEl.value; renderFiltros(); render(); });
incBuscaEl.addEventListener("input", () => { incBusca = incBuscaEl.value; renderIncidentes(); });
incGravEl.addEventListener("change", renderIncidentes);
incStatusEl.addEventListener("change", renderIncidentes);
document.getElementById("inc-export")!.addEventListener("click", exportarCSV);
document.querySelectorAll<HTMLAnchorElement>("[data-view]").forEach((a) =>
  a.addEventListener("click", (e) => { e.preventDefault(); trocarView(a.dataset.view as View); }),
);
// Wordmark P.O.T.O (sidebar e topo) volta à view inicial do painel.
for (const id of ["logo-home", "brand-home"]) {
  document.getElementById(id)?.addEventListener("click", () => trocarView("painel"));
}
document.querySelectorAll<HTMLAnchorElement>("[data-soon]").forEach((a) =>
  a.addEventListener("click", (e) => e.preventDefault()),
);
carregar();
conectarWS();

// ---- Chamada A/V ao vivo: a central recebe a chamada do totem (WebRTC nativo) --
// O totem publica na sala (=chamado_id) e o backend emite "video_ativo"; mostramos
// um banner de chamada recebida → Atender abre o vídeo bidirecional.
const chamadasAtivas = new Set<string>();
function bannerChamadaAoVivo(chamadoId: string, totemId?: string) {
  if (chamadasAtivas.has(chamadoId)) return; // já há banner/atendimento p/ este chamado
  chamadasAtivas.add(chamadoId);
  const el = document.createElement("div");
  el.className = "voz-incoming";
  el.innerHTML = `
    <div class="voz-card chamando">
      <span class="sym sym-md" aria-hidden="true">call</span>
      <div class="voz-info"><strong>Chamada do totem</strong><span>${totemId || chamadoId}</span></div>
      <div class="voz-acts">
        <button class="btn-ack voz-aceitar" type="button">${sym("call", "xs")}Atender</button>
        <button class="btn-ghost voz-rejeitar" type="button">Recusar</button>
      </div>
    </div>`;
  document.body.appendChild(el);
  const fechar = () => { el.remove(); chamadasAtivas.delete(chamadoId); };
  el.querySelector(".voz-rejeitar")!.addEventListener("click", fechar);
  el.querySelector(".voz-aceitar")!.addEventListener("click", () => {
    el.remove(); // o overlay de vídeo assume; mantém o chamado em chamadasAtivas
    abrirVideo(chamadoId).catch(() => {});
    chamadasAtivas.delete(chamadoId);
  });
}

setInterval(carregar, 20_000);
setInterval(() => { render(); if (view === "totens") renderTotens(); }, 1000); // SLA + liveness dos totens
