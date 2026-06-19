// Totem kiosk — fluxos enxutos, ≤ 2 toques na trilha principal.
import {
  enviarEvento, estaOnline, novoEvento, pendentes, sincronizar,
  apiBase, type EventoOut, type Modo, type TipoOcorrencia,
} from "./api";
import { GravadorAudio, transcrever, type EstadoAudio } from "./audio";
import { CameraController, enviarEvidencia, publicar, type SessaoRTC } from "./video";
import { ConversaVoz, type EstadoConversa } from "./voice";
import { SYM, sym } from "./icons";

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
    <p class="alt-entry"><button type="button" id="describe">Descrever a situação</button></p>
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
  document.getElementById("panic")!.addEventListener("click", () =>
    acionar(novoEvento("seguranca", "normal", "botao_fisico")),
  );
  document.getElementById("describe")!.addEventListener("click", () => describe());
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
      <button class="btn-primary" type="button" id="ir-texto" style="width:100%;margin-top:24px">Descrever por texto</button>
    `;
    bindBack();
    document.getElementById("ir-texto")!.addEventListener("click", describe);
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

function describe() {
  footer("");
  app.innerHTML = `
    <div class="screen-bar"><button class="btn-back" type="button" id="voltar">${sym(SYM.back, "sm")} Voltar</button></div>
    <h1 class="screen-title" style="font-size:28px;margin-bottom:20px">Descreva a situação</h1>
    <div class="compose">
      <textarea id="txt" placeholder="O que está acontecendo?"></textarea>
      <p class="hint" id="hint"></p>
      <div class="compose-actions">
        <button class="btn-icon" type="button" id="mic" data-estado="ocioso" aria-label="Gravar áudio">${sym(SYM.mic, "md")}</button>
        <button class="btn-primary" type="button" id="enviar">Enviar pedido</button>
      </div>
    </div>
    <p class="alt-entry"><button type="button" id="modo-voz">Prefiro conversar só por voz</button></p>
  `;
  bindBack();

  const mic = document.getElementById("mic")!;
  const hint = document.getElementById("hint")!;
  const txt = document.getElementById("txt") as HTMLTextAreaElement;

  const gravador = new GravadorAudio({
    onEstado: (e: EstadoAudio) => {
      mic.setAttribute("data-estado", e === "gravando" ? "gravando" : e === "processando" ? "processando" : "ocioso");
      hint.textContent =
        e === "gravando" ? "Gravando… toque de novo para parar" :
        e === "processando" ? "Transcrevendo…" : "";
    },
    onLog: () => {},
  });

  mic.addEventListener("click", async () => {
    if (gravador.gravando) {
      const blob = await gravador.parar();
      if (!blob) return;
      try {
        const r = await transcrever(blob);
        if (r.disponivel && r.texto) {
          txt.value = r.texto;
          hint.textContent = "Transcrição pronta — revise e envie.";
        } else {
          hint.textContent = "Áudio recebido. Digite o texto acima.";
        }
      } catch {
        hint.textContent = "Falha na transcrição. Digite o texto.";
      }
    } else {
      await gravador.iniciar();
    }
  });

  document.getElementById("enviar")!.addEventListener("click", () => enviarDescricao(txt.value.trim()));
  document.getElementById("modo-voz")!.addEventListener("click", conversaVoz);
}

async function enviarDescricao(texto: string) {
  const hint = document.getElementById("hint");
  if (!texto) {
    if (hint) hint.textContent = "Escreva ou grave antes de enviar.";
    return;
  }
  let tipo: TipoOcorrencia = "ouvidoria";
  let modo: Modo = "normal";
  try {
    const r = await fetch(`${apiBase()}/triagem`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ texto, modo: "normal" }),
    });
    if (r.ok) {
      const t = await r.json();
      tipo = t.tipo_sugerido;
      if (tipo === "mulher") modo = "discreto";
    }
  } catch { /* offline */ }
  acionar(novoEvento(tipo, modo, "touch", texto));
}

async function acionar(ev: ReturnType<typeof novoEvento>) {
  const out = await enviarEvento(ev);
  confirmar(out);
  refreshStatus();
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
      ${podeVideo ? `<button class="btn-primary" type="button" id="video" style="max-width:320px;margin:0 auto">Falar com atendente</button>` : ""}
    </div>
  `;
  if (out.instrucao_totem.feedback_sonoro) beep();
  const t = setTimeout(home, neutro ? 5_000 : critico ? 12_000 : 9_000);
  document.getElementById("video")?.addEventListener("click", () => {
    clearTimeout(t);
    videoChamada(out.chamado_id);
  });
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

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
window.addEventListener("online", refreshStatus);
window.addEventListener("offline", refreshStatus);
setInterval(refreshStatus, 15_000);

home();
refreshStatus();
