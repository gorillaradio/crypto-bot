# Primo deploy VPS + CI/CD — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare il bot in produzione per la prima volta su un VPS esistente (condiviso, con nginx già davanti), esposto in HTTPS su un sottodominio dedicato, e automatizzare test/build/deploy con GitHub Actions + GHCR.

**Architecture:** GitHub Actions su push a `main` esegue test (pytest + vitest + build FE), builda l'immagine singola FE+BE e la pusha su GHCR, poi entra via SSH sul box per `docker compose pull && up -d`. Sul box gira un `docker compose` con `postgres` (volume `pgdata`, non esposto) + `app` (bind su `127.0.0.1:<porta>`), e nginx fa da reverse proxy con TLS verso il sottodominio.

**Tech Stack:** Docker / docker compose, GitHub Actions, GHCR (`ghcr.io/gorillaradio/crypto-bot`), nginx + certbot/Let's Encrypt, Python 3.12/FastAPI, Node 20/Vite, Postgres 16.

## Global Constraints

- Immagine GHCR: `ghcr.io/gorillaradio/crypto-bot` (owner GitHub: `gorillaradio`).
- `OPENROUTER_API_KEY` e DB creds vivono SOLO nel `.env` sul box, mai in CI né nell'immagine.
- Cadenze di produzione: NON sovrascrivere `HEARTBEAT_SECONDS`/`DECISION_SECONDS` → restano i default del codice (300/3600). `INITIAL_CAPITAL_USD=100`.
- Nessuna auth applicativa in questa fase (rischio accettato). Nessun backup DB.
- Il container `app` in prod bind SOLO su `127.0.0.1` (mai `0.0.0.0`): lo raggiunge solo nginx.
- Box CONDIVISO: non toccare la config nginx degli altri servizi, non occupare porte già in uso.
- Postgres resta non esposto all'host. Debug: `docker compose exec postgres psql -U crypto -d crypto`.
- Backend test command: da `backend/`, `pytest -q` (66 pass; 1 warning benigno preesistente httpx/starlette). Frontend: da `frontend/`, `npm ci && npm run test && npm run build`.

## File Structure

| File | Tipo | Responsabilità |
|------|------|----------------|
| `.dockerignore` | nuovo (repo) | Ridurre il contesto di build; escludere `.venv`, `node_modules`, `.git`, docs, `.env`. |
| `docker-compose.prod.yml` | nuovo (repo) | Compose di produzione: `app` da immagine GHCR, bind `127.0.0.1:${APP_PORT}`, postgres con `pgdata`. |
| `.github/workflows/deploy.yml` | nuovo (repo) | Pipeline: job `test` → `build-push` (GHCR) → `deploy` (SSH). Costruito in 3 task. |
| `.env` (sul box) | nuovo (NON in repo) | Segreti + config runtime di produzione. Creato a mano sul box. |
| nginx server block (sul box) | nuovo (NON in repo) | Reverse proxy `<sottodominio>` → `127.0.0.1:${APP_PORT}` + TLS. |

## Note di esecuzione (leggere prima di iniziare)

- **Task 1–4 e 7 (porzione repo)** sono eseguibili da un agente: producono/modificano file nel repo, verificabili localmente o su GitHub.
- **Task 5, 6 e la verifica finale di Task 7** sono **operativi**: richiedono accesso SSH al box, il nome del sottodominio e l'inserimento dei secret su GitHub. Vanno svolti interattivamente con l'utente. Un agente non può completarli senza credenziali.
- **Parametri da raccogliere dall'utente all'inizio di Task 5:**
  - `SUBDOMAIN` — il sottodominio (es. `bot.esempio.com`).
  - `SSH_HOST`, `SSH_USER` — accesso al box.
  - `APP_PORT` — una porta locale **libera** sul box (verificata in Task 5, step 2). Default proposto `8010`.
  - `DEPLOY_DIR` — cartella di deploy sul box (default proposto `/opt/crypto-bot`).

---

### Task 1: `.dockerignore`

**Files:**
- Create: `.dockerignore`

**Interfaces:**
- Consumes: nulla.
- Produces: contesto di build ridotto; il `docker build` deve continuare a funzionare identico (il Dockerfile fa `npm install` e `pip install` da sorgente, quindi escludere artefatti locali non rompe nulla).

- [ ] **Step 1: Scrivere `.dockerignore`**

```
.git
.gitignore
.dockerignore
.github/
.superpowers/
docs/
*.md
.env
.env.*
**/.venv
**/node_modules
frontend/dist
backend/static
**/__pycache__/
**/*.pyc
**/.pytest_cache/
**/.ruff_cache/
**/.mypy_cache/
.DS_Store
.vscode/
.idea/
```

- [ ] **Step 2: Verificare che il build funzioni ancora con il contesto ridotto**

Run: `docker build -t crypto-bot:dockerignore-test .`
Expected: build completa con SUCCESS (frontend buildato in-image, backend installato, dist copiata in `backend/static`).

- [ ] **Step 3: (facoltativo) confermare la riduzione del contesto**

Run: `docker build -t crypto-bot:dockerignore-test . 2>&1 | grep -i "transferring context"`
Expected: dimensione del contesto sensibilmente più piccola rispetto a prima (niente `.venv`/`node_modules`/`.git`).

- [ ] **Step 4: Commit**

```bash
git add .dockerignore
git commit -m "build: add .dockerignore to shrink build context"
```

---

### Task 2: `docker-compose.prod.yml`

**Files:**
- Create: `docker-compose.prod.yml`

**Interfaces:**
- Consumes: immagine `ghcr.io/gorillaradio/crypto-bot:latest` (popolata in Task 4); variabile `APP_PORT` e il file `.env` (presenti sul box, Task 5).
- Produces: definizione dei servizi di prod usata sul box da `docker compose -f docker-compose.prod.yml`.

- [ ] **Step 1: Scrivere `docker-compose.prod.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: crypto
      POSTGRES_PASSWORD: crypto
      POSTGRES_DB: crypto
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U crypto -d crypto"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  app:
    image: ghcr.io/gorillaradio/crypto-bot:latest
    env_file: .env
    ports:
      - "127.0.0.1:${APP_PORT}:8000"
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pgdata:
```

- [ ] **Step 2: Validare la sintassi del compose**

Run: `APP_PORT=8010 docker compose -f docker-compose.prod.yml config`
Expected: output YAML normalizzato senza errori; il bind di `app` risulta `127.0.0.1:8010:8000`; l'immagine è `ghcr.io/gorillaradio/crypto-bot:latest`.

- [ ] **Step 3: Verificare che il bind NON sia pubblico**

Confermare nell'output dello step 2 che la porta host è legata a `127.0.0.1` e non a `0.0.0.0`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "deploy: add production compose (GHCR image, loopback bind)"
```

---

### Task 3: Workflow CI — job `test`

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: i sorgenti `backend/` e `frontend/`.
- Produces: il workflow `deploy.yml` con un job `test` che gli altri job (Task 4, 7) useranno come dipendenza (`needs: test`).

- [ ] **Step 1: Creare `.github/workflows/deploy.yml` con trigger + job `test`**

```yaml
name: deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install backend (with dev deps)
        working-directory: backend
        run: pip install ".[dev]"

      - name: Run backend tests
        working-directory: backend
        run: pytest -q

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend
        working-directory: frontend
        run: npm ci

      - name: Run frontend tests
        working-directory: frontend
        run: npm run test

      - name: Build frontend
        working-directory: frontend
        run: npm run build
```

- [ ] **Step 2: Validare la sintassi YAML del workflow**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"`
Expected: stampa `ok` (nessun errore di parsing).

- [ ] **Step 3: (opzionale, consigliato) provare il job in locale con act**

Se `act` è disponibile: `act -j test`
Expected: backend `pytest` 66 passed; frontend vitest 3 passed; `vite build` SUCCESS.
Se `act` non c'è, salta: la verifica reale avviene al push (step successivo del commit).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add GitHub Actions workflow with backend+frontend test job"
```

- [ ] **Step 5: Verificare il job su GitHub**

Dopo il push del commit su `main`, controllare la tab Actions del repo (`gh run watch` o web).
Expected: il job `test` diventa verde (backend 66 pass, frontend 3 pass + build).

---

### Task 4: Workflow CI — job `build-push` su GHCR

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: job `test` (`needs: test`); il `GITHUB_TOKEN` automatico per autenticarsi a GHCR.
- Produces: l'immagine `ghcr.io/gorillaradio/crypto-bot` con tag `latest` e `${{ github.sha }}` su GHCR. Questa immagine è quella che il box scaricherà (Task 5/7).

- [ ] **Step 1: Aggiungere il job `build-push` in coda al file (dopo il job `test`)**

```yaml
  build-push:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/gorillaradio/crypto-bot:latest
            ghcr.io/gorillaradio/crypto-bot:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Validare la sintassi YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: build and push image to GHCR after tests pass"
```

- [ ] **Step 4: Verificare su GitHub**

Dopo il push su `main`: tab Actions → il job `build-push` diventa verde.
Expected: nei Packages del repo compare `crypto-bot` con tag `latest` e lo SHA. (Se il package nasce privato, va bene: il box userà un token per il pull — vedi Task 5 step 4.)

---

### Task 5: Bootstrap del box (operativo, con l'utente)

> Richiede SSH al box. Raccogliere prima i parametri: `SUBDOMAIN`, `SSH_HOST`, `SSH_USER`, `APP_PORT` (default `8010`), `DEPLOY_DIR` (default `/opt/crypto-bot`).

**Files:**
- Create (sul box): `${DEPLOY_DIR}/docker-compose.prod.yml` (copia del file di repo), `${DEPLOY_DIR}/.env`.

**Interfaces:**
- Consumes: immagine su GHCR (Task 4), `docker-compose.prod.yml` (Task 2).
- Produces: stack `app`+`postgres` attivo sul box, in ascolto su `127.0.0.1:${APP_PORT}`.

- [ ] **Step 1: Verificare Docker sul box**

Run (sul box): `docker --version && docker compose version`
Expected: entrambe rispondono. Se mancano, installare Docker Engine + plugin compose dalla guida ufficiale (`https://docs.docker.com/engine/install/`) prima di proseguire.

- [ ] **Step 2: Scegliere/confermare una porta locale libera**

Run (sul box): `ss -ltnp | grep -E ':(8000|8010)\b' || echo "8000 e 8010 liberi"`
Expected: la porta scelta (`APP_PORT`, default `8010`) NON compare. Se occupata, sceglierne un'altra e aggiornare `APP_PORT` ovunque.

- [ ] **Step 3: Creare la cartella di deploy e copiarvi il compose**

```bash
sudo mkdir -p ${DEPLOY_DIR} && sudo chown $USER ${DEPLOY_DIR}
# copiare docker-compose.prod.yml dal repo a ${DEPLOY_DIR}/ (scp dal locale, o git clone/sparse, o curl raw da GitHub)
```
Expected: `${DEPLOY_DIR}/docker-compose.prod.yml` presente e identico al file di repo.

- [ ] **Step 4: Autenticare il box a GHCR (se il package è privato)**

```bash
# usare un Personal Access Token (classic) con scope read:packages
echo "<GHCR_PAT>" | docker login ghcr.io -u gorillaradio --password-stdin
```
Expected: `Login Succeeded`. (Se il package è pubblico, questo step si può saltare.)

- [ ] **Step 5: Creare il `.env` di produzione**

```bash
cat > ${DEPLOY_DIR}/.env <<'EOF'
APP_PORT=8010
DATABASE_URL=postgresql+psycopg://crypto:crypto@postgres:5432/crypto
OPENROUTER_API_KEY=<la-tua-chiave-reale>
INITIAL_CAPITAL_USD=100
FEE_RATE=0.001
UNIVERSE_DEFAULT=<come-in-locale>
EOF
chmod 600 ${DEPLOY_DIR}/.env
```
Note: NON impostare `HEARTBEAT_SECONDS`/`DECISION_SECONDS` (restano i default 300/3600). Confermare `FEE_RATE`/`UNIVERSE_DEFAULT` con i valori reali (allinearli al `.env` locale).
Expected: file creato, permessi `600`, contiene la chiave reale.

- [ ] **Step 6: Primo pull & avvio**

```bash
cd ${DEPLOY_DIR}
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```
Expected: postgres `healthy`, poi `app` parte. (Se l'immagine non è ancora su GHCR, eseguire prima il workflow via `workflow_dispatch` o un push a `main`.)

- [ ] **Step 7: Verificare migrazioni e healthcheck applicativo**

```bash
docker compose -f docker-compose.prod.yml logs app | grep -i "alembic\|uvicorn\|running"
curl -fsS http://127.0.0.1:8010/ | head -c 200
```
Expected: nei log si vede `alembic upgrade head` completato e uvicorn in ascolto; il `curl` restituisce HTML della dashboard (status 200).

---

### Task 6: nginx reverse proxy + TLS (operativo, con l'utente)

> Box condiviso: aggiungere SOLO un nuovo server block, senza toccare quelli esistenti.

**Files:**
- Create (sul box): nuovo file in `/etc/nginx/sites-available/` (o `/etc/nginx/conf.d/`) per `${SUBDOMAIN}`.

**Interfaces:**
- Consumes: app in ascolto su `127.0.0.1:${APP_PORT}` (Task 5).
- Produces: `${SUBDOMAIN}` raggiungibile in HTTPS, proxy verso l'app.

- [ ] **Step 1: Puntare il DNS del sottodominio al box**

Creare un record A `${SUBDOMAIN}` → IP del box.
Run: `dig +short ${SUBDOMAIN}`
Expected: restituisce l'IP del box (attendere la propagazione).

- [ ] **Step 2: Creare il server block nginx (HTTP, pre-TLS)**

```nginx
server {
    listen 80;
    server_name <SUBDOMAIN>;

    location / {
        proxy_pass http://127.0.0.1:<APP_PORT>;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Abilitare (se `sites-available`): `sudo ln -s /etc/nginx/sites-available/<file> /etc/nginx/sites-enabled/`.

- [ ] **Step 3: Testare e ricaricare nginx**

```bash
sudo nginx -t && sudo systemctl reload nginx
```
Expected: `nginx -t` riporta `syntax is ok` / `test is successful`; reload senza errori; gli altri siti restano up.

- [ ] **Step 4: Emettere il certificato TLS con certbot**

```bash
sudo certbot --nginx -d <SUBDOMAIN>
```
Expected: certbot ottiene il certificato e riscrive il server block con il blocco `listen 443 ssl` + redirect 80→443. (Se certbot non è installato: installarlo dalla guida ufficiale `https://certbot.eff.org/` prima.)

- [ ] **Step 5: Verifica end-to-end via HTTPS**

```bash
curl -fsS https://<SUBDOMAIN>/ | head -c 200
```
Expected: HTML della dashboard su HTTPS (status 200), certificato valido. Aprire il sottodominio nel browser e confermare che la dashboard carica e che si possono vedere/creare agenti.

---

### Task 7: CD — job `deploy` via SSH (auto-deploy su `main`)

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: job `build-push` (`needs: build-push`); secret repo `SSH_HOST`, `SSH_USER`, `SSH_KEY`; lo stack sul box (Task 5) e nginx (Task 6).
- Produces: ogni push a `main` che passa i test ridistribuisce automaticamente l'immagine sul box.

- [ ] **Step 1: Generare una chiave SSH dedicata al deploy e autorizzarla sul box**

```bash
# in locale
ssh-keygen -t ed25519 -f ./deploy_key -N "" -C "github-actions-deploy"
# copiare la PUBBLICA sul box
ssh-copy-id -i ./deploy_key.pub ${SSH_USER}@${SSH_HOST}   # oppure aggiungerla a ~/.ssh/authorized_keys del box
```
Expected: `ssh -i ./deploy_key ${SSH_USER}@${SSH_HOST} 'echo ok'` stampa `ok`.

- [ ] **Step 2: Configurare i secret nel repo GitHub**

```bash
gh secret set SSH_HOST --body "${SSH_HOST}"
gh secret set SSH_USER --body "${SSH_USER}"
gh secret set SSH_KEY  < ./deploy_key
```
Expected: `gh secret list` mostra `SSH_HOST`, `SSH_USER`, `SSH_KEY`. Poi eliminare la chiave privata locale: `rm ./deploy_key ./deploy_key.pub`.

- [ ] **Step 3: Aggiungere il job `deploy` in coda al workflow**

```yaml
  deploy:
    needs: build-push
    runs-on: ubuntu-latest
    steps:
      - name: Deploy over SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_KEY }}
          script: |
            cd /opt/crypto-bot
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d
            docker image prune -f
```
Note: se `DEPLOY_DIR` non è `/opt/crypto-bot`, aggiornare il `cd`. Se GHCR è privato, il box deve restare loggato (Task 5 step 4) — il `docker login` persiste in `~/.docker/config.json`.

- [ ] **Step 4: Validare la sintassi YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "cd: auto-deploy to box over SSH after image push"
```

- [ ] **Step 6: Verifica end-to-end dell'auto-deploy**

Fare un commit di prova innocuo su `main` (es. una riga nel README) e pushare.
Expected: in Actions i job `test → build-push → deploy` diventano tutti verdi; sul box `docker compose -f docker-compose.prod.yml ps` mostra l'immagine aggiornata (SHA nuovo) e l'app risponde ancora su `https://<SUBDOMAIN>/`.

---

## Self-Review

**Spec coverage:**
- Decisione 1 (box esistente) → Task 5. ✓
- Decisione 2 (nginx esistente) → Task 6. ✓
- Decisione 3 (sottodominio + TLS) → Task 6. ✓
- Decisione 4 (nessuna auth) → nessun task (esplicitamente fuori scope; rischio documentato nei Global Constraints). ✓
- Decisione 5 (GHCR registry) → Task 4 (build-push) + Task 5/7 (pull). ✓
- Decisione 6 (auto-deploy su main) → Task 3 trigger + Task 7 deploy. ✓
- Decisione 7 (cadenze default) → Global Constraints + Task 5 step 5 (nessun override). ✓
- Decisione 8 (capitale 100) → Task 5 step 5. ✓
- Decisione 9 (nessun backup) → fuori scope, documentato. ✓
- Decisione 10 (segreti) → Global Constraints + Task 5 step 5 (.env sul box) + Task 7 step 2 (solo SSH in CI). ✓
- `.dockerignore` early win → Task 1. ✓
- `docker-compose.prod.yml` → Task 2. ✓

**Placeholder scan:** i `<SUBDOMAIN>`/`<APP_PORT>`/`<GHCR_PAT>`/`<la-tua-chiave-reale>` sono valori d'ambiente forniti dall'utente a runtime, esplicitamente elencati nelle Note di esecuzione — non placeholder di contenuto mancante.

**Type/consistency:** nomi job (`test`/`build-push`/`deploy`) e catena `needs` coerenti tra Task 3/4/7; nome immagine GHCR identico ovunque; `APP_PORT`/`DEPLOY_DIR` coerenti tra compose, box e job deploy.
