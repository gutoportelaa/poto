# Teste: triagem agêntica com Ollama remoto (pré-Hailo)

Enquanto a Raspberry Pi não tem acelerador (Hailo), a triagem por IA roda num
**workstation com GPU** e a Pi consome remotamente. Espelha o modelo de produção
"central executa o LLM, totem na borda consome" — quando o Hailo chegar, troca-se
o backend de inferência e a Pi roda local, sem túnel.

## Arquitetura

```
Pi (backend FastAPI)  ──localhost:11434──►  [túnel SSH reverso]  ──►  Ollama do workstation (GPU)
        agentes (langgraph)                                              qwen2.5:14b
```

A Pi não precisa expor nada nem ter IP de entrada: o **túnel reverso parte do
workstation** (que alcança a Pi) e publica o Ollama local em `localhost:11434` da Pi.
O backend usa o default `POTO_OLLAMA_URL=http://localhost:11434` → cai no túnel.

## Passos

1. **Túnel** (do workstation que roda o Ollama, com acesso SSH à Pi):
   ```bash
   ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
       -N -R 11434:localhost:11434 raspvigia@<pi-tailscale-ip>
   ```
2. **Pi** — apontar para o modelo bom e reiniciar:
   ```bash
   sed -i 's/^POTO_OLLAMA_MODEL=.*/POTO_OLLAMA_MODEL=qwen2.5:14b/' backend/.env
   sudo systemctl restart poto-backend
   ```
3. **Validar**:
   ```bash
   curl -s http://localhost:11434/api/tags        # na Pi: deve listar os modelos do workstation
   curl -s <pi>:8000/api/v1/triagem -H 'content-type: application/json' \
     -d '{"texto":"...","modo":"normal"}'         # fonte=agentes, confiança alta
   ```

## Resultados medidos (RTX 4070 Laptop, qwen2.5:14b)

| Cenário | Latência | Precisão |
|---|---|---|
| 1ª chamada (load do modelo) | ~53 s | conf 1.0, correto |
| chamadas seguintes (quente) | ~5,6 s | conf 1.0, correto |

vs. `llama3.2:3b` na heurística da Pi: classificava emergências como `orientacao`/conf 0.3.

## Notas
- **Cold start**: o Ollama descarrega o modelo após o `keep_alive` (5min). Para evitar
  os ~53s, mantenha-o quente (`OLLAMA_KEEP_ALIVE=-1`/`30m` no serviço do Ollama, ou um
  ping periódico).
- **Tailscale SSH** com re-checagem periódica pode derrubar o túnel; o backend cai
  graciosamente na heurística determinística se o Ollama ficar inacessível.
- Botões de categoria e **pânico não usam o LLM** (roteamento direto) — só o
  "descrever em texto livre" depende do Ollama.
- **Makefile**: `make backend`/`make dev` agora carregam o `.env` (`uv run --env-file .env`);
  antes subiam sem as variáveis (ex.: Twilio caía em modo `log` silenciosamente).
