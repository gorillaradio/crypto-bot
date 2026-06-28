# D2 Deploy Report — One-Command Docker Deploy

Date: 2026-06-28
Branch: feat/v0-scaffolding

## Files Changed

| File | Change |
|------|--------|
| `docker-compose.yml` | Added `postgres` service with healthcheck (`pg_isready -U crypto -d crypto`, interval 5s, timeout 3s, retries 5); removed SQLite volume; added `pgdata` named volume; changed `app.depends_on` to `condition: service_healthy` |
| `Dockerfile` | Added `RUN chmod +x entrypoint.sh`; changed `CMD` to `ENTRYPOINT ["./entrypoint.sh"]` |
| `backend/entrypoint.sh` | New file — runs `alembic upgrade head` then `exec uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `.env.example` | Updated `DATABASE_URL` from SQLite to `postgresql+psycopg://crypto:crypto@postgres:5432/crypto` |

## Alembic wiring confirmed

`backend/alembic/env.py` already reads `DATABASE_URL` from env via `os.environ.get("DATABASE_URL", settings.database_url)` — no changes needed.

## Live Smoke Test (docker compose up --build -d)

Container logs confirmed alembic ran before uvicorn:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 4fe169988067, initial schema
INFO:     Application startup complete.
```

### curl /health
```
{"status":"ok"}
```

### curl POST /api/agents
```
{"id":1,"name":"Smoke","instructions":"x","status":"running","cash_usd":"100.00000000"}
```
HTTP 201 Created.

### curl GET /api/agents
```
[{"id":1,"name":"Smoke","instructions":"x","status":"running","cash_usd":"100.00000000"}]
```

## Test Suite

```
29 passed, 1 warning in 0.24s
```

1 warning: `httpx` + `starlette.testclient` deprecation notice (pre-existing, unrelated to this change).

## Concerns

None. The `pgdata` volume is preserved across `docker compose down` (no `-v` flag used at cleanup).
