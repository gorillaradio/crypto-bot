# Ticket 28 — Dettaglio desktop delle posizioni aperte

## Obiettivo

Permettere di selezionare una posizione aperta dalla lista lifecycle e leggere nella stessa superficie la sua ultima valutazione esplicita, l'economia corrente e i trade contabili. La zona sinistra della lista resta immobile; soltanto le colonne comparative a destra vengono sostituite dal dettaglio.

## Perimetro

Questo ticket implementa soltanto il dettaglio desktop delle aperte. Non include dettaglio delle chiuse, timeline paginata, comportamento mobile dedicato, separazione di Operazioni/Attività o rimozione dei contratti legacy, che restano nei ticket #29–#32.

Non vengono migrati, reinterpretati o cancellati dati paper-trading esistenti. Le nuove colonne delle valutazioni sono additive e nullable per mantenere leggibili le righe già registrate.

## Decisioni

### Endpoint dedicato

Il seam pubblico è:

`GET /api/agents/{agent_id}/lifecycles/{lifecycle_id}`

La collection resta leggera e continua a governare filtri, ordinamento e polling. Il dettaglio viene caricato soltanto dopo una selezione, così loading, errore e retry rimangono locali e non rendono inutilizzabile la lista.

Per #28 l'endpoint accetta soltanto lifecycle aperti dell'agente richiesto. Agente o lifecycle inesistente restituiscono `404`; un lifecycle chiuso non viene esposto come dettaglio aperto. Il contratto sarà esteso dal ticket #29 per le chiuse senza creare una seconda fonte.

La risposta contiene:

- identità, simbolo, stato e timestamp del lifecycle;
- ultima `PositionEvaluation`, oppure `null` senza inferenze;
- economia: quantità, prezzo medio, ultimo prezzo, esposizione, investito, realizzato, non realizzato, fee e risultato netto USD/percentuale;
- stato di mercato `fresh`, `stale` o `unavailable` con timestamp;
- trade del lifecycle necessari alla disclosure Contabilità.

Il dettaglio riusa il provider/cache introdotto da #27. Un fallimento di mercato non blocca valutazione e contabilità: i valori market-derived usano il dato stale compatibile oppure diventano `null`.

### Valutazioni append-only

`PositionEvaluation` viene estesa con:

- `policy_refs` come JSON nullable;
- `policy_alignment` nullable;
- `override_reason` nullable.

Le righe nuove normalizzano assenza di policy a lista vuota, allineamento `unrelated` e override vuoto. L'API normalizza nello stesso modo le righe legacy con colonne nulle.

BUY e SELL eseguiti continuano a scrivere trade, valutazione e proiezione nella stessa unità atomica; il runtime passa anche rationale, policy e override all'engine.

Un HOLD con simbolo che corrisponde a una posizione aperta scrive una valutazione append-only sul suo lifecycle e aggiorna `last_cycle_id`, senza creare trade o modificare contabilità. Azioni riferite a simboli senza lifecycle non possono produrre una `PositionEvaluation` e restano skip espliciti nel ciclo decisionale.

### Layout desktop

La tabella conserva una zona sinistra stabile per le aperte:

`Coin | 24h | Età`

Senza selezione, la destra continua a mostrare:

`Esposizione | Peso | Risultato netto`

Con una selezione, la destra viene sostituita da un'unica cella di dettaglio allineata in alto e estesa sull'altezza naturale della lista. Le righe di sinistra non vengono riordinate, promosse o centrate. Le larghezze della zona sinistra vengono dichiarate esplicitamente e restano uguali nei due stati.

Soltanto le righe aperte sono selezionabili in #28. La riga usa un controllo tastiera con nome accessibile, `aria-expanded` e stato selezionato non affidato al solo colore. Il dettaglio ha un titolo focalizzabile; chiusura esplicita ed Escape restituiscono il focus al controllo della riga.

Durante la selezione viene congelato l'ordine degli id lifecycle visibili. I poll possono aggiornare i valori delle righe, ma non il loro ordine. Alla chiusura del dettaglio torna l'ordine corrente della collection. Non vengono aggiunte animazioni di layout o riordino.

### Contenuto del dettaglio

La gerarchia è:

1. ultima valutazione esplicita, con azione, rationale, timestamp, policy e override;
2. economia corrente, con risultato netto e breakdown realizzato/non realizzato/fee;
3. Contabilità, collassata per impostazione predefinita, con i trade del lifecycle.

Se non esiste una valutazione, il pannello dichiara “Nessuna valutazione esplicita registrata” e non consulta memoria, note generiche o eventi. Se il mercato è unavailable, le grandezze market-derived mostrano `—` con disclosure; i trade e le fee restano leggibili.

Contabilità usa un controllo disclosure nativo/accessibile, non uno scroll interno. Il pannello assume altezza naturale e non introduce una card annidata o un modal.

### Stati locali

- Loading: contenuto locale di caricamento nella zona destra; lista e filtri restano utilizzabili.
- Errore: messaggio locale e comando `Riprova`; la lista non viene svuotata.
- Autorizzazione persa: mantiene il comportamento globale esistente e torna al login.
- Cambio selezione: annulla logicamente la risposta precedente; una risposta tardiva non può sostituire il dettaglio della nuova riga.
- Cambio vista/agente: chiude il dettaglio e rimuove il congelamento dell'ordine.

## Componenti e responsabilità

### Backend

- `PositionEvaluation`: persistenza append-only dei nuovi metadati.
- Runtime decisionale: registra HOLD per lifecycle esistenti e inoltra metadati a BUY/SELL.
- Engine: mantiene atomica la scrittura di trade e valutazione per BUY/SELL.
- Endpoint dettaglio: proietta valutazione, economia, mercato e trade da fonti canoniche.

### Frontend

- `api.ts`: tipi e fetch del dettaglio.
- `PositionsTable`: selezione, zona sinistra stabile e congelamento dell'ordine.
- `OpenLifecycleDetail`: fetch locale, race protection, loading/error/retry, focus ed Escape, rendering di valutazione/economia/contabilità.
- `App`: passa agent id e perdita auth; azzera la selezione quando cambia agente o vista.

## Seams TDD confermati

### Runtime decisionale

Testare `run_decision` come seam pubblico:

- BUY/SELL persistono rationale, policy, allineamento e override sul lifecycle corretto;
- HOLD di una posizione aperta persiste senza creare trade;
- HOLD senza posizione non inventa un lifecycle;
- le valutazioni restano append-only;
- errore nella valutazione BUY/SELL mantiene il rollback atomico già garantito.

### API dettaglio

Testare il nuovo endpoint:

- ultima valutazione completa e caso senza valutazione;
- economia con valori letterali noti e fee nette;
- trade limitati al lifecycle richiesto;
- mercato fresh, stale e unavailable senza perdere contabilità;
- agente/lifecycle errato e lifecycle di altro agente;
- accesso anonimo e viewer revocato.

### Pannello React

Testare con Testing Library:

- selezione e cambio diretto di riga;
- zona sinistra invariata e destra sostituita;
- loading, errore e retry locali;
- valutazione mancante dichiarata;
- dettaglio chiuso da comando ed Escape con focus ripristinato;
- navigazione tastiera e stato accessibile;
- Contabilità collassata e trade del lifecycle;
- ordine congelato durante poll e ripristinato alla chiusura;
- nessuna animazione di riordino;
- regressione dei filtri e della paginazione #26.

## Criteri di completamento

Il ticket è completo quando tutti gli acceptance criteria di #28 sono osservabili attraverso i tre seams confermati, le migrazioni additive funzionano su database usa-e-getta, le suite backend/frontend sono verdi, lint/build hanno exit 0 e la review finale non trova difetti Critical o Important.
