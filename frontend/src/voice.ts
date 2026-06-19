// Conversa apenas por voz (hands-free). Loop: VAD detecta a fala -> Whisper
// transcreve (/transcrever) -> agente decide a próxima fala ou conclui
// (/conversa) -> TTS responde -> repete. Sem toque na tela.
import { apiBase, type Modo } from "./api";
import { transcrever } from "./audio";

export type EstadoConversa =
  | "ocioso" | "ouvindo" | "processando" | "falando" | "encerrado" | "erro";

export interface ConversaResultado {
  tipo_sugerido?: string;
  gravidade?: string;
  canal_sugerido?: string;
  escalonar_humano?: boolean;
}

export interface ConversaCallbacks {
  onEstado: (e: EstadoConversa, detalhe?: string) => void;
  onNivel?: (n: number) => void;
  onFala?: (papel: "voce" | "poto", texto: string) => void;
  onConcluido: (r: ConversaResultado, transcricao: string) => void;
  onLog?: (m: string) => void;
}

function mimeAudio(): string {
  const c = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return c.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
}

// Parâmetros do detector de atividade de voz (VAD).
const LIMIAR = 0.045;     // energia RMS mínima para considerar "fala"
const SILENCIO_MS = 900;  // silêncio que encerra um segmento
const MIN_FALA_MS = 350;  // descarta ruídos muito curtos
const MAX_TURNOS = 4;     // trava de segurança no cliente

export class ConversaVoz {
  private stream?: MediaStream;
  private ctx?: AudioContext;
  private analiser?: AnalyserNode;
  private raf = 0;
  private rec?: MediaRecorder;
  private chunks: Blob[] = [];
  private gravando = false;
  private falando = false;
  private ativo = false;
  private ultimoSom = 0;
  private inicioSeg = 0;
  private turnos = 0;
  private historico: { papel: string; texto: string }[] = [];
  private modo: Modo = "normal";

  constructor(private cb: ConversaCallbacks) {}

  async iniciar(modo: Modo = "normal"): Promise<void> {
    this.modo = modo;
    if (!navigator.mediaDevices?.getUserMedia) {
      this.cb.onEstado("erro", "Microfone indisponível");
      return;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e: any) {
      this.cb.onEstado("erro", "Permissão de microfone negada");
      this.cb.onLog?.(String(e?.message || e));
      return;
    }
    this.ctx = new AudioContext();
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analiser = this.ctx.createAnalyser();
    this.analiser.fftSize = 512;
    src.connect(this.analiser);
    this.ativo = true;
    await this.poto("Pode falar. Estou ouvindo você.");
    this.cb.onEstado("ouvindo");
    this.loopVAD();
  }

  private rms(): number {
    const buf = new Uint8Array(this.analiser!.fftSize);
    this.analiser!.getByteTimeDomainData(buf);
    let s = 0;
    for (const v of buf) { const x = (v - 128) / 128; s += x * x; }
    return Math.sqrt(s / buf.length);
  }

  private loopVAD(): void {
    const tick = () => {
      if (!this.ativo) return;
      const nivel = this.rms();
      this.cb.onNivel?.(Math.min(1, nivel * 4));
      const agora = performance.now();
      if (!this.falando) {
        if (nivel > LIMIAR) {
          this.ultimoSom = agora;
          if (!this.gravando) this.abrirSegmento();
        } else if (this.gravando && agora - this.ultimoSom > SILENCIO_MS) {
          if (agora - this.inicioSeg > MIN_FALA_MS) this.fecharSegmento();
          else this.descartarSegmento();
        }
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  private abrirSegmento(): void {
    this.chunks = [];
    const mime = mimeAudio();
    this.rec = new MediaRecorder(this.stream!, mime ? { mimeType: mime } : undefined);
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start();
    this.gravando = true;
    this.inicioSeg = performance.now();
    this.cb.onEstado("ouvindo", "Ouvindo…");
  }

  private descartarSegmento(): void {
    try { this.rec?.stop(); } catch { /* */ }
    this.gravando = false;
  }

  private fecharSegmento(): void {
    this.gravando = false;
    const rec = this.rec!;
    rec.onstop = () => {
      const blob = new Blob(this.chunks, { type: rec.mimeType || "audio/webm" });
      void this.processar(blob);
    };
    try { rec.stop(); } catch { /* */ }
  }

  private async processar(blob: Blob): Promise<void> {
    this.cb.onEstado("processando", "Transcrevendo…");
    let texto = "";
    try {
      const r = await transcrever(blob);
      if (!r.disponivel) {
        this.cb.onEstado("erro", "Transcrição indisponível");
        this.cb.onLog?.("A conversa por voz exige STT. Ative com `make stt-setup`.");
        this.parar();
        return;
      }
      texto = (r.texto || "").trim();
    } catch (e: any) {
      this.cb.onLog?.("Falha na transcrição: " + (e?.message || e));
      this.cb.onEstado("ouvindo");
      return;
    }
    if (!texto) { this.cb.onEstado("ouvindo"); return; }

    this.historico.push({ papel: "usuario", texto });
    this.turnos++;
    this.cb.onFala?.("voce", texto);

    this.cb.onEstado("processando", "Pensando…");
    let resp: any;
    try {
      const r = await fetch(`${apiBase()}/conversa`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ historico: this.historico, modo: this.modo }),
      });
      resp = await r.json();
    } catch (e: any) {
      this.cb.onLog?.("Falha no atendimento: " + (e?.message || e));
      this.cb.onEstado("ouvindo");
      return;
    }

    this.historico.push({ papel: "assistente", texto: resp.fala });
    this.cb.onFala?.("poto", resp.fala);
    await this.poto(resp.fala);

    const concluir = resp.concluido || this.turnos >= MAX_TURNOS;
    if (concluir) {
      this.ativo = false;
      const transcricao = this.historico
        .filter((h) => h.papel === "usuario").map((h) => h.texto).join(". ");
      this.pararStream();
      this.cb.onEstado("encerrado");
      this.cb.onConcluido(resp as ConversaResultado, transcricao);
    } else {
      this.cb.onEstado("ouvindo");
    }
  }

  // Fala via síntese de voz do navegador (pt-BR). Suspende o VAD para não captar a si mesmo.
  private poto(texto: string): Promise<void> {
    return new Promise((resolve) => {
      this.falando = true;
      this.cb.onEstado("falando", texto);
      try {
        const u = new SpeechSynthesisUtterance(texto);
        u.lang = "pt-BR";
        u.rate = 1; u.pitch = 1;
        const fim = () => { this.falando = false; resolve(); };
        u.onend = fim;
        u.onerror = fim;
        speechSynthesis.cancel();
        speechSynthesis.speak(u);
        // salvaguarda: se onend não disparar, libera após estimativa.
        setTimeout(fim, Math.min(12000, 1200 + texto.length * 70));
      } catch {
        this.falando = false;
        resolve();
      }
    });
  }

  parar(): void {
    this.ativo = false;
    try { speechSynthesis.cancel(); } catch { /* */ }
    this.pararStream();
    this.cb.onEstado("encerrado");
  }

  private pararStream(): void {
    cancelAnimationFrame(this.raf);
    try { this.rec?.stop(); } catch { /* */ }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.cb.onNivel?.(0);
  }
}
