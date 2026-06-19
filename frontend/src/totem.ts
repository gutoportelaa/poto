// Totem (kiosk): triagem por toque, modo discreto e confirmação.
// Funciona online e offline (ver api.ts).
import {
  enviarEvento, estaOnline, novoEvento, pendentes, sincronizar,
  apiBase, type EventoOut, type Modo, type TipoOcorrencia,
} from "./api";
import { GravadorAudio, transcrever, type EstadoAudio } from "./audio";
import { CameraController, enviarEvidencia, publicar, type SessaoRTC } from "./video";
import { ConversaVoz, type EstadoConversa } from "./voice";

const TOTEM_ID = localStorage.getItem("poto_totem_id") || "TOTEM-CCS-01";

const app = document.getElementById("app")!;
const statusEl = document.getElementById("status")!;

const TRILHAS: { tipo: TipoOcorrencia; ic: string; t: string; d: string; modo: Modo }[] = [
  { tipo: "seguranca", ic: "🛡️", t: "Segurança", d: "Ameaça, roubo, agressão no campus", modo: "normal" },
  { tipo: "mulher", ic: "💜", t: "Atendimento à Mulher", d: "Assédio ou violência — sigiloso", modo: "discreto" },
  { tipo: "saude", ic: "➕", t: "Saúde", d: "Mal-estar, apoio psicológico", modo: "normal" },
  { tipo: "ouvidoria", ic: "📣", t: "Ouvidoria", d: "Reclamação, denúncia, orientação", modo: "normal" },
];

async function refreshStatus() {
  const online = await estaOnline();
  const pend = pendentes();
  statusEl.className = "status " + (online ? "online" : "offline");
  statusEl.innerHTML =
    `<span class="dot"></span>${online ? "Online" : "Offline"}` +
    (pend ? ` · ${pend} na fila` : "");
  if (online && pend) {
    const n = await sincronizar();
    if (n) refreshStatus();
  }
}

function home() {
  app.innerHTML = `
    <h1>Como podemos ajudar?</h1>
    <p class="sub">Toque na opção que melhor descreve a situação.</p>
    <div class="grid">
      ${TRILHAS.map((x, i) => `
        <button class="choice" data-i="${i}">
          <span class="ic">${x.ic}</span>
          <span class="t">${x.t}</span>
          <span class="d">${x.d}</span>
        </button>`).join("")}
    </div>
    <button class="panic" id="panic"><span class="ic">⚠️</span> EMERGÊNCIA — acionar segurança</button>
    <button class="btn voz-cta" id="voz">🎙️ Falar com o atendimento (voz)</button>
    <div class="minor"><button class="linkbtn" id="describe">Prefiro escrever a situação</button></div>
  `;
  app.querySelectorAll<HTMLButtonElement>(".choice").forEach((b) =>
    b.addEventListener("click", () => {
      const x = TRILHAS[Number(b.dataset.i)];
      acionar(novoEvento(x.tipo, x.modo, "touch"));
    }),
  );
  document.getElementById("panic")!.addEventListener("click", () =>
    acionar(novoEvento("seguranca", "normal", "botao_fisico")),
  );
  document.getElementById("voz")!.addEventListener("click", conversaVoz);
  document.getElementById("describe")!.addEventListener("click", describe);
}

// Mapeia o estado da conversa para o visual do orbe (reutiliza o CSS do microfone).
const ESTADO_ORB: Record<EstadoConversa, string> = {
  ocioso: "ocioso", ouvindo: "gravando", processando: "processando",
  falando: "falando", encerrado: "concluido", erro: "erro",
};

async function conversaVoz() {
  // A conversa por voz depende de STT (Whisper). Avisa se estiver indisponível.
  let sttOk = false;
  try {
    const h = await fetch(`${apiBase()}/health`).then((r) => r.json());
    sttOk = !!h?.stt?.disponivel;
  } catch { /* trata como indisponível */ }

  if (!sttOk) {
    app.innerHTML = `
      <h1>Atendimento por voz</h1>
      <p class="sub">O reconhecimento de fala (STT) não está ativo neste servidor.</p>
      <div class="row">
        <button class="btn" id="ir-descrever">Escrever a situação</button>
        <button class="btn ghost" id="voltar">Voltar</button>
      </div>
      <p class="note-offline" style="margin-top:16px">Para habilitar a voz: <code>make stt-setup</code> e <code>POTO_STT_PROVIDER=faster-whisper</code>.</p>
    `;
    document.getElementById("ir-descrever")!.addEventListener("click", describe);
    document.getElementById("voltar")!.addEventListener("click", home);
    return;
  }

  app.innerHTML = `
    <h1>Atendimento por voz</h1>
    <p class="sub">Fale naturalmente. Eu ouço, respondo e encaminho.</p>
    <div class="mic-zone">
      <div class="mic" id="orb" data-estado="ocioso"><span class="orb"><span class="wave"></span><span class="ic">🎙️</span></span></div>
      <div class="mic-status" id="cstatus">Iniciando…</div>
    </div>
    <ul class="dialog" id="dialog" aria-live="polite"></ul>
    <div class="row" style="justify-content:center"><button class="btn ghost" id="parar">Encerrar</button></div>
  `;
  const orb = document.getElementById("orb")!;
  const orbEl = orb.querySelector(".orb") as HTMLElement;
  const cstatus = document.getElementById("cstatus")!;
  const dialog = document.getElementById("dialog")!;

  const conversa = new ConversaVoz({
    onEstado: (e, det) => {
      orb.setAttribute("data-estado", ESTADO_ORB[e]);
      cstatus.textContent = det || (
        e === "ouvindo" ? "Pode falar…" :
        e === "falando" ? "…" :
        e === "encerrado" ? "Encaminhando seu pedido…" : ""
      );
    },
    onNivel: (n) => orbEl.style.setProperty("--nivel", String(0.9 + n * 0.9)),
    onFala: (papel, texto) => {
      const li = document.createElement("li");
      li.className = "fala " + papel;
      li.textContent = (papel === "voce" ? "Você: " : "P.O.T.O: ") + texto;
      dialog.appendChild(li);
      dialog.scrollTop = dialog.scrollHeight;
    },
    onLog: (m) => console.log("[voz]", m),
    onConcluido: (r, transcricao) => {
      const tipo = (r.tipo_sugerido as TipoOcorrencia) || "ouvidoria";
      const modo: Modo = tipo === "mulher" ? "discreto" : "normal";
      acionar(novoEvento(tipo, modo, "touch", transcricao || undefined));
    },
  });

  document.getElementById("parar")!.addEventListener("click", () => { conversa.parar(); home(); });
  conversa.iniciar("normal");
}

const ESTADO_TEXTO: Record<EstadoAudio, string> = {
  ocioso: "Toque no microfone para falar",
  solicitando: "Liberando o microfone…",
  gravando: "Ouvindo você…",
  processando: "Transcrevendo…",
  concluido: "Áudio concluído",
  erro: "Não foi possível captar o áudio",
};

function describe() {
  app.innerHTML = `
    <h1>Descreva a situação</h1>
    <p class="sub">Fale ou escreva. A triagem é feita por IA com supervisão humana.</p>
    <div class="describe">
      <div class="mic-zone">
        <button class="mic" id="mic" aria-label="Gravar áudio" data-estado="ocioso">
          <span class="orb"><span class="wave"></span><span class="ic">🎙️</span></span>
        </button>
        <div class="mic-status" id="mic-status">${ESTADO_TEXTO.ocioso}</div>
      </div>
      <textarea id="txt" placeholder="Ex.: estou sendo seguida por um homem perto do bloco 7..."></textarea>
      <ul class="logs" id="logs" aria-live="polite"></ul>
      <div class="row">
        <button class="btn" id="enviar">Pedir ajuda</button>
        <button class="btn ghost" id="voltar">Voltar</button>
      </div>
    </div>
  `;
  document.getElementById("voltar")!.addEventListener("click", home);

  // ---- Áudio ----
  const mic = document.getElementById("mic")!;
  const orb = mic.querySelector(".orb") as HTMLElement;
  const micStatus = document.getElementById("mic-status")!;
  const logs = document.getElementById("logs")!;
  const txtEl = document.getElementById("txt") as HTMLTextAreaElement;

  const log = (m: string) => {
    const li = document.createElement("li");
    const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    li.innerHTML = `<span class="t">${hora}</span> ${m}`;
    logs.prepend(li);
    while (logs.childElementCount > 6) logs.lastElementChild!.remove();
  };
  const setEstado = (e: EstadoAudio, detalhe?: string) => {
    mic.setAttribute("data-estado", e);
    micStatus.textContent = detalhe || ESTADO_TEXTO[e];
  };

  const gravador = new GravadorAudio({
    onEstado: setEstado,
    onNivel: (n) => orb.style.setProperty("--nivel", String(0.9 + n * 0.9)),
    onLog: log,
  });

  mic.addEventListener("click", async () => {
    if (gravador.gravando) {
      const blob = await gravador.parar();
      if (!blob) return setEstado("ocioso");
      try {
        const r = await transcrever(blob);
        if (r.disponivel && r.texto) {
          txtEl.value = r.texto;
          setEstado("concluido", "Áudio concluído");
          log("Transcrição concluída.");
        } else {
          setEstado("concluido", "Áudio recebido — transcrição indisponível");
          log(r.detalhe || "Transcrição automática indisponível. Escreva no campo abaixo.");
        }
      } catch (err: any) {
        setEstado("erro", "Erro na recepção do áudio");
        log("Falha ao transcrever: " + (err?.message || err));
      }
    } else {
      await gravador.iniciar();
    }
  });

  document.getElementById("enviar")!.addEventListener("click", async () => {
    const txt = txtEl.value.trim();
    if (!txt) { log("Escreva ou grave a situação antes de enviar."); return; }
    let tipo: TipoOcorrencia = "ouvidoria";
    let modo: Modo = "normal";
    try {
      // Triagem por agentes (online). Define tipo/modo antes do acionamento.
      const r = await fetch(`${apiBase()}/triagem`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ texto: txt, modo: "normal" }),
      });
      if (r.ok) {
        const t = await r.json();
        tipo = t.tipo_sugerido;
        if (tipo === "mulher") modo = "discreto";
      }
    } catch { /* offline: segue com ouvidoria + texto na fila */ }
    acionar(novoEvento(tipo, modo, "touch", txt));
  });
}

async function acionar(ev: ReturnType<typeof novoEvento>) {
  const out = await enviarEvento(ev);
  confirmar(out);
  refreshStatus();
}

function confirmar(out: EventoOut) {
  const neutro = out.instrucao_totem.tela_neutra;
  // Vídeo só fora do modo discreto, online e com chamado válido (não offline).
  const podeVideo = !neutro && !out._offline && !out.chamado_id.startsWith("LOCAL-");
  app.innerHTML = `
    <div class="confirm ${neutro ? "neutral" : ""}">
      <div class="mark">${neutro ? "•" : "✓"}</div>
      <h2>${out.instrucao_totem.mensagem_tela}</h2>
      ${neutro ? "" : `<p>Protocolo <strong>${out.chamado_id}</strong></p>`}
      ${out._offline ? `<div class="note-offline">Sem rede agora — registrado no totem e será enviado automaticamente.</div>` : ""}
      ${podeVideo ? `<div class="row" style="justify-content:center"><button class="btn" id="abrir-video">📹 Abrir vídeo com a central</button></div>` : ""}
      <p class="meta">Esta tela volta ao início em instantes.</p>
    </div>
  `;
  if (out.instrucao_totem.feedback_sonoro) beep();
  const voltar = setTimeout(home, neutro ? 6000 : 12000);
  if (podeVideo) {
    document.getElementById("abrir-video")!.addEventListener("click", () => {
      clearTimeout(voltar);
      videoChamada(out.chamado_id);
    });
  }
}

// Tela de chamada de vídeo: publica a câmera na central e grava evidência local.
async function videoChamada(chamadoId: string) {
  const camera = new CameraController();
  let sessao: SessaoRTC | null = null;
  app.innerHTML = `
    <div class="callscreen">
      <h1>Vídeo com a central</h1>
      <video id="local" autoplay muted playsinline></video>
      <div class="call-status" id="call-status">Conectando…</div>
      <ul class="logs" id="vlogs" aria-live="polite"></ul>
      <div class="row" style="justify-content:center">
        <button class="btn" id="encerrar">Encerrar chamada</button>
      </div>
    </div>
  `;
  const statusEl2 = document.getElementById("call-status")!;
  const vlogs = document.getElementById("vlogs")!;
  const localVideo = document.getElementById("local") as HTMLVideoElement;
  const vlog = (m: string) => {
    const li = document.createElement("li");
    const h = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    li.innerHTML = `<span class="t">${h}</span> ${m}`;
    vlogs.prepend(li);
    while (vlogs.childElementCount > 6) vlogs.lastElementChild!.remove();
  };

  const encerrar = async () => {
    sessao?.encerrar();
    vlog("Encerrando e salvando evidência…");
    const blob = await camera.pararGravacao();
    camera.parar();
    if (blob) {
      try { const m = await enviarEvidencia(blob, chamadoId, TOTEM_ID); vlog(`Evidência registrada (${Math.max(1, m.bytes / 1024 | 0)} KB).`); }
      catch (e: any) { vlog("Falha ao enviar evidência: " + (e?.message || e)); }
    }
    setTimeout(home, 1200);
  };
  document.getElementById("encerrar")!.addEventListener("click", encerrar);

  if (!camera.suportada) {
    statusEl2.textContent = "Câmera indisponível neste dispositivo.";
    vlog("getUserMedia indisponível (use HTTPS ou localhost).");
    return;
  }
  try {
    vlog("Solicitando câmera e microfone…");
    const stream = await camera.iniciar(true);
    localVideo.srcObject = stream;
    camera.gravar();
    vlog("Gravando evidência localmente.");
    sessao = await publicar(chamadoId, stream, TOTEM_ID, {
      onEstado: (e) => {
        statusEl2.textContent =
          e === "connected" ? "Conectado à central" :
          e === "connecting" ? "Conectando…" :
          e === "failed" ? "Falha na conexão (evidência segue gravando)" : e;
        vlog("Estado da conexão: " + e);
      },
    });
    vlog("Transmitindo para a central…");
  } catch (e: any) {
    statusEl2.textContent = "Não foi possível acessar a câmera.";
    vlog("Erro: " + (e?.message || e));
  }
}

function beep() {
  try {
    const ctx = new AudioContext();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 660; o.connect(g); g.connect(ctx.destination);
    g.gain.setValueAtTime(0.08, ctx.currentTime);
    o.start(); o.stop(ctx.currentTime + 0.15);
  } catch { /* sem áudio */ }
}

// PWA + status
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
window.addEventListener("online", refreshStatus);
window.addEventListener("offline", refreshStatus);
setInterval(refreshStatus, 15000);

home();
refreshStatus();
