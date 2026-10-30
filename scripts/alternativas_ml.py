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

    return {c.nome: c for c in (EmbedLogreg, E5Base, Bert)}
