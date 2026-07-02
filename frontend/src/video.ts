// Vídeo do P.O.T.O: registro por câmera (evidência) e transmissão WebRTC.
// - Totem = publicador (publica a câmera na sala = chamado_id e grava evidência).
// - Central = visualizador (assiste à sala do chamado).
// O backend só faz a sinalização (SDP/ICE); o vídeo é peer-to-peer.
import { apiBase } from "./api";

function salaWS(sala: string): string {
  return apiBase().replace(/^http/, "ws") + "/rtc/" + encodeURIComponent(sala);
}

async function rtcConfig(): Promise<RTCConfiguration> {
  try {
    const r = await fetch(`${apiBase()}/rtc/config`);
    if (r.ok) return await r.json();
  } catch { /* usa fallback */ }
  return { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] };
}

function escolherMime(): string {
  const cands = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];
  return cands.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
}

// ---- Câmera + gravação de evidência -------------------------------------
export class CameraController {
  stream?: MediaStream;
  private rec?: MediaRecorder;
  private chunks: Blob[] = [];

  get suportada(): boolean {
    return !!navigator.mediaDevices?.getUserMedia;
  }

  async iniciar(comAudio = true): Promise<MediaStream> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
      audio: comAudio,
    });
    return this.stream;
  }

  gravar(): void {
    if (!this.stream) return;
    this.chunks = [];
    const mime = escolherMime();
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start(1000);
  }

  async pararGravacao(): Promise<Blob | null> {
    if (!this.rec || this.rec.state === "inactive") return null;
    return new Promise((resolve) => {
      this.rec!.onstop = () =>
        resolve(new Blob(this.chunks, { type: this.rec!.mimeType || "video/webm" }));
      this.rec!.stop();
    });
  }

  parar(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = undefined;
  }
}

export async function enviarEvidencia(blob: Blob, chamadoId: string, totemId: string): Promise<any> {
  const fd = new FormData();
  fd.append("video", blob, "evidencia.webm");
  fd.append("chamado_id", chamadoId);
  fd.append("totem_id", totemId);
  const r = await fetch(`${apiBase()}/evidencia`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// ---- WebRTC -------------------------------------------------------------
export interface SessaoRTC {
  encerrar: () => void;
  onEstado?: (estado: RTCPeerConnectionState) => void;
}

interface CBPub {
  onEstado?: (e: RTCPeerConnectionState) => void;
  onRemoteStream?: (s: MediaStream) => void; // A/V de volta da central (chamada bidirecional)
}
interface CBView { onStream?: () => void; onEstado?: (e: RTCPeerConnectionState) => void; }

function montar(ws: WebSocket, pc: RTCPeerConnection): SessaoRTC {
  return {
    encerrar() {
      try { pc.getSenders().forEach((s) => s.track?.stop()); } catch { /* */ }
      try { pc.close(); } catch { /* */ }
      try { ws.close(); } catch { /* */ }
    },
  };
}

const env = (ws: WebSocket, m: unknown) => {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(m));
};

// Totem publica a câmera na sala.
export async function publicar(
  sala: string, stream: MediaStream, totemId: string, cb: CBPub = {},
): Promise<SessaoRTC> {
  const pc = new RTCPeerConnection(await rtcConfig());
  stream.getTracks().forEach((t) => pc.addTrack(t, stream));
  // A central pode devolver A/V (chamada bidirecional): tocamos o stream dela.
  pc.ontrack = (e) => cb.onRemoteStream?.(e.streams[0]);
  const ws = new WebSocket(salaWS(sala));
  pc.onicecandidate = (e) => { if (e.candidate) env(ws, { tipo: "ice", candidate: e.candidate }); };
  pc.onconnectionstatechange = () => cb.onEstado?.(pc.connectionState);
  ws.onopen = () => {
    env(ws, { tipo: "publicando", totem_id: totemId });
    env(ws, { tipo: "totem-pronto" });
  };
  ws.onmessage = async (ev) => {
    const m = JSON.parse(ev.data);
    if (m.tipo === "operador-pronto") {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      env(ws, { tipo: "offer", sdp: pc.localDescription });
    } else if (m.tipo === "answer") {
      await pc.setRemoteDescription(m.sdp);
    } else if (m.tipo === "ice" && m.candidate) {
      try { await pc.addIceCandidate(m.candidate); } catch { /* */ }
    }
  };
  return montar(ws, pc);
}

// Central assiste à sala. Se `localStream` for passado, a central também envia
// seu A/V (mic+câmera) — a chamada vira bidirecional (atendimento ao vivo).
export async function assistir(
  sala: string, videoEl: HTMLVideoElement, cb: CBView = {}, localStream?: MediaStream,
): Promise<SessaoRTC> {
  const pc = new RTCPeerConnection(await rtcConfig());
  // Não pré-criamos transceivers: a oferta do totem dita as m-lines (evita
  // descasamento). O ontrack dispara ao receber as faixas do publicador.
  pc.ontrack = (e) => { videoEl.srcObject = e.streams[0]; cb.onStream?.(); };
  const ws = new WebSocket(salaWS(sala));
  pc.onicecandidate = (e) => { if (e.candidate) env(ws, { tipo: "ice", candidate: e.candidate }); };
  pc.onconnectionstatechange = () => cb.onEstado?.(pc.connectionState);
  ws.onopen = () => env(ws, { tipo: "operador-pronto" });
  ws.onmessage = async (ev) => {
    const m = JSON.parse(ev.data);
    if (m.tipo === "totem-pronto") {
      env(ws, { tipo: "operador-pronto" });
    } else if (m.tipo === "offer") {
      await pc.setRemoteDescription(m.sdp);
      // Anexa o A/V da central às m-lines da oferta (recvonly → sendrecv).
      if (localStream) localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
      const ans = await pc.createAnswer();
      await pc.setLocalDescription(ans);
      env(ws, { tipo: "answer", sdp: pc.localDescription });
    } else if (m.tipo === "ice" && m.candidate) {
      try { await pc.addIceCandidate(m.candidate); } catch { /* */ }
    }
  };
  return montar(ws, pc);
}
