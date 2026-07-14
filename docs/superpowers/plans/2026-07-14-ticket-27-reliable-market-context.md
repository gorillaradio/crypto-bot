# Reliable Lifecycle Market Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the canonical lifecycle collection return timestamped current market context, 24-hour coin series, and explicit fresh/stale/unavailable disclosure without making accounting depend on Binance availability.

**Architecture:** Keep `GET /api/agents/{agent_id}/lifecycles` as the sole collection seam. Extend `BinanceClient` with a process-lifetime last-known lifecycle market snapshot and return its freshness metadata with every collection page. The API computes all open exposure, portfolio weight, and sorting from one returned price map; the React table renders the supplied series only.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest; React 19, TypeScript, Vitest, Testing Library, Tailwind.

## Global Constraints

- Implement only GitHub ticket #27; do not add master-detail, timeline, mobile layout, surface separation, or legacy cutover work from #28–#32.
- Keep the existing lifecycle endpoint and every legacy endpoint/payload available.
- Market data is context, never lifecycle P&L; the UI must label stale or unavailable state without inventing a quote or series.
- Snapshot prices for all open lifecycle rows must be fetched once per collection response and must be the sole source for exposure, portfolio weight, and open ordering.
- Provider failure must leave lifecycle/accounting rows readable; use last known values and timestamp when available.
- Do not add a manual sort control or animated list reordering.
- Do not read, edit, stage, or delete `.codex/config.toml`.

---

### Task 1: Define the public market context and cache boundary

**Files:**
- Modify: `backend/app/market/binance.py`
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/tests/test_binance.py`

**Interfaces:**
- Produces `LifecycleMarketSnapshot(as_of, prices, series_24h)` from `BinanceClient.get_lifecycle_market_snapshot(symbols)`.
- Produces `LifecycleMarketOut(status: Literal["fresh", "stale", "unavailable"], as_of: datetime | None)` on `LifecycleCollectionOut`.
- Produces `market_series_24h: list[Decimal] | None` on `LifecycleSummary`.

- [ ] **Step 1: Write the failing provider tests**

```python
async def test_lifecycle_market_snapshot_fetches_quotes_and_hourly_closes(respx_mock):
    # ticker snapshot and one 24h kline response for each requested symbol
    snapshot = await BinanceClient().get_lifecycle_market_snapshot(["BTCUSDT", "ETHUSDT"])
    assert snapshot.prices == {"BTCUSDT": Decimal("110"), "ETHUSDT": Decimal("90")}
    assert snapshot.series_24h["BTCUSDT"] == [Decimal("100"), Decimal("110")]
    assert snapshot.as_of.tzinfo is not None
```

- [ ] **Step 2: Run the provider test red**

Run: `.venv/bin/python -m pytest tests/test_binance.py -q`

Expected: FAIL because `get_lifecycle_market_snapshot` and its public result do not exist.

- [ ] **Step 3: Implement the minimum provider contract**

```python
@dataclass(frozen=True)
class LifecycleMarketSnapshot:
    as_of: datetime
    prices: dict[str, Decimal]
    series_24h: dict[str, list[Decimal]]

async def get_lifecycle_market_snapshot(self, symbols: list[str]) -> LifecycleMarketSnapshot:
    # Fetch the universe quote snapshot once, request 24 one-hour closes per distinct symbol,
    # and retain the fully successful result as this client's last-known snapshot.
```

Use `datetime.now(timezone.utc)`, de-duplicate symbols, and propagate provider errors to the collection route; do not invent partial quotes.

- [ ] **Step 4: Add the API schema types**

```python
class LifecycleMarketOut(BaseModel):
    status: Literal["fresh", "stale", "unavailable"]
    as_of: datetime | None = None

class LifecycleSummary(BaseModel):
    # existing fields
    market_series_24h: list[Decimal] | None = None

class LifecycleCollectionOut(BaseModel):
    items: list[LifecycleSummary]
    next_cursor: str | None = None
    market: LifecycleMarketOut
```

- [ ] **Step 5: Run provider tests green**

Run: `.venv/bin/python -m pytest tests/test_binance.py -q`

Expected: PASS.

### Task 2: Project the coherent snapshot through the lifecycle collection

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/tests/test_api.py`
- Test: `backend/tests/test_auth.py` (regression only)

**Interfaces:**
- Consumes `BinanceClient.get_lifecycle_market_snapshot(symbols)` and its last known snapshot.
- Produces `{items, next_cursor, market}` from the existing collection route.

- [ ] **Step 1: Write live-market API tests red**

```python
def test_lifecycle_collection_returns_one_timestamped_snapshot_for_value_weight_order_and_series(db_session):
    # BTC and ETH are open with intentionally opposing quantity/price inputs.
    # The fake market returns one quote map and 24h closes.
    body = client.get(f"/api/agents/{agent.id}/lifecycles").json()
    assert body["market"]["status"] == "fresh"
    assert body["market"]["as_of"]
    assert [row["symbol"] for row in body["items"]] == ["ETHUSDT", "BTCUSDT"]
    assert Decimal(body["items"][0]["exposure_usd"]) == Decimal("300")
    assert Decimal(body["items"][0]["portfolio_weight_pct"]) == Decimal("30")
    assert body["items"][0]["market_series_24h"] == ["90", "100"]
```

Also assert chart series on a closed row in `state=closed` and in `state=all`, while `exposure_usd` remains null on closed rows.

- [ ] **Step 2: Run the targeted API test red**

Run: `.venv/bin/python -m pytest tests/test_api.py -k lifecycle_market -q`

Expected: FAIL because `market` and `market_series_24h` are absent.

- [ ] **Step 3: Implement coherent market projection**

```python
market_snapshot, market_meta = await _lifecycle_market_context(market, symbols)
prices = market_snapshot.prices if market_snapshot else {}
# Build exposure from `prices`; sort and calculate all portfolio weights before pagination.
# Project `market_series_24h` by symbol onto every returned row.
return LifecycleCollectionOut(items=page, next_cursor=next_cursor, market=market_meta)
```

Preserve the current fixed open/closed/all ordering and cursor behavior. Use a module-level `BinanceClient` dependency (or equivalent persistent cache owner), rather than a new client per request, so a later failed request can access the last successful snapshot.

- [ ] **Step 4: Write stale and unavailable API tests red**

```python
def test_lifecycle_collection_uses_timestamped_stale_snapshot_when_provider_fails(db_session):
    first = client.get(url).json()  # controlled successful provider
    second = failing_client.get(url).json()
    assert second["market"] == {"status": "stale", "as_of": first["market"]["as_of"]}
    assert second["items"][0]["exposure_usd"] == first["items"][0]["exposure_usd"]

def test_lifecycle_collection_explicitly_marks_market_unavailable_without_cache(db_session):
    body = failing_client.get(url).json()
    assert body["market"] == {"status": "unavailable", "as_of": None}
    assert body["items"][0]["exposure_usd"] is None
    assert body["items"][0]["portfolio_weight_pct"] is None
    assert body["items"][0]["market_series_24h"] is None
```

- [ ] **Step 5: Implement fallback and regression coverage**

On any provider exception, log once at warning level, return the last known snapshot with `stale`, or empty market fields with `unavailable`. Keep the existing auth, 404, limit, validation, and cursor behavior untouched.

- [ ] **Step 6: Run the lifecycle API suite green**

Run: `.venv/bin/python -m pytest tests/test_api.py tests/test_auth.py -q`

Expected: PASS, including anonymous/revoked viewer regression coverage.

### Task 3: Replace browser-side Sparkline fetching with API-owned data

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/Sparkline.tsx`
- Modify: `frontend/src/__tests__/Sparkline.test.tsx`

**Interfaces:**
- Consumes `LifecycleSummary.market_series_24h`.
- Produces `<Sparkline closes={number[] | null} symbol={string} />` with no network effect.

- [ ] **Step 1: Write the failing component test**

```tsx
it("renders supplied lifecycle closes without calling a browser market API", () => {
  render(<Sparkline symbol="BTCUSDT" closes={[100, 105, 110]} />);
  expect(screen.getByRole("img", { name: /andamento 24h in rialzo/i })).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the Sparkline test red**

Run: `npm test -- src/__tests__/Sparkline.test.tsx`

Expected: FAIL because the component accepts only `symbol` and fetches `getKlines`.

- [ ] **Step 3: Implement the pure rendering component and types**

Remove `getKlines`, `klineCache`, and the browser Binance URL from `api.ts`. Make `Sparkline` derive its SVG, direction, and signed percentage from supplied closes; render the existing unavailable placeholder for null or fewer than two points.

- [ ] **Step 4: Run the component test green**

Run: `npm test -- src/__tests__/Sparkline.test.tsx`

Expected: PASS.

### Task 4: Render chart and freshness disclosure in all desktop list states

**Files:**
- Modify: `frontend/src/components/PositionsTable.tsx`
- Modify: `frontend/src/__tests__/PositionsTable.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/__tests__/App.auth.test.tsx`

**Interfaces:**
- Consumes `LifecyclePage.market` and lifecycle series from `getLifecycles`.
- Produces the stable left table zone `Coin | 24h` for `open`, `closed`, and `all`, plus an accessible fresh/stale/unavailable disclosure.

- [ ] **Step 1: Write failing desktop rendering tests**

```tsx
it.each(["open", "closed", "all"] as const)("renders the API sparkline in %s", (state) => {
  render(<PositionsTable state={state} market={staleMarket} items={[lifecycle({ market_series_24h: [100, 110] })]} />);
  expect(screen.getByRole("columnheader", { name: "24h" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /andamento 24h/i })).toBeInTheDocument();
  expect(screen.getByText(/dato di mercato non aggiornato/i)).toBeInTheDocument();
});

it("declares unavailable market data without a fabricated chart", () => {
  render(<PositionsTable state="open" market={unavailableMarket} items={[lifecycle({ market_series_24h: null })]} />);
  expect(screen.getByText(/dati di mercato non disponibili/i)).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /andamento 24h/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the table test red**

Run: `npm test -- src/__tests__/PositionsTable.test.tsx`

Expected: FAIL because `PositionsTable` has no market metadata or chart column.

- [ ] **Step 3: Implement the narrow UI slice**

Pass `page.market` from `App` to `PositionsTable`. Insert the 24h chart next to Coin as the desktop stable-left column in every table schema. Use text plus existing semantic colors for fresh/stale/unavailable; stale copy includes the returned timestamp. Do not add CSS transitions to table rows and do not change polling, filters, or pagination logic.

- [ ] **Step 4: Add polling/pagination regression test**

Verify the fetched `market` response reaches the table and that existing `Aperte`/`Chiuse`/`Tutte`, filters, and `Carica altro` behavior still use the canonical collection request. Assert no class or style adds an order-changing transition/animation.

- [ ] **Step 5: Run frontend feature tests green**

Run: `npm test -- src/__tests__/Sparkline.test.tsx src/__tests__/PositionsTable.test.tsx src/__tests__/App.auth.test.tsx`

Expected: PASS.

### Task 5: Verify scope and deliver the ticket

**Files:**
- Review: all modified files.

- [ ] **Step 1: Run focused suites**

Run: `.venv/bin/python -m pytest tests/test_binance.py tests/test_api.py tests/test_auth.py -q`

Run: `npm test -- src/__tests__/Sparkline.test.tsx src/__tests__/PositionsTable.test.tsx src/__tests__/App.auth.test.tsx`

- [ ] **Step 2: Run full verification**

Run: `.venv/bin/python -m pytest`

Run: `npm test`

Run: `npm run lint`

Run: `npm run build`

- [ ] **Step 3: Check acceptance criteria against observed evidence**

Confirm the test evidence covers live coherent quote/order/weight, series on all collection states, stale timestamp, no-known-data unavailability, auth/validation regressions, and all three desktop React renderings. Inspect `git diff --check` and `git status --short`; verify no legacy endpoint, paper data, or ticket #28–#32 surface changed.

- [ ] **Step 4: Commit the ticket**

```bash
git add backend/app/market/binance.py backend/app/api/routes.py backend/app/api/schemas.py backend/tests/test_binance.py backend/tests/test_api.py frontend/src/api.ts frontend/src/components/Sparkline.tsx frontend/src/components/PositionsTable.tsx frontend/src/App.tsx frontend/src/__tests__/Sparkline.test.tsx frontend/src/__tests__/PositionsTable.test.tsx frontend/src/__tests__/App.auth.test.tsx docs/superpowers/plans/2026-07-14-ticket-27-reliable-market-context.md
git commit -m "feat: add reliable lifecycle market context (#27)"
```
