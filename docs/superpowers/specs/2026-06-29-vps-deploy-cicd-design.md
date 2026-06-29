# Design — Primo deploy su VPS + CI/CD

**Date:** 2026-06-29
**Status:** approved (design), pre-implementation
**Repo:** `crypto-bot` · branch `main`

## Obiettivo

Mettere in produzione il bot per la prima volta su un VPS esistente, esposto su un
sottodominio dedicato via HTTPS, e automatizzare build/test/deploy con GitHub Actions.
Sessione prevalentemente infra/decisioni: nessuna nuova feature applicativa.

## Contesto (stato attuale, verificato)

- L'app gira oggi solo in locale via `docker compose up -d --build`, dashboard su `localhost:8000`.
- Immagine **singola** multi-stage (`Dockerfile` a root): `node:20` builda il frontend → `python:3.12-slim` installa `backend/` e copia la dist in `backend/static`. ENTRYPOINT `./entrypoint.sh`.
- `backend/entrypoint.sh`: `alembic upgrade head` poi `uvicorn app.main:app --host 0.0.0.0 --port 8000`. **Le migrazioni si auto-applicano all'avvio del container** — nessuno step manuale di migrazione al deploy.
- `docker-compose.yml`: servizio `postgres` (16-alpine, volume `pgdata`, creds `crypto/crypto/crypto`, healthcheck che gatekeepa `app`) + servizio `app` (`build: .`, `env_file: .env`, porta `8000:8000`).
- `.env` (gitignored, non nel repo): `DATABASE_URL`, `INITIAL_CAPITAL_USD`, `FEE_RATE`, `HEARTBEAT_SECONDS`, `DECISION_SECONDS`, `UNIVERSE_DEFAULT`, `OPENROUTER_API_KEY`. **L'unico segreto reale è `OPENROUTER_API_KEY`.**
- Default cadenze in `backend/app/core/config.py`: `heartbeat_seconds=300`, `decision_seconds=3600`; default `initial_capital_usd=100`. In locale il `.env` li sovrascrive a 60/300 per osservazione.
- **Non esiste `.dockerignore`** → il contesto di build spedisce tutto (`.venv`, `node_modules`, `.git`, ecc.).
- **Non esiste `.github/`** → nessuna CI oggi.
- Test: backend `backend/.venv/bin/pytest backend/tests -q` (66 pass, offline, SQLite in-memory); frontend `cd frontend && npm test` (vitest, 3 pass) + `npm run build`. 1 warning benigno preesistente nel backend (`starlette.testclient`/httpx deprecation).

## Decisioni prese (con l'utente)

| # | Tema | Decisione |
|---|------|-----------|
| 1 | Host | **Box esistente già in uso** (non un host nuovo), **condiviso** con altri servizi. |
| 2 | Reverse proxy | Sul box c'è già **nginx** davanti agli altri servizi; ci agganciamo con un nuovo server block. |
| 3 | Esposizione | **Sottodominio dedicato** + HTTPS (certbot/Let's Encrypt). Nome del sottodominio da fornire in esecuzione. |
| 4 | Auth | **Nessuna auth per v1** — rischio di spesa OpenRouter da `POST /api/agents` aperto esplicitamente accettato dall'utente. L'auth applicativa resta la feature successiva. |
| 5 | Consegna codice | **Registry GHCR**: GitHub Actions builda+pusha l'immagine, il box fa solo pull. Build pesante fuori dal box condiviso. |
| 6 | Trigger deploy | **Automatico su push a `main`** (dopo test verdi). |
| 7 | Cadenze prod | **Default 300/3600** — il `.env` di prod NON sovrascrive le cadenze. |
| 8 | Capitale | `INITIAL_CAPITAL_USD=100` (default). |
| 9 | Backup DB | **Nessun backup** per v1; solo volume `pgdata` persistente. |
| 10 | Segreti | `OPENROUTER_API_KEY` (+ DB creds) vivono nel `.env` **sul box** a runtime, mai in CI né baked nell'immagine. In GitHub solo i secret SSH; GHCR via `GITHUB_TOKEN` automatico. |

## Architettura a regime

```
push → main
  │
  ▼
GitHub Actions
  ① test:  pytest (backend) + vitest + npm run build (frontend)
  ② build: docker build (immagine singola FE+BE)
  ③ push:  → ghcr.io/gorillaradio/crypto-bot:<tag>
  ④ deploy: ssh box → docker compose pull && up -d
  │
  ▼
BOX (condiviso)
  nginx (esistente)
    └─ server block: <sottodominio> ──proxy──▶ 127.0.0.1:<porta-libera>
                                                    │
                                            docker compose
                                              ├─ app  (bind 127.0.0.1:<porta>:8000)
                                              └─ postgres (volume pgdata, non esposto)
```

Note di design:
- Il container `app` sul box **non** pubblica su `0.0.0.0`: bind su `127.0.0.1:<porta-libera>`, solo nginx lo raggiunge. (In locale resta `8000:8000`; il compose di prod usa un override o un file dedicato.)
- Postgres resta non esposto all'host (come oggi). Debug DB: `docker compose exec postgres psql -U crypto -d crypto`.
- TLS gestito da nginx/certbot sul box (non da Traefik/Caddy: lo stack web esistente è nginx).

## Componenti da creare

1. **`.dockerignore`** (root) — escludere `.venv`, `node_modules`, `.git`, `.superpowers/`, `docs/`, file locali. Early win: build più veloce e immagine più pulita.
2. **File compose di produzione** — un `docker-compose.prod.yml` (o override) che:
   - usa `image: ghcr.io/...` invece di `build: .` per il servizio `app`;
   - bind `127.0.0.1:<porta>:8000`;
   - resta su `env_file: .env` (il `.env` di prod sta sul box).
3. **`.env` di produzione (sul box, non nel repo)** — `OPENROUTER_API_KEY` reale, `DATABASE_URL` verso il postgres del compose, `INITIAL_CAPITAL_USD=100`, `FEE_RATE`/`UNIVERSE_DEFAULT` come opportuno, **senza** override di `HEARTBEAT_SECONDS`/`DECISION_SECONDS`.
4. **Server block nginx** (sul box) — `<sottodominio>` → `proxy_pass http://127.0.0.1:<porta>;` + certificato certbot.
5. **GitHub Actions workflow** (`.github/workflows/`) — job test → job build+push GHCR → job deploy SSH; trigger `push` su `main`.
6. **Secret GitHub** — `SSH_HOST`, `SSH_USER`, `SSH_KEY` (chiave dedicata al deploy).

## Sequenza di esecuzione (2 fasi)

### Fase 1 — Bootstrap manuale (validare end-to-end)
1. Accesso SSH al box; verificare presenza di **Docker + docker compose** (installarli se mancano).
2. Creare cartella di deploy sul box; scrivere `.env` di prod a mano.
3. Portare la **prima immagine** su GHCR (primo run del build, anche manuale/`workflow_dispatch`) e fare `docker compose -f ... pull && up -d` a mano.
4. Aggiungere il server block nginx + certificato TLS per il sottodominio.
5. Verifica: dashboard raggiungibile in HTTPS sul sottodominio; agenti creabili; heartbeat/decisioni girano.

### Fase 2 — Automazione CI/CD
6. `.dockerignore` + compose di prod committati nel repo.
7. Workflow Actions completo (test → build → push → deploy SSH) su push a `main`.
8. Configurare i secret SSH nel repo + chiave di deploy sul box.
9. Verifica: un push a `main` di prova builda, pusha e ridistribuisce da solo.

## Prerequisiti da raccogliere in esecuzione

- Nome del **sottodominio** desiderato.
- Accessi **SSH** al box (host, user) e da dove gestire DNS del dominio.
- Conferma/verifica diretta sul box: Docker presente, layout config nginx (`sites-available`/`conf.d`), certbot disponibile, una **porta locale libera** per il bind del container.

## Fuori scope

- Auth applicativa (feature successiva).
- Backup DB.
- Fonti news/informazione (prossimo pezzo di prodotto dopo il deploy).
- Eventuale separazione FE/BE in immagini distinte (l'immagine singola va bene per v1).

## Rischi / consequenze note

- **Nessuna auth**: `POST /api/agents` aperto su URL pubblico → possibile spesa OpenRouter da creazione agenti non autorizzata. Accettato per v1.
- Una modifica solo-frontend richiede comunque il **rebuild dell'intera immagine** (design a immagine singola). Accettabile per v1.
- Box condiviso: il deploy non deve toccare la config nginx degli altri servizi né occupare porte già in uso.
