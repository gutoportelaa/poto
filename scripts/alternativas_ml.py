"""Alternativas de triagem baseadas em encoders (issue #10), plugadas no harness.

Carregado por `compare_triagem.py` apenas se torch/transformers/sentence-transformers
estiverem instalados. Treina na GPU (se houver) e MEDE a latência na CPU, que é o
alvo de implantação (Pi 5) — o número da workstation é só um limite inferior.

  e5small_lr / e5base_lr   embeddings multilingual-e5 congelados + LogReg (2 cabeças)
  bertimbau                BERTimbau-base com ajuste fino multitarefa (tipo + gravidade)

Dependências:  uv run --with torch --with transformers --with sentence-transformers ...
"""

from __future__ import annotations

import os
import pickle

SEED = 42


def registro(Alternativa) -> dict:  # noqa: N803 — recebe a classe base do harness
    import numpy as np
    import torch

    def _dispositivo() -> str:
        return "cuda" if torch.cuda.is_available() and not os.getenv("POTO_FORCE_CPU") else "cpu"

    class EmbedLogreg(Alternativa):
        """Embeddings e5 congelados + regressão logística por cabeça."""

        modelo = "intfloat/multilingual-e5-small"
        nome = "e5small_lr"

        def _enc(self, textos):
            if not hasattr(self, "_st"):
                from sentence_transformers import SentenceTransformer
                self._st = SentenceTransformer(self.modelo, device="cpu")
            # e5 exige o prefixo "query: " nos dois lados da tarefa de classificação
            return self._st.encode([f"query: {t}" for t in textos], batch_size=32,
                                   normalize_embeddings=True, show_progress_bar=False)

        def fit(self, dados):
            from sklearn.linear_model import LogisticRegression
            x = self._enc([d["texto"] for d in dados])
            mk = lambda: LogisticRegression(max_iter=2000, C=20.0, class_weight="balanced")  # noqa: E731
            self.c_tipo = mk().fit(x, [d["tipo"] for d in dados])
            self.c_grav = mk().fit(x, [d["gravidade"] for d in dados])
            return self

        def predict(self, textos):
            x = self._enc(textos)
            return list(zip(self.c_tipo.predict(x), self.c_grav.predict(x)))

        def tamanho_bytes(self):
            n = sum(p.numel() for p in self._st[0].auto_model.parameters())
            return n * 4 + len(pickle.dumps((self.c_tipo, self.c_grav)))

    class E5Base(EmbedLogreg):
        modelo = "intfloat/multilingual-e5-base"
        nome = "e5base_lr"

    class Bert(Alternativa):
        """Ajuste fino multitarefa: um encoder, duas cabeças lineares (tipo, gravidade)."""

        modelo = "neuralmind/bert-base-portuguese-cased"
        nome = "bertimbau"
        epocas, lr, lote, max_len = 10, 3e-5, 16, 64
        TIPOS = ["seguranca", "mulher", "saude", "ouvidoria"]
        GRAVS = ["risco_imediato", "risco_potencial", "orientacao"]

        def _montar(self):
            from transformers import AutoModel, AutoTokenizer
            self.tok = AutoTokenizer.from_pretrained(self.modelo)
            enc = AutoModel.from_pretrained(self.modelo)
            h = enc.config.hidden_size
            self.enc = enc
            self.h_tipo = torch.nn.Linear(h, len(self.TIPOS))
            self.h_grav = torch.nn.Linear(h, len(self.GRAVS))
            self.drop = torch.nn.Dropout(0.1)

        def _logits(self, textos, dev):
            b = self.tok(textos, padding=True, truncation=True, max_length=self.max_len,
                         return_tensors="pt").to(dev)
            cls = self.enc(**b).last_hidden_state[:, 0]
            cls = self.drop(cls)
            return self.h_tipo(cls), self.h_grav(cls)

        def _modulos(self):
            return torch.nn.ModuleList([self.enc, self.h_tipo, self.h_grav, self.drop])

        def fit(self, dados):
            torch.manual_seed(SEED)
            rng = np.random.default_rng(SEED)
            self._montar()
            dev = _dispositivo()
            mods = self._modulos().to(dev).train()
            opt = torch.optim.AdamW(mods.parameters(), lr=self.lr, weight_decay=0.01)
            passos = self.epocas * ((len(dados) + self.lote - 1) // self.lote)
            sch = torch.optim.lr_scheduler.LambdaLR(
                opt, lambda s: min(1.0, (s + 1) / (0.1 * passos)) * max(0.0, (passos - s) / passos))
            yt = torch.tensor([self.TIPOS.index(d["tipo"]) for d in dados])
            yg = torch.tensor([self.GRAVS.index(d["gravidade"]) for d in dados])
            for _ in range(self.epocas):
                for idx in np.array_split(rng.permutation(len(dados)),
                                          max(1, len(dados) // self.lote)):
                    lt, lg = self._logits([dados[i]["texto"] for i in idx], dev)
                    loss = (torch.nn.functional.cross_entropy(lt, yt[idx].to(dev))
                            + torch.nn.functional.cross_entropy(lg, yg[idx].to(dev)))
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
                    sch.step()
            mods.eval().to("cpu")  # inferência/latência na CPU (alvo: Pi 5)
            return self

        @torch.no_grad()
        def predict(self, textos):
            out = []
            for i in range(0, len(textos), 32):
                lt, lg = self._logits(textos[i:i + 32], "cpu")
                out += [(self.TIPOS[a], self.GRAVS[b])
                        for a, b in zip(lt.argmax(1).tolist(), lg.argmax(1).tolist())]
            return out

        def tamanho_bytes(self):
            return sum(p.numel() for p in self._modulos().parameters()) * 4

    class ZeroShotNLI(Alternativa):
        """Zero-shot por inferência de linguagem natural (sem treino): cada rótulo vira
        uma hipótese descritiva em português. Não usa o dataset de treino."""

        modelo = "MoritzLaurer/ModernBERT-large-zeroshot-v2.0"
        nome = "zs_modernbert"
        ROT_TIPO = {
            "seguranca": "segurança, crime ou perigo no campus",
            "mulher": "violência ou assédio contra a mulher",
            "saude": "problema de saúde ou emergência médica",
            "ouvidoria": "reclamação, denúncia, sugestão ou elogio administrativo",
        }
        ROT_GRAV = {
            "risco_imediato": "um perigo imediato acontecendo agora",
            "risco_potencial": "uma situação preocupante sem perigo imediato",
            "orientacao": "um pedido de informação sem nenhum risco",
        }

        def fit(self, dados):
            from transformers import pipeline
            self.pipe = pipeline("zero-shot-classification", model=self.modelo,
                                 device=0 if _dispositivo() == "cuda" else -1)
            return self

        def _melhor(self, textos, rotulos, modelo_hip):
            nomes = list(rotulos)
            res = self.pipe(textos, [rotulos[n] for n in nomes], hypothesis_template=modelo_hip,
                            batch_size=16)
            res = res if isinstance(res, list) else [res]
            inv = {v: k for k, v in rotulos.items()}
            return [inv[r["labels"][0]] for r in res]

        def predict(self, textos):
            return list(zip(self._melhor(textos, self.ROT_TIPO, "Esta mensagem é sobre {}."),
                            self._melhor(textos, self.ROT_GRAV, "Esta mensagem descreve {}.")))

        def tamanho_bytes(self):
            return sum(p.numel() for p in self.pipe.model.parameters()) * 4

    class ZeroShotMDeberta(ZeroShotNLI):
        modelo = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
        nome = "zs_mdeberta"

    class LlmLogprobs(Alternativa):
        """LLM local (Ollama) como classificador System 1: a resposta é UMA letra e a
        decisão sai das probabilidades (logprobs) dessa letra, sem gerar texto.
        `k` exemplos por rótulo vêm do treino (few-shot); k=0 é zero-shot."""

        modelo, k = "gemma3:4b", 0
        nome = "llm_gemma3_4b"
        url = os.getenv("POTO_OLLAMA_URL", "http://localhost:11434")
        TIPOS = {"seguranca": "ameaça, crime, invasão, briga, incêndio ou perigo físico no campus, ou dúvida sobre a segurança",
                 "mulher": "violência, assédio ou importunação contra mulher, ou orientação sobre a rede de proteção",
                 "saude": "mal-estar, acidente, emergência clínica, saúde mental ou dúvida sobre atendimento de saúde",
                 "ouvidoria": "reclamação, denúncia de irregularidade, sugestão, elogio ou dúvida sobre a ouvidoria"}
        GRAVS = {"risco_imediato": "acontecendo AGORA, risco iminente à vida ou integridade",
                 "risco_potencial": "situação preocupante ou ameaça difusa, sem perigo iminente",
                 "orientacao": "pedido de informação ou orientação, sem risco"}

        def fit(self, dados):
            self.exemplos = {"tipo": [], "gravidade": []}
            if self.k:
                for campo, rots in (("tipo", self.TIPOS), ("gravidade", self.GRAVS)):
                    for r in rots:
                        ds = [d for d in dados if d[campo] == r]
                        for d in ds[:: max(1, len(ds) // self.k)][: self.k]:
                            self.exemplos[campo].append((d["texto"], r))
            return self

        def _prompt(self, campo, rots, texto):
            letras = "ABCD"[: len(rots)]
            opcoes = "\n".join(f"{l}) {r}: {d}" for l, (r, d) in zip(letras, rots.items()))
            shots = "".join(
                f'Mensagem: "{t}"\nResposta: {letras[list(rots).index(r)]}\n\n'
                for t, r in self.exemplos[campo])
            return (f"Você classifica mensagens de um totem de emergência da UFPI ({campo}).\n"
                    f"Opções:\n{opcoes}\nResponda SOMENTE com a letra.\n\n{shots}"
                    f'Mensagem: "{texto}"\nResposta:'), letras

        def _escolher(self, campo, rots, texto):
            import json
            import math
            import urllib.request
            prompt, letras = self._prompt(campo, rots, texto)
            corpo = {"model": self.modelo, "stream": False, "think": False, "logprobs": True,
                     "top_logprobs": 10, "options": {"temperature": 0, "num_predict": 1},
                     "messages": [{"role": "user", "content": prompt}]}
            req = urllib.request.Request(f"{self.url}/api/chat", json.dumps(corpo).encode(),
                                         {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                lp = json.loads(r.read()).get("logprobs") or []
            top = {t["token"].strip(): t["logprob"] for t in (lp[0]["top_logprobs"] if lp else [])}
            pontos = [top.get(l, -1e9) for l in letras]
            if max(pontos) < -1e8:  # modelo não respondeu com letra: cai no mais protetivo
                return list(rots)[0]
            z = sum(math.exp(p) for p in pontos)
            self.ultima_prob = [math.exp(p) / z for p in pontos]
            return list(rots)[pontos.index(max(pontos))]

        def predict(self, textos):
            return [(self._escolher("tipo", self.TIPOS, t), self._escolher("gravidade", self.GRAVS, t))
                    for t in textos]

    class LlmGemma3Fs(LlmLogprobs):
        k, nome = 3, "llm_gemma3_4b_fs"

    class LlmQwen3Fs(LlmLogprobs):
        modelo, k, nome = "qwen3:8b", 3, "llm_qwen3_8b_fs"

    return {c.nome: c for c in (EmbedLogreg, E5Base, Bert, ZeroShotNLI, ZeroShotMDeberta,
                                LlmLogprobs, LlmGemma3Fs, LlmQwen3Fs)}
