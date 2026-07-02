# Monitor dei prompt per-agente — Design Spec

**Data:** 2026-07-01
**Stato:** Draft (brainstorming completato, in attesa di review utente)
**Tipo:** Feature — osservabilità, read-only

## Obiettivo

Dare un **posto unico nella dashboard** dove vedere i prompt che compongono la pipeline decisionale, per un agente selezionato, **renderizzati dal vivo con dati reali** e con lo **stesso codice** che la pipeline usa davvero (nessuna copia che può divergere).

## Requisiti (dal brainstorming)

- **Monitor, non editing.** L'editing dei prompt è esplicitamente rimandato a una fase successiva. Questo spec copre solo la visualizzazione.
- **Live per-agente:** scelto un agente, si vede il `system` + `user` esatti che verrebbero inviati ora all'LLM per quell'agente.
- **Tutti i pezzi che concorrono alla pipeline:** decision, reflection, retry.
- **Auth:** viewer + admin (come gli altri GET dell'agente).
- **Zero drift:** ciò che si vede deve essere ciò che la pipeline costruisce, non una descrizione a parte.

## Non-obiettivi

- Nessun editing dei prompt (né istruzioni per-agente né template globali) — fase successiva.
- Nessuno storage nuovo: niente cattura/persistenza dei prompt per ciclo (lo "storico" è stato scartato in favore del live).
- Nessuna chiamata LLM: la preview costruisce i prompt ma non li invia.
- Nessuna modifica al contratto JSON o a `schema.py`.

## I cinque pezzi e come vengono mostrati

| Pezzo | Sorgente | Come è mostrato |
|-------|----------|-----------------|
| Decision `system` (`_SYSTEM`) + user | `prompt.py` `render_prompt` | **Live**, dati reali. `wake_reason=None` (nota: la riga `⚠` compare solo su breach off-cycle) |
| Retry (suffisso su JSON invalido) | `brain/__init__.py` | **Live**: decision `user` + suffisso, con un **errore d'esempio** al posto di `{first_err}` |
| Reflection `system` (`_REFLECT_SYSTEM`) + user | `memory.py` `build_reflection_prompt` | **Live**: memoria/istruzioni/holdings reali; `closed` derivati dalle **posizioni attuali come se chiuse ora** (avg reale + prezzo reale → realized %), etichettato come anteprima. Nessuna posizione ⇒ struttura + nota |

## Architettura

### Punto chiave — anti-drift: estrazione di `build_agent_context`

Oggi la raccolta dati + `build_context` vive **dentro** `_run_decision_llm` ([runtime.py](../../backend/app/agents/runtime.py)). La estraiamo in una funzione pura riusabile:

```
build_agent_context(session, agent, market, symbols, *, wake_reason=None) -> DecisionContext
```

Raccoglie holdings (posizioni + `get_price`), universe snapshot, eventi recenti (ultimi 10) e memoria, poi ritorna il `DecisionContext`. La usano **entrambi**:
- `_run_decision_llm` (comportamento invariato — chiama `build_agent_context` poi `brain_decide`);
- il nuovo endpoint di preview (chiama `build_agent_context` poi `render_prompt`, **senza** LLM).

Questo garantisce che il monitor mostri esattamente ciò che la pipeline costruirebbe.

### Backend

- **Helper puro** in un modulo dedicato (es. `app/brain/preview.py` o `app/agents/preview.py`):
  `render_agent_prompts_preview(session, agent, market) -> PromptPreview`
  - `symbols = market.get_top_symbols("USDT", n)` (n per universo agente)
  - `ctx = build_agent_context(session, agent, market, symbols, wake_reason=None)`
  - `decision = render_prompt(ctx)` → `(system, user)`
  - `retry = (decision.system, decision.user + RETRY_SUFFIX_EXAMPLE)`
  - `reflection = build_reflection_prompt(memory, closed_hypot, held_symbols, instructions)` dove `closed_hypot` deriva dalle posizioni attuali
- **Endpoint** `GET /api/agents/{id}/prompt` (auth `require_viewer_or_admin`) → JSON:
  ```json
  {
    "decision":   { "system": "...", "user": "..." },
    "reflection": { "system": "...", "user": "...", "note": "anteprima: posizioni attuali come se chiuse ora" },
    "retry":      { "system": "...", "user": "...", "note": "suffisso mostrato con un errore d'esempio" }
  }
  ```
  Read-only, nessuna persistenza. Il market client è `BinanceClient` (come in `jobs.py`); nei test è iniettabile (fake).
- **Costo:** 2 chiamate Binance live per apertura (`get_top_symbols` + `get_universe_snapshot`) + N `get_price` per le posizioni. Accettabile on-demand.

### Frontend

- Nuova sezione **"Prompt"** nella scheda dell'agente (accanto a memoria/eventi/posizioni).
- Tre viste (tab o accordion): **Decision / Reflection / Retry**, ciascuna con due blocchi monospace (`system`, `user`) nello stile del blocco codice dell'explainer.
- Sola lettura, role-aware (visibile a viewer e admin). Fetch da `GET /api/agents/{id}/prompt` al primo apri/refresh.
- Le `note` (reflection/retry) mostrate come didascalia sotto il blocco.

## Data flow

1. UI apre la scheda agente → richiede `GET /api/agents/{id}/prompt`.
2. Endpoint: `build_agent_context` (dati reali) → `render_prompt` / `build_reflection_prompt` → 3 coppie (system, user).
3. UI renderizza i blocchi monospace nelle tre tab.

## Error handling

- Agente inesistente → 404 (come gli altri endpoint).
- Errore market (Binance) → l'endpoint restituisce 200 con i prompt costruibili offline (system template + parti non-mercato) e una `note` che segnala universo non disponibile, **oppure** 502 con messaggio. **Decisione:** degradare con nota (il monitor resta utile anche senza universo). Da confermare in review.
- Nessuna posizione / nessuna memoria → prompt renderizzati con le rispettive righe "(none)" (comportamento già esistente in `render_prompt`).

## Testing

- **Backend** (pytest, FakeMarket come nei test runtime):
  - `GET /api/agents/{id}/prompt` per agente seedato con posizioni+memoria → `decision.system` contiene le istruzioni, `decision.user` contiene simbolo posizione, universo, memoria; nessuna riga di evento LLM creata, nessuna persistenza.
  - reflection: `user` contiene le posizioni attuali come trade "chiusi" ipotetici (una `ClosedTrade` per posizione) con realized % coerente.
  - retry: `user` = decision user + suffisso.
  - auth: viewer e admin OK; non autenticato → 401.
  - edge: agente senza posizioni/memoria → 200, righe "(none)", note coerenti.
- **Regressione:** l'estrazione di `build_agent_context` è coperta dai test runtime esistenti (decision/heartbeat) — devono restare verdi senza modifiche.

## Consequences / note

- **Branch dedicato:** feature diversa dal rischio → implementare su `prompt-monitor` impilato sul tip di `risk-thresholds-llm` (che porta i componenti shadcn necessari), per non inquinare la PR #6. Al merge di #6, rebase su main.
- **Refactor a basso rischio:** estrarre `build_agent_context` tocca `runtime.py` ma è comportamento-preservante e coperto dai test esistenti.
- **Editing futuro:** questo design lascia la porta aperta — quando si vorrà l'editing, i template globali dovranno passare da costanti-codice a dati + guardrail (`{instructions}` obbligatorio, JSON allineato a `schema.py`) + scope + versioning. Fuori scope qui.
