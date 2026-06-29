# Auth — Design

**Date:** 2026-06-29
**Status:** Approved (pending spec review)

## Goal

Put the app behind access control. Today the API is fully open on the public
internet: anyone can hit `POST/PATCH/DELETE /api/agents` and create or delete
trading agents — and LLM agents burn real OpenRouter credits. We need:

- **One owner (admin) = the user** — logs in with a password, full read + write.
- **Viewers** — people the owner gives read-only visibility, via **secret
  shareable links**. No accounts, no passwords, no signup.
- **Multiple links at once**, each with an optional label, each individually
  **revocable**, revocation effective immediately.
- A small **admin UI** to create / copy / revoke those links.

The whole app requires access. Nothing is publicly visible except the login
screen and the link-exchange handshake.

## Why not Clerk / WorkOS / Better Auth (decision)

They solve a different problem — **many users who each own an account**
(signup, social login, MFA, orgs, enterprise SSO). Our model is **one owner +
anonymous read-only share links**; none of them has a native primitive for
that, so we'd still hand-build the `share_links` table and viewer logic on top.
Adding an external identity platform to authenticate a single person, and still
writing the link part ourselves, is more moving parts, not fewer. Cost is not
the driver (their free tiers cover this scale comfortably) — fit is.

We use the framework's **signed-cookie session** (Starlette `SessionMiddleware`,
backed by `itsdangerous`) plus Python stdlib (`secrets` for tokens and
constant-time compare). We do **not** hand-roll any crypto, password hashing, or
session signing — those are exactly the parts a managed service would own, and
here the framework already owns them.

**Revisit trigger:** if the project becomes genuinely multi-user (other people
register their own accounts, "sign in with Google", teams, SSO), adopt Clerk (or
WorkOS AuthKit) then — don't grow a hand-rolled account system.

## Scope decisions (agreed)

| Topic | Decision |
|---|---|
| Owner identity | **Single admin**, password in env (`ADMIN_PASSWORD`). No registration, no reset flow. |
| Viewer identity | **No accounts.** Access via secret link only; read-only. |
| Links | **Multiple**, each with optional label, each individually revocable. Revocation is immediate. |
| Session mechanism | Starlette **`SessionMiddleware`** — signed cookie via `SECRET_KEY`. No session table. |
| Cookie payload | `{role:"admin"}` or `{role:"viewer","link_id":N}`. Signed (tamper-proof), **not** secret. |
| Token storage | Token stored **plaintext** in `share_links` so the admin UI can re-display and re-copy an existing link. |
| Viewer link format | URL **hash fragment**: `https://<host>/#<token>`. Token never sent to the server in a URL; exchanged client-side via POST body. |
| API gating | Every `/api` data endpoint requires a session. SPA bundle + `/health` stay public. |

### Non-goals
- No multi-user accounts, signup, social login, MFA, or SSO (that's the
  Clerk revisit trigger, not this work).
- No password reset / "forgot password" — the admin password is an env var.
- No per-link permission scopes or expiry dates — links are read-only and live
  until revoked.
- No login rate-limiting / lockout in v1 (noted as optional hardening below; a
  256-bit token and a strong admin password are the v1 defense).

## Threat model (what this does and doesn't protect)

- **Protects:** the write endpoints (no anonymous agent create/delete →
  credits safe) and the data endpoints (no anonymous read of the dashboard).
- **Bearer model:** a viewer link is a bearer secret — whoever holds it can
  view, until revoked. That's the intended sharing mechanism, not a weakness.
- **Signed, not encrypted cookie:** the cookie's contents (`role`, `link_id`)
  are visible to the holder but cannot be forged without `SECRET_KEY`. We put
  **nothing sensitive** in it. The admin password and link tokens are never in
  the cookie.

---

## Backend changes

All in `backend/app/`.

### 1. `core/config.py` — new settings
- `admin_password: str = ""` — empty means admin login is **disabled** (fail
  closed: an empty submitted password never matches an empty configured one).
- `secret_key: str = ""` — required; app refuses to start with a clear error if
  empty (see `main.py`). No silent ephemeral fallback (it would invalidate all
  sessions on every restart and mask a misconfig).
- `session_https_only: bool = True` — cookie `Secure` flag. `True` in prod
  (HTTPS); local dev `.env` sets `False` so the cookie works over `http://localhost`.
- `session_max_age_seconds: int = 1209600` — 14 days.

### 2. `db/models.py` — new model `ShareLink`
Columns:
- `id: int` PK
- `label: str | None` — optional human label ("amici", "twitter", …)
- `token: str` — unique, indexed; `secrets.token_urlsafe(32)` (~256-bit)
- `created_at: datetime` — UTC, default now

Matches existing model conventions in the file (declarative `Base`, same column
style as `Agent`).

### 3. Alembic migration
New revision, `down_revision = "e5f6a7b8c9d0"` (current head). Creates the
`share_links` table with a unique index on `token`. Runs automatically at deploy
via `entrypoint.sh` (`alembic upgrade head`).

### 4. `api/auth.py` (new) — session helpers + dependencies
- `current_role(request) -> "admin" | "viewer" | None` — reads
  `request.session`. For a viewer, **re-validates** `link_id` against
  `share_links`; if the row is gone (revoked) → treat as `None`.
- `require_admin` — FastAPI dependency: role must be `admin`, else `401`.
- `require_viewer_or_admin` — dependency: role must be `admin` or a **still-valid**
  `viewer`, else `401`.

(Re-validation hits the DB on every gated request. Fine at this scale; it's what
makes revocation immediate.)

### 5. `api/routes.py` — new endpoints + apply dependencies

New auth endpoints (public — no session required to call them):
| Method | Path | Body | Success | Failure |
|---|---|---|---|---|
| POST | `/api/auth/login` | `{password}` | `200 {role:"admin"}` + sets cookie | `401` (wrong/empty password) |
| POST | `/api/auth/logout` | — | `204`, clears session | — |
| GET | `/api/auth/me` | — | `200 {role:"admin"\|"viewer"\|null}` | never errors |
| POST | `/api/auth/viewer` | `{token}` | `200 {role:"viewer"}` + sets cookie | `401` (invalid/revoked token) |

`/api/auth/me` re-validates a viewer's `link_id` too: a revoked viewer gets
`{role:null}` on the next poll and is bounced to login.

New admin-only share-link management (depends on `require_admin`):
| Method | Path | Body | Success |
|---|---|---|---|
| GET | `/api/share-links` | — | `200 [{id,label,token,url,created_at}]` |
| POST | `/api/share-links` | `{label?}` | `201 {id,label,token,url,created_at}` |
| DELETE | `/api/share-links/{id}` | — | `204` (revoke); `404` if missing |

`url` is computed for convenience: `f"{request.base_url}#{token}"` (the full link
the admin copies).

Apply dependencies to existing routes:
- **Writes** — `POST /agents`, `PATCH /agents/{id}`, `DELETE /agents/{id}` →
  `Depends(require_admin)`.
- **Reads** — all `GET /agents…` → `Depends(require_viewer_or_admin)`.

`/health` stays public. `session_dep` is unchanged.

### 6. `main.py` — middleware + startup guard
- Add `SessionMiddleware` **before** `include_router`:
  `secret_key=settings.secret_key`, `session_cookie="crypto_session"`,
  `https_only=settings.session_https_only`, `same_site="lax"`,
  `max_age=settings.session_max_age_seconds`. (Starlette sets the cookie
  `HttpOnly` and `path=/` itself.)
- At startup, if `settings.secret_key` is empty → raise `RuntimeError` with a
  clear message (fail fast, don't boot insecure).
- StaticFiles mount at `/` stays **last** (unchanged). Because the viewer token
  lives in the URL hash, the root `/` is always served by the existing mount —
  **no SPA fallback routing needed.**

### 7. `api/schemas.py` — request/response models
`LoginIn{password}`, `ViewerIn{token}`, `MeOut{role}`, `ShareLinkIn{label?}`,
`ShareLinkOut{id,label,token,url,created_at}`.

---

## Frontend changes

All in `frontend/src/`.

### 1. `api.ts`
- `me()` → `GET /api/auth/me` → `{role}`.
- `login(password)` → `POST /api/auth/login`.
- `logout()` → `POST /api/auth/logout`.
- `exchangeViewerToken(token)` → `POST /api/auth/viewer`.
- `listShareLinks()`, `createShareLink(label?)`, `revokeShareLink(id)`.
- The existing `get`/`mutate` helpers must treat **`401` as "session lost"** so
  callers can flip the app back to the login screen instead of showing a generic
  error. The session cookie rides along automatically because the SPA is served
  **same-origin** by the backend (in prod, and locally when testing the built
  bundle out of `backend/static`) — no `credentials` change needed. Only a
  separately-run `vite dev` server (cross-origin → backend) would require
  `credentials:"include"` + backend CORS; we avoid that by testing via the built
  bundle.

### 2. `App.tsx` — gate + roles
- On mount: if `window.location.hash` looks like a token, call
  `exchangeViewerToken(hash)`, then `history.replaceState` to clear the hash
  (token never lingers in the address bar / history).
- Then call `me()`:
  - `role === null` → render `<Login/>`.
  - `role === "admin"` → full dashboard + **"Condividi"** button + **Logout**.
  - `role === "viewer"` → dashboard in **read-only**: hide create / edit / delete
    controls; show **Logout**.
- If any data fetch returns `401` mid-session (e.g. viewer revoked), flip to the
  login screen.
- Binance klines (client-side, direct to Binance) are unaffected by auth.

### 3. New components
- **`Login.tsx`** — single password field → `login()` → on success re-run `me()`.
  Wrong password shows an inline error; field stays for retry.
- **`ShareLinksModal.tsx`** ("Condividi") — admin only. Lists existing links
  (label + full copyable URL + created date), a "crea link" action with an
  optional label, and a per-link "revoca". On create/revoke, refetch the list.
  Reuses existing modal/overlay/button styles from `index.css`.

### 4. `index.css`
Reuse existing `.modal-overlay`, `.modal`, `.btn-*` styles. Add only what the
login screen and the link rows need, consistent with the control-room aesthetic
(quiet, dense; respect `prefers-reduced-motion`).

## Data flow

```
Admin:
  load "/" → me() → null → <Login/> → login(password)
    → 200 sets admin cookie → me() → "admin" → full dashboard
  "Condividi" → ShareLinksModal → createShareLink("amici")
    → 201 {url} → admin copies https://host/#<token>

Viewer:
  opens https://host/#<token>
    → App reads hash → exchangeViewerToken(token)
      → 200 sets viewer cookie → clear hash → me() → "viewer"
      → read-only dashboard (no write controls)

Revoke:
  admin DELETE /api/share-links/{id}
    → viewer's next /api call re-validates link_id → gone → 401
    → viewer app flips to <Login/> (no password → no access)
```

## Error handling
- Login/exchange failures surface inline; the screen stays for retry.
- `401` on data fetches = session lost → login screen (not a generic error toast).
- Share-link create/revoke failures show a non-blocking message in the modal.

## Config / deploy
- New env vars on the box (`/opt/crypto-bot/.env`):
  - `ADMIN_PASSWORD=<chosen password>`
  - `SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(32))">`
  - (prod leaves `SESSION_HTTPS_ONLY` default `True`.)
- Local dev `.env`: set `ADMIN_PASSWORD`, a throwaway `SECRET_KEY`, and
  `SESSION_HTTPS_ONLY=false` (cookie over `http://localhost`).
- Migration runs automatically at deploy. **Until the env vars are set on the
  box, admin login fails closed and the app refuses to boot without `SECRET_KEY`
  — set them as part of the deploy, not after.**

## Security considerations
- `secrets.compare_digest` for the password check (constant-time).
- Empty `ADMIN_PASSWORD` ⇒ login always fails (no empty-matches-empty).
- Token entropy ~256 bits (`token_urlsafe(32)`); unique-indexed.
- Cookie: signed (itsdangerous), `HttpOnly`, `SameSite=Lax`, `Secure` in prod;
  contains only `role`/`link_id`.
- Viewer access re-validated against the DB on every request → immediate revoke.
- **Optional hardening (not v1):** rate-limit `/api/auth/login`. Documented for
  later; the token entropy + strong password are the v1 defense.

## Testing

### Backend (`backend/tests/test_auth.py`, new)
Client fixture wires `SessionMiddleware` + overrides `session_dep` to the
in-memory `db_session`, with `ADMIN_PASSWORD`/`SECRET_KEY` set for the test.
- login: correct password → `200`, then `/me` → `admin`.
- login: wrong password → `401`; empty configured password → always `401`.
- `/me` with no session → `{role:null}`.
- viewer exchange: valid token → `200`, then `/me` → `viewer`.
- viewer exchange: unknown token → `401`.
- **revocation immediate:** exchange a link, then `DELETE` it (as admin), then a
  viewer read → `401` and `/me` → `null`.
- writes (`POST/PATCH/DELETE /agents`): anon → `401`, viewer → `401`,
  admin → success.
- reads (`GET /agents`): anon → `401`, viewer → success, admin → success.
- share-links: anon/viewer → `401`; admin can create, list, delete; deleted id
  → `404`.

### Frontend (`frontend/src/__tests__/`)
- `App`: `me()` → null renders `<Login/>`; → "viewer" hides create/edit/delete;
  → "admin" shows Condividi + write controls (mock the api module, matching the
  existing vitest + testing-library style).
- `Login`: wrong password shows error and keeps the field; success triggers a
  re-check.
- `ShareLinksModal`: "crea link" calls `createShareLink`; a row's "revoca" calls
  `revokeShareLink`; the full link URL is shown/copyable.
- hash-token bootstrap: a `#<token>` on load calls `exchangeViewerToken` and the
  hash is cleared.

## Files touched
- `backend/app/core/config.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/<new>_share_links.py` (new)
- `backend/app/api/auth.py` (new)
- `backend/app/api/routes.py`
- `backend/app/api/schemas.py`
- `backend/app/main.py`
- `backend/tests/test_auth.py` (new)
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/components/Login.tsx` (new)
- `frontend/src/components/ShareLinksModal.tsx` (new)
- `frontend/src/index.css`
- `frontend/src/__tests__/Login.test.tsx` (new)
- `frontend/src/__tests__/ShareLinksModal.test.tsx` (new)
- `frontend/src/__tests__/App.auth.test.tsx` (new)
- `.env.example` / deploy `.env` (document `ADMIN_PASSWORD`, `SECRET_KEY`, `SESSION_HTTPS_ONLY`)
