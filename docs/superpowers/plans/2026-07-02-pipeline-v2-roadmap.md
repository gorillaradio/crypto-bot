# Pipeline v2 — Roadmap di intervento

> Documento master. Ogni fase avrà il proprio piano di implementazione dettagliato
> (TDD, task bite-sized) in `docs/superpowers/plans/`, scritto al momento di iniziarla.
> Le decisioni di design sono state prese col committente il 2026-07-02 e sono
> annotate come **Deciso** in ogni fase.

**Obiettivo:** trasformare la pipeline decisionale da "un prompt a orologio con una
tabella prezzi" a una pipeline a stadi guidata dall'informazione, misurabile, con
audit completo delle decisioni.

**Principio d'ordine: misura prima di cambiare.** Le fasi 1–2 costruiscono la
strumentazione (audit + benchmark). Solo dopo si tocca il cervello: così ogni
modifica successiva (memoria, news, brain a due stadi, trigger) ha un impatto
misurabile contro una baseline, invece che valutato a impressioni.

---

## Fase 1 — Decision record

**Problema che risolve:** la risposta grezza dell'LLM viene buttata via
(`brain/__init__.py`); impossibile fare replay, debugging o confronto tra modelli.

**Deliverable:**
- Tabella `DecisionRecord`: agent_id, cycle_id, trigger (schedule/breach/…),
  system prompt, user prompt, risposta grezza, decision parsata, esito parse
  (ok / repaired / failed), modello+provider, latenza, timestamp.
- Scrittura del record dentro `decide()` / `_run_decision_llm` (anche per le
  reflection).
- Endpoint read-only `GET /api/agents/{id}/decisions` per la dashboard.

**Dipendenze:** nessuna. Sinergia con il prompt-monitor (branch corrente): riusa
l'estrazione di `build_agent_context`.

**Deciso:** si tiene tutto (paper trading, volumi bassi, nessuna retention policy
in v1); si registrano anche le chiamate di reflection.

---

## Fase 2 — Evaluation harness

**Problema che risolve:** nessun benchmark → impossibile sapere se l'edge esiste
(la domanda della North Star).

**Deliverable:**
- Portafogli fantasma per agente: HODL BTC, equal-weight universo e random trader
  (a costo zero: snapshot calcolati con i prezzi già scaricati dall'heartbeat).
- Scoring per decisione: job che rivaluta ogni `DecisionRecord` dopo finestre
  fisse — cosa ha comprato/venduto/tenuto vs come è andata.
- Metriche di confronto: equity, hit-rate, max drawdown, Sharpe ratio.
- Dashboard: equity dell'agente sovrapposta ai benchmark; hit-rate e metriche
  per agente e per modello.

**Dipendenze:** Fase 1 (lo scoring per decisione legge i DecisionRecord).
I benchmark di portafoglio invece non dipendono da nulla.

**Deciso:** finestre di scoring 24h e 7g; eval completa fin da subito — anche
random trader (isola la fortuna dalla skill) e metriche di rischio
(max drawdown, Sharpe).

---

## Fase 3 — Memoria a journal

**Problema che risolve:** la memoria viene riscritta integralmente dall'LLM a ogni
reflection (rischio perdita/deriva) e si aggiorna solo alla chiusura di un trade.

**Deliverable:**
- `AgentMemory` diventa journal append-only: la reflection *aggiunge* voci
  (timestampate, con sezione) invece di riscrivere tutto.
- Distillazione periodica: quando una sezione supera il cap, un passaggio LLM
  la compatta preservando le voci più recenti/rilevanti.
- Il prompt continua a ricevere la vista compatta (nessun cambiamento di formato
  lato decisione).

**Dipendenze:** nessuna tecnica; va dopo la Fase 2 così l'effetto sulla qualità
decisionale è misurabile.

**Deciso:** distillazione per recency (criteri di "utilità" eventualmente in v2);
reflection resta solo sui trade chiusi, niente reflection su cicli HOLD in v1.

---

## Fase 4 — Ingestion news

**Problema che risolve:** la tesi del progetto è "edge dalla sintesi
d'informazione" ma l'LLM riceve solo prezzi + variazione 24h.

**Deliverable:**
- Tabella `Observation`: source, tipo (news/market_signal), symbols correlati,
  contenuto normalizzato, timestamp, dedup hash.
- Primo adapter di feed (una fonte sola per v1) + job di polling nello scheduler.
- Le osservazioni recenti entrano nel prompt di decisione (sezione nuova nel
  contesto, con cap di token).

**Dipendenze:** nessuna tecnica. È il "prossimo step" già previsto dalla roadmap
di prodotto.

**Deciso:** vincolo committente — **solo soluzioni gratuite** (RSS di testate o
API con free tier adeguato); la scelta puntuale del provider si fa con una
ricerca comparativa al momento di dettagliare questa fase. Filtro di rilevanza
pre-LLM = match sui simboli dell'universo; polling ~15 minuti.

---

## Fase 5 — Trigger engine

**Problema che risolve:** cadenza a orologio (1h) invece che a informazione;
oggi l'unico risveglio evento-driven è il breach di soglia.

**Perché prima del brain a due stadi:** riusa il meccanismo di wake già esistente
e collaudato (breach → `wake_reason`), quindi è a basso rischio e realizza subito
la tesi "si decide quando succede qualcosa"; il brain a due stadi è il cambiamento
più invasivo e va per ultimo, con tutta la strumentazione attiva.

**Deliverable:**
- Generalizzazione del meccanismo di wake già esistente (breach → `wake_reason`)
  a più tipi di evento: news rilevante per un simbolo in portafoglio, spike di
  volatilità/volume, breach (esistente).
- Budget di risvegli per agente per controllare i costi LLM.
- Il timer orario resta come fallback, eventualmente allungato.

**Dipendenze:** Fase 4 (i trigger news leggono le Observation); il pattern
edge-triggered/armed esistente in `strategy.py` + heartbeat si riusa.

**Deciso:** budget risvegli configurabile, default 2/ora per agente; "news
rilevante" senza chiamate LLM (match per simbolo in portafoglio); timer orario
mantenuto come fallback.

**Deciso in dettaglio (2026-07-03, brainstorming Fase 5):**
- Trigger v1: `schedule` (timer 1h, esente dal budget), `breach` (esistente,
  **esente** — l'allarme di rischio sveglia sempre), `movement` e `news` (nuovi,
  contano nel budget).
- **movement** = |mossa su finestra ~1h| ≥ 5% (configurabili `movement_threshold`,
  `movement_window_hours`) su una moneta **in portafoglio**, misurata via klines;
  edge-trigger arma/disarma gemello del breach (nuova colonna `positions.move_armed`).
- **news** = prima osservazione nuova (`Observation.id` oltre il segnalibro) che
  nomina una moneta in portafoglio; edge-trigger via segnalibro per-agente (nuova
  colonna `agents.last_seen_observation_id`), che avanza dopo ogni decisione.
- **budget**: max 2 sveglie `news`+`movement`/ora, conteggio rolling sui cicli
  `DecisionRecord` (nessuna tabella nuova); esaurito ⇒ evento **rimandato, non buttato**.
- Orchestrazione dentro `run_heartbeat`: una sola decisione per battito, priorità
  `breach > movement > news`; `trigger` filato esplicito fino a `DecisionRecord`.
- Chiusura nota Fase 4: commento UTC-aware su `published_at` in `models.py`.
- **Non-goal v1**: spike di volume (serve baseline storica → rimandato),
  movimento/news sull'universo (solo portafoglio), rilevanza via LLM.

---

## Fase 6 — Brain a due stadi

**Problema che risolve:** un solo prompt monolitico fa analisi + gestione
portafoglio + risk in one-shot; il costo cresce linearmente con gli agenti
(ognuno ri-analizza lo stesso mercato).

**Deliverable:**
- Stadio *analyst*: una chiamata condivisa per ciclo che sintetizza universo +
  osservazioni in un "market brief" compatto (persistito, riusato da tutti gli
  agenti del ciclo).
- Stadio *trader*: la decisione per-agente riceve brief + portafoglio + memoria
  + istruzioni (prompt molto più corto dell'attuale).
- Entrambe le chiamate registrate come DecisionRecord (Fase 1) → confronto
  A/B misurabile (Fase 2) tra brain v1 e v2.

**Dipendenze:** Fase 4 (senza osservazioni, l'analyst non ha nulla da
sintetizzare oltre ai prezzi); Fasi 1–2 per misurare che sia un miglioramento;
Fase 5 (i trigger definiscono *quando* il brain gira).

**Deciso:** analyst con modello capace fisso (unico brief di qualità, costo per
ciclo indipendente dal numero di agenti — il confronto tra modelli misura lo
stadio trader); brief strutturato, uno globale su TOP_100 poi filtrato per
l'universo dell'agente.

---

## Riepilogo dipendenze

```
Fase 1 (decision record) ──→ Fase 2 (eval) ──→ [baseline misurabile]
Fase 3 (memoria)  — indipendente, dopo la 2 per misurarne l'effetto
Fase 4 (news) ──→ Fase 5 (trigger engine) ──→ Fase 6 (brain 2 stadi)
```

Ogni fase è software funzionante e testabile da sola; la pipeline attuale resta
operativa durante tutto il percorso (nessuna fase è un big-bang rewrite).

---

## Tracker

> Convenzione di lavoro: **una sessione a contesto pulito per fase**. Ogni sessione
> parte da questo documento, scrive il piano TDD della fase con la skill
> `superpowers:writing-plans`, lo esegue subagent-driven, poi aggiorna questa
> tabella (stato + link) prima di chiudere.

| Fase | Stato | Piano | Note |
|------|-------|-------|------|
| 1 — Decision record | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-02-decision-record](2026-07-02-decision-record.md) | 7 commit, 130 test verdi, review opus ready-to-merge |
| 2 — Evaluation harness | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-03-evaluation-harness](2026-07-03-evaluation-harness.md) | 15 task (13 piano + 2 finaliz.), 18 commit, 173 backend + 39 frontend verdi, final review opus ready-to-merge |
| 3 — Memoria a journal | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-03-memoria-journal](2026-07-03-memoria-journal.md) | 10 task, 10 commit, 188 backend + 41 frontend verdi, 2 migration (create+backfill, drop), final review opus ready-to-merge |
| 4 — Ingestion news | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-03-ingestion-news](2026-07-03-ingestion-news.md) | 9 task, 9 commit, crypto-native RSS (CoinDesk/Cointelegraph/CryptoSlate), Observation table + poll tick + sezione prompt, feedparser dep; 213 backend + 41 frontend verdi; final review opus ready-to-merge |
| 5 — Trigger engine | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-03-trigger-engine](2026-07-03-trigger-engine.md) | 8 task + fix watermark loss-free + finaliz.; 10 commit; news+movimento(klines)+budget su `run_heartbeat`; 239 backend + 41 frontend verdi; single Alembic head `940cbbd9c670`; final OPUS review ready-to-merge (1 Important fixato) |
| 6 — Brain a due stadi | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-04-brain-due-stadi](2026-07-04-brain-due-stadi.md) | 11 task + fix (test discriminante T5 + warning asyncio) + finaliz.; 13 commit (`c49e937..51e4520`); analyst+trader dietro flag `brain_version` (v1 baseline **byte-identico**), tabella `MarketBrief`, brief riusato per ciclo + cold-start bootstrap; design [specs/2026-07-04-brain-due-stadi-design](../specs/2026-07-04-brain-due-stadi-design.md); 274 backend + 41 frontend verdi; smoke migrazione up/down ok, single Alembic head `49407193a9ac`; final OPUS review **ready-to-merge** (0 Critical/Important; 1 Important plan-mandata = duplicazione memory-block, accettata per la finestra A/B, follow-up post-ritiro v1); **vista market brief → Fase 7** (deciso 4 lug) |
| 7 — UI di completamento | ✅ fatta su `pipeline-v2` (non in main) | [2026-07-04-ui-completamento](2026-07-04-ui-completamento.md) | 9 task (4 backend + 5 frontend) + finaliz. + 2 minor post-review; 10 commit (`3258b7e..af4572e`); endpoint di lettura (P&L per posizione **autorevole** via leggera, feed **osservazioni** globale, **market brief** per-agente filtrato) + pannello **decisioni** archiviate + `brain_version` esposto/badge; **zero migrazioni** (single head `49407193a9ac` invariata); design [specs/2026-07-04-ui-completamento-design](../specs/2026-07-04-ui-completamento-design.md); 284 backend + 51 frontend verdi, `npm run build` clean; final OPUS review **ready-to-merge** (0 Critical/Important; 3 Minor cosmetici, 2 fixati) |

Stati: ⬜ da pianificare → 📝 piano scritto → 🔨 in esecuzione → ✅ mergiata.

### Chiusura branch (dopo Fase 6, prima o insieme alla Fase 7)

Il merge `pipeline-v2` → `main` **auto-deploya in produzione** tutto in un colpo.
Da sapere (censimento 3 lug, a fasi 1–5 complete):
- catena di migrazioni Alembic nuove, tra cui **backfill `agent_memory` →
  `memory_entries` seguito dal drop di `agent_memory`** (irreversibile in prod:
  il backfill deve girare prima del drop — l'ordine della catena lo garantisce,
  non fare interventi manuali);
- dipendenza nuova backend: `feedparser` (pura Python, nessun requisito di sistema);
- 2 env var opzionali con default 900s: `SCORING_SECONDS`, `NEWS_POLL_SECONDS`
  (da aggiungere a `/opt/crypto-bot/.env` solo se si vuole un tuning diverso).

**Resta backlog, NON è completamento** (feature nuove con decisioni di prodotto
proprie, da prioritizzare dopo qualche settimana di eval): notifiche
Telegram/WhatsApp; benchmark esterni S&P/NVDA (serve fonte dati non-Binance);
curatela dinamica dell'universo.
