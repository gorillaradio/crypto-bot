# UI di completamento (Pipeline v2 — Fase 7) — Design Spec

**Data:** 2026-07-04
**Stato:** Draft (brainstorming completato, in attesa di review utente)
**Tipo:** Feature — UI/API di lettura, la meno invasiva delle 7 fasi (nessuna migrazione)
**Branch:** `pipeline-v2` (base per la review finale: `d5423d0`)

## Obiettivo

Pipeline v2 ha aggiunto molta macchina **dietro le quinte** (decisioni auditate, osservazioni
news, brain a due stadi col market brief) che oggi ha **poca o nessuna superficie in dashboard**.
La Fase 7 la rende **osservabile**: è l'ultimo lavoro UI prima del merge `pipeline-v2 → main`, e
serve a guardare in modo utile il paper-trading A/B v1-vs-v2.

Quattro fronti (dal censimento 3 lug + rinvio dalla Fase 6):

1. **Pannello decisioni archiviate** — l'endpoint `GET /agents/{id}/decisions` esiste già; manca solo
   il frontend.
2. **Feed osservazioni news** — manca l'endpoint e il frontend.
3. **Vista market brief** — rinviata esplicitamente dalla Fase 6; manca endpoint e frontend.
4. **P&L per posizione** — il calcolo esiste già nel brain (`PositionView`), ma l'API espone solo il
   costo; manca la colonna.

## Decisioni chiuse (dal brainstorming, 2026-07-04)

1. **Scope = tutti e 4 i fronti** in Fase 7 (osservabilità completa di pipeline-v2 prima del merge).
2. **Pannello decisioni = sintesi compatta.** Tabella: ora · badge `kind` (decision/reflection) ·
   badge `trigger` · azioni (da `parsed_output`) · modello · latenza · `parse_status`. **Niente
   prompt grezzi storici** — `DecisionRecordOut` li restituisce già, ma il pannello non li mostra; il
   `PromptPanel` esistente copre già i prompt del ciclo *corrente*. Backend **invariato**.
3. **P&L = backend autorevole, via leggera.** La cifra mostrata è la **stessa che vede il brain**
   (`PositionView.unrealized_pnl_pct`, formula in `context.py:71`), non un ricalcolo lato frontend.
   L'endpoint posizioni prende i prezzi **solo dei simboli in portafoglio** (non l'intero universo) →
   autorevole e a costo minimo.
4. **Brief = pannello per-agente filtrato.** Compare nel dettaglio agente, con gli `highlights`
   filtrati all'universo dell'agente (`regime` + `key_news` interi). Per un agente v1 (che non usa il
   brief) il pannello mostra il contesto con una nota "brain v1 non lo usa".
5. **Osservazioni = feed globale recente.** Ultime N osservazioni senza filtro universo: le news sono
   globali per natura e il filtro darebbe valore marginale in un feed da dashboard costando una
   chiamata Binance in più a ogni refresh. Il brain continua a consumarle filtrate per conto suo
   (invariato).
6. **`brain_version` esposto in `AgentOut` + badge** in dashboard — per *vedere* quali agenti sono
   v1/v2 (osservabilità dell'A/B) e per la nota del punto 4. Piccola aggiunta oltre il censimento,
   giustificata dallo scopo della fase.

## Non-obiettivi

- **Nessuna migrazione, nessuna nuova tabella/colonna DB.** Tutto è lettura su tabelle esistenti +
  schemi Pydantic + frontend. La **single Alembic head `49407193a9ac`** resta intatta.
- **Nessun filtro universo** sul feed osservazioni (globale recente).
- **Nessun P&L calcolato lato frontend** (autorevole dal backend).
- **Nessun prompt grezzo storico** nel pannello decisioni (il `PromptPanel` del ciclo corrente basta).
- **`build_agent_context` NON si tocca** — lo usa il monitor `preview.py`. Il P&L usa una via leggera
  dedicata (prezzi dei soli simboli detenuti), non `build_agent_context` (che scaricherebbe l'intero
  universo a ogni poll).
- **Nessuna cache Binance / snapshot condiviso** tra endpoint in questa fase (possibile follow-up; al
  scale attuale — pochi agenti, 1-2 viewer — il budget rate-limit regge).
- **Nessun indicatore "visto/non visto"** (watermark `last_seen_observation_id`) sul feed osservazioni.

## Architettura

Nessuna novità strutturale: endpoint di **lettura** in `app/api/routes.py` che rispecchiano quelli
esistenti (auth `require_viewer_or_admin`), nuovi schemi in `app/api/schemas.py`, nuovi pannelli
shadcn nel dettaglio agente di `frontend/src/App.tsx`, funzioni client in `frontend/src/api.ts`.

### Backend — endpoint

| Endpoint | Cosa cambia | Riuso / sorgente |
|---|---|---|
| `GET /agents/{id}/positions` | `PositionOut` +`last_price` +`unrealized_pnl_pct` +`market_value`; diventa **async** con `market=Depends(market_dep)`; **degrada** a cost-only se il market fallisce | prezzi via `market.get_universe_snapshot(simboli_detenuti)`; P&L con la formula di `context.py:71` |
| `GET /agents/{id}/observations` | **nuovo** → `list[ObservationOut]` | query recente su `Observation` (DB only, nessuna chiamata Binance) |
| `GET /agents/{id}/brief` | **nuovo** → `MarketBriefOut \| null` | `latest_valid_brief` + `filter_brief_for` + risoluzione universo (come il ciclo v2) |
| `GET /agents/{id}/decisions` | **backend invariato** (già esiste) | consumato dal frontend |
| `AgentOut` | +`brain_version` | `_agent_out` legge `agent.brain_version` |

### Frontend — pannelli (dettaglio agente in `App.tsx`)

| Pannello | Contenuto |
|---|---|
| Decisioni (nuovo) | tabella compatta: ora · badge kind · badge trigger · azioni (da `parsed_output`) · modello · latenza · parse_status |
| Osservazioni (nuovo) | lista news recenti: source · titolo→url · data · badge simboli |
| Market brief (nuovo) | `regime` · `highlights` (simbolo, segnale 🟢/🔴/⚪, nota) · `key_news`; nota "brain v1 non lo usa" se l'agente è v1 |
| Posizioni (modifica) | +colonna **P&L** (% e valore) alla `PositionsTable` esistente |
| Badge brain (modifica) | badge `v1`/`v2` per agente (header/lista) |

## Componenti & Interfacce

**Backend — nuovi schemi Pydantic (`app/api/schemas.py`)**

- `PositionOut` esteso: `+ last_price: Decimal | None`, `+ unrealized_pnl_pct: Decimal | None`,
  `+ market_value: Decimal | None` (nullable: se il prezzo non è disponibile la tabella degrada a
  cost-only). `cost_basis` resta.
- `ObservationOut{ source: str, title: str, url: str | None, published_at: datetime,
  symbols: list[str] }` — mirror di riga `Observation` (`symbols` da `symbols_json`).
- `MarketBriefOut{ regime: str, highlights: list[HighlightOut], key_news: list[str],
  as_of: datetime | None }`, `HighlightOut{ symbol: str, snapshot: str, signal: str, note: str }` —
  mirror di `MarketBriefView`/`HighlightView` (`context.py:37-50`).
- `AgentOut` esteso: `+ brain_version: str`.

**Backend — endpoint (`app/api/routes.py`)**

- `get_positions` → `async`, `market=Depends(market_dep)`. Legge le `Position` (DB), estrae i simboli
  detenuti, `snap = await market.get_universe_snapshot(held_symbols)` (una `/ticker/24hr`), per ogni
  posizione: `last_price` dallo snapshot, `unrealized_pnl_pct = (last-avg)/avg*100` (identica a
  `context.py:71`, `0` se `avg==0`), `market_value = quantity*last`. Simbolo assente dallo snapshot
  (delistato) → campi P&L `None`. **Market fail → degrada a cost-only** (`None` sui campi P&L), non
  502: le posizioni sono un pannello centrale, non deve sparire la tabella.
- `get_observations` → query su `Observation` `order_by(published_at desc, id desc) limit 100`, map a
  `ObservationOut`. Nessuna dipendenza market.
- `get_brief` → `async`, `market=Depends(market_dep)`. Risolve i simboli dell'universo dell'agente
  **con la stessa chiamata del ciclo decisionale v2** (vedi nota *base/USDT* sotto), `row =
  latest_valid_brief(session)`; se `None` → ritorna `null` (200); altrimenti
  `filter_brief_for(row, universe_symbols)` → `MarketBriefView` → `MarketBriefOut`. Market fail →
  502 (come `get_prompt`): il brief è secondario, il frontend mostra stato d'errore.
- `_agent_out` → aggiunge `brain_version=agent.brain_version`.

**Frontend (`frontend/src/`)**

- `api.ts`: nuove `getDecisions(id)`, `getObservations(id)`, `getBrief(id)` (fetch wrapper `get<T>`
  esistente); tipo `Position` += `last_price`/`unrealized_pnl_pct`/`market_value`; tipo `Agent` +=
  `brain_version`.
- `components/DecisionsPanel.tsx`, `components/ObservationsFeed.tsx`, `components/MarketBriefPanel.tsx`
  (nuovi), montati nel flusso del dettaglio agente in `App.tsx`. Pattern di fetch = `PromptPanel.tsx`
  (`useEffect` + flag `alive` + stati loading/error).
- `components/PositionsTable.tsx`: +colonna P&L (% colorato + valore); fallback "—" se `last_price`
  è `None`.
- Badge `brain_version` accanto al nome agente (riusa il primitive Badge shadcn già in uso).

## Data flow (per-request, sola lettura)

- **positions:** `Position` (DB) + **1** `/ticker/24hr` Binance (prezzi dei soli detenuti) → P&L.
- **brief:** risoluzione universo (**1** `/ticker/24hr`) + `latest_valid_brief` (DB) → filtro → view.
- **observations:** **solo DB**.
- **decisions:** **solo DB** (endpoint invariato).

Polling: le posizioni sono già pollate ~15s; brief/osservazioni possono pollare più lento (il brief
cambia per ciclo). Al scale attuale il budget Binance (1200 peso/min; `/ticker/24hr` full-market =
peso 40) assorbe le poche chiamate.

## Error handling & resilience

- **positions:** market down o simbolo delistato → **degrada a cost-only** (campi P&L `None`), la
  tabella resta. Nessun 502.
- **brief:** nessun brief valido → `null` (200, il frontend mostra "nessun brief ancora"); market
  down (risoluzione universo) → 502 (pannello secondario, stato d'errore lato UI).
- **observations:** sola lettura DB; nessun percorso d'errore esterno.
- **Datetime UTC-aware:** `published_at`/`created_at` esposti tz-aware; gli `ORDER BY … desc` sono
  ordinamenti SQL (non confronti Python), sicuri su SQLite — disciplina di Fase 4/5.
- **Auth:** tutti i nuovi endpoint dietro `require_viewer_or_admin`, come gli altri read.

## Testing

- **positions/P&L:** stub market con prezzi noti → `unrealized_pnl_pct`/`market_value` corretti;
  simbolo assente dallo snapshot → campi P&L `None`; **market che solleva → degrado cost-only** (non
  502).
- **observations:** ritorna le più recenti, forma `ObservationOut`, `limit`, ordine DESC.
- **brief:** con un `MarketBrief` persistito + stub `get_top_symbols` → `highlights` filtrati
  all'universo, `regime`/`key_news` interi; nessun brief valido → `null`.
- **AgentOut:** `brain_version` presente e corretto (v1/v2).
- **decisions:** backend invariato (test endpoint esistente resta verde); copertura frontend nel
  pannello.
- **Frontend:** i nuovi pannelli testati secondo l'infra dei 41 test verdi attuali (setup esatto —
  vitest/RTL — da confermare nel piano).
- Tutti i test backend usano `Base.metadata.create_all` e **stub del market** (nessuna Binance reale);
  **nessuna migrazione**.

## Migrazione & rollout

- **Zero migrazioni.** Solo aggiunte Pydantic + endpoint di lettura + frontend. La catena Alembic
  delle Fasi 1-6 è invariata, **single head `49407193a9ac`**.
- **Additivo e retrocompatibile:** i campi nuovi di `PositionOut`/`AgentOut` sono aggiuntivi; nessun
  client esistente si rompe. Il merge finale `pipeline-v2 → main` non cambia lato schema.

## Note latenti da rispettare

- **`build_agent_context` intatto** (usato dal monitor `preview.py`): il P&L usa una via leggera
  dedicata (`get_universe_snapshot` sui soli detenuti), non `build_agent_context`.
- **Coupling base/USDT** (`feeds/query.py`, `filter_brief_for`): l'endpoint brief deve risolvere i
  simboli dell'universo **nella stessa forma** che il ciclo decisionale v2 passa a `filter_brief_for`
  (base vs pair `…USDT`), altrimenti il filtro scarta tutto. Va **confermato nel piano** leggendo
  `build_agent_context` (percorso v2) — non assumere.
- **Binance senza cache:** `BinanceClient` apre un client httpx per chiamata (nessuna cache). Gli
  endpoint market-touching (positions, brief) fanno una `/ticker/24hr` per request. Accettabile ora;
  cache/snapshot condiviso = follow-up se il numero di agenti/viewer cresce.
- **Watermark news loss-free (Fase 5):** invariato; nessun endpoint di questa fase tocca
  `last_seen_observation_id`.

## Dependencies

- Fase 1 (`DecisionRecord` + endpoint decisions) — pannello decisioni.
- Fase 4 (`Observation`) — feed osservazioni.
- Fase 6 (`MarketBrief` + `latest_valid_brief`/`filter_brief_for`) — vista brief; `Agent.brain_version`
  — badge e nota v1.
- **Nessuna nuova dipendenza di libreria** (backend o frontend).

## Aperti per il piano (da pinnare leggendo il codice, non indovinare)

- Forma esatta di `parsed_output` (schema `Decision`/azioni) per il rendering compatto delle azioni.
- Forma dei simboli in `filter_brief_for` (base vs `…USDT`) e la funzione di risoluzione universo che
  il ciclo v2 usa — l'endpoint brief deve combaciare.
- Setup esatto dei test frontend (vitest/RTL) su cui agganciare i nuovi pannelli.
