# Polygonscan Collection — Status Report

**Last updated:** 2026-04-27  
**Branch:** task02h/ffic-trade-backfill

---

## Current State

| Metric | Value |
|---|---|
| Total wallets in DB | 815,304 |
| Enriched (`first_seen_chain_at` set) | 2,449 (0.3%) |
| With `funding_sources` data | 4,706 (0.6%) |
| Attempted but returned empty | 810,598 (99.4%) |
| **Stale wallets remaining** | **812,855** |
| Estimated time to complete at 4 req/s | **56.4 hours** |

**Progress snapshot:** 2,449 wallets with confirmed on-chain data. The collection
has barely started relative to the full corpus (< 1% enriched).

---

## Run History

| Run ID | Date | Duration | Status | n_written | Error |
|---|---|---|---|---|---|
| 11714 | 2026-04-27 05:28 | 2s | failed | 0 | Deprecated V1 endpoint |
| 11715 | 2026-04-27 05:29 | 1s | failed | 0 | Deprecated V1 endpoint |
| 11716 | 2026-04-27 05:29 | 34s | failed | 0 | DNS resolution failure |
| 11717 | 2026-04-27 06:15 | — | ~~running~~ → failed | 0 | Process died without cleanup *(closed manually)* |
| 11718 | 2026-04-27 06:23 | 78s | failed | 0 | Rate limit: Max 3 req/s |
| 11719 | 2026-04-27 06:24 | — | ~~running~~ → failed | 0 | Process died without cleanup *(closed manually)* |
| 11720 | 2026-04-27 06:25 | 14,352s (~4h) | failed | 0 | Server timeout / too busy |

**All 7 runs failed.** Two stale `running` records (ids 11717, 11719) were left open by
crashed processes — closed manually on 2026-04-27.

---

## Failure Taxonomy

### 1. Deprecated V1 endpoint (runs 11714–11715, 3s)
- **Error:** `NOTOK | You are using a deprecated V1 endpoint, switch to Etherscan V2`
- **Root cause:** `polygonscan_url` in config was `https://api.polygonscan.com/api` — deprecated.
- **Fix already applied:** config.py now uses `https://api.etherscan.io/v2/api` (the V2 unified endpoint). This fix is on `task02d+` branches but was re-applied on `task02h` via config.py update.

### 2. DNS failure (run 11716, 34s)
- **Error:** `[Errno 8] nodename nor servname provided, or not known`
- **Root cause:** Transient network failure — no code issue.

### 3. Rate limit exceeded (run 11718, 78s)
- **Error:** `Max calls per sec rate limit reached (3/sec)`
- **Root cause:** The `.env` key is a free-tier key capped at **3 req/s** (not 5 as the code assumes). The `_RATE_LIMIT` constant in `polygonscan.py` is set to 4 req/s, which exceeds the actual key limit.
- **Fix needed:** Set `_RATE_LIMIT = 2` (conservative, below the 3/sec cap) to avoid triggering rate errors.

### 4. Server timeout (run 11720, ~4h)
- **Error:** `Unexpected error, timeout or server too busy. Please try again`
- **Root cause:** The `all_stale` batch queried 812,855 wallets in a single long-running process. After ~4 hours the Etherscan/Polygonscan API returned a server error that wasn't retried gracefully. The collector has no checkpoint/resume — on failure the entire run is lost.
- **Fix needed:** Add a checkpoint mechanism: persist progress (last completed wallet address) to `data_collection_runs.run_metadata` every N wallets, and resume from that address on restart.

---

## Last Enriched Wallets (checkpoint for resume)

These are the 5 most recently enriched wallets (by `last_refreshed_at`), usable as
resume anchors if the collector is restarted alphabetically or by `first_seen_polymarket_at`:

| Wallet address | last_refreshed_at |
|---|---|
| `0x3801c747ac8ae7fa77514dd852e81f44376883dd` | 2026-04-27 ~06:18 UTC |
| `0xec8d797a40d5990d00e7468f347c732d4e3b453d` | 2026-04-27 ~06:18 UTC |
| `0x1b73480fbf1bc450991d93f687570ccdf6b545d9` | 2026-04-27 ~06:18 UTC |
| `0xd713f0d2761a77f7834dcbbbc8a25abc319daf79` | 2026-04-27 ~06:18 UTC |
| `0x4f5e6216719c7347caf4dc42cf49013ce4671773` | 2026-04-27 ~06:18 UTC |

The `_get_stale_wallets` query does **not** order by any resumable key — it returns all
wallets where `first_seen_chain_at IS NULL OR last_refreshed_at < cutoff`. Without a
checkpoint, a resume re-queries all 812,855 wallets from scratch, but `ON CONFLICT DO
UPDATE` on `address` means already-enriched wallets are safely overwritten with the same
data. The 2,449 already-enriched wallets will not be re-queried (they have
`first_seen_chain_at IS NOT NULL` and a recent `last_refreshed_at`).

---

## Blockers Before Next Run

Two fixes required before the next `--all-stale` run will succeed:

### Fix A — Rate limit (required)
In `fflow/collectors/polygonscan.py`, change:
```python
_RATE_LIMIT = 4  # req/s  ← exceeds actual free-tier cap of 3/sec
```
to:
```python
_RATE_LIMIT = 2  # req/s  ← conservative under 3/sec free-tier cap
```

### Fix B — Checkpoint/resume (strongly recommended for full corpus)
At 2 req/s the full 812,855-wallet run would take **113 hours** (~4.7 days). Without
checkpoint/resume, any interruption (network blip, server timeout, process kill) loses
all progress and restarts from scratch.

Minimal implementation: every 1,000 wallets, write `{"last_address": addr, "n_done": n}`
to `data_collection_runs.run_metadata` for the current run. On restart, read the metadata
and pass `address > last_address` to `_get_stale_wallets`.

### Fix C — API key upgrade (optional but recommended)
A paid Etherscan/Polygonscan key unlocks 10+ req/s (vs 3/sec free). At 10 req/s the
full corpus would take ~22 hours (manageable in a single overnight run). Cost: ~$10-20/month.

---

## Recommendation for Next Run

Priority order:
1. Apply Fix A (rate limit) — 5 min change, prevents immediate failure.
2. Apply Fix B (checkpoint) — prevents 4-hour loss on next server timeout.
3. Run `fflow collect polygonscan --all-stale` in a tmux/screen session or as a background service.
4. Monitor via `SELECT COUNT(*) FROM wallets WHERE first_seen_chain_at IS NOT NULL` — should increment steadily.

At 2 req/s without Fix B, expect the run to take 4+ days. With Fix B + checkpoint, interruptions become recoverable.

---

## Why This Matters for Task 03

The polygonscan `funding_sources` field identifies wallet provenance — whether a trader
funded from a CEX, another wallet cluster, or fresh on-chain. This is a secondary signal
for insider-trading detection (well-funded wallets with pre-news positions are stronger
candidates than retail wallets). The 2,449 currently enriched wallets are a small fraction
of the relevant population. Full enrichment is not a blocker for Task 03 ILS methodology,
but is needed for the full wallet-level analysis in Task 04+.
