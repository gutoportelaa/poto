// Atendimento por chat de texto (multi-turno) — integra o fluxo com o LLM via
// POST /conversa. O backend decide a próxima fala de acolhimento e quando há
// informação suficiente para encaminhar (conclui de imediato em sinal crítico).
//
// Visual: identidade P.O.T.O (DESIGN.md) sobre um layout de assistente de chat.
// O poto-icon.png faz as vezes do "orbe": herói das boas-vindas + avatar do bot.
import { apiBase, type Modo, type TipoOcorrencia } from "./api";
import { SYM, sym } from "./icons";

const ICON = "/poto-icon.png";
const MAX_TURNOS = 4; // trava de segurança no cliente (espelha voice.ts)
const INATIVIDADE_MS = 10 * 60 * 1000; // 10 min sem atividade -> reinicia a conversa
const TOTEM_ID = localStorage.getItem("poto_totem_id") || "TOTEM-CCS-01";

// Registra o abandono da conversa (desistência manual ou inatividade). Usa
// sendBeacon para sobreviver à navegação; o backend só guarda motivo + turnos.
function logAbandono(motivo: "desistencia" | "inatividade", turnos: number): void {
  const corpo = JSON.stringify({ totem_id: TOTEM_ID, motivo, turnos });
  const url = `${apiBase()}/conversa/abandono`;
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([corpo], { type: "application/json" }));
      return;
    }
  } catch {
    /* cai no fetch abaixo */
  }
  void fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: corpo,
    keepalive: true,
  }).catch(() => {});
}

type Papel = "usuario" | "assistente";
interface Turn {
  papel: Papel;
  texto: string;
}

export interface ChatOpts {
  modo?: Modo;
  onConcluir: (tipo: TipoOcorrencia, modo: Modo, texto: string) => void;
  onVoltar: () => void;
  onVoz?: () => void;
}

const SUGESTOES = [
  "Estou passando mal e preciso de ajuda",
  "Tem alguém me seguindo, estou com medo",
  "Quero falar com a Sala Lilás",
  "Preciso de uma orientação",
];

export function chatTexto(app: HTMLElement, opts: ChatOpts): void {
  const modoBase: Modo = opts.modo ?? "normal";
  const historico: Turn[] = [];
  let enviando = false;
  let encerrado = false;
  let turnos = 0;

  app.innerHTML = `
    <section class="chat">
      <div class="chat-bar">
        <button class="btn-back" type="button" id="chat-voltar">${sym(SYM.back, "sm")} <span id="chat-voltar-rot">Voltar</span></button>
        ${opts.onVoz ? `<button class="chat-voz" type="button" id="chat-voz">${sym(SYM.mic, "xs")}<span>Conversar por voz</span></button>` : ""}
      </div>
      <div class="chat-scroll" id="chat-scroll">
        <div class="chat-welcome" id="chat-welcome">
          <div class="poto-orb" aria-hidden="true"><img src="${ICON}" alt="" /></div>
          <h1 class="chat-greeting">Como posso ajudar você?</h1>
          <p class="chat-sub">Conte com as suas palavras o que está acontecendo. Se for uma emergência, eu aciono ajuda na hora. <strong>Após 10 minutos sem atividade, a conversa reinicia automaticamente.</strong></p>
          <div class="chat-cards" id="chat-cards">
            ${SUGESTOES.map(
              (s) => `<button class="chat-card" type="button" data-s="${encodeURIComponent(s)}">${s}</button>`,
            ).join("")}
          </div>
        </div>
        <div class="chat-msgs" id="chat-msgs" aria-live="polite"></div>
      </div>
      <div class="chat-composer">
        <div class="chat-box">
          <textarea id="chat-ta" class="chat-ta" rows="1" placeholder="Escreva aqui…"></textarea>
          <div class="chat-box-foot">
            <span class="chat-id">P<span>.</span>O<span>.</span>T<span>.</span>O · atendimento</span>
            <button class="chat-send" type="button" id="chat-send" aria-label="Enviar" disabled>${sym(SYM.send, "sm")}</button>
          </div>
        </div>
      </div>
    </section>`;

  const scroll = app.querySelector<HTMLElement>("#chat-scroll")!;
  const welcome = app.querySelector<HTMLElement>("#chat-welcome")!;
  const msgs = app.querySelector<HTMLElement>("#chat-msgs")!;
  const ta = app.querySelector<HTMLTextAreaElement>("#chat-ta")!;
  const send = app.querySelector<HTMLButtonElement>("#chat-send")!;
  const voltarRot = app.querySelector<HTMLElement>("#chat-voltar-rot")!;

  // --- Inatividade: 10 min sem atividade reinicia a conversa (volta à home) ---
  let idle = 0;
  function tocaIdle() {
    clearTimeout(idle);
    if (encerrado) return;
    idle = window.setTimeout(() => {
      if (encerrado) return;
      encerrado = true;
      if (turnos > 0) logAbandono("inatividade", turnos);
      opts.onVoltar();
    }, INATIVIDADE_MS);
  }
  function paraIdle() {
    clearTimeout(idle);
  }

  // Sair da conversa em andamento = desistir (logado). Antes de começar, é só voltar.
  function desistir() {
    paraIdle();
    if (turnos > 0 && !encerrado) logAbandono("desistencia", turnos);
    encerrado = true;
    opts.onVoltar();
  }

  app.querySelector("#chat-voltar")!.addEventListener("click", desistir);
  app.querySelector("#chat-voz")?.addEventListener("click", () => {
    paraIdle();
    opts.onVoz?.();
  });
  app.querySelectorAll<HTMLButtonElement>(".chat-card").forEach((b) =>
    b.addEventListener("click", () => {
      ta.value = decodeURIComponent(b.dataset.s || "");
      autoGrow();
      void enviar();
    }),
  );

  function scrollDown() {
    scroll.scrollTop = scroll.scrollHeight;
  }

  function autoGrow() {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
    send.disabled = enviando || encerrado || !ta.value.trim();
  }
  ta.addEventListener("input", () => {
    autoGrow();
    tocaIdle();
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void enviar();
    }
  });
  send.addEventListener("click", () => void enviar());

  // Bolha de mensagem. O texto vai por textContent (nunca innerHTML) — entrada
  // do usuário é dado, não marcação.
  function bolha(papel: Papel, texto: string): void {
    const row = document.createElement("div");
    row.className = "chat-msg " + (papel === "usuario" ? "is-user" : "is-bot");
    if (papel === "assistente") {
      const av = document.createElement("span");
      av.className = "chat-avatar";
      av.setAttribute("aria-hidden", "true");
      av.innerHTML = `<img src="${ICON}" alt="" />`;
      row.appendChild(av);
    }
    const b = document.createElement("div");
    b.className = "chat-bubble";
    b.textContent = texto;
    row.appendChild(b);
    msgs.appendChild(row);
    scrollDown();
  }

  function typing(): HTMLElement {
    const row = document.createElement("div");
    row.className = "chat-msg is-bot";
    row.innerHTML =
      `<span class="chat-avatar" aria-hidden="true"><img src="${ICON}" alt="" /></span>` +
      `<div class="chat-bubble"><span class="chat-typing"><i></i><i></i><i></i></span></div>`;
    msgs.appendChild(row);
    scrollDown();
    return row;
  }

  function finalizar(resp: { tipo_sugerido?: string }): void {
    encerrado = true;
    paraIdle();
    ta.disabled = true;
    send.disabled = true;
    const tipo = (resp.tipo_sugerido as TipoOcorrencia) || "ouvidoria";
    const modo: Modo = tipo === "mulher" ? "discreto" : modoBase;
    const texto = historico
      .filter((h) => h.papel === "usuario")
      .map((h) => h.texto)
      .join(". ");
    // Pequena pausa para a pessoa ler a fala final antes de ir à confirmação.
    setTimeout(() => opts.onConcluir(tipo, modo, texto), 950);
  }

  async function enviar(): Promise<void> {
    const texto = ta.value.trim();
    if (!texto || enviando || encerrado) return;
    welcome.hidden = true;
    enviando = true;
    send.disabled = true;
    ta.value = "";
    autoGrow();

    historico.push({ papel: "usuario", texto });
    turnos++;
    if (turnos === 1) voltarRot.textContent = "Desistir"; // conversa em andamento
    bolha("usuario", texto);
    tocaIdle();

    const t = typing();
    let resp: { fala?: string; concluido?: boolean; tipo_sugerido?: string };
    try {
      const r = await fetch(`${apiBase()}/conversa`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ historico, modo: modoBase }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      resp = await r.json();
    } catch {
      // Sem conexão: registra o pedido (store-and-forward via onConcluir) e
      // encerra com honestidade — nada de travar quem pede ajuda.
      t.remove();
      bolha(
        "assistente",
        "Estou sem conexão agora, mas registrei o seu pedido. Ele será enviado assim que a rede voltar.",
      );
      enviando = false;
      finalizar({ tipo_sugerido: "ouvidoria" });
      return;
    }

    t.remove();
    const fala = (resp.fala || "Recebi o seu pedido.").toString();
    historico.push({ papel: "assistente", texto: fala });
    bolha("assistente", fala);
    enviando = false;

    if (resp.concluido || turnos >= MAX_TURNOS) {
      finalizar(resp);
    } else {
      autoGrow();
      ta.focus();
      tocaIdle();
    }
  }

  ta.focus();
  tocaIdle();
}
