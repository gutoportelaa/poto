// Totem (kiosk): triagem por toque, modo discreto e confirmação.
// Funciona online e offline (ver api.ts).
import {
  enviarEvento, estaOnline, novoEvento, pendentes, sincronizar,
  apiBase, type EventoOut, type Modo, type TipoOcorrencia,
} from "./api";
import { GravadorAudio, transcrever, type EstadoAudio } from "./audio";

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
    <div class="minor"><button class="linkbtn" id="describe">Não sei classificar — descrever a situação</button></div>
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
  document.getElementById("describe")!.addEventListener("click", describe);
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
  app.innerHTML = `
    <div class="confirm ${neutro ? "neutral" : ""}">
      <div class="mark">${neutro ? "•" : "✓"}</div>
      <h2>${out.instrucao_totem.mensagem_tela}</h2>
      ${neutro ? "" : `<p>Protocolo <strong>${out.chamado_id}</strong></p>`}
      ${out._offline ? `<div class="note-offline">Sem rede agora — registrado no totem e será enviado automaticamente.</div>` : ""}
      <p class="meta">Esta tela volta ao início em instantes.</p>
    </div>
  `;
  if (out.instrucao_totem.feedback_sonoro) beep();
  setTimeout(home, neutro ? 6000 : 9000);
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
