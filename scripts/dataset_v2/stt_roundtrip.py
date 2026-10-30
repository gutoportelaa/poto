#!/usr/bin/env python3
"""Gera conjuntos de teste "passados por STT" (issue #9): voz sintética pt-BR (Piper) →
ruído de microfone de totem (opcional) → Whisper local (faster-whisper) → texto.

Os rótulos são os da frase original; o que muda é o texto, com os erros reais do
reconhecimento (acentos, palavras trocadas, cortes). Limitação: voz sintética única e
limpa; não substitui áudio gravado de pessoas em ambiente real.

Uso (a partir da raiz):
  uv run --no-project --with piper-tts --with faster-whisper --with numpy \\
     python scripts/dataset_v2/stt_roundtrip.py --voz voz.onnx --modelo base --snr 15
Saída: scripts/dataset_v2/teste_stt_<modelo>[_snr<N>].json
"""

from __future__ import annotations

import argparse
import json
import tempfile
import wave
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent


def sintetizar(voz, texto: str, caminho: str) -> None:
    with wave.open(caminho, "wb") as w:
        voz.synthesize_wav(texto, w)


def com_ruido(caminho: str, snr_db: float, rng: np.random.Generator) -> None:
    with wave.open(caminho, "rb") as w:
        par = w.getparams()
        x = np.frombuffer(w.readframes(par.nframes), dtype=np.int16).astype(np.float32)
    pot = float(np.mean(x ** 2)) or 1.0
    ruido = rng.normal(0, np.sqrt(pot / (10 ** (snr_db / 10))), x.shape)
    y = np.clip(x + ruido, -32768, 32767).astype(np.int16)
    with wave.open(caminho, "wb") as w:
        w.setparams(par)
        w.writeframes(y.tobytes())


def ler_16k(caminho: str) -> np.ndarray:
    """WAV 16-bit mono → float32 a 16 kHz (evita a decodificação via PyAV)."""
    with wave.open(caminho, "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voz", required=True, help="modelo .onnx do Piper")
    ap.add_argument("--modelo", default="base", help="tiny | base | small …")
    ap.add_argument("--snr", type=float, default=None, help="relação sinal/ruído em dB (opcional)")
    ap.add_argument("--fontes", default="teste,teste_ext")
    ap.add_argument("--limite", type=int, default=0, help="só as N primeiras (depuração)")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    from piper import PiperVoice

    voz = PiperVoice.load(args.voz)
    stt = WhisperModel(args.modelo, device="cpu", compute_type="int8")
    rng = np.random.default_rng(42)

    dados = []
    for nome in args.fontes.split(","):
        dados += json.loads((AQUI / f"{nome}.json").read_text("utf-8"))
    if args.limite:
        dados = dados[: args.limite]

    saida = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, d in enumerate(dados):
            wav = f"{tmp}/a.wav"
            sintetizar(voz, d["texto"], wav)
            if args.snr is not None:
                com_ruido(wav, args.snr, rng)
            segs, _ = stt.transcribe(ler_16k(wav), language="pt", beam_size=1, vad_filter=False)
            texto = " ".join(s.text.strip() for s in segs).strip()
            saida.append({**d, "texto": texto or d["texto"][:0], "texto_original": d["texto"],
                          "origem": f"stt-{args.modelo}"})
            if i % 25 == 0:
                print(f"{i}/{len(dados)}  {d['texto'][:45]!r} -> {texto[:45]!r}", flush=True)
    sufixo = f"_snr{int(args.snr)}" if args.snr is not None else ""
    destino = AQUI / f"teste_stt_{args.modelo}{sufixo}.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, indent=1), "utf-8")
    vazios = sum(1 for s in saida if not s["texto"])
    print(f"{destino.name}: {len(saida)} frases · {vazios} transcrições vazias")


if __name__ == "__main__":
    main()
