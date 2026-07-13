# Ticket 26 Lifecycle Collection Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere navigabili lifecycle aperti, chiusi e complessivi tramite una collezione canonica e un pannello React con filtri, finestra temporale, ordinamenti fissi e paginazione a cursore.

**Architecture:** Estendere il seam pubblico introdotto dal ticket #25 con `GET /api/agents/{agent_id}/lifecycles`, che proietta `PositionLifecycle` e `Trade` senza leggere riepiloghi dagli eventi. Il frontend usa un unico tipo di riepilogo e mantiene il fetch legacy disponibile ma non più come fonte del pannello Posizioni.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, pytest; React 19, TypeScript, Vitest, Testing Library.

## Global Constraints

- Conservare endpoint e payload legacy fino al ticket #32.
- Non migrare, resettare o cancellare dati paper-trading esistenti.
- Non implementare market freshness/chart #27, dettaglio #28, timeline #29, mobile #30 o separazione superfici #31.
- `closed_since` filtra soltanto lifecycle chiusi e usa sette giorni come default.
- Non offrire ordinamento manuale.
- Non leggere o modificare `.codex/config.toml`.

---

### Task 1: Contratto API della collezione

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces: `GET /api/agents/{agent_id}/lifecycles?state=open|closed|all&closed_since=<ISO8601>&limit=<1..100>&cursor=<opaque>`.
- Produces: `{items: LifecycleSummary[], next_cursor: string | null}` con campi comparativi nullable secondo lo stato.

- [ ] Scrivere test API rossi per default open, stati, finestra di sette giorni e `closed_since` applicato solo alle chiuse.
- [ ] Eseguire i test mirati e verificare 404/422 prima dell'implementazione.
- [ ] Implementare schema, validazione esplicita e proiezione netta delle fee dal ledger.
- [ ] Scrivere test rossi per limite 0/101, stato/data/cursore invalidi e confini 1/100.
- [ ] Implementare cursore opaco deterministico su timestamp e id lifecycle.
- [ ] Scrivere test rossi per ordinamenti, timestamp uguali, lifecycle ripetuti dello stesso simbolo e nessun salto/duplicato.
- [ ] Implementare ordinamento open per esposizione, closed per chiusura e all a gruppi open/closed.
- [ ] Scrivere e rendere verdi i test di autorizzazione anonimo e viewer revocato sul nuovo endpoint.

### Task 2: Navigazione React della collezione

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/PositionsTable.tsx`
- Test: `frontend/src/__tests__/PositionsTable.test.tsx`
- Test: `frontend/src/__tests__/App.auth.test.tsx`

**Interfaces:**
- Consumes: `getLifecycles(agentId, {state, closedSince, limit, cursor})`.
- Produces: filtri `Aperte`, `Chiuse`, `Tutte`, controllo data/tutto lo storico, colonne specifiche, empty state specifici e caricamento progressivo delle chiuse.

- [ ] Scrivere test React rosso per vista Aperte predefinita e assenza di ordinamento manuale.
- [ ] Sostituire il pannello espandibile con rendering non-detail delle colonne approvate per Aperte.
- [ ] Scrivere test rossi per cambio a Chiuse/Tutte, controllo temporale e richieste API osservabili.
- [ ] Implementare stato filtro e query, mantenendo il polling esistente.
- [ ] Scrivere test rossi per colonne ed empty state specifici delle tre viste.
- [ ] Implementare schemi comparativi e copy degli empty state.
- [ ] Scrivere test rosso per `Carica altro` e concatenazione senza duplicati.
- [ ] Implementare paginazione progressiva quando `next_cursor` è presente.
- [ ] Eseguire test React mirati e typecheck fino al verde.

### Task 3: Verifica, review e commit

**Files:**
- Review all modified files.

- [ ] Eseguire test backend mirati e suite backend completa.
- [ ] Eseguire test frontend mirati, suite completa, lint e build/typecheck.
- [ ] Controllare ogni acceptance criterion #26 contro test e comportamento osservabile.
- [ ] Revisionare il diff per scope, compatibilità legacy e dipendenze involontarie dagli eventi.
- [ ] Committare sul branch corrente con un messaggio riferito al ticket #26.
