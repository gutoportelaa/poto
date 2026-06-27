// Totem kiosk — fluxos enxutos, ≤ 2 toques na trilha principal.
import {
  enviarEvento, estaOnline, novoEvento, pendentes, sincronizar,
  apiBase, type EventoOut, type Modo, type TipoOcorrencia,
} from "./api";
import { CameraController, enviarEvidencia, publicar, type SessaoRTC } from "./video";
import { ConversaVoz, type EstadoConversa } from "./voice";
import { chatTexto } from "./chat";
import { ligar, type ControleChamada } from "./voicesdk";
import { SYM, sym } from "./icons";
import { initServiceWorker } from "./sw-register";

const TOTEM_ID = localStorage.getItem("poto_totem_id") || "TOTEM-CCS-01";
const app = document.getElementById("app")!;
const statusEl = document.getElementById("status")!;

type Trilha = {
  tipo: TipoOcorrencia;
  icon: string;
  label: string;
  modo: Modo;
  muted?: boolean;
};

const TRILHAS: Trilha[] = [
  { tipo: "saude", icon: SYM.saude, label: "Emergência médica", modo: "normal" },
  { tipo: "seguranca", icon: SYM.seguranca, label: "Segurança", modo: "normal" },
  { tipo: "mulher", icon: SYM.mulher, label: "Assédio / Sala Lilás", modo: "discreto" },
  { tipo: "ouvidoria", icon: SYM.outros, label: "Outros", modo: "normal", muted: true },
];

async function refreshStatus() {
  const online = await estaOnline();
  const pend = pendentes();
  statusEl.className = "status " + (online ? "online" : "offline");
  statusEl.innerHTML = `<span class="dot"></span>${online ? "Online" : "Offline"}`;
  if (pend) statusEl.innerHTML += `<span class="queue"> · ${pend} na fila</span>`;
  if (online && pend) {
    const n = await sincronizar();
    if (n) refreshStatus();
  }
}

function footer(html: string) {
  const el = document.getElementById("footer-actions")!;
  el.hidden = !html;
  el.innerHTML = html;
}

function bindBack(id = "voltar", fn = home) {
  document.getElementById(id)?.addEventListener("click", fn);
}

function home() {
  app.innerHTML = `
    <h1 class="screen-title">Como podemos ajudar?</h1>
    <div class="grid">
      ${TRILHAS.map((t, i) => `
        <button class="choice${t.muted ? " muted" : ""}" type="button" data-i="${i}">
          ${sym(t.icon, "xl")}
          <span class="choice-label">${t.label}</span>
        </button>`).join("")}
    </div>
    <p class="alt-entry"><button type="button" id="conversar">Conversar com o atendimento</button></p>
  `;
  footer(`
    <button class="panic" type="button" id="panic">
      ${sym(SYM.panic, "md")}<span>Pânico</span>
    </button>
  `);
  app.querySelectorAll<HTMLButtonElement>(".choice").forEach((b) =>
    b.addEventListener("click", () => {
      const t = TRILHAS[Number(b.dataset.i)];
      acionar(novoEvento(t.tipo, t.modo, "touch"));
    }),
  );
  document.getElementById("panic")!.addEventListener("click", acionarPanico);
  document.getElementById("conversar")!.addEventListener("click", chat);
}

// Atendimento por chat de texto (multi-turno) — fluxo do LLM via /conversa.
function chat() {
  footer("");
  chatTexto(app, {
    onConcluir: (tipo, modo, texto) =>
      acionar(novoEvento(tipo, modo, "touch", texto || undefined)),
    onVoltar: home,
    onVoz: conversaVoz,
  });
}

const ESTADO_ORB: Record<EstadoConversa, string> = {
  ocioso: "ocioso", ouvindo: "ouvindo", processando: "processando",
  falando: "processando", encerrado: "ocioso", erro: "ocioso",
};

async function conversaVoz() {
  footer("");
  let sttOk = false;
  try {
    const h = await fetch(`${apiBase()}/health`).then((r) => r.json());
    sttOk = !!h?.stt?.disponivel;
  } catch { /* offline */ }

  if (!sttOk) {
    app.innerHTML = `
      <div class="screen-bar">${sym(SYM.back, "sm")}<button class="btn-back" type="button" id="voltar">Voltar</button></div>
      <h1 class="screen-title" style="font-size:28px">Voz indisponível</h1>
      <p class="hint">Use texto ou escolha uma opção na tela inicial.</p>
      <button class="btn-primary" type="button" id="ir-texto" style="width:100%;margin-top:24px">Conversar por texto</button>
    `;
    bindBack();
    document.getElementById("ir-texto")!.addEventListener("click", chat);
    return;
  }

  app.innerHTML = `
    <div class="screen-bar"><button class="btn-back" type="button" id="voltar">${sym(SYM.back, "sm")} Voltar</button></div>
    <div class="voice-stage">
      <div class="orb-wrap" id="orb-wrap" data-estado="ocioso">
        <div class="orb">${sym(SYM.mic, "lg")}<span class="wave"></span></div>
      </div>
      <p class="voice-caption" id="caption">Pode falar…</p>
      <p class="voice-last" id="last"></p>
    </div>
    <button class="btn-primary" type="button" id="parar" style="width:100%">Encerrar</button>
  `;
  bindBack();

  const wrap = document.getElementById("orb-wrap")!;
  const wave = wrap.querySelector(".orb") as HTMLElement;
  const caption = document.getElementById("caption")!;
  const last = document.getElementById("last")!;

  const conversa = new ConversaVoz({
    onEstado: (e, det) => {
      wrap.setAttribute("data-estado", ESTADO_ORB[e]);
      caption.textContent = det || (
        e === "ouvindo" ? "Ouvindo…" :
        e === "falando" ? "Respondendo…" :
        e === "encerrado" ? "Encaminhando…" : "Pode falar…"
      );
    },
    onNivel: (n) => wave.style.setProperty("--nivel", String(0.95 + n * 0.8)),
    onFala: (papel, texto) => {
      last.textContent = (papel === "voce" ? "Você: " : "") + texto;
    },
    onConcluido: (r, transcricao) => {
      const tipo = (r.tipo_sugerido as TipoOcorrencia) || "ouvidoria";
      const modo: Modo = tipo === "mulher" ? "discreto" : "normal";
      acionar(novoEvento(tipo, modo, "touch", transcricao || undefined));
    },
  });

  document.getElementById("parar")!.addEventListener("click", () => { conversa.parar(); home(); });
  conversa.iniciar("normal");
}

async function acionar(ev: ReturnType<typeof novoEvento>) {
  const out = await enviarEvento(ev);
  confirmar(out);
  refreshStatus();
}

// --- Pânico (P1) → tela de alerta ativo (P2/P3), DESIGN.md §13.2 ------------
const STATUS_ALERTA: Record<string, string> = {
  alerta_ativo: "Alerta enviado. Aguardando a central…",
  notificado: "Alerta enviado. Aguardando a central…",
  reconhecido: "A central recebeu seu alerta.",
  em_atendimento: "Atendimento a caminho.",
  escalonado: "Escalonado às autoridades.",
  encerrado: "Atendimento encerrado.",
};

// Assina o /ws e filtra eventos do próprio chamado (acompanhamento ao vivo):
// 'atualizado' (estado do chamado) e 'ligacao' (status do Twilio por canal).
type AssinaturaHandlers = {
  onUpdate?: (c: any) => void;
  onLigacao?: (l: any) => void;
};
function assinarChamado(id: string, handlers: AssinaturaHandlers): () => void {
  const url = apiBase().replace(/^http/, "ws") + "/ws";
  let ws: WebSocket;
  try { ws = new WebSocket(url); } catch { return () => {}; }
  ws.onmessage = (e) => {
    try {
      const m = JSON.parse(e.data);
      if (m.dados?.chamado_id !== id) return;
      if (m.evento === "atualizado") handlers.onUpdate?.(m.dados);
      else if (m.evento === "ligacao") handlers.onLigacao?.(m.dados);
    } catch { /* ignora frames malformados */ }
  };
  return () => { try { ws.close(); } catch { /* já fechado */ } };
}

// Twilio CallStatus -> classe visual da telinha de ligações.
function classeLigacao(status: string): string {
  if (status === "in-progress") return "atendida";
  if (["ringing", "initiated", "queued"].includes(status)) return "tocando";
  if (status === "completed") return "encerrada";
  return "falhou"; // busy | failed | no-answer | canceled
}

async function acionarPanico() {
  footer("");
  app.innerHTML = `
    <div class="alerta-ativo enviando">
      <div class="alerta-pulse">${sym(SYM.panic, "xl")}</div>
      <h1 class="alerta-titulo">Enviando alerta…</h1>
    </div>`;
  const ev = novoEvento("seguranca", "normal", "botao_fisico");
  try {
    const r = await fetch(`${apiBase()}/panico`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        evento_id: ev.evento_id, totem_id: TOTEM_ID,
        modo: "normal", timestamp_local: ev.timestamp_local,
      }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    alertaAtivo(await r.json());
  } catch {
    // Offline / falha: store-and-forward de um evento de segurança e confirma.
    confirmar(await enviarEvento(ev));
  }
  refreshStatus();
}

function alertaAtivo(out: any) {
  footer("");
  const inicio = Date.now();
  const esc = (out.escalonamento_disponivel || []) as { canal: string; nome: string }[];
  app.innerHTML = `
    <div class="alerta-ativo" id="alerta">
      <div class="alerta-pulse">${sym(SYM.panic, "xl")}</div>
      <h1 class="alerta-titulo">Alerta acionado</h1>
      <p class="alerta-status" id="al-status">${STATUS_ALERTA.alerta_ativo}</p>
      <div class="alerta-proto">${out.chamado_id}</div>
      <div class="alerta-cron" id="al-cron">00:00</div>
      <div class="alerta-ligacoes" id="al-ligacoes" hidden></div>
      ${esc.length ? `
      <div class="alerta-escalonar">
        <p class="alerta-escalonar-lab">Acionar autoridades do estado</p>
        <div class="esc-grid">
          ${esc.map((c) => `<button class="esc-btn" type="button" data-esc="${c.canal}" data-nome="${c.nome}">${sym("emergency", "xs")}${c.nome}</button>`).join("")}
        </div>
      </div>` : ""}
      <button class="btn-inicio" type="button" id="al-inicio">Voltar ao início</button>
    </div>`;
  beep();

  const statusLine = document.getElementById("al-status")!;
  const cronEl = document.getElementById("al-cron")!;
  const cron = window.setInterval(() => {
    const s = Math.floor((Date.now() - inicio) / 1000);
    cronEl.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);

  // Status das ligações ao vivo (Twilio statusCallback): um chip por canal.
  const ligEl = document.getElementById("al-ligacoes")!;
  const ligacoes = new Map<string, { nome: string; rotulo: string; status: string }>();
  function renderLigacoes() {
    if (!ligacoes.size) return;
    ligEl.hidden = false;
    ligEl.innerHTML = `<p class="alerta-lig-lab">${sym("call", "xs")}Ligações</p>
      <div class="lig-grid">${[...ligacoes.values()].map((l) =>
        `<span class="lig-chip ${classeLigacao(l.status)}">${l.nome}<b>${l.rotulo}</b></span>`).join("")}</div>`;
  }

  const desassinar = assinarChamado(out.chamado_id, {
    onUpdate: (c) => {
      statusLine.textContent = STATUS_ALERTA[c.status] || statusLine.textContent;
      if (c.status === "reconhecido" || c.status === "em_atendimento") {
        document.getElementById("alerta")?.classList.add("reconhecido");
      }
    },
    onLigacao: (l) => {
      ligacoes.set(l.canal || l.canal_nome, {
        nome: l.canal_nome || l.canal, rotulo: l.rotulo || l.status, status: l.status,
      });
      renderLigacoes();
    },
  });

  const sair = () => { clearInterval(cron); desassinar(); home(); };
  document.getElementById("al-inicio")!.addEventListener("click", sair);

  app.querySelectorAll<HTMLButtonElement>("[data-esc]").forEach((b) =>
    b.addEventListener("click", async () => {
      b.disabled = true;
      const nome = b.dataset.nome || "";
      try {
        const r = await fetch(`${apiBase()}/chamados/${out.chamado_id}/escalonar`, {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ canal: b.dataset.esc }),
        }).then((x) => x.json());
        b.classList.add(r.sucesso ? "done" : "fail");
        b.innerHTML = `${sym(r.sucesso ? "check" : "error", "xs")}${nome}`;
      } catch {
        b.disabled = false;
        b.classList.add("fail");
      }
    }),
  );
}

function confirmar(out: EventoOut) {
  footer("");
  const neutro = out.instrucao_totem.tela_neutra;
  const critico = out.gravidade === "risco_imediato" && !neutro;
  const podeVideo = !neutro && !out._offline && !out.chamado_id.startsWith("LOCAL-");
  const msg = critico ? "Pedido enviado. Ajuda a caminho." : out.instrucao_totem.mensagem_tela;

  app.innerHTML = `
    <div class="confirm ${neutro ? "neutral" : critico ? "critico" : ""}">
      <div class="confirm-icon">${sym(critico || !neutro ? SYM.check : SYM.outros, "md")}</div>
      <h2>${msg}</h2>
      ${neutro ? "" : `<div class="protocolo">${out.chamado_id}</div>`}
      ${out._offline ? `<div class="note-offline">Sem internet — salvo e enviado ao reconectar.</div>` : ""}
      ${podeVideo ? `
      <button class="btn-primary" type="button" id="voz" style="max-width:320px;margin:0 auto">${sym("call", "sm")} Falar com a central</button>
      <button class="btn-ghost" type="button" id="video" style="max-width:320px;margin:8px auto 0">${sym(SYM.video, "sm")} Vídeo</button>` : ""}
    </div>
  `;
  if (out.instrucao_totem.feedback_sonoro) beep();
  const t = setTimeout(home, neutro ? 5_000 : critico ? 12_000 : 9_000);
  document.getElementById("voz")?.addEventListener("click", () => {
    clearTimeout(t);
    chamadaVoz();
  });
  document.getElementById("video")?.addEventListener("click", () => {
    clearTimeout(t);
    videoChamada(out.chamado_id);
  });
}

// Chamada de voz ao vivo com a central (Twilio Voice SDK, navegador↔navegador).
async function chamadaVoz() {
  footer("");
  app.innerHTML = `
    <div class="vozcall" id="vozcall" data-estado="chamando">
      <div class="poto-orb" aria-hidden="true"><img src="/poto-icon.png" alt="" /></div>
      <p class="vozcall-status" id="vz-status">Chamando a central…</p>
      <div class="vozcall-acts">
        <button class="btn-icon" type="button" id="vz-mute" aria-label="Mudo">${sym(SYM.mic, "md")}</button>
        <button class="btn-end" type="button" id="vz-end">Encerrar</button>
      </div>
    </div>`;
  const status = document.getElementById("vz-status")!;
  const wrap = document.getElementById("vozcall")!;
  const muteBtn = document.getElementById("vz-mute")!;
  let mutado = false;
  let saiu = false;
  let ctrl: ControleChamada | null = null;
  const sair = () => {
    if (saiu) return;
    saiu = true;
    ctrl?.encerrar();
    home();
  };
  document.getElementById("vz-end")!.addEventListener("click", sair);
  muteBtn.addEventListener("click", () => {
    if (!ctrl) return;
    mutado = !mutado;
    ctrl.mutar(mutado);
    muteBtn.setAttribute("data-on", String(mutado));
  });
  try {
    ctrl = await ligar(TOTEM_ID, "central", {
      onEstado: (e, det) => {
        wrap.setAttribute("data-estado", e);
        status.textContent =
          e === "chamando" ? "Chamando a central…" :
          e === "em_chamada" ? "Conectado à central" :
          e === "erro" ? "Falha: " + (det || "tente de novo") :
          "Chamada encerrada";
        if (e === "encerrada") setTimeout(sair, 2200);
      },
    });
  } catch {
    status.textContent = "Não foi possível chamar a central.";
    setTimeout(sair, 2500);
  }
}

async function videoChamada(chamadoId: string) {
  footer("");
  const camera = new CameraController();
  let sessao: SessaoRTC | null = null;

  app.innerHTML = `
    <div class="call-layout">
      <video id="local" autoplay muted playsinline></video>
      <p class="call-caption" id="call-status">Conectando…</p>
      <button class="btn-end" type="button" id="encerrar">Encerrar</button>
    </div>
  `;
  const status = document.getElementById("call-status")!;
  const localVideo = document.getElementById("local") as HTMLVideoElement;

  const encerrar = async () => {
    sessao?.encerrar();
    const blob = await camera.pararGravacao();
    camera.parar();
    if (blob) {
      try { await enviarEvidencia(blob, chamadoId, TOTEM_ID); } catch { /* silencioso */ }
    }
    home();
  };
  document.getElementById("encerrar")!.addEventListener("click", encerrar);

  if (!camera.suportada) {
    status.textContent = "Câmera indisponível neste dispositivo.";
    return;
  }
  try {
    const stream = await camera.iniciar(true);
    localVideo.srcObject = stream;
    camera.gravar();
    sessao = await publicar(chamadoId, stream, TOTEM_ID, {
      onEstado: (e) => {
        status.textContent =
          e === "connected" ? "Conectado à central" :
          e === "failed" ? "Falha na conexão" : "Conectando…";
      },
    });
  } catch {
    status.textContent = "Não foi possível acessar a câmera.";
  }
}

function beep() {
  try {
    const ctx = new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 660;
    o.connect(g);
    g.connect(ctx.destination);
    g.gain.setValueAtTime(0.06, ctx.currentTime);
    o.start();
    o.stop(ctx.currentTime + 0.12);
  } catch { /* sem áudio */ }
}

// Heartbeat: o totem (Raspberry Pi) reporta presença e telemetria à central.
// Falha de envio é esperada offline — o painel marca o totem como offline pela
// ausência de batidas recentes.
async function heartbeat(): Promise<void> {
  const hb: Record<string, unknown> = { online: navigator.onLine };
  const conn = (navigator as any).connection;
  const c = conn?.type || conn?.effectiveType;
  if (c) hb.conectividade = c;
  try {
    const getBattery = (navigator as any).getBattery;
    if (getBattery) {
      const bm = await getBattery.call(navigator);
      if (bm && typeof bm.level === "number") hb.bateria = Math.round(bm.level * 100);
    }
  } catch { /* sem API de bateria (Pi sem bateria) — segue sem o campo */ }
  try {
    await fetch(`${apiBase()}/totens/${encodeURIComponent(TOTEM_ID)}/heartbeat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(hb),
    });
  } catch { /* offline: a batida se perde, esperado */ }
}

initServiceWorker();
// Wordmark P.O.T.O no header volta ao início (a qualquer momento do fluxo).
document.getElementById("brand-home")?.addEventListener("click", home);
window.addEventListener("online", refreshStatus);
window.addEventListener("offline", refreshStatus);
setInterval(refreshStatus, 15_000);
setInterval(heartbeat, 15_000);

home();
refreshStatus();
heartbeat();
