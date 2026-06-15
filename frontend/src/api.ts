// Cliente da API com suporte ONLINE e OFFLINE (store-and-forward).
// Online : POST direto no backend; agentes rodam no servidor.
// Offline: evento é persistido em fila local e a confirmação discreta é dada
//          imediatamente; a fila é drenada quando a conexão volta.

export type TipoOcorrencia = "seguranca" | "mulher" | "saude" | "ouvidoria";
export type Modo = "normal" | "discreto";

export interface EventoIn {
  evento_id: string;
  totem_id: string;
  tipo_ocorrencia: TipoOcorrencia;
  modo: Modo;
  origem_acionamento: "botao_fisico" | "touch";
  timestamp_local: string;
  texto_livre?: string;
}

export interface InstrucaoTotem {
  mensagem_tela: string;
  feedback_sonoro: boolean;
  tela_neutra: boolean;
}

export interface EventoOut {
  chamado_id: string;
  status: string;
  canal_roteado: string;
  gravidade: string;
  instrucao_totem: InstrucaoTotem;
  duplicado: boolean;
  _offline?: boolean;
}

const QUEUE_KEY = "poto_queue";

export function apiBase(): string {
  const override = localStorage.getItem("poto_api");
  if (override) return override;
  // Em dev o frontend roda na 5173 e o backend na 8000.
  if (location.port === "5173") return `http://${location.hostname}:8000/api/v1`;
  return `${location.origin}/api/v1`;
}

export function uuid(): string {
  return crypto.randomUUID();
}

export function novoEvento(
  tipo: TipoOcorrencia,
  modo: Modo,
  origem: "botao_fisico" | "touch" = "touch",
  texto?: string,
): EventoIn {
  return {
    evento_id: uuid(),
    totem_id: localStorage.getItem("poto_totem_id") || "TOTEM-CCS-01",
    tipo_ocorrencia: tipo,
    modo,
    origem_acionamento: origem,
    timestamp_local: new Date().toISOString(),
    texto_livre: texto,
  };
}

function readQueue(): EventoIn[] {
  try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]"); }
  catch { return []; }
}
function writeQueue(q: EventoIn[]): void {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
}
export function pendentes(): number { return readQueue().length; }

async function postEvento(ev: EventoIn): Promise<EventoOut> {
  const res = await fetch(`${apiBase()}/eventos`, {
    method: "POST",
    headers: { "content-type": "application/json", "Idempotency-Key": ev.evento_id },
    body: JSON.stringify(ev),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Confirmação discreta padrão para o caminho offline.
function stubOffline(ev: EventoIn): EventoOut {
  const discreto = ev.modo === "discreto" || ev.tipo_ocorrencia === "mulher";
  return {
    chamado_id: "LOCAL-" + ev.evento_id.slice(0, 8),
    status: "enfileirado_local",
    canal_roteado: ev.tipo_ocorrencia,
    gravidade: "risco_potencial",
    instrucao_totem: {
      mensagem_tela: "Seu pedido foi registrado. Aguarde atendimento.",
      feedback_sonoro: !discreto,
      tela_neutra: discreto,
    },
    duplicado: false,
    _offline: true,
  };
}

// Envia o evento; em falha, enfileira localmente e confirma mesmo assim.
export async function enviarEvento(ev: EventoIn): Promise<EventoOut> {
  try {
    return await postEvento(ev);
  } catch {
    const q = readQueue();
    q.push(ev);
    writeQueue(q);
    return stubOffline(ev);
  }
}

// Drena a fila local (idempotente no servidor: reenvio é seguro).
export async function sincronizar(): Promise<number> {
  const q = readQueue();
  if (!q.length) return 0;
  const restantes: EventoIn[] = [];
  let enviados = 0;
  for (const ev of q) {
    try { await postEvento(ev); enviados++; }
    catch { restantes.push(ev); }
  }
  writeQueue(restantes);
  return enviados;
}

export async function estaOnline(): Promise<boolean> {
  if (!navigator.onLine) return false;
  try {
    const res = await fetch(`${apiBase()}/health`, { method: "GET" });
    return res.ok;
  } catch { return false; }
}
