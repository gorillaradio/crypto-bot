# Redesign Attività + Posizioni + striscia salute

**Data**: 2026-07-09 · **Stato**: spec approvata a voce, in attesa di review scritta

## Contesto e problema

Il pannello Attività (decision diary, `EventsFeed.tsx`) è illeggibile: tutti i cicli hanno
lo stesso peso visivo (i "non faccio niente" seppelliscono le operazioni), mancano gli
esiti (il P&L realizzato viene calcolato dal backend ma mai mostrato), non c'è filo
narrativo tra apertura e chiusura di una posizione, e il gergo tecnico (riflessione
fallita, P3329, quantità grezze) è mischiato alla storia. Alla radice: il frontend
ricostruisce la struttura riparsando con regex stringhe pre-formattate dal backend.

## Principi decisi

1. **Il pannello Attività risponde a: "è successo questo → per questo motivo."**
   Ogni blocco apre col fatto (italiano, generato dai dati, mai dall'LLM) e sotto il
   motivo (la voce dell'agente, citazione inglese verbatim). Dettagli solo espandendo.
2. **I dati possono ripetersi, le responsabilità no.**
   - *Attività* = il registro del tempo: cosa è vero nell'istante dell'evento.
   - *Posizioni* = la vita degli asset: cosa è vero della posizione (arco, tenuta, biografia).
   - Il ponte tra i due è un link, mai una copia. Test per ogni campo: "era vero nel
     momento dell'evento, o è vero della posizione?"
3. **Colore = esito, e nient'altro.** Verde solo profitto, rosso solo perdita.
   Comprare/vendere sono atti neutri (pill grigie). Niente frecce ▲▼ (su/giù si legge
   come guadagno/perdita), niente emoji. La striscia salute non usa mai il verde:
   grigia quando tutto va, ambra sui degradi, rossa solo per rottura vera — così il
   rosso in pagina significa sempre "guarda qui adesso".
4. **La tabella racconta, il dettaglio rende conto.** I numeri da contabile (costo
   medio, quantità precise, prezzi di entrata/uscita, fee) vivono nei dettagli
   espandibili, mai nelle righe principali.

## Fondamenta dati: eventi strutturati

### Schema

- `events` acquisisce una colonna `payload` (JSON, nullable). `message` resta com'è:
  riga di log leggibile, fallback e debug.
- `positions` acquisisce `opened_at` (set alla creazione) e `realized_usd`
  (accumulato dalle vendite parziali). Oggi la riga viene cancellata alla chiusura
  totale senza lasciare traccia (`engine.py`).

### Payload per kind

- `decision` → `{note, executed, skipped: [{type, symbol, reason}], errors, trigger, wake_reason}`
  — le azioni saltate diventano spiegabili (oggi sono solo un contatore).
- `trade` (BUY) → `{side, symbol, qty, price, fee, usd_value, rationale, position: "new"|"increase"}`
- `trade` (SELL) → BUY + `{fraction, realized_pnl_pct, realized_pnl_usd, avg_cost}`.
  Il rationale entra nel payload del trade: muore l'accoppiamento fragile di oggi
  (evento `reasoning` abbinato al trade per adiacenza).
- `trade` (SELL a chiusura totale) → in più `position_summary:
  {opened_at, held_minutes, invested_usd, realized_total_usd, realized_total_pct}`
  — la biografia completa, parziali incluse. Lo storico posizioni si legge da qui:
  **nessuna tabella nuova**, gli eventi sono la fonte di verità immutabile.
- `reflection` → `{status: ok|invalid|error, sections_updated, detail}`

Convenzione P&L: realizzato calcolato come oggi in `runtime.py` — lordo rispetto alle
fee, contro il costo medio ((prezzo − avg_cost) / avg_cost). Le fee restano visibili
a parte nei dettagli; nessun cambio di formula, solo registrazione.

### Migrazione ed eventi storici

- Migrazione Alembic: aggiunge le colonne; backfill del `payload` sugli eventi
  esistenti riusando le regex oggi nel frontend (trasferite nel backend, usate una
  volta sola). Dove non matchano: `payload = {raw: message}` → il diario mostra la
  riga grezza smorzata. `positions.opened_at` backfillata dallo storico trades.
- L'API espone `payload`; il frontend non riparsa mai più stringhe.

## Pannello Attività

- **Blocchi per ciclo**, dal più recente, con separatori di giorno (come oggi).
- **Cicli fermi consecutivi raggruppati** in un blocco unico smorzato:
  "10:29–10:34 · Nessuna mossa (2 cicli)" + PERCHÉ con la nota più recente;
  espandibile per vedere i singoli cicli. Criterio deterministico: nessuna operazione.
- **Blocchi con operazioni**: ora → righe operazione → PERCHÉ (nota del ciclo
  verbatim) → "dettagli ›".
  - Pill neutre a larghezza fissa: `VENDITA` / `ACQUISTO`.
  - Vendita, sempre auto-conclusiva: `VENDITA SPELL venduto il 50% · +15,2% +$2,20`.
    La quota compare **solo se parziale** (grigia, separata dal P&L col punto
    centrale); l'assenza significa chiusura totale. Nessuna riga di totale del
    blocco: due vendite simultanee sono coincidenza, non un'entità.
  - Acquisto, muto sull'esito: `ACQUISTO SPELL ~$29 · nuova posizione` oppure
    `· posizione aumentata`.
  - Dettagli espandibili: qty, prezzi, fee, costo medio, rationale per operazione.
- **Riferimenti policy** (P####) nelle citazioni: tooltip col testo della regola
  (dati già disponibili via memory API `self_policy`).
- **Simboli linkano** alla riga corrispondente in Posizioni (aperta o storica).
- **Filtro** "tutto / solo operazioni" + contatore cicli·operazioni: nell'header del
  pannello, a destra, come oggi. "Solo operazioni" nasconde i blocchi d'attesa.
- **Eventi legacy** non interpretati dal backfill: riga grezza smorzata.
- Sparisce dal diario ogni segnale d'impianto: chips "riflessione fallita",
  "azioni saltate", "guardrail" (→ striscia salute), "memoria aggiornata" (routine,
  non compare da nessuna parte).

## Pannello Posizioni

- **APERTE** — colonne: asset (con "aperta oggi 10:10"), storia ("−50% alle 10:21 ·
  aumentata alle 10:26", con link ai blocchi di Attività), valore, non realizzato,
  già incassato. Dettaglio espandibile: quantità, costo medio, prezzo attuale
  affiancati (verifica a occhio), fee pagate.
- **CHIUSE** (storico, nuovo) — colonne: asset, arco (solo tempi: "10:10 → 10:21"),
  tenuta, investito, esito (% e $, colorato). Dettaglio: prezzi di entrata/uscita,
  quantità, fee. Rimandi "perché aperta › perché chiusa" ai blocchi di Attività
  (le citazioni dell'agente hanno una casa sola).
- Una posizione passa allo storico **solo alla chiusura totale**, con l'esito
  complessivo di tutta la vita (vendite parziali incluse). Finché è aperta, le
  parziali si vedono su "già incassato" e nella storia.
- Vendite parziali e riacquisti sono **eventi pieni in Attività** (mai nascosti) e
  aggiornamenti di stato in Posizioni: stessa realtà, due responsabilità.

## Striscia salute

- **Posizione**: in testa alla pagina, sotto la riga delle card di sintesi.
  Non dentro Attività: parla della macchina, non del racconto. Non sticky (per ora).
- **Contenuto** (tutto derivato da eventi strutturati + timestamp ultimo ciclo):
  ultimo ciclo X min fa · riflessioni scartate/fallite oggi · azioni saltate oggi ·
  errori di esecuzione oggi.
- **Tre stati**: grigia e muta (normale) / ambra (degradi: saltate, riflessione
  scartata) / rossa con bordo (rottura: loop fermo oltre l'intervallo atteso,
  errori di esecuzione). Mai verde.
- Contatori cliccabili → motivi/dettagli (es. saltate: "importo sotto il minimo",
  "coin fuori universo").

## Cosa resta invariato

- Pannello Decisioni (telemetria LLM), Operazioni (lista trades), Memoria, Market
  brief, Osservazioni, Prompt.
- La lingua della voce dell'agente: inglese verbatim, mai tradotta né riscritta
  (zero costi, zero rischi sull'esperimento, fedele ai dati grezzi).

## Fuori scope

- Traduzione o riscrittura LLM delle note; striscia salute sticky; notifiche;
  modifiche al prompt dell'agente; ogni cambiamento alla logica di trading o al
  learning loop (si aggiungono solo campi registrati, mai comportamento).

## Criteri di successo (verificabili sui dati grezzi)

1. Aprendo Attività si risponde in pochi secondi a "cosa ha fatto e perché" senza
   leggere blocchi ripetitivi: i cicli fermi consecutivi occupano un blocco solo.
2. Ogni vendita mostra il suo esito (% e $) sulla riga; il numero è verificabile
   contro costo medio e prezzo nel dettaglio espandibile.
3. Una vendita parziale è visibile come evento in Attività E come "già incassato"
   sulla posizione aperta; i due numeri coincidono.
4. Lo storico CHIUSE mostra per ogni posizione chiusa arco, tenuta, investito ed
   esito totale coerente con la somma dei trade grezzi.
5. Nel frontend non esiste più alcuna regex di parsing dei messaggi evento.
6. Un guasto del loop (fermo oltre l'intervallo) è visibile in testa alla pagina
   entro un refresh, senza aprire nessun pannello.
7. Rosso e verde compaiono in pagina esclusivamente su P&L e stati di rottura.

## Conseguenze e note di implementazione

- Migrazione Alembic su DB di prod (head unico attuale: `7b8c9d0e1f2a`); il deploy è
  automatico al push su main → la PR si merge solo completa e verificata.
- Punti toccati: `db/models.py`, `trading/engine.py`, `agents/runtime.py`,
  `agents/learning.py`, endpoint events/positions, `api.ts`, `EventsFeed.tsx`
  (riscritto), `PositionsTable.tsx` (esteso), nuova striscia salute, `App.tsx`.
- Test su entrambi i lati (backend: payload scritti e backfill; frontend: rendering
  dei tre tipi di blocco, raggruppamento, legacy raw).
- Mockup di riferimento in `.superpowers/brainstorm/` (non committati, gitignored):
  `attivita-posizioni-v7.html`, `salute-v1.html`.
