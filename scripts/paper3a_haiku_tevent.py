"""Paper 3a — T_event recovery: Haiku-fast two-stage pipeline.

Stage 1: Claude Haiku, no tools, training knowledge only  (~$0.0005/market)
Stage 2: Claude Haiku, web_search, for Stage-1 nulls      (~$0.05-0.10/market)

Target: military_geopolitics + regulatory_decision + corporate_disclosure
        markets with volume ≥ $50k, resolved YES.

Usage:
    uv run python scripts/paper3a_haiku_tevent.py
    uv run python scripts/paper3a_haiku_tevent.py --stage1-only
    uv run python scripts/paper3a_haiku_tevent.py --limit 50  # dry run / test
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import anthropic
import pandas as pd
import pyarrow.parquet as pq
import structlog

log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────
PARQUET_PATH = Path("datasets/polymarket-resolution-typology/data/typology-v1.parquet")
CHECKPOINT_PATH = Path("data/paper3a/t_event_checkpoint.jsonl")
OUTPUT_DIR = Path("data/paper3a")

TARGET_CATEGORIES = frozenset({"military_geopolitics", "regulatory_decision", "corporate_disclosure"})
MIN_VOLUME_USDC = 50_000
COST_ALERT_USD = 50.0   # pause if total cost exceeds this

_MODEL = "claude-haiku-4-5-20251001"
_HAIKU_IN  = 0.80 / 1_000_000
_HAIKU_OUT = 4.00 / 1_000_000

# ── Stage-1 prompt (no tools) ──────────────────────────────────────────────────
_S1_PROMPT = """\
A Polymarket prediction market resolved YES. Find the date the underlying \
real-world event physically occurred.

Market question: {question}
Market opened:   {t_open}
Market resolved: {t_resolve}

Using ONLY your training knowledge, output ONLY this JSON (no markdown):
{{
  "T_event": "<YYYY-MM-DD or null if unknown>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>"
}}

Confidence: 0.9=certain date, 0.7=likely correct, 0.5=approximate, 0.0=unknown."""

# ── Stage-2 prompt (web_search) ────────────────────────────────────────────────
_S2_PROMPT = """\
You recover the exact date a real-world event publicly occurred.
Use web_search to find ≥2 independent sources.

Market question: {question}
Market opened: {t_open}
Market resolved YES: {t_resolve}

Find: the UTC date at which the underlying event PHYSICALLY OCCURRED.
The date must fall within [{t_open}, {t_resolve}].

Output ONLY this JSON (no markdown fences):
{{
  "T_event": "<YYYY-MM-DD or null if not recoverable>",
  "confidence": <0.0-1.0>,
  "sources": ["<url or outlet>", ...],
  "reasoning": "<1-2 sentences>"
}}

Confidence: 0.9=≥3 sources, 0.8=2 sources, 0.7=1 reliable source, 0.0=not found."""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_json_date(text: str) -> tuple[str | None, float, str]:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None, 0.0, "no json"
    try:
        d = json.loads(m.group())
    except json.JSONDecodeError:
        return None, 0.0, "parse error"
    raw = d.get("T_event")
    if raw and str(raw).lower() not in ("null", "none", ""):
        try:
            datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d")
            return str(raw).strip()[:10], float(d.get("confidence", 0.0)), str(d.get("reasoning", ""))
        except ValueError:
            pass
    return None, float(d.get("confidence", 0.0)), str(d.get("reasoning", ""))


def _load_checkpoint() -> dict[str, dict]:
    """Return {market_id: record} for all successful checkpoint entries."""
    done: dict[str, dict] = {}
    if CHECKPOINT_PATH.exists():
        for line in CHECKPOINT_PATH.read_text().splitlines():
            try:
                r = json.loads(line)
                if r.get("market_id") and r.get("t_event") and r.get("confidence", 0) > 0:
                    done[r["market_id"]] = r
            except Exception:
                pass
    return done


def _append_checkpoint(record: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── Stage 1: Haiku, no tools ───────────────────────────────────────────────────

async def _stage1_one(
    client: anthropic.AsyncAnthropic,
    mid: str,
    question: str,
    t_open: str,
    t_resolve: str,
) -> dict:
    prompt = _S1_PROMPT.format(question=question, t_open=t_open[:10], t_resolve=t_resolve[:10])
    try:
        resp = await client.messages.create(
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        date, conf, reason = _parse_json_date(text)
        cost = resp.usage.input_tokens * _HAIKU_IN + resp.usage.output_tokens * _HAIKU_OUT
        return {
            "market_id": mid, "t_event": date, "confidence": conf,
            "reasoning": reason, "cost": cost, "stage": 1,
            "in_tok": resp.usage.input_tokens, "out_tok": resp.usage.output_tokens,
        }
    except Exception as exc:
        log.warning("stage1_error", market_id=mid[:16], error=str(exc))
        return {"market_id": mid, "t_event": None, "confidence": 0.0,
                "reasoning": str(exc), "cost": 0.0, "stage": 1}


async def run_stage1(
    markets: list[dict],
    client: anthropic.AsyncAnthropic,
    concurrency: int = 20,
) -> tuple[list[dict], list[dict]]:
    """Returns (hits, misses) where hits have t_event set."""
    sem = asyncio.Semaphore(concurrency)
    results = []

    async def _one(m: dict) -> None:
        async with sem:
            r = await _stage1_one(client, m["market_id"], m["question"],
                                   m["t_open"], m["t_resolve"])
        results.append(r)
        icon = "✓" if r["t_event"] else "✗"
        print(f"  S1{icon} [{r['t_event'] or 'null':10}] c={r['confidence']:.1f} "
              f"${r['cost']:.4f}  {m['question'][:60]}", flush=True)

    await asyncio.gather(*[_one(m) for m in markets])
    hits   = [r for r in results if r["t_event"] and r["confidence"] >= 0.5]
    misses = [r for r in results if not (r["t_event"] and r["confidence"] >= 0.5)]
    return hits, misses


# ── Stage 2: Haiku + web_search ────────────────────────────────────────────────

async def _stage2_one(
    client: anthropic.AsyncAnthropic,
    mid: str,
    question: str,
    t_open: str,
    t_resolve: str,
) -> dict:
    prompt = _S2_PROMPT.format(question=question, t_open=t_open[:10], t_resolve=t_resolve[:10])
    _RETRY_WAITS = (15, 30, 60)
    for attempt, wait in enumerate((*_RETRY_WAITS, None)):
        try:
            resp = await client.messages.create(
                model=_MODEL,
                max_tokens=512,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError as exc:
            if wait is None:
                return {"market_id": mid, "t_event": None, "confidence": 0.0,
                        "reasoning": f"rate limit: {exc}", "cost": 0.0, "stage": 2}
            ra = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
            await asyncio.sleep(float(ra) + 1 if ra else wait)
        except Exception as exc:
            return {"market_id": mid, "t_event": None, "confidence": 0.0,
                    "reasoning": str(exc), "cost": 0.0, "stage": 2}

    text = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()
    date, conf, reason = _parse_json_date(text)
    cost = resp.usage.input_tokens * _HAIKU_IN + resp.usage.output_tokens * _HAIKU_OUT
    return {
        "market_id": mid, "t_event": date, "confidence": conf,
        "reasoning": reason, "cost": cost, "stage": 2,
        "in_tok": resp.usage.input_tokens, "out_tok": resp.usage.output_tokens,
    }


async def run_stage2(
    misses: list[dict],
    markets_by_id: dict[str, dict],
    client: anthropic.AsyncAnthropic,
    concurrency: int = 8,
) -> tuple[list[dict], list[dict]]:
    sem = asyncio.Semaphore(concurrency)
    results = []

    async def _one(r: dict) -> None:
        mid = r["market_id"]
        m = markets_by_id[mid]
        async with sem:
            r2 = await _stage2_one(client, mid, m["question"], m["t_open"], m["t_resolve"])
        results.append(r2)
        icon = "✓" if r2["t_event"] else "✗"
        print(f"  S2{icon} [{r2['t_event'] or 'null':10}] c={r2['confidence']:.1f} "
              f"${r2['cost']:.4f}  {m['question'][:60]}", flush=True)

    await asyncio.gather(*[_one(r) for r in misses])
    hits   = [r for r in results if r["t_event"] and r["confidence"] >= 0.5]
    misses2 = [r for r in results if not (r["t_event"] and r["confidence"] >= 0.5)]
    return hits, misses2


# ── Main ───────────────────────────────────────────────────────────────────────

async def main(stage1_only: bool = False, limit: int | None = None) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("FFLOW_ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY or FFLOW_ANTHROPIC_API_KEY")

    # Load parquet — same filter as paper3a_phase1.py
    log.info("loading_parquet", path=str(PARQUET_PATH))
    full_df = pq.read_table(PARQUET_PATH).to_pandas()
    df = full_df[
        full_df["category_fflow"].isin(TARGET_CATEGORIES) &
        full_df["volume_total_usdc"].notna() &
        (full_df["volume_total_usdc"] >= MIN_VOLUME_USDC) &
        full_df["resolved_at"].notna() &
        (full_df["resolution_outcome"] == 1.0)
    ].copy()
    log.info("yes_resolved_filtered", n=len(df))

    done = _load_checkpoint()
    log.info("checkpoint_loaded", n_done=len(done))

    remaining_df = df[~df["market_id"].isin(done)].copy()
    log.info("remaining", n=len(remaining_df))

    if limit:
        remaining_df = remaining_df.head(limit)
        log.info("limit_applied", n=len(remaining_df))

    if remaining_df.empty:
        print("Nothing to process — all markets in checkpoint.")
        return

    markets = [
        {
            "market_id": row["market_id"],
            "question": row["question"],
            "t_open": str(row["created_at"])[:10],
            "t_resolve": str(row["resolved_at"])[:10],
        }
        for _, row in remaining_df.iterrows()
    ]
    markets_by_id = {m["market_id"]: m for m in markets}

    client = anthropic.AsyncAnthropic(api_key=api_key)
    total_cost = 0.0

    # ── Stage 1 ────────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"Stage 1: Haiku (no tools) — {len(markets)} markets")
    print(f"{'='*70}")

    s1_hits, s1_misses = await run_stage1(markets, client)

    for r in s1_hits:
        _append_checkpoint({
            "market_id": r["market_id"],
            "t_event": r["t_event"],
            "confidence": r["confidence"],
            "reasoning": r["reasoning"],
            "stage": 1,
            "cost_usd": r["cost"],
        })
        total_cost += r["cost"]
        if total_cost > COST_ALERT_USD:
            print(f"\nCOST ALERT: ${total_cost:.2f} — stopping.")
            sys.exit(1)

    s1_cost = sum(r["cost"] for r in s1_hits) + sum(r["cost"] for r in s1_misses)
    total_cost += sum(r["cost"] for r in s1_misses)

    print(f"\nStage 1 results:")
    print(f"  Hits:   {len(s1_hits)}/{len(markets)} = {len(s1_hits)/len(markets)*100:.0f}%")
    print(f"  Misses: {len(s1_misses)}")
    print(f"  Cost:   ${s1_cost:.4f}")

    if stage1_only or not s1_misses:
        _print_final(done, markets, s1_hits, [], total_cost)
        return

    # ── Stage 2 ────────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"Stage 2: Haiku + web_search — {len(s1_misses)} markets")
    print(f"{'='*70}")

    s2_hits, s2_misses = await run_stage2(s1_misses, markets_by_id, client)

    for r in s2_hits:
        _append_checkpoint({
            "market_id": r["market_id"],
            "t_event": r["t_event"],
            "confidence": r["confidence"],
            "reasoning": r["reasoning"],
            "stage": 2,
            "cost_usd": r["cost"],
        })
        total_cost += r["cost"]
        if total_cost > COST_ALERT_USD:
            print(f"\nCOST ALERT: ${total_cost:.2f} — stopping.")
            sys.exit(1)

    total_cost += sum(r["cost"] for r in s2_misses)
    s2_cost = sum(r["cost"] for r in s2_hits) + sum(r["cost"] for r in s2_misses)
    print(f"\nStage 2 results:")
    print(f"  Hits:   {len(s2_hits)}/{len(s1_misses)} = {len(s2_hits)/max(len(s1_misses),1)*100:.0f}%")
    print(f"  Misses: {len(s2_misses)}")
    print(f"  Cost:   ${s2_cost:.4f}")

    _print_final(done, markets, s1_hits, s2_hits, total_cost, s2_misses)


def _print_final(
    done: dict,
    markets: list[dict],
    s1_hits: list[dict],
    s2_hits: list[dict],
    total_cost: float,
    final_misses: list[dict] | None = None,
) -> None:
    all_hits = len(s1_hits) + len(s2_hits)
    total = len(markets)
    print(f"\n{'='*70}")
    print(f"TOTAL RESULTS (this run)")
    print(f"  Recovered:    {all_hits}/{total} = {all_hits/max(total,1)*100:.0f}%")
    print(f"  S1 hits:      {len(s1_hits)}")
    print(f"  S2 hits:      {len(s2_hits)}")
    print(f"  Total cost:   ${total_cost:.4f}")
    print(f"  Per market:   ${total_cost/max(total,1):.4f}")
    all_done = len(done) + all_hits
    print(f"\nCheckpoint total: {all_done} markets")
    if final_misses:
        print(f"\nFinal misses ({len(final_misses)}) — T_event not recovered:")
        for r in final_misses[:20]:
            m = r["market_id"]
            print(f"  • {m[:16]}  {r.get('reasoning','')[:80]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(main(stage1_only=args.stage1_only, limit=args.limit or None))
