# P.O.T.O — orquestração de backend (uv), frontend (bun) e agentes (ollama).
# Uso rápido:  make setup  &&  make dev

SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
OLLAMA_MODEL ?= llama3.2:3b
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

.DEFAULT_GOAL := help

.PHONY: help
help: ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup ----
.PHONY: setup
setup: setup-backend setup-frontend ## Instala dependências de backend e frontend

.PHONY: setup-backend
setup-backend: ## Cria o venv e instala deps do backend (uv)
	cd $(BACKEND) && uv sync

.PHONY: setup-frontend
setup-frontend: ## Instala deps do frontend (bun)
	cd $(FRONTEND) && bun install

# -------------------------------------------------------------- agentes ----
.PHONY: agents-pull
agents-pull: ## Baixa o modelo do Ollama (OLLAMA_MODEL=llama3.2:3b)
	ollama pull $(OLLAMA_MODEL)

.PHONY: agents-check
agents-check: ## Mostra o status da camada de agentes
	cd $(BACKEND) && uv run python -c "from app.agents.graph import status_agentes; import json; print(json.dumps(status_agentes(), indent=2, ensure_ascii=False))"

.PHONY: studio
studio: ## Abre o LangGraph Studio (visualiza e testa o fluxo agêntico)
	cd $(BACKEND) && ([ -f .env ] || cp .env.example .env) && uv run langgraph dev

.PHONY: graph
graph: ## Exporta o grafo dos agentes (Mermaid -> docs/agent-graph.mmd)
	cd $(BACKEND) && uv run python -c "from app.agents.graph import exportar_mermaid; open('../docs/agent-graph.mmd','w').write(exportar_mermaid()); print('docs/agent-graph.mmd gerado')"

.PHONY: stt-setup
stt-setup: ## Instala o Whisper local (faster-whisper) para transcrição
	cd $(BACKEND) && uv sync --extra stt --extra dev
	@echo "Defina POTO_STT_PROVIDER=faster-whisper no backend/.env para ativar."

# --------------------------------------------------------------- runtime ----
.PHONY: backend
backend: ## Sobe a API FastAPI (porta 8000)
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port $(BACKEND_PORT)

.PHONY: frontend
frontend: ## Builda e serve o frontend (porta 5173)
	cd $(FRONTEND) && bun run dev

.PHONY: build-frontend
build-frontend: ## Apenas builda o frontend para ./frontend/dist
	cd $(FRONTEND) && bun run build

.PHONY: seed
seed: ## Popula o banco com chamados de exemplo
	cd $(BACKEND) && uv run python -m app.seed

.PHONY: dev
dev: ## Sobe backend e frontend juntos
	@echo "Backend :$(BACKEND_PORT) | Frontend :$(FRONTEND_PORT) | Ctrl+C encerra ambos"
	@trap 'kill 0' INT TERM; \
	( cd $(BACKEND) && uv run uvicorn app.main:app --reload --port $(BACKEND_PORT) ) & \
	( cd $(FRONTEND) && bun run dev ) & \
	wait

# ----------------------------------------------------------------- test ----
.PHONY: test
test: ## Roda os testes do backend
	cd $(BACKEND) && uv run pytest -q

.PHONY: smoke
smoke: ## Teste de fumaça: importa app e roteia um evento sem subir servidor
	cd $(BACKEND) && uv run python -c "from app.router_engine import rotear; from app.models import TipoOcorrencia, Modo; print(rotear(TipoOcorrencia.mulher, Modo.normal))"

.PHONY: clean
clean: ## Remove artefatos e banco local
	rm -f $(BACKEND)/poto.db
	rm -rf $(FRONTEND)/dist $(BACKEND)/.venv
	@echo "limpo."
