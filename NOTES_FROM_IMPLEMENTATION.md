# Notes from Implementation (Task 01)

Deviations from the Task 01 brief and API behavior observed during implementation.

## Gamma API deviations

**No `tags` field in response.** The brief describes `tags` as a list of strings on each market. The live API (verified 2026-04-25) returns no `tags` field. Instead:
- Category filtering uses the `tag=` query parameter (e.g. `?tag=politics`).
- The response includes `events[0].title` which contains a human-readable category label (e.g. "Geopolitics: Will X happen?").
- We store `events[0].title` (or `groupItemTitle` as fallback) in `category_raw`.

**`clobTokenIds` is a JSON-encoded string, not an array.** The field comes back as a JSON string `"[\"111...\", \"222...\"]"` and requires `json.loads()` before use. YES token is at index 1.

**`conditionId` vs `id`.** The numeric `id` field is Polymarket's internal market ID. The `conditionId` field (`0x...` hex) is the canonical ID used everywhere in the system. We use `conditionId` as the primary key.

## CLOB API deviations

**`interval` parameter means time range, not candle resolution.** Known values: `1m` (1 month), `1w`, `1d`, `6h`, `1h`. The brief's example of `interval=1m&fidelity=1` fails: minimum fidelity for the `1m` range is 10.

**Use `startTs`/`endTs` for 1-minute candles.** When `startTs` and `endTs` are provided with `fidelity=1`, the API returns 1-minute candles regardless of `interval`. This is the correct approach for full historical backfill.

**No volume in price-history endpoint.** The `/prices-history` endpoint returns only `{"t": unix_ts, "p": price}`. `volume_minute` is stored as NULL.

## UMA collector approach

**Using UMA subgraph, not direct RPC.** Direct decoding of `OptimisticOracleV2` logs via JSON-RPC was deferred to Task 02 per the brief's recommendation. The UMA subgraph on The Graph is used for Task 01. The search approach (scan all Polymarket requester requests, match by market_id in ancillaryData) is O(n) and may be slow for large backfills — optimize in Task 02 with direct RPC.

**UMA subgraph URL.** Used `C8jHSA2ZEaJ8h9pK7XFMnNGnNsA4cNJgN6eHmJWjxBqv` subgraph ID on The Graph. Verify this is current before running the UMA collector.

## Subgraph entity name

The brief uses `orderFilledEvents` as the GraphQL entity name. The actual entity on the current Polymarket subgraph is `orderFilleds` (verified by schema inspection). Updated accordingly.

## Price computation from subgraph

Subgraph amounts (`makerAmountFilled`, `takerAmountFilled`) are in base units (scaled by 1e6 for USDC, 1e6 for shares). Price = (USDC_paid / shares_received), both already divided by 1e6, so: `price = usdc_paid_raw / shares_raw` (no further scaling needed).
