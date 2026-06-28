# Crypto Trading Sim — Project Overview

> Working title (placeholder — da definire). Esperimento: un agente IA gestisce un portafoglio crypto simulato e prova a far crescere un capitale virtuale, in condizioni reali, partendo da €100.

---

## 1. Concept

Affidiamo a un agente IA un capitale virtuale di **€100** con l'obiettivo di portarlo a un target prefissato (es. **€1.000**) investendo in criptovalute.

Il punto chiave: **è una simulazione, ma realistica**. Nessun acquisto reale avviene, però tutto il resto è vero:

- Prezzi reali, presi dal mercato in tempo reale.
- Tempi reali (l'agente opera nel presente, non su dati storici accelerati).
- Guadagni e perdite reali da un punto di vista matematico: ogni operazione è coerente con ciò che sarebbe successo davvero.

In sostanza è **paper trading** con dati live. Niente soldi in movimento, ma i numeri non mentono.

### Natura del progetto

Questa prima versione è un **esperimento ludico**: lo scopo è l'intrattenimento e l'osservazione, non costruire un sistema di trading da mettere in produzione. Vogliamo vedere risultati in tempi brevi e divertirci a guardarli.

---

## 2. Principi guida

1. **Realismo matematico** — ogni cifra deve combaciare con la realtà del mercato. Perdite incluse.
2. **Autonomia dell'agente** — una volta partito, l'agente decide da solo. Nessun intervento umano durante la run, altrimenti non si capirebbe più chi contribuisce: l'umano o l'IA.
3. **Timeframe breve** — massimo un mese per la prima run.
4. **Osservabilità** — devo poter monitorare tutto quello che succede e quello che è successo, in modo chiaro e gradevole.

---

## 3. Come funziona l'agente

**Setup iniziale.** Prima della partenza, chi crea l'agente definisce un set di **regole** (strategia, limiti, criteri di buy/sell/hold). Queste regole sono l'unico input umano.

**Run autonoma.** Allo scoccare del via, l'agente opera indisturbato per tutta la durata del timeframe:

- Decide autonomamente quando comprare, vendere o restare fermo.
- Può **osservare senza operare**: a volte simula una mossa solo per vedere cosa sarebbe successo, imparando progressivamente cosa conviene fare.
- Può informarmi delle scelte fatte (log / eventuali notifiche), ma non riceve istruzioni in risposta.

**Stop d'emergenza.** L'unico intervento ammesso è un'interruzione brusca se qualcosa va storto. Niente correzioni o suggerimenti in corsa.

---

## 4. La dashboard

Una dashboard semplice, con aggiornamento in tempo reale (i dati non cambiano ogni secondo, quindi niente complessità inutile).

**Cosa mostra:** l'andamento della strategia IA messo a confronto con dei benchmark passivi, per capire se l'IA batte o sta sotto un investimento "stupido". Tutte le linee partono dallo stesso capitale teorico (**€100**) così sono confrontabili direttamente:

| Linea | Cosa rappresenta |
|---|---|
| **Strategia IA** | I €100 gestiti attivamente dall'agente in crypto |
| **S&P 500 ETF** | €100 investiti nell'indice nello stesso periodo |
| **Nvidia (buy & hold)** | €100 in NVDA comprati all'inizio del timeframe e venduti alla fine |

---

## 5. Stack tecnico

| Componente | Scelta |
|---|---|
| **Backend** | FastAPI (Python), gira 24/7, contiene la logica di trading e decisionale |
| **Decisioni IA** | Integrazione con Claude API |
| **Dati crypto** | API real-time (CoinGecko come candidata — da confermare) |
| **Database** | SQLite o PostgreSQL per lo storico delle transazioni |
| **Dashboard** | Frontend leggero (React o Vue) che consuma una REST API dal backend |
| **Packaging** | Tutto in un **singolo container Docker**, orchestrato con docker-compose |

Backend e dashboard vivono insieme: FastAPI serve sia l'API sia la dashboard statica. Nessuna separazione, tutto in un posto.

---

## 6. Deploy & infrastruttura

- **Hosting:** VPS su Hostinger (gira sempre, requisito necessario per un agente always-on — niente serverless/Netlify).
- **Primo deploy:** manuale sul VPS — clone della repo, `docker compose up`, e il container parte.
- **Deploy successivi:** push su GitHub → webhook sul VPS → pull, rebuild dell'immagine, restart del container. Automatico.

---

## 7. Workflow di sviluppo

Lo sviluppo gira su **Claude Code sul web** (claude.ai/code), in modo asincrono:

1. Creo una repo vuota su GitHub.
2. La collego su claude.ai/code e lancio i task.
3. L'agente lavora nel cloud, su infrastruttura Anthropic, anche a laptop spento.
4. Monitoro da browser o da app mobile quando voglio, e do nuovi task.
5. Il codice viene pushato su un branch (di default con prefisso `claude/`); da lì il webhook fa il deploy sul VPS.

Per un progetto personale come questo si possono abilitare i push diretti, così le modifiche vanno in produzione senza passaggi intermedi.

---

## 8. Da definire

- [ ] **Nome** del progetto.
- [ ] **Target** capitale (€1.000? altro?) e **durata** esatta della run (≤ 1 mese).
- [ ] **Fonte dati** crypto definitiva (CoinGecko vs Binance vs altro).
- [ ] **Regole** della strategia iniziale dell'agente.
- [ ] **Quali crypto** sono nell'universo investibile.

## 9. Fasi successive (non ora)

- Notifiche: PWA, oppure bot Telegram / WhatsApp (preferenza per WhatsApp, anche per esplorare la piattaforma).
- Run più lunghe ed eventuali strategie multiple a confronto.
