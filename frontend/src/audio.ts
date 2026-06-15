// Captura de áudio do totem: MediaRecorder + medição de nível (para animação)
// + máquina de estados com logs. Envia ao backend para transcrição (STT).
import { apiBase } from "./api";

export type EstadoAudio =
  | "ocioso"        // pronto, "a receber"
  | "solicitando"   // pedindo permissão do microfone
  | "gravando"      // microfone recebendo
  | "processando"   // enviando/transcrevendo
  | "concluido"     // áudio concluído
  | "erro";         // erro na recepção

export interface AudioCallbacks {
  onEstado: (e: EstadoAudio, detalhe?: string) => void;
  onNivel?: (nivel: number) => void; // 0..1, para a animação
  onLog: (msg: string) => void;
}

export class GravadorAudio {
  private rec?: MediaRecorder;
  private chunks: Blob[] = [];
  private stream?: MediaStream;
  private ctx?: AudioContext;
  private raf = 0;
  private inicio = 0;

  constructor(private cb: AudioCallbacks) {}

  get gravando(): boolean {
    return this.rec?.state === "recording";
  }

  async iniciar(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      this.cb.onEstado("erro", "Microfone não suportado neste dispositivo");
      this.cb.onLog("MediaDevices indisponível.");
      return;
    }
    try {
      this.cb.onEstado("solicitando");
      this.cb.onLog("Solicitando acesso ao microfone…");
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.medirNivel(this.stream);
      this.chunks = [];
      this.rec = new MediaRecorder(this.stream);
      this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
      this.rec.start();
      this.inicio = Date.now();
      this.cb.onEstado("gravando");
      this.cb.onLog("Gravando… toque novamente para parar.");
    } catch (e: any) {
      this.cb.onEstado("erro", "Permissão negada ou microfone indisponível");
      this.cb.onLog("Erro ao acessar o microfone: " + (e?.message || e));
      this.limpar();
    }
  }

  async parar(): Promise<Blob | null> {
    if (!this.rec || this.rec.state === "inactive") return null;
    return new Promise((resolve) => {
      this.rec!.onstop = () => {
        const dur = ((Date.now() - this.inicio) / 1000).toFixed(1);
        const blob = new Blob(this.chunks, { type: this.rec!.mimeType || "audio/webm" });
        this.cb.onLog(`Áudio capturado (${dur}s · ${Math.max(1, blob.size / 1024 | 0)} KB).`);
        this.cb.onEstado("processando", "Transcrevendo…");
        this.limpar();
        resolve(blob);
      };
      this.rec!.stop();
    });
  }

  cancelar(): void {
    try { this.rec?.stop(); } catch { /* noop */ }
    this.cb.onLog("Gravação cancelada.");
    this.cb.onEstado("ocioso");
    this.limpar();
  }

  private medirNivel(stream: MediaStream): void {
    try {
      this.ctx = new AudioContext();
      const fonte = this.ctx.createMediaStreamSource(stream);
      const analiser = this.ctx.createAnalyser();
      analiser.fftSize = 256;
      fonte.connect(analiser);
      const buf = new Uint8Array(analiser.frequencyBinCount);
      const loop = () => {
        analiser.getByteFrequencyData(buf);
        const media = buf.reduce((a, b) => a + b, 0) / buf.length / 255;
        this.cb.onNivel?.(Math.min(1, media * 1.8));
        this.raf = requestAnimationFrame(loop);
      };
      loop();
    } catch { /* sem visualização de nível */ }
  }

  private limpar(): void {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = undefined;
    this.cb.onNivel?.(0);
  }
}

export interface ResultadoTranscricao {
  texto: string;
  disponivel: boolean;
  detalhe?: string;
}

export async function transcrever(blob: Blob): Promise<ResultadoTranscricao> {
  const fd = new FormData();
  fd.append("audio", blob, "fala.webm");
  const r = await fetch(`${apiBase()}/transcrever`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const j = await r.json();
  return { texto: j.texto || "", disponivel: !!j.transcricao_disponivel, detalhe: j.detalhe };
}
