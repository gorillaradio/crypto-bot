# Ticket 25 Open Lifecycle Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare le posizioni aperte su un ledger append-only con identità stabile del lifecycle, attraversando persistenza, runtime, API e dashboard senza modificare le decisioni di trading.

**Architecture:** Aggiungere `PositionLifecycle` come identità durevole, collegare `Position` e `Trade` tramite `lifecycle_id`, e registrare le valutazioni disponibili per BUY/SELL in `PositionEvaluation`. Le mutazioni di trade, valutazione e proiezioni avvengono in una singola transazione; un servizio contabile ricostruisce saldo e posizione dal ledger. Un endpoint additivo `/api/agents/{agent_id}/lifecycles/open` alimenta la tabella React esistente, mentre gli endpoint legacy restano disponibili.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest; React, TypeScript, Vitest, Testing Library.

## Global Constraints

- Non migrare, cancellare o reinterpretare dati paper-trading esistenti.
- Non modificare formule, sizing o regole decisionali BUY/SELL.
- Non implementare filtri closed/all, timeline, master-detail o mobile dei ticket #26–#30.
- Conservare gli endpoint e i payload legacy fino al ticket #32.
- Non leggere o modificare `.codex/config.toml`.

---

### Task 1: Persistenza canonica e migrazione additiva

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/1a2b3c4d5e6f_lifecycle_ledger.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `PositionLifecycle`, `PositionEvaluation`, `Position.lifecycle_id`, `Trade.lifecycle_id`, `Trade.cycle_id`.

- [ ] Scrivere test rossi per vincoli, identità e campi canonici.
- [ ] Eseguire il singolo file e verificare il fallimento per modelli mancanti.
- [ ] Aggiungere modelli e migrazione nullable/additiva, senza backfill o reset.
- [ ] Eseguire il singolo file e verificare il verde.

### Task 2: Ciclo contabile atomico e rebuild

**Files:**
- Modify: `backend/app/trading/engine.py`
- Create: `backend/app/trading/ledger.py`
- Test: `backend/tests/test_engine.py`
- Test: `backend/tests/test_ledger.py`

**Interfaces:**
- Produces: trade con lifecycle/cycle, lifecycle stabile tra incrementi e parziali, nuovo lifecycle dopo chiusura; `rebuild_agent_state(session, agent_id)` e `verify_agent_state(session, agent_id)`.

- [ ] Scrivere un test rosso per apertura, incremento, parziale, chiusura e seconda vita.
- [ ] Implementare la minima assegnazione lifecycle e mantenere invariati calcoli e guardrail esistenti.
- [ ] Scrivere un test rosso che prova rollback completo dopo un errore prima del commit.
- [ ] Rendere trade, valutazione disponibile, evento e proiezioni una singola unità atomica.
- [ ] Scrivere test rossi di rebuild per quantità, costo medio, realizzato e cash netto fee.
- [ ] Implementare rebuild/verify esclusivamente dal capitale iniziale e dai trade canonici.
- [ ] Eseguire i test engine/ledger fino al verde.

### Task 3: Endpoint additivo delle aperte

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces: `GET /api/agents/{agent_id}/lifecycles/open` con lifecycle, cycle, stato, tempi, quantità, prezzi, fee, esposizione e risultato netto.

- [ ] Scrivere test API rossi sul percorso contabile completo e sull'assenza di dipendenze da `Event.payload.position_summary`.
- [ ] Scrivere test rossi per agente inesistente, accesso anonimo e sessione revocata.
- [ ] Aggiungere schema e route usando lifecycle/trade/proiezione, mantenendo degradazione del mercato coerente col legacy.
- [ ] Eseguire test API e auth fino al verde.

### Task 4: Migrazione della vista React delle aperte

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/PositionsTable.tsx`
- Test: `frontend/src/__tests__/PositionsTable.test.tsx`
- Test: `frontend/src/__tests__/App.auth.test.tsx`

**Interfaces:**
- Consumes: `getOpenLifecycles(agentId)`.
- Produces: comportamento visibile attuale alimentato dal nuovo contratto.

- [ ] Scrivere test React rosso per identità lifecycle e valori netti fee mostrati.
- [ ] Aggiornare tipi, fetch e props senza introdurre UX dei ticket successivi.
- [ ] Verificare empty state e perdita auth durante il fetch.
- [ ] Eseguire test React mirati e typecheck fino al verde.

### Task 5: Verifica, review e commit

**Files:**
- Review all modified files.

- [ ] Eseguire suite backend completa.
- [ ] Eseguire suite frontend completa, typecheck e build.
- [ ] Verificare migrazione Alembic su database usa-e-getta senza alterare dati condivisi.
- [ ] Controllare diff, scope #25, append-only e assenza di modifiche alla strategia.
- [ ] Eseguire la review richiesta e correggere soltanto difetti in scope.
- [ ] Committare sul branch corrente con messaggio riferito al ticket #25.
