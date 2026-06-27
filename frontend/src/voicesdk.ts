// Chamada de voz ao vivo via Twilio Voice JS SDK — totem↔atendente (navegador↔
// navegador). Cliente↔cliente não toca PSTN: sem preâmbulo de trial. O token vem
// de /voice/token; o roteamento (<Dial><Client>) vem do webhook /voice/twiml.
import { type Call, Device } from "@twilio/voice-sdk";
import { apiBase } from "./api";

async function obterToken(identity: string): Promise<string> {
  const r = await fetch(`${apiBase()}/voice/token?identity=${encodeURIComponent(identity)}`);
  if (!r.ok) throw new Error(`token HTTP ${r.status}`);
  return (await r.json()).token as string;
}

// Garante a captura do microfone (e a permissão do navegador) ANTES de conectar.
// Sem isto, o originador pode entrar na chamada antes de a trilha de áudio existir
// e o outro lado não o ouve (sintoma: áudio só num sentido). Adquire, valida e
// libera — a permissão persiste e o SDK readquire o mic ao conectar.
async function prepararMicrofone(): Promise<void> {
  const s = await navigator.mediaDevices.getUserMedia({ audio: true });
  s.getTracks().forEach((t) => t.stop());
}

export async function criarDevice(identity: string): Promise<Device> {
  const device = new Device(await obterToken(identity), {
    logLevel: "error",
    // Opus (HD) com fallback PCMU — negociação de codec mais previsível entre navegadores.
    codecPreferences: ["opus", "pcmu"] as unknown as Device.Options["codecPreferences"],
  });
  device.on("tokenWillExpire", async () => {
    try {
      device.updateToken(await obterToken(identity));
    } catch {
      /* renovação falhou — a chamada corrente segue até expirar */
    }
  });
  return device;
}

export type EstadoChamada = "chamando" | "em_chamada" | "encerrada" | "erro";
export interface CallbacksChamada {
  onEstado: (e: EstadoChamada, detalhe?: string) => void;
}
export interface ControleChamada {
  encerrar: () => void;
  mutar: (m: boolean) => void;
}

function ligarEventos(call: Call, device: Device, cb: CallbacksChamada): void {
  call.on("accept", () => cb.onEstado("em_chamada"));
  const fim = () => {
    cb.onEstado("encerrada");
    try { device.destroy(); } catch { /* já destruído */ }
  };
  call.on("disconnect", fim);
  call.on("cancel", fim);
  call.on("reject", fim);
  call.on("error", (e: { message?: string }) => cb.onEstado("erro", e?.message || "erro"));
}

// Totem origina a chamada para o atendente (alvo = identidade da central).
export async function ligar(
  identity: string, alvo: string, cb: CallbacksChamada,
): Promise<ControleChamada> {
  await prepararMicrofone();
  const device = await criarDevice(identity);
  const call = await device.connect({ params: { To: alvo } });
  ligarEventos(call, device, cb);
  cb.onEstado("chamando");
  return {
    encerrar: () => {
      try { call.disconnect(); } catch { /* */ }
      try { device.destroy(); } catch { /* */ }
    },
    mutar: (m: boolean) => {
      try { call.mute(m); } catch { /* */ }
    },
  };
}

// Central registra-se para receber as chamadas do totem.
export async function registrarCentral(
  identity: string, onIncoming: (call: Call) => void,
): Promise<Device> {
  await prepararMicrofone();
  const device = await criarDevice(identity);
  device.on("incoming", onIncoming);
  await device.register();
  return device;
}

export type { Call };
