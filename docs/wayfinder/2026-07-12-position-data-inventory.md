# Inventario dati per raccontare una posizione

Ricerca per la mappa Wayfinder “Ripensare il pannello Posizioni”. Questo documento descrive ciò che il sistema registra oggi, cosa il frontend può ricostruire e dove mancano dati affidabili. Non decide ancora il contratto futuro.

## Sintesi

Il sistema dispone già di dati solidi per:

- stato e valorizzazione delle posizioni aperte;
- singole esecuzioni BUY/SELL, incluse rationale e costi;
- vendite parziali e risultato realizzato;
- riepilogo economico di una posizione quando viene chiusa completamente.

Il sistema non dispone invece di un'identità stabile della vita della posizione né di uno stato esplicito che risponda a “perché è ancora aperta”. Queste informazioni si possono inferire solo combinando eventi, decision record e memoria, tutti con limiti di cardinalità o struttura.

## Fonti esistenti

### Posizione aperta

La tabella `positions` conserva una riga per coppia agente/simbolo finché la quantità rimane positiva:

- quantità corrente;
- costo medio corrente;
- timestamp di apertura della vita corrente;
- somma dei notional BUY della vita corrente (`invested_usd`);
- P&L già realizzato dalle vendite parziali (`realized_usd`);
- flag tecnici dei trigger.

Alla chiusura totale la riga viene eliminata. Un successivo BUY dello stesso simbolo crea una nuova vita, ma non esiste un identificatore di lifecycle conservato negli eventi.

L'endpoint delle posizioni aperte aggiunge prezzi live e restituisce:

- quantità e costo medio;
- cost basis corrente;
- ultimo prezzo;
- valore di mercato;
- P&L non realizzato percentuale;
- apertura;
- P&L realizzato parziale.

`invested_usd` esiste nel database ma non è esposto dall'endpoint. Il P&L non realizzato in dollari e il peso sul portafoglio sono calcolabili dai dati già restituiti, con la cautela che l'equity dell'agente proviene dall'ultimo snapshot e può non essere temporalmente allineata ai prezzi live usati dalle posizioni.

Se il market snapshot fallisce, ultimo prezzo, valore e P&L live degradano correttamente a `null` invece di far fallire l'endpoint.

### Operazioni ed eventi strutturati

Ogni BUY/SELL crea sia un `Trade` contabile sia un evento `trade` strutturato.

Il payload BUY contiene:

- simbolo, quantità, prezzo, fee e notional;
- rationale dell'azione;
- classificazione `new` o `increase`;
- `cycle_id` dell'azione.

Il payload SELL contiene inoltre:

- frazione della quantità allora esistente;
- costo medio;
- P&L realizzato percentuale e in dollari;
- rationale dell'azione.

Alla chiusura totale il SELL incorpora `position_summary` con apertura, chiusura, durata, capitale complessivamente investito e P&L totale realizzato.

Limiti:

- l'endpoint eventi restituisce solo gli ultimi 100 eventi;
- l'endpoint trades restituisce solo gli ultimi 100 trade;
- `Trade` non conserva rationale, `cycle_id` o identità della vita della posizione;
- gli eventi legacy possono avere payload incompleti o solo una riga raw;
- i P&L registrati sono lordi rispetto alle fee; le fee sono disponibili separatamente, ma non esiste un totale netto di lifecycle.

### Posizioni chiuse

Lo storico chiuse non vive in una tabella dedicata. L'endpoint cerca `position_summary` negli ultimi 500 eventi e restituisce al massimo 50 chiusure.

Sono disponibili:

- simbolo;
- apertura e chiusura;
- durata;
- capitale investito;
- P&L totale percentuale e in dollari;
- ciclo della chiusura.

Limiti:

- nessun filtro temporale, cursore o paginazione server-side;
- chiusure oltre la finestra degli ultimi 500 eventi non sono raggiungibili;
- mancano ciclo e rationale di apertura, fee totali, prezzi medi di entrata/uscita e identità stabile del lifecycle;
- due vite successive dello stesso simbolo sono distinguibili soltanto tramite intervalli temporali e riepiloghi di chiusura.

### Decisioni dell'agente

Il `DecisionRecord.parsed_output` conserva l'output completo del modello, incluse azioni BUY, SELL e HOLD con:

- simbolo;
- rationale;
- riferimenti alle policy;
- allineamento o violazione della policy;
- eventuale motivo di override.

L'evento `decision` conserva invece solo la nota generale del ciclo, il conteggio delle azioni eseguite, gli skip, gli errori e il trigger. Le azioni HOLD non vengono materializzate nel payload dell'evento.

L'endpoint decisioni restituisce gli ultimi 100 record. Per stabilire “perché è ancora aperta” si potrebbe cercare l'ultima azione HOLD sul simbolo dentro `parsed_output`, ma sarebbe un'inferenza fragile:

- non ogni ciclo contiene un HOLD esplicito per ogni posizione;
- la nota è riferita al ciclo, non necessariamente al simbolo;
- la finestra è limitata;
- non esiste un campo persistente “tesi corrente della posizione” o “ultima valutazione”.

### Memoria

La memoria espone tesi per coin, lezioni, note di strategia e self-policy. Le tesi per coin sono righe narrative con una convenzione testuale del tipo `SYMBOL: ...`, non record strutturati collegati a una posizione.

La memoria può dare contesto alla condotta dell'agente, ma non è una fonte affidabile dello stato corrente della posizione:

- viene aggiornata da riflessioni su trade chiusi e decisioni valutate a posteriori;
- può non contenere il simbolo;
- può essere distillata o ritirata;
- non distingue automaticamente vite successive dello stesso simbolo.

## Risposta alle quattro domande approvate

### Perché è stata aperta?

Disponibile per eventi nuovi: rationale del primo BUY con `position: new`, collegabile al ciclo. Non garantito per eventi legacy o quando il primo evento è uscito dalla finestra degli ultimi 100.

### Come è cambiata nel tempo?

Ricostruibile dagli eventi BUY `increase` e SELL parziali compresi tra `opened_at` e chiusura. La ricostruzione è incompleta quando la vita supera la finestra eventi o quando manca un lifecycle id.

### Perché è ancora aperta?

Non disponibile come fatto di prima classe. Decision note, azioni HOLD e memoria forniscono indizi, ma nessuna fonte dichiara in modo stabile l'ultima tesi dell'agente sulla posizione e quando è stata valutata.

### Quale risultato ha prodotto finora?

Per le aperte sono disponibili P&L non realizzato percentuale, valore corrente e realizzato parziale. Il totale combinato è calcolabile, ma il contratto API non espone ancora tutti i valori già presenti nel database e non offre una convenzione netta comprensiva di fee.

Per le chiuse esiste il risultato totale lordo nel `position_summary`; le fee della vita non sono aggregate.

## Conseguenze per i prossimi ticket

Le decisioni successive dovranno affrontare esplicitamente:

1. se introdurre un'identità stabile per ogni vita di posizione;
2. se creare un read model o endpoint unificato per aperte, chiuse e dettaglio;
3. come rappresentare una tesi corrente senza spacciare inferenze per fatti;
4. quale convenzione usare per P&L lordo, fee e risultato netto;
5. come supportare filtro temporale e paginazione delle chiuse;
6. quali eventi e decisioni includere nel dettaglio senza dipendere dai limiti globali degli endpoint attuali.

## Seams di test già disponibili

La base di test esistente offre seams ad alto livello adeguati:

- test API per posizioni aperte, chiuse ed eventi;
- test dell'engine per apertura, incremento, vendita parziale e chiusura totale;
- test del backfill degli eventi legacy;
- test frontend di `PositionsTable`, `ClosedPositionsTable` ed `EventsFeed`.

Il futuro contratto dovrebbe essere verificato principalmente a livello API, con pochi test frontend orientati al comportamento visibile. Non serve introdurre seams più bassi finché il contratto non sarà deciso.
