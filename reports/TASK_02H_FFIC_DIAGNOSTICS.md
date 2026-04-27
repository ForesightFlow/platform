# Task 02h — FFIC Trade-History Diagnostics

**Generated:** 2026-04-27  
**Branch:** task02h/ffic-trade-backfill

Per-market diagnosis of missing trade history for all 24 FFIC markets.

---

## Diagnostic Table

| Case | Label | Market ID | Vol ($) | Trades in DB | n_runs | Last status | n_written | Diagnosis | Recommendation |
|---|---|---|---|---|---|---|---|---|---|
| fficd-001 | Trump wins | `0xdd22472e552920…` | 1,531,479,285 | 0 | 4 | failed | 0 | ran_indexer_failed | try_rpc_direct |
| fficd-001 | Harris wins | `0xc6485bb7ea46d7…` | 1,037,039,118 | 0 | 1 | failed | 0 | ran_indexer_failed | try_rpc_direct |
| fficd-001 | Other Republican wins | `0x55c551896c10a7…` | 241,655,100 | 0 | 1 | failed | 0 | ran_indexer_failed | try_rpc_direct |
| fficd-001 | Michelle Obama wins | `0x230144e34a84df…` | 153,382,276 | 0 | 1 | failed | 0 | ran_indexer_failed | try_rpc_direct |
| fficd-002 | Iran strike today | `0xc1b6d7128a66a7…` | 148,732 | 309 | 1 | success | 309 | ok | ok |
| fficd-002 | Another strike by Friday | `0x9372742055caba…` | 100,479 | 607 | 1 | success | 607 | ok | ok |
| fficd-002 | Iran strike by Nov 8 | `0xc83128531d31cc…` | 788,895 | 1,929 | 1 | success | 1929 | ok | ok |
| fficd-003 | US forces enter Iran by Apr 30 | `0x6d0e09d0f04572…` | 269,049,107 | 0 | 2 | running | — | ran_indexer_failed | try_rpc_direct |
| fficd-003 | US-Iran ceasefire by Apr 7 | `0x4c5701bcde0b8f…` | 173,696,184 | 0 | 1 | failed | 0 | ran_indexer_failed | try_rpc_direct |
| fficd-003 | Khamenei out by Feb 28 | `0xd4bbf7f6707c67…` | 131,114,971 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-003 | Israel-Hezbollah ceasefire by Apr 18 | `0x9823d715687a0a…` | 98,599,882 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-003 | US strikes Iran by Feb 28 | `0x3488f31e6449f9…` | 89,652,867 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-003 | Khamenei out by Mar 31 | `0x70909f0ba8256a…` | 63,238,698 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-004 | Maduro in US custody by Jan 31 | `0xbfa45527ec959a…` | 11,034,070 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-004 | US-Venezuela military by Dec 31 | `0x62b0cd598091a1…` | 51,073,021 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-004 | US invades Venezuela by Jan 31 | `0x7f3c6b9029a1a4…` | 8,368,551 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-005 | Bitcoin ETF approved by Jan 15 | `0xb36886bb0cf7ce…` | 12,622,418 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-006 | Gene Hackman #1 Passings | `0x54361608e7307b…` | 2,952,428 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-006 | Ismail Haniyeh #1 Passings | `0x4512635352a1ae…` | 1,591,632 | 358 | 1 | success | 358 | ok | ok |
| fficd-006 | Zendaya #1 Actors | `0x264771233508f8…` | 755,946 | 299 | 1 | success | 299 | ok | ok |
| fficd-007 | Biden pardons SBF | `0xf4078ddd084c89…` | 8,209,071 | 0 | 0 | — | — | never_run | rerun_subgraph |
| fficd-007 | SBF sentenced to 50+ years | `0x2b8608c1c98160…` | 363,283 | 493 | 1 | success | 493 | ok | ok |
| fficd-007 | FTX no payouts in 2024 | `0x02c8326d2a5e3b…` | 952,525 | 2,148 | 1 | success | 2148 | ok | ok |
| fficd-008 | Ciuca wins Romanian election | `0x9872fe47fbf628…` | 326,507,671 | 9,288 | 2 | success | 9288 | ok | ok |

---

## Diagnosis Definitions

| Diagnosis | Meaning |
|---|---|
| `ok` | ≥ 100 trades in DB, no action needed |
| `never_run` | subgraph collector has never been run for this market |
| `ran_returned_zero` | collector ran successfully but returned 0 trades (low-volume or subgraph gap) |
| `ran_indexer_failed` | collector ran but returned 0 despite high volume — likely The Graph indexer capacity limit |
| `partial` | < 100 trades in DB, re-run needed |
| `not_in_db` | market not present in markets table at all |
| `investigate_further` | ambiguous state requiring manual review |

## Recommendation Definitions

| Recommendation | Action |
|---|---|
| `ok` | No action |
| `rerun_subgraph` | `fflow collect subgraph --market <id> --max-pages 200` |
| `try_rpc_direct` | Direct Polygon JSON-RPC or Polygonscan logs endpoint (Phase 3) |
| `check_gamma_collection` | Market not in DB — re-run gamma collector first |
| `investigate_further` | Manual review required |

---

## Summary

| Diagnosis | Count |
|---|---|
| never_run | 10 |
| ok | 8 |
| ran_indexer_failed | 6 |

| Recommendation | Count |
|---|---|
| rerun_subgraph | 10 |
| ok | 8 |
| try_rpc_direct | 6 |

---

## Phase 2 Target List (rerun_subgraph)

| Case | Label | Market ID | Vol ($) | Trades in DB |
|---|---|---|---|---|
| fficd-003 | Khamenei out by Feb 28 | `0xd4bbf7f6707c67beb736135ad32a41f6db41f8ae52d3ac4919650de9eeb94ed8` | 131,114,971 | 0 |
| fficd-003 | Israel-Hezbollah ceasefire by Apr 18 | `0x9823d715687a0a82d2a03731792e83bf58a0409f10def1379e00e4d67a95ba69` | 98,599,882 | 0 |
| fficd-003 | US strikes Iran by Feb 28 | `0x3488f31e6449f9803f99a8b5dd232c7ad883637f1c86e6953305a2ef19c77f20` | 89,652,867 | 0 |
| fficd-003 | Khamenei out by Mar 31 | `0x70909f0ba8256a89c301da58812ae47203df54957a07c7f8b10235e877ad63c2` | 63,238,698 | 0 |
| fficd-004 | Maduro in US custody by Jan 31 | `0xbfa45527ec959aacc36f7c312bd4f328171a7681ef1aeb3a7e34db5fb47d3f1d` | 11,034,070 | 0 |
| fficd-004 | US-Venezuela military by Dec 31 | `0x62b0cd598091a179147acbd4616400f804acfdff6f76f029944b481b37cbd45f` | 51,073,021 | 0 |
| fficd-004 | US invades Venezuela by Jan 31 | `0x7f3c6b9029a1a4a932509c147a2cc0762e1116b7a4568cde472908b29dd4889d` | 8,368,551 | 0 |
| fficd-005 | Bitcoin ETF approved by Jan 15 | `0xb36886bb0cf7cede4fd57fedbbbf80342ec76921d567fa9958275c22e1df04bd` | 12,622,418 | 0 |
| fficd-006 | Gene Hackman #1 Passings | `0x54361608e7307b22f080b6e6eed9f1d698e1fe122f7f6813efa7a2d8f2eb470c` | 2,952,428 | 0 |
| fficd-007 | Biden pardons SBF | `0xf4078ddd084c8979c81f1ac4674d5e846b87a13b7f568bdd402296181e83b4d9` | 8,209,071 | 0 |

## Phase 3 Target List (try_rpc_direct — Group A)

| Case | Label | Market ID | Vol ($) |
|---|---|---|---|
| fficd-001 | Trump wins | `0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee91a6b86c39ead110917` | 1,531,479,285 |
| fficd-001 | Harris wins | `0xc6485bb7ea46d7bb89beb9c91e7572ecfc72a6273789496f78bc5e989e4d1638` | 1,037,039,118 |
| fficd-001 | Other Republican wins | `0x55c551896c10a74861f2fd88b4f928694310114704cc74b29b9760d1156cade6` | 241,655,100 |
| fficd-001 | Michelle Obama wins | `0x230144e34a84dfd0ebdc6de7fde37780e28154f6f84dd8880c7f0e58d302d448` | 153,382,276 |
| fficd-003 | US forces enter Iran by Apr 30 | `0x6d0e09d0f04572d9b1adad84703458b0297bc5603b69dccbde93147ee4443246` | 269,049,107 |
| fficd-003 | US-Iran ceasefire by Apr 7 | `0x4c5701bcde0b8fb7d7f48c8e9d20245a6caa58c61a77f981fad98f2bfa0b1bc7` | 173,696,184 |
