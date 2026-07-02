#!/usr/bin/env python3
"""Diagnóstico do módulo SIMCom A7670SA na rasp (voz/SMS via AT/serial).

Uso — rode NA RASP (o módulo está lá). Por padrão só LÊ (não disca, não manda SMS):

    # descobrir a porta AT (teste cada ttyUSB até 'AT' responder OK)
    python3 scripts/simcom_test.py --scan

    # diagnóstico read-only numa porta (SIM, sinal, registro, modo de rede)
    python3 scripts/simcom_test.py --port /dev/ttyUSB2

    # AÇÕES REAIS (gastam crédito do SIM) — use o SEU número em teste:
    python3 scripts/simcom_test.py --port /dev/ttyUSB2 --sms +5586981804692 --text "POTO teste"
    python3 scripts/simcom_test.py --port /dev/ttyUSB2 --call +5586981804692 --seconds 15

Requer pyserial:  uv run --extra simcom python scripts/simcom_test.py ...
                  (ou: pip install pyserial)
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial  # type: ignore
except ImportError:
    sys.exit("pyserial ausente. Instale: uv sync --extra simcom  (ou pip install pyserial)")

CTRL_Z = "\x1a"


def at(ser, cmd: str, wait: float = 2.0) -> str:
    """Envia um comando AT e devolve a resposta bruta (para inspeção humana)."""
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    ser.flush()
    fim = time.monotonic() + wait
    buf = b""
    while time.monotonic() < fim:
        buf += ser.read(256)
        if b"OK" in buf or b"ERROR" in buf or b">" in buf:
            break
    return buf.decode("utf-8", "ignore").strip()


def scan() -> None:
    for i in range(5):
        porta = f"/dev/ttyUSB{i}"
        try:
            with serial.Serial(porta, 115200, timeout=0.5) as ser:
                resp = at(ser, "AT", 1.0)
                marca = "  <-- porta AT" if "OK" in resp else ""
                print(f"{porta}: {resp!r}{marca}")
        except Exception as e:  # noqa: BLE001
            print(f"{porta}: indisponível ({e})")


def diagnostico(ser) -> None:
    checagens = [
        ("AT", "eco/sanidade"),
        ("ATI", "identificação do módulo"),
        ("AT+CPIN?", "estado do SIM (READY?)"),
        ("AT+CSQ", "sinal (RSSI; 99 = sem sinal)"),
        ("AT+CREG?", "registro CS (voz) — 0,1 ou 0,5 = ok"),
        ("AT+CGREG?", "registro PS (dados)"),
        ("AT+CNMP?", "modo de rede (13=GSM/2G, 38=LTE, 2=auto)"),
        ("AT+COPS?", "operadora"),
    ]
    for cmd, desc in checagens:
        print(f"\n>>> {cmd}  ({desc})")
        print(at(ser, cmd))


def enviar_sms(ser, numero: str, texto: str) -> None:
    print(f"\n>>> forçando modo texto e enviando SMS para {numero}")
    print(at(ser, "AT+CMGF=1"))
    ser.write(f'AT+CMGS="{numero}"\r'.encode())
    time.sleep(1.0)
    ser.write((texto + CTRL_Z).encode())
    fim = time.monotonic() + 15
    buf = b""
    while time.monotonic() < fim:
        buf += ser.read(256)
        if b"+CMGS" in buf or b"ERROR" in buf:
            break
    print(buf.decode("utf-8", "ignore").strip())


def ligar(ser, numero: str, seconds: int, force_gsm: bool) -> None:
    if force_gsm:
        print("\n>>> forçando 2G (AT+CNMP=13) — A7670SA não tem VoLTE, voz só em GSM")
        print(at(ser, "AT+CNMP=13", 3.0))
        time.sleep(2)
    print(f"\n>>> discando {numero} (voz) por {seconds}s")
    print(at(ser, f"ATD{numero};"))
    time.sleep(seconds)
    print(">>> desligando (AT+CHUP)")
    print(at(ser, "AT+CHUP"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnóstico SIMCom A7670SA (AT/serial)")
    ap.add_argument("--scan", action="store_true", help="varre /dev/ttyUSB0..4 achando a porta AT")
    ap.add_argument("--port", default="/dev/ttyUSB2", help="porta AT (padrão /dev/ttyUSB2)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--sms", metavar="NUMERO", help="envia SMS de teste (E.164, ex.: +5586...)")
    ap.add_argument("--call", metavar="NUMERO", help="faz ligação de voz de teste")
    ap.add_argument("--text", default="POTO: teste de canal SIMCom.", help="corpo do SMS")
    ap.add_argument("--seconds", type=int, default=15, help="duração da ligação de teste")
    ap.add_argument("--no-force-gsm", action="store_true", help="não força 2G antes de discar")
    args = ap.parse_args()

    if args.scan:
        scan()
        return

    with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
        diagnostico(ser)
        if args.sms:
            enviar_sms(ser, args.sms, args.text)
        if args.call:
            ligar(ser, args.call, args.seconds, force_gsm=not args.no_force_gsm)


if __name__ == "__main__":
    main()
