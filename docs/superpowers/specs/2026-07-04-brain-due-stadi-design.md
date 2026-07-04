# Brain a due stadi (Pipeline v2 — Fase 6) — Design Spec

**Data:** 2026-07-04
**Stato:** Draft (brainstorming completato, in attesa di review utente)
**Tipo:** Feature — pipeline decisionale, la più invasiva delle 6 fasi
**Branch:** `pipeline-v2` (base per la review finale: `d5423d0`)

## Obiettivo

Spezzare il **prompt monolitico** attuale (un'unica chiamata LLM per agente fa analisi di
mercato + gestione portafoglio + risk in one-shot) in **due stadi**:

- **analyst** — UNA chiamata condivisa per ciclo che sintetizza universo + osservazioni news
  in un **market brief** compatto e strutturato, persistito e riusato da tutti gli agenti del
  ciclo. Il costo di questa sintesi diventa **indipendente dal numero di agenti** (oggi ogni
  agente ri-analizza lo stesso mercato → costo lineare col numero di agenti).
- **trader** — la decisione per-agente riceve brief + portafoglio + memoria + istruzioni. Prompt
  molto più corto dell'attuale.

I due brain (v1 monolitico, v2 due-stadi) **coesistono** dietro un flag per-agente, così il
confronto A/B è misurabile con lo scoring di Fase 2 sullo stesso mercato e nella stessa finestra.

## Decisioni chiuse (dal brainstorming, 2026-07-04)

1. **analyst ↔ sveglie fuori ciclo = riuso puro.** Il brief è un artefatto condiviso per-ciclo;
   le sveglie di Fase 5 (breach/movement/news) lo **riusano** — non rifanno girare l'analyst. La
   freschezza al momento della sveglia la porta il *trigger*: il `wake_reason` già nomina l'evento
   preciso, e il trader vede comunque le sue posizioni a prezzo vivo. Nessun TTL in v1 (rimane come
   knob per v2 se la staleness si rivela un problema).
2. **Cadenza analyst** (conseguenza di #1): una chiamata per **ciclo orario** (`_decision_tick`),
   **mai su sveglia**, e **solo se esiste almeno un agente v2** (tutti v1 ⇒ l'analyst non gira, zero
   costo).
3. **Schema del brief = shortlist + regime** (non copertura piena delle 100 coin). L'analyst
   estrae il segnale: un blocco di *regime di mercato* globale + solo le coin che contano
   (movers, news, opportunità/rischi). Compatto, con cap di token.
4. **Cosa vede il trader = solo brief.** Brief filtrato + posizioni (prezzo vivo) + memoria +
   istruzioni + `wake_reason`. **Niente tabella grezza dell'universo.** Conseguenza: il trader può
   **aprire** posizioni solo sulle coin evidenziate nel brief (le altre non le conosce); le
   posizioni **detenute** le gestisce comunque a prezzo vivo.
5. **A/B = flag per-agente `brain_version` (v1|v2)**, default `v1`. Path v1 identico a oggi (è la
   baseline, non va disturbata). Confronto via lo scoring per-decisione di Fase 2, spaccato per
   versione.
6. **Persistenza = tabella dedicata `MarketBrief`** (non `DecisionRecord`). Fa triplo lavoro:
   persistenza/riuso del brief, audit della chiamata analyst (stessi campi di Fase 1), sorgente per
   la futura vista brief in dashboard.
7. **Modello analyst = deepseek v4 pro** (fisso, condiviso), via knob `analyst_model`. Il trader
   resta sul **modello dell'agente** (la variabile dell'A/B). Reflection e distillation **invariate**
   (restano sul modello dell'agente — nessun tiering per-task extra in questa fase).

## Non-obiettivi

- **Nessun TTL / refresh del brief su sveglia** in v1 (riuso puro; TTL è un knob per dopo).
- **Nessun tiering per-task** oltre l'analyst (reflection/distillation restano sul modello
  dell'agente).
- **Nessuna copertura piena** dell'universo nel brief (solo shortlist).
- **Nessuna tabella grezza dell'universo** nel prompt del trader.
- **Nessun cambiamento al brain v1**: il monolite resta byte-identico (baseline dell'A/B).
- **Nessun avanzamento del watermark news a ogni decisione** — la Fase 5 lo ha reso *loss-free*
  (avanza solo sulla sveglia news, all'obs scatenante). Non reintrodurre l'avanzamento generico.

## Architettura

Due stadi, orchestrati nei due tick già esistenti:

```
_decision_tick (orario, condiviso)          run_heartbeat (battito 5 min, per-agente)
  │                                            │
  ├─ se ∃ agente v2: run_analyst() ──┐         └─ sveglia breach/movement/news →
  │     → persiste MarketBrief       │              trader v2 riusa l'ultimo brief valido
  │                                  │              (nessun analyst qui)
  └─ per ogni agente running:        │
       brain_version == v1 → evaluate() (monolite, invariato)
       brain_version == v2 → trader() su brief filtrato ◄──┘
```

- **analyst** legge la snapshot **TOP_100** + le osservazioni news recenti, produce il brief
  globale, lo persiste in `MarketBrief`. Gira una volta per ciclo orario (gate su "∃ agente v2").
- **trader** (v2) costruisce un context corto: **ultimo brief valido filtrato** per il suo universo
  + posizioni live + memoria + istruzioni + `wake_reason`. Chiama il modello dell'agente.
- **v1** resta sul percorso attuale (`build_agent_context` → `evaluate` → `render_prompt`),
  invariato.

### Riuso e cold start

- Riuso: ogni decisione v2 legge **l'ultimo `MarketBrief` valido** (`created_at` desc, `parse_status`
  ok). Le sveglie riusano quello del ciclo corrente/precedente.
- **Cold start:** se una decisione v2 serve un brief e non ne esiste ancora nessuno (sistema appena
  avviato, prima del primo ciclo orario), l'analyst gira **una volta** per bootstrap, poi si riusa.
  Unica eccezione al "mai su sveglia" — senza, con "solo brief" il trader sarebbe cieco.

## Componenti & Interfacce

**Nuovi file**
- `backend/app/brain/analyst_schema.py` — schema Pydantic del brief: `MarketBriefSchema{regime: str,
  highlights: list[Highlight], key_news: list[str]}`, `Highlight{symbol, snapshot, signal, note}`
  con `signal ∈ {bullish, bearish, neutral}` (nome `…Schema` per distinguerlo dal modello DB
  `MarketBrief`, come `Decision` vs `DecisionRecord`). Più un `AnalystResult` (gemello di
  `DecisionResult`: brief parsato + `system`/`user`/`raw`/`parse_status`/`latency_ms`).
- `backend/app/brain/analyst.py` — `run_analyst(analyst_ctx, adapter) -> AnalystResult`
  (stessa forma di `evaluate`: chiama, prova a parsare, retry-una-volta, esito). E il render del
  prompt analyst (system "sei un analista di mercato, produci SOLO questo JSON…" + user: tabella
  TOP_100 + news recenti). Le osservazioni riusano `recent_observations_for` sui simboli TOP_100 —
  la funzione include **già** le news market-wide (symbols vuoto) per alimentare `key_news`.
- `backend/app/brain/trader_prompt.py` (o funzione in `prompt.py`) — `render_trader_prompt(ctx) ->
  (system, user)`: brief filtrato + posizioni + memoria + istruzioni + `wake_reason`, **senza** la
  tabella universo. La forma va **congelata** con un test (come fatto per il monolite in Fasi 3-4).

**Modifiche**
- `backend/app/brain/context.py` — `DecisionContext` guadagna un campo opzionale `brief:
  MarketBriefView | None`. `build_context(...)` lo accetta (default None → path v1 invariato).
- `backend/app/agents/runtime.py`:
  - `build_agent_context(...)` per un agente v2 carica **l'ultimo brief valido**, ne **filtra** gli
    `highlights` ai simboli dell'universo dell'agente (già disponibili come `symbols`), e lo mette in
    `ctx.brief`. `regime`+`key_news` passano interi.
  - `_run_decision_llm` seleziona il brain in base a `agent.brain_version`: v1 → `evaluate`
    (monolite); v2 → **riusa la macchina di `evaluate`** (chiama/parsa/retry-una-volta) con
    `render_trader_prompt` al posto di `render_prompt`. **Il guardrail BUY usa la lista `symbols`**
    (già passata al runtime), non più `{c.symbol for c in ctx.universe}` — così regge anche quando
    l'universo non è nel prompt.
  - Helper `get_or_bootstrap_brief(session, market)` per il cold start.
- `backend/app/scheduler/jobs.py` — `_decision_tick` in preambolo: se ∃ agente v2 running, chiama
  `run_analyst` una volta e persiste il `MarketBrief`, prima del loop per-agente.
- `backend/app/db/models.py`:
  - `Agent.brain_version: Mapped[str]` `String(10)` default `"v1"`.
  - Nuovo modello `MarketBrief` (sotto).
- `backend/app/core/config.py` — nuovi knob:
  - `analyst_model: str = "deepseek/deepseek-v4-pro"` (slug OpenRouter **da verificare al wiring**).
  - `brief_max_highlights: int = 15` (cap della shortlist).

**Tabella `MarketBrief`**
- identità: `id`, `cycle_id` (String(32)), `created_at` (DateTime tz-aware, indicizzato — ancora di
  freschezza).
- payload: `parsed_brief` (String, JSON del brief; NULL se il parse fallisce).
- audit (parità Fase 1): `system_prompt`, `user_prompt`, `raw_response`, `parse_status`,
  `model_provider`, `model_name`, `latency_ms`.

**Migrazione** (una sola, mirror a mano del modello)
- Aggiunge `agents.brain_version` (default `"v1"`) + crea `market_briefs`.
- Down: drop `market_briefs` + drop colonna. Smoke-test up/down su SQLite usa-e-getta in
  finalizzazione. Deve restare **single Alembic head**.

## Data flow

**Ciclo orario, agente v2:** `_decision_tick` → (∃ v2) `run_analyst` legge TOP_100 + news →
`MarketBrief` persistito → per l'agente v2: `build_agent_context` carica+filtra l'ultimo brief →
`render_trader_prompt` → chiamata al modello dell'agente → azioni eseguite → `DecisionRecord`
(kind=`decision`, trigger=`schedule`).

**Ciclo orario, agente v1:** invariato (`evaluate`/`render_prompt`, monolite).

**Sveglia fuori ciclo, agente v2:** `run_heartbeat` rileva breach/movement/news → trader v2 **riusa**
l'ultimo brief valido (nessun analyst) + `wake_reason` col trigger preciso → `DecisionRecord`
(trigger=`breach|movement|news`). Watermark news invariato (loss-free di Fase 5).

**Cold start:** decisione v2, nessun brief ⇒ `run_analyst` una volta → persiste → usa.

## Audit e A/B (Fase 1 / Fase 2)

- La **chiamata analyst** è audita in `MarketBrief` (stessi campi di Fase 1), **non** in
  `DecisionRecord`: è condivisa/per-ciclo, mentre `DecisionRecord` è per-agente e viene *scorato*.
  Questo realizza l'intento del roadmap ("entrambe le chiamate registrate") mantenendo
  `DecisionRecord` pulito e scorabile.
- La **decisione trader** (v2) e la **decisione monolite** (v1) sono entrambe `DecisionRecord`
  `kind=decision` con azioni → entrambe scorate da Fase 2. L'A/B è per-agente via `brain_version`.

## Error handling & resilience

- **Parse del brief fallito:** `run_analyst` segue il pattern di `evaluate` (retry una volta, poi
  `parse_status=failed`, `parsed_brief=NULL`). Un brief fallito **non** diventa l'"ultimo valido":
  il trader riusa l'ultimo brief *con parse ok*, o fa cold-start bootstrap se non ce n'è nessuno.
- **Analyst in errore/rete:** isolato — non deve rompere il ciclo. Se l'analyst non produce un brief
  valido e non ne esiste uno precedente, il trader v2 di quel giro degrada (brief assente →
  documentato); gli agenti v1 non sono toccati.
- **Datetime UTC-aware:** ogni ordinamento/confronto su `created_at`/`published_at` in Python via
  `_as_utc` (mai in SQL su SQLite) — disciplina di Fase 4/5.

## Testing

- `run_analyst`: parse ok / repaired / failed; render del prompt analyst congelato.
- `render_trader_prompt`: forma congelata; **niente tabella universo**; brief presente e filtrato;
  `wake_reason` incluso.
- Persistenza/riuso: `latest_valid_brief` ritorna il più recente con parse ok, salta i failed.
- Filtro: `highlights` ridotti ai simboli dell'universo; `regime`+`key_news` interi.
- Cold start: nessun brief ⇒ analyst gira una volta.
- Selezione brain: v1 → monolite (regressione byte-identica del prompt v1); v2 → trader.
- Guardrail BUY: regge su `symbols` anche senza universo nel prompt (rifiuta coin fuori universo).
- Orchestrazione: analyst gira una volta/ciclo e **solo** se ∃ v2; le sveglie non lo fanno girare.
- A/B: sia v1 sia v2 scrivono `DecisionRecord` scorabili; l'analyst scrive `MarketBrief`.
- Tutti i test usano `Base.metadata.create_all`, mai le migrazioni.

## Migrazione & rollout

- Additivo e retrocompatibile: `brain_version` default `"v1"` ⇒ **gli agenti esistenti non cambiano
  comportamento**; i v2 si creano apposta. `MarketBrief` è tabella nuova.
- Il merge finale `pipeline-v2 → main` auto-deploya: questa migrazione si aggiunge alla catena delle
  Fasi 1-5 (mantenere single head).

## Note latenti da rispettare (da Fase 5)

- **Watermark news loss-free:** non reintrodurre l'avanzamento di `last_seen_observation_id` a ogni
  decisione. Resta come in Fase 5 (solo sulla sveglia news, all'obs scatenante, in `run_heartbeat`).
- **`_base`/USDT coupling** (`feeds/query.py`) invariato: i chiamanti passano `USDT`.
- **UTC-aware** su ogni datetime (vedi Error handling).

## Scope: vista brief → Fase 7 (deciso 2026-07-04)

- **Vista del market brief in dashboard = rimandata alla Fase 7** (UI di completamento). La Fase 6 è
  **backend-pura**. La tabella `MarketBrief` salva già tutto ciò che servirà alla UI (campi di audit
  + brief parsato), quindi la Fase 7 la costruisce senza rilavorare il backend.

## Dependencies

- Fase 4 (Observation) — l'analyst legge le news via `recent_observations_for`.
- Fasi 1-2 (DecisionRecord + scoring) — per misurare l'A/B.
- Fase 5 (trigger engine) — le sveglie definiscono *quando* il trader v2 gira fuori ciclo.
- Nessuna nuova dipendenza di libreria (OpenRouter già in uso via `make_adapter`).
