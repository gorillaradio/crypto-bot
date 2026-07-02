# Soglie di rischio mediate dall'LLM — Design

Data: 2026-07-01
Stato: approvato (brainstorming), da trasformare in piano

## Contesto e problema

Oggi il **battito** (`run_heartbeat`, ogni 5 min) applica una regola di rischio
**hardcoded** e completamente fuori dal controllo dell'agente:

- `agents/strategy.py::guardrail_action` usa soglie fisse di default (`stop_loss=0.10`,
  `take_profit=0.20`) mai sovrascritte;
- `agents/runtime.py::run_heartbeat` la chiama su ogni posizione e, al breach,
  esegue **direttamente** `execute_sell` dell'intera posizione, senza passare dall'LLM.

Due problemi:

1. **Scavalca il giudizio dell'agente** — l'LLM può voler tenere una posizione, ma una
   regola meccanica la liquida comunque. Contraddice la tesi del progetto («edge dalla
   sintesi dell'agente», non da regole fisse).
2. **Soglie non configurabili** — uguali per tutti gli agenti, non impostabili, non
   confrontabili.

## Obiettivo

- Le soglie diventano **per-agente**, impostabili alla creazione.
- Al breach, **decide l'LLM**, non una regola meccanica. Il battito diventa un
  **trigger veloce** che sveglia l'LLM, non più un esecutore.

## Decisioni di design

| # | Decisione | Scelta | Note |
|---|-----------|--------|------|
| D1 | Tempismo sul breach | **Risveglio off-cycle dell'LLM** | Il breach lancia un ciclo di decisione entro un tick (≤5 min). Mantiene la reattività + dà l'agenzia all'LLM. |
| D2 | Dove si configurano | **Per-agente, nel form di creazione** | Abilita esperimenti «aggressivo vs conservativo». |
| D3 | Scope della decisione off-cycle | **Riusa il ciclo intero** (`run_decision`) | L'LLM vede tutto il portafoglio e può ribilanciare, non solo la posizione in breach. |
| D4 | Anti-spam sui risvegli | **Edge-triggered, per-posizione** | Una posizione sveglia l'LLM quando *attraversa* la soglia, una volta sola (`Position.breach_armed`); si ri-arma solo se rientra nella banda. Niente cooldown a tempo. |
| D5 | Soglie opzionali | **Sì, default 10% / 20%** | `null` = soglia disattivata. Abilita l'agente "cieco" come confronto. |
| D6 | Modificabilità | **Fisse per l'intera run** | Coerente con le `instructions` (già fisse alla creazione). |

## Comportamento target

### Battito (`run_heartbeat`, ogni 5 min, invariato come cadenza)

1. Per ogni posizione: legge il prezzo, accumula il valore per l'equity (come oggi).
2. Per ogni posizione calcola se è oltre soglia (con le soglie **dell'agente**, non i default
   hardcoded). Le posizioni *dentro la banda* si **ri-armano**; quelle oltre soglia **e
   armate** sono *breach freschi* (hanno appena attraversato — vedi Re-arm). Per la nota di
   risveglio basta il primo fresco (simbolo, lato `stop`/`take`, variazione %).
3. Salva sempre l'`EquitySnapshot` (invariato).
4. Se **almeno una** posizione è un *breach fresco* → lancia una **decisione off-cycle** per
   quell'agente e **disarma** tutte le posizioni attualmente in breach (vedi Re-arm). Niente
   vendita meccanica.

Il battito **non chiama più `execute_sell`**. La vendita, se ci sarà, arriva dalla
`Decision` dell'LLM, esattamente come nel ciclo orario.

### Rilevamento del breach (`strategy.py`)

`guardrail_action` viene sostituita da una funzione pura che riceve le soglie (non più
default hardcoded) e dice **se e quale** soglia è stata sforata:

```python
def breached(avg_price, last_price, stop_loss, take_profit) -> str | None:
    # ritorna "stop" | "take" | None ; soglie None = disattivate
    if avg_price <= 0:
        return None
    change = (last_price - avg_price) / avg_price
    if stop_loss is not None and change <= -stop_loss:
        return "stop"
    if take_profit is not None and change >= take_profit:
        return "take"
    return None
```

### Decisione off-cycle

- Riusa il ciclo di decisione esistente (`run_decision` / `_run_decision_llm`).
- I `symbols` dell'universo non sono in mano al battito: vengono recuperati **on-demand**
  al momento del breach (`market.get_top_symbols(universe_size)`), dato che i breach sono
  occasionali.
- Il contesto della decisione include una **nota di risveglio** esplicita, così l'LLM sa
  perché è stato svegliato. Esempio: *«⚠ Risveglio fuori ciclo: SOLUSDT a −12.3%, oltre la
  tua soglia di stop −10%. Rivaluta.»*
- L'evento `decision` risultante è marcato come off-cycle nel messaggio (riconoscibile nel
  feed).

### Re-arm (edge-triggered, per-posizione)

- Stato per posizione: `Position.breach_armed` (bool, default `True`).
- A ogni battito, per ogni posizione:
  - **dentro la banda** (non oltre soglia) → si **ri-arma** (`breach_armed = True`);
  - **oltre soglia e armata** → è un *breach fresco* (ha appena attraversato la soglia);
  - **oltre soglia ma già disarmata** → si **ignora** (ha già svegliato per questo episodio).
- Se c'è almeno un breach fresco **e** nessuna decisione è già in corso per l'agente (vedi
  Concorrenza) → si lancia la decisione off-cycle e si **disarma** *tutte* le posizioni
  attualmente in breach (la decisione mostra all'LLM l'intero portafoglio: le ha viste tutte).
- Se una decisione è già in corso, si **salta senza disarmare** → si ritenta al battito
  successivo (il breach non si perde).
- Effetto: ogni episodio di breach sveglia l'LLM **una volta sola**. Una posizione bloccata
  oltre soglia non genera solleciti periodici; risveglierà solo se rientra nella banda e poi
  sfora di nuovo.
- **Caveat oscillazione**: una posizione che ondeggia esattamente attorno alla soglia
  (es. −9.9% / −10.1% a ogni tick) può ri-armarsi e risvegliare a ogni attraversamento.
  Mitigazione (fuori scope): isteresi sul re-arm — ri-armare solo oltre un piccolo margine
  dentro la banda.

### Concorrenza

Battito e ciclo orario sono **job distinti** dello scheduler: possono girare insieme sullo
stesso agente. Una decisione off-cycle innescata dal battito e la decisione oraria
potrebbero sovrapporsi → doppio trade / race sulla sessione.

Mitigazione: **lock asincrono per-agente** (in-process; il backend è un singolo container).

- Un `dict[int, asyncio.Lock]` per `agent.id` nello scheduler.
- Ogni `run_decision` (oraria **e** off-cycle) passa per un helper che acquisisce il lock
  dell'agente.
- Acquisizione **non bloccante**: se il lock è già preso (una decisione è in corso per
  quell'agente), la nuova decisione — oraria **o** off-cycle — viene **saltata** (quella in
  corso copre la situazione; il contesto è comunque fresco).

## Modello dati

`Agent` (`db/models.py`) + 2 campi, **nullable**:

```python
stop_loss:   Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
take_profit: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
```

- Frazioni (0.10 = 10%). `Numeric(5,4)` → fino a 9.9999.
- `null` = soglia disattivata.
- Migrazione Alembic additiva (due colonne nullable). **Backfill**: la migrazione imposta
  gli agenti esistenti (almeno quelli `running`) a 0.10 / 0.20, per non cambiare
  silenziosamente il rischio delle run in corso. I nuovi agenti partono dai valori scelti
  nel form.

`Position` (`db/models.py`) + 1 campo di stato per il re-arm **per-posizione**:

```python
breach_armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

- `True` = pronta a svegliare al prossimo attraversamento di soglia. Default per le nuove
  posizioni; la migrazione imposta `true` anche sulle posizioni esistenti.

## Configurazione (`core/config.py`)

```python
default_stop_loss: Decimal = Decimal("0.10")   # default mostrato nel form
default_take_profit: Decimal = Decimal("0.20")
```

I default servono al form (valori iniziali) e come riferimento per il backfill. Con il
re-arm edge-triggered **non serve** un cooldown a tempo.

## Contesto / prompt

- `DecisionContext` (`brain/context.py`) guadagna un campo opzionale `wake_reason: str | None`.
- `build_context` lo accetta e lo passa.
- `brain/prompt.py::render_prompt`: se `wake_reason` è presente, lo mette in evidenza nel
  messaggio user (in cima allo stato), così l'LLM capisce subito perché è stato svegliato.
- Nel ciclo orario `wake_reason` è `None` (nessun cambiamento di comportamento lì).

## API e frontend

- `api/schemas.py`: il payload di creazione agente accetta `stop_loss` e `take_profit`
  opzionali come **frazioni** (0.10 = 10%), coerenti con DB e backend. Il form mostra le
  percentuali all'utente e converte in frazione prima del POST (la conversione è una
  preoccupazione di UI).
- Validazione: se presenti, `stop_loss ∈ (0, 1)` e `take_profit ∈ (0, 5]` (entrambi
  rappresentabili in `Numeric(5,4)`). Valori fuori range → 422.
- `api/routes.py`: passa i campi alla creazione dell'`Agent`.
- Frontend `components/AgentFormModal.tsx`: due campi numerici opzionali (stop-loss %,
  take-profit %), con i default 10 / 20 precompilati e possibilità di svuotarli per
  disattivare. Coerenti con lo stile del form esistente.

## Gestione errori

- La decisione off-cycle riusa il path esistente, che già cattura gli errori LLM/parse e
  scrive un evento `decision` di errore senza crashare.
- Il `_heartbeat_tick` mantiene il `try/except` per-agente esistente (un errore su un agente
  non blocca gli altri).
- Il re-arm edge-triggered impedisce lo spam: un breach persistente sveglia una volta sola.

## Testing

Estende la suite esistente (`tests/`), seguendo i pattern di `test_runtime.py` /
`test_jobs.py` (market e adapter mockati):

1. **`breached`**: stop colpito, take colpito, dentro banda, soglie `None` (disattivate),
   `avg_price = 0`.
2. **`run_heartbeat` senza breach**: salva equity, **non** chiama `run_decision`, **non**
   vende.
3. **`run_heartbeat` con breach fresco** (posizione armata): chiama `run_decision` una volta,
   con `wake_reason` valorizzato; **nessun** `execute_sell` diretto dal battito; la posizione
   viene **disarmata**.
4. **Re-arm edge-triggered**: una posizione oltre soglia **già disarmata** non rilancia;
   rientrata nella banda si ri-arma; una posizione *diversa* che attraversa la soglia
   risveglia comunque. Al risveglio tutte le posizioni in breach vengono disarmate.
5. **Soglie per-agente**: due agenti, soglie diverse → comportamenti diversi sullo stesso
   prezzo.
6. **Soglie disattivate** (`null`): nessun breach mai, nessun risveglio.
7. **Concorrenza**: se il lock dell'agente è già preso, la decisione off-cycle viene saltata
   **senza disarmare** (si ritenta al tick successivo).
8. **API**: creazione con soglie valide; rifiuto (422) con soglie fuori range; creazione
   senza soglie (entrambe `null`).

## Aggiornamento documentazione

- `docs/pipeline.html`: aggiornare la sezione **Battito** (loop 1) e il **diagramma master**
  per riflettere il nuovo comportamento (battito = trigger che sveglia l'LLM, non più
  vendita meccanica; soglie per-agente; re-arm edge-triggered). Aggiornare anche il pannello «Le manopole».

## Criteri di successo

- Il battito **non** contiene più alcuna vendita meccanica.
- Le soglie sono impostabili per-agente nel form e usate dal battito.
- Un breach sveglia l'LLM entro un tick (≤5 min), **una volta per episodio** (ri-sveglia solo dopo un rientro nella banda).
- La decisione di vendere/tenere/aggiungere è **sempre** dell'LLM.
- Un agente con soglie `null` gira senza guardrail (pure LLM orario).
- I test esistenti passano; i nuovi coprono i punti sopra.

## Fuori scope (YAGNI)

- Isteresi sul re-arm (margine anti-oscillazione): si usa l'edge-triggered semplice;
  l'isteresi è un raffinamento da aggiungere solo se l'oscillazione attorno alla soglia
  diventa un problema reale.
- Modifica delle soglie dopo la creazione (fisse per la run, come le `instructions`).
- Soglie multiple / trailing stop / altri tipi di ordine.
