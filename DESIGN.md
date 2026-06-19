# P.O.T.O — Identidade Visual & Sistema de Design

> **Plataforma de Orientação, Triagem e Ouvidoria** — Totem Inteligente de Emergência (UFPI, Campus Ministro Petrônio Portella).
>
> Este documento define a linguagem visual do produto e serve como **brief para o Google Stitch** gerar protótipos de tela. Os tokens aqui descritos espelham e estendem o que já existe em [`frontend/src/styles.css`](frontend/src/styles.css).

---

## 1. Conceito & personalidade

A marca nasce do **potó** (besouro *Paederus*, o "inseto-pólvora" comum no Nordeste e familiar no campus de Teresina): um corpo segmentado, ágil, de cabeça preta e dorso laranja-ferrugem. Ele dá à plataforma uma identidade **regional, reconhecível e direta** — não um genérico ícone de "alerta".

Tradução do inseto para a interface:

| Atributo do potó | Tradução em UI/UX |
|---|---|
| Cabeça preta, sólida | Tipografia firme, contraste alto, autoridade institucional |
| Segmentos do corpo (curvas suaves repetidas) | **Curvas contínuas** — cantos arredondados consistentes, "cápsulas" |
| Laranja-ferrugem vibrante | Cor de **ação e atenção**; usada com parcimônia, nunca decorativa |
| Antenas / movimento ágil | **Microanimações** rápidas e intencionais; nada gratuito |
| Corpo alongado e horizontal | Layouts **horizontais e amplos** (totem em paisagem, painel em grade) |

**Tom de voz visual:** sério mas acolhedor, público (governo/saúde), legível à distância, calmo em repouso e inequívoco na emergência. A interface é de **alto risco e baixa fricção**: qualquer pessoa, em estresse, resolve em ≤ 2 toques.

---

## 2. Curvas — a assinatura da forma

As curvas são o elemento mais característico, derivado dos segmentos do corpo do inseto. **Regra única:** todo raio é múltiplo da escala base e os elementos interativos primários tendem à **cápsula** (pill).

| Token | Valor | Uso |
|---|---|---|
| `--r-xs` | `8px` | chips, tags, inputs pequenos |
| `--r-sm` | `10px` | selects, botões secundários |
| `--r-md` | `14px` | **raio padrão** — cards, botões, textarea (`--radius` atual) |
| `--r-lg` | `20px` | painéis, modais, containers de tela |
| `--r-xl` | `28px` | superfícies grandes do totem |
| `--r-pill` | `999px` | status, badges, botões de ação primária no totem |

Princípios:
- **Concentricidade:** um elemento dentro do outro deve ter raio interno = raio externo − padding. Nunca cantos "competindo".
- **Curva = afeto, reto = dado.** Botões e mensagens são arredondados; tabelas/listas densas do painel podem ter cantos menores para densidade.
- A própria silhueta do potó pode aparecer como **divisor/ornamento sutil** (linha de segmentos) em cabeçalhos e telas vazias — sempre monocromático e discreto.

---

## 3. Paleta de cores

Derivada diretamente da logo: **preto-tinta + laranja-ferrugem sobre papel quente**. O laranja é semáforo de ação, não enfeite.

### Tokens base (espelham `styles.css`)

```css
:root {
  /* Tinta / neutros quentes */
  --ink:        #17150F;  /* texto, cabeça do inseto, autoridade */
  --muted:      #6F6862;  /* texto secundário */
  --faint:      #9A938B;  /* legendas, metadados, estados desabilitados */
  --line:       #E8E3DD;  /* bordas, divisores */
  --paper:      #FBF9F6;  /* superfície quente (cards em repouso) */
  --bg:         #FFFFFF;  /* fundo */

  /* Ferrugem (cor da marca / ação / atenção) */
  --rust:       #C0392B;  /* primária — corpo do potó */
  --rust-d:     #8F2A17;  /* hover / texto sobre claro */
  --rust-soft:  #F6E7E3;  /* fundo suave, realce calmo */

  /* Semáforo (triagem) */
  --crit:       #C0392B;  /* IMEDIATO — reusa rust */
  --warn:       #D68A2E;  /* POTENCIAL — âmbar */
  --info:       #9A938B;  /* ORIENTAÇÃO — neutro */
  --ok:         #2F7D4F;  /* concluído / online */
}
```

### Uso semântico (triagem) — herdado do painel

| Gravidade | Cor | Token | Aplicação |
|---|---|---|---|
| **Imediato** (crítico) | vermelho-ferrugem | `--crit` | barra lateral do card, botão de pânico, alerta full-screen |
| **Potencial** | âmbar | `--warn` | barra lateral, chip |
| **Orientação** | neutro quente | `--info` | barra lateral, chip |
| **Concluído / Online** | verde | `--ok` | confirmações, status do totem |

### Regras de cor
- **60 / 30 / 10:** ~60% papel/branco, ~30% tinta, ~10% ferrugem. Ferrugem em saturação cheia só em CTA, alerta e marca.
- Contraste mínimo **AA** (4.5:1 texto, 3:1 UI). `--rust` sobre branco passa para texto grande/UI; para texto corrido use `--rust-d`.
- Modo emergência inverte a hierarquia: a tela inteira pode ir a `--crit` com texto branco — ver §9.
- **Sem gradientes ruidosos.** No máximo, um gradiente sutil ferrugem→ferrugem-escuro em superfícies de pânico.

---

## 4. Tipografia — Michroma (linhagem Michrogramma/Eurostile)

A fonte de display é **Michroma** — herdeira open-source direta do DNA **Michrogramma → Eurostile**: geométrica, quadrada, larga e técnica. Ecoa o corpo alongado e horizontal do potó e a estética de "instrumento de emergência / engenharia", **sem custo de licença e disponível no Google Fonts**. Eurostile Extended fica como opção paga apenas se precisarmos de um negrito mais encorpado (ver abaixo).

### Família e pesos

| Papel | Fonte | Observação |
|---|---|---|
| **Display / títulos / wordmark / rótulos** | **Michroma** | Google Fonts; quadrada e larga, ótima em caixa-alta |
| **Negrito robusto** (opcional) | **Eurostile Extended Bold** (licenciada) ou **Orbitron 700/900** (livre) | Michroma só tem peso 400 — ver limitação |
| **Texto de interface / corpo / parágrafos** | **Inter** (atual) ou **Saira** | Michroma é pesada demais em texto corrido — reservar à display |

> **⚠️ Limitação real da Michroma:** ela existe **só no peso 400 (regular)**. Não há `700` nativo. Para hierarquia de peso, três caminhos:
> 1. **Tamanho + tracking + caixa-alta** fazem o trabalho de "peso" na maioria dos títulos (recomendado — é o jeito mais limpo).
> 2. **Eurostile Extended Bold** licenciada via `@font-face`, usada só onde o negrito pesado importa (wordmark, botão de pânico).
> 3. **Orbitron** (Google Fonts, vai a 900) como par de peso para a Michroma — DNA quadrado compatível.
> Evitar `font-weight: bold` cru sobre Michroma (gera *faux-bold* irregular). Se precisar de reforço sintético, prefira `-webkit-text-stroke: .4px currentColor`.

### Implementação

```css
/* Display livre (Google Fonts) */
@import url("https://fonts.googleapis.com/css2?family=Michroma&family=Inter:wght@400;500;600;700&display=swap");

/* Negrito robusto opcional — só se a licença existir */
@font-face {
  font-family: "Eurostile Extended";
  src: url("/assets/fonts/EurostileExtended-Bold.woff2") format("woff2");
  font-weight: 700; font-display: swap;
}

:root {
  --font-display:      "Michroma", "Orbitron", "Saira", system-ui, sans-serif;
  --font-display-bold: "Eurostile Extended", "Orbitron", "Michroma", sans-serif;
  --font-ui:           "Inter", system-ui, sans-serif;
}
```

> **Para o Google Stitch:** prototipar com **Michroma** (display) + **Inter** (corpo), ambas no Google Fonts. Onde o protótipo pedir negrito de display, usar **Orbitron 700/900**.

### Escala tipográfica (totem em paisagem, leitura à distância)

| Papel | Família | Tamanho | Peso | Tracking | Caixa |
|---|---|---|---|---|---|
| Display / pergunta do totem | display | 30–40px | 600–700 | `-0.01em` | normal |
| H1 painel | display | 24px | 600 | `0` | normal |
| Rótulo de botão / chip | display | 13–16px | 600–700 | **`+0.08em`** | UPPERCASE |
| Wordmark "P.O.T.O" | display | 18px | 700 | **`+0.12em`** | UPPERCASE, pontos em `--rust` |
| Tagline | display | 11px | 500 | `+0.14em` | UPPERCASE, `--faint` |
| Corpo / sub | ui | 15–18px | 400–500 | `0` | normal |
| Meta / log | ui | 12–13px | 400 | `0` | normal, `tabular-nums` |

**Wordmark:** preserve os pontos separadores `P.O.T.O` com os pontos em `--rust` — é o detalhe que conecta texto e marca. Tracking generoso (Extended já é larga; não aperte).

---

## 5. Grid, espaçamento & elevação

- **Escala de espaço (base 4):** `4 · 8 · 12 · 16 · 20 · 24 · 32 · 48`. Padding de card = 16–22px; gutter de grade = 14–16px.
- **Totem:** coluna central `max-width: 720px`, alvos de toque **≥ 64px de altura** (uso em pé, sob estresse). Botões iniciais em grade 2×2 que colapsa para 1 coluna < 560px.
- **Painel:** grade fluida `repeat(auto-fill, minmax(320px, 1fr))`.
- **Elevação:** sombra única e quente — `0 1px 2px rgba(20,15,5,.05), 0 10px 30px rgba(20,15,5,.06)`. Profundidade vem de **cor/borda**, não de muitas sombras.
- **Bordas:** `1.5px` (não 1px) — leitura nítida no totem.

---

## 6. Iconografia

- Estilo **outline, traço 2px, cantos arredondados** (alinhado às curvas). Biblioteca-base: **Material Symbols Rounded** (`FILL 0`, `wght 400`) — combina com a linguagem de curva e é o conjunto usado no protótipo; Lucide/Phosphor como alternativas equivalentes.
- Tamanhos: 24 (UI), 30–36 (totem padrão), **até 72 nos cartões de escolha do totem** (leitura à distância), 26–40 (pânico).
- Glifos validados (tela inicial): `stethoscope` (médica), `security`/`shield` (segurança), `female` (Sala Lilás), `info` (outros), `mic` (voz), `emergency` (pânico).
- Cor segue o texto do contexto; ferrugem só em ícones de ação/alerta.
- **Mascote:** a silhueta do potó é reservada à marca e a ilustrações de tela vazia/onboarding — **nunca** como ícone funcional (evita confundir com "praga/erro").

---

## 7. Biblioteca de componentes

> Base já implementada nas classes de `styles.css`; abaixo, a especificação canônica.

### 7.1 Botão de escolha (totem) — `.choice`
Card-botão grande: ícone (30px) + título (display) + descrição (ui). `--paper` com borda `1.5px --line`; hover → borda `--rust`; active → `translateY(1px)`. Mín. 132px de altura, texto à esquerda.

### 7.2 Botão de pânico — `.panic`
Largura total, `--rust` sólido, texto branco 22px/700, ícone 26px, cápsula ou `--r-md`. Hover → `--rust-d`. **Sempre o elemento de maior peso visual da tela.**

### 7.3 Botões padrão — `.btn` / `.btn.ghost`
Primário: tinta sólida (`--ink`), texto branco. Ghost: contorno tinta, fundo transparente. Raio `--r-md`, padding `14×22`.

### 7.4 Status pill — `.status`
Cápsula com ponto colorido: `online` (verde), `offline` (ferrugem), ocioso (faint). Sempre visível no topo do totem e do painel.

### 7.5 Card de chamado (painel) — `.card`
Borda esquerda 5px na cor da gravidade (`.imediato`/`.potencial`/`.orientacao`), id em display, timestamp em faint, chips de classificação, ações (ack/atribuir). Raio `--r-md`.

### 7.6 Chips / tags — `.chip`
Cápsula `--paper`/borda `--line`. Variante `.rust` para destaque crítico.

### 7.7 Orb de microfone — `.orb` (ver §8)
Disco 96px com anel reativo; é o componente de mais personalidade do produto.

### 7.8 Campos
Textarea/input: borda `1.5px --line`, raio `--r-md`, foco com `outline: 3px --rust`. Fonte ui ≥ 16px (evita zoom no iOS).

### 7.9 Confirmação — `.confirm`
Marca circular (✓) + título display + texto. Variante `neutral` (recebido) e crítica (ferrugem). Mensagem de offline em `--rust-soft`.

---

## 8. Movimento & animação

**Princípio:** *calmo em repouso, claro na transição, inequívoco na emergência.* Animação comunica **estado**, nunca decora.

| Token | Duração | Curva |
|---|---|---|
| micro (hover, press) | 60–120ms | `ease` |
| transição de tela | 200–250ms | `ease` / `cubic-bezier(.2,.8,.2,1)` |
| pulso / respiração | 1.1–3.4s | `ease-in-out` loop |

### Estados do microfone (já especificados no README) — referência canônica de movimento

| Estado | Animação | Quando |
|---|---|---|
| ocioso | `respira` 3.4s (escala 1→1.05) | pronto para gravar |
| solicitando | `respira` 1.4s + borda ferrugem | pedindo permissão |
| gravando | anel `eco` reativo ao volume (`--nivel`) | captando voz |
| processando | anel tracejado `girar` 1.6s | enviando/transcrevendo |
| concluído | tom verde + ✓ | sucesso |
| erro | tom ferrugem + `tremor` 0.35s ×2 | falha/permissão negada |

**Respeitar `prefers-reduced-motion`:** desligar transições/animações, manter apenas mudança de cor/estado (já implementado).

---

## 9. Padrão de emergência (alerta crítico)

Quando a triagem retorna **Imediato** / pânico acionado:
- A tela assume `--crit` (ou gradiente `--rust → --rust-d`) com **texto branco**.
- Mensagem curta e literal: *"Pedido enviado. Ajuda a caminho."* + número do protocolo grande (tabular).
- Um único pulso de confirmação (não piscar agressivo — público vulnerável).
- Botão único de ação/contato; nada que exija decisão.
- No painel correspondente: card sobe ao topo, borda `--crit`, badge pulsante discreto, som opcional.

---

## 10. Acessibilidade (não-negociável)

- Contraste **AA**; alvos de toque **≥ 48px** (totem ≥ 64px).
- Foco visível sempre (`outline 3px --rust`).
- Texto base ≥ 16px; suporta ampliação até 200%.
- Cor **nunca** é o único sinal — gravidade tem cor **+** rótulo **+** ícone.
- Português claro, frases curtas, voz ativa. Voz como entrada alternativa (totem).
- Modo offline com feedback honesto e imediato (store-and-forward).

---

## 11. Briefs de tela para o Google Stitch

> Cole cada bloco como prompt no Stitch. Contexto global a anexar em todos:
>
> **Contexto:** *Totem de emergência num campus universitário (UFPI Teresina). Identidade "P.O.T.O": preto-tinta `#17150F` + laranja-ferrugem `#C0392B` sobre papel quente `#FBF9F6`. Fonte de títulos **Michroma** + corpo **Inter** (Google Fonts); onde precisar de negrito de display, **Orbitron**. Cantos arredondados (raio 14px; ações primárias em cápsula). Botões grandes, alto contraste, calmo em repouso e inequívoco na emergência. Acessível AA, alvos ≥ 64px.*

### 11.1 Tela inicial — disposição dos botões
> *Tela de totem em paisagem. Cabeçalho com wordmark "P.O.T.O" (pontos em laranja) + tagline e pill de status "Online" verde à direita. Título grande: "Como podemos ajudar?". Abaixo, grade 2×2 de botões-cartão grandes (ícone centralizado no topo + título centralizado): "Emergência médica", "Segurança", "Assédio / Sala Lilás", "Outros". Sob a grade, sub-ação "Descrever por voz" (ícone de microfone em círculo + texto) e, abaixo, um botão de PÂNICO em largura total, cápsula laranja-ferrugem sólida, texto branco. Variante mobile: grade em 1 coluna. (Layout fixado em §12.)*

### 11.2 Caso de alerta (emergência crítica)
> *Tela de confirmação pós-acionamento, em estado crítico: fundo laranja-ferrugem (gradiente sutil para tom escuro), texto branco. Ícone grande de confirmação, mensagem "Pedido enviado. Ajuda a caminho." e número de protocolo em tipografia tabular grande. Um único botão branco "Falar com atendente agora". Microcópia de tranquilização. Sem elementos competindo por atenção. Mostrar também a variante "modo offline": mesma tela com aviso calmo em faixa clara "Sem internet — seu pedido foi salvo e será enviado automaticamente".*

### 11.3 Tela de chat (animação)
> *Interface de conversa de triagem assistida por IA. Bolhas arredondadas: usuário em laranja-ferrugem (texto branco, alinhado à direita), assistente em papel claro (texto tinta, à esquerda). Indicador de "digitando" com três pontos pulsando. Topo com título e status do agente. Rodapé com campo de texto arredondado + botão de microfone circular (o "orb"). Mostrar 3 quadros: (a) repouso — orb com respiração lenta; (b) gravando — orb laranja com anel pulsante reativo ao volume; (c) processando — orb com anel tracejado girando. Painel lateral opcional de "logs ao vivo" da triagem.*

### 11.4 Tela de monitoramento (painel central)
> *Dashboard em tempo real para a central de atendimento (desktop, paisagem). Cabeçalho com título "Painel — Chamados" e filtros em cápsula (gravidade, tipo, status). Grade fluida de cards de chamado: cada card com borda esquerda colorida pela gravidade (vermelho-ferrugem = Imediato, âmbar = Potencial, neutro = Orientação), id em destaque, horário, chips de classificação (tipo, canal) e ações "Reconhecer" / "Atribuir". Cards "Imediato" no topo com badge pulsante discreto. Barra lateral ou topo com contadores por gravidade. Tom institucional, denso porém legível.*

### 11.5 Tela de chamada (voz/vídeo com atendente)
> *Tela de chamada ao vivo entre solicitante e atendente da central. Layout em paisagem: área principal de vídeo/avatar do atendente, miniatura do solicitante no canto. Barra inferior com controles circulares grandes: mudo, alto-falante, encerrar (vermelho-ferrugem). Cronômetro da chamada em tipografia tabular no topo, com status "Conectado". Faixa de contexto mostrando o protocolo e a classificação da triagem. Versão "chamando…" com avatar pulsando e botão de cancelar. Alto contraste, controles ≥ 64px.*

### 11.6 Demais telas
> - **Descrever a situação (voz):** textarea grande + orb de microfone central com os 6 estados (ocioso, solicitando, gravando, processando, concluído, erro) e lista de logs ao vivo abaixo; botões "Enviar" (tinta) e "Voltar" (ghost).
> - **Confirmação não-crítica:** marca circular neutra ✓, "Recebido. Procure a orientação indicada.", protocolo e metadados em faint.
> - **Tela vazia / standby do totem:** wordmark centralizado, silhueta sutil do potó como ornamento, "Toque para começar", relógio e status de conexão.
> - **Login da central:** card centralizado, campos arredondados, botão primário tinta, marca no topo.
> - **Detalhe do chamado (central):** timeline do evento, transcrição da voz, classificação da IA (tipo/gravidade/canal/escalonar), botões de ação e atribuição.

---

## 12. Blueprint de layout — Tela inicial do totem

Esta seção fixa a **disposição dos elementos** validada no protótipo (`referencia/screen.png` + `referencia/code.html`). É a referência canônica de arranjo espacial para a tela inicial; demais telas herdam as mesmas zonas (cabeçalho / conteúdo / rodapé de ação).

### Estrutura em três zonas (totem full-screen, paisagem)

```
┌───────────────────────────────────────────────────────────────┐
│  ▸ margem segura (--space-totem 64px) em toda a borda          │
│                                                                 │
│  P.O.T.O                                          ● ONLINE      │  ← HEADER
│  (wordmark, pontos rust)                  (status pill, ping)    │
│                                                                 │
│                  Como podemos ajudar?                           │  ← MAIN
│                     (headline display)                          │   (centro
│        ┌───────────────────┐ ┌───────────────────┐             │    vertical)
│        │   [ícone 72]      │ │   [ícone 72]      │             │
│        │ Emergência médica │ │   Segurança       │             │
│        └───────────────────┘ └───────────────────┘             │
│        ┌───────────────────┐ ┌───────────────────┐             │
│        │   [ícone 72]      │ │   [ícone 72]      │             │
│        │ Assédio/Sala Lilás│ │   Outros          │             │
│        └───────────────────┘ └───────────────────┘             │
│                                                                 │
│                ( 🎙 )  Descrever por voz                         │  ← FOOTER
│        ╭───────────────────────────────────────────╮            │   (mt-auto)
│        │   ✱   BOTÃO DE PÂNICO                       │            │
│        ╰───────────────────────────────────────────╯            │
└───────────────────────────────────────────────────────────────┘
```

- **Container:** ocupa a tela inteira, `overflow: hidden`, `user-select: none` (kiosk), coluna central `max-width ~1280px`, margem segura uniforme de **64px** (`--space-totem`).
- **Header** (`space-between`): wordmark à esquerda, status pill à direita; ambos fixos (`shrink: 0`).
- **Main** (`flex-grow`, centrado V/H): headline + grade 2×2; respira com o espaço disponível.
- **Footer** (`margin-top: auto`, fixo embaixo): sub-ação de voz acima do botão de pânico — o pânico é sempre o último e mais pesado elemento.

### Medidas-chave (mapeadas aos nossos tokens)

| Elemento | Especificação |
|---|---|
| Margem segura | `64px` (`--space-totem`) |
| Headline | display (Michroma), ~`48–64px`, `line-height: 1`, centrado |
| Grade | 2 colunas, `gap` `24px` (`--space-lg`), `max-width ~896px` |
| Cartão de escolha | branco (`--bg`), borda `1.5px --line`, raio **`--r-lg` (20px)**, altura `~220px`, conteúdo centrado, padding `48px` |
| Ícone do cartão | `72px`, `--rust` (o "Outros" em `--muted`) |
| Rótulo do cartão | display, `24px`, centrado |
| Hover do cartão | fundo `--rust-soft`, borda realça, ícone escala `1.1`, sombra `--shadow`; `active` escala `0.95` |
| Sub-ação voz | círculo `56px` com ícone `mic` + texto `20px` `--muted` |
| Botão de pânico | cápsula (`--r-pill`), `--rust`, texto branco, largura plena (`max-width ~896px`), rótulo UPPERCASE com tracking, ícone `40px` |

### Reconciliações com o DESIGN.md (o protótipo divergiu — vale o documento)

| Ponto | Protótipo (Stitch) | **Canônico (este doc)** |
|---|---|---|
| Fonte display | Space Grotesk | **Michroma** (linhagem Eurostile, §4). Como é mais larga, reduzir headline para ~48–56px e manter tracking nos rótulos UPPERCASE |
| Ícones | Material Symbols **filled** | **Material Symbols Rounded** `FILL 0` (§6) — alinha à linguagem de curva/outline |
| Raio dos cartões | `xl` = 12px | **`--r-lg` 20px** para superfícies grandes do totem (§2) |
| Conteúdo do cartão | ícone + título centrados, **sem descrição** | Adotado como **variante "cartão de escolha do totem"** (centrada, sem descrição); a variante à esquerda com descrição de §7.1 fica para listas/painel |
| Pulso do pânico | `pulse-ready` (halo 3s) sem guarda | Aceito como pulso **único e sutil**, mas **deve respeitar `prefers-reduced-motion`** (§8) |
| Fundo | `surface #fff8f6` | `--paper #FBF9F6` no corpo, `--bg #FFFFFF` nos cartões (§3) |

> **Para o Stitch nas próximas telas:** reaproveitar exatamente estas três zonas (header/main/footer) e estes tokens; trocar Space Grotesk por Michroma e os ícones por Material Symbols Rounded na exportação final.

---

## 13. Resumo de tokens (copiar para o projeto)

```css
:root {
  /* cor */
  --ink:#17150F; --muted:#6F6862; --faint:#9A938B; --line:#E8E3DD;
  --paper:#FBF9F6; --bg:#FFFFFF;
  --rust:#C0392B; --rust-d:#8F2A17; --rust-soft:#F6E7E3;
  --crit:#C0392B; --warn:#D68A2E; --info:#9A938B; --ok:#2F7D4F;
  /* curva */
  --r-xs:8px; --r-sm:10px; --r-md:14px; --r-lg:20px; --r-xl:28px; --r-pill:999px;
  --radius:var(--r-md);
  /* espaço (base 4) */
  --space-xs:8px; --space-sm:12px; --space-md:16px; --space-lg:24px;
  --space-xl:32px; --space-xxl:48px; --space-totem:64px;
  /* tipografia */
  --font-display:"Michroma","Orbitron","Saira",system-ui,sans-serif;
  --font-display-bold:"Eurostile Extended","Orbitron","Michroma",sans-serif;
  --font-ui:"Inter",system-ui,sans-serif;
  /* elevação / movimento */
  --shadow:0 1px 2px rgba(20,15,5,.05), 0 10px 30px rgba(20,15,5,.06);
  --t-micro:120ms; --t-screen:240ms;
}
```

| Pilar | Decisão |
|---|---|
| **Cor** | Preto-tinta + laranja-ferrugem sobre papel quente; ferrugem só em ação/alerta (10%) |
| **Curva** | Cantos arredondados consistentes; ações primárias em cápsula; concentricidade |
| **Tipo** | Michroma (display, quadrada/larga, tracking generoso; só peso 400) + Inter para corpo; Eurostile Extended/Orbitron só p/ negrito robusto |
| **Movimento** | Calmo em repouso, claro na transição, inequívoco na emergência; respeita reduced-motion |
| **A11y** | AA, alvos ≥ 64px, cor + rótulo + ícone, voz como entrada alternativa |
