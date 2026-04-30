"""Test: Haiku without web search for T_event recovery.

Samples 20 unprocessed markets from the typology dataset,
runs Haiku (no tools) and reports hit-rate, confidence, cost.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from datetime import UTC, datetime
from pathlib import Path

import anthropic
import pandas as pd
import structlog

log = structlog.get_logger()

_MODEL_HAIKU = "claude-haiku-4-5-20251001"
_HAIKU_IN  = 0.80 / 1_000_000
_HAIKU_OUT = 4.00 / 1_000_000

_PROMPT = """\
A Polymarket prediction market resolved YES. Your job is to find the date \
the underlying real-world event physically occurred.

Market question: {question}
Market opened:   {t_open}
Market resolved: {t_resolve}

Using only your training knowledge, output ONLY this JSON (no markdown):
{{
  "T_event": "<YYYY-MM-DD or null if unknown>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>"
}}

Confidence guide: 0.9=certain, 0.7=likely, 0.5=approximate, 0.0=unknown."""


def _parse(text: str) -> tuple[str | None, float, str]:
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
    return None, 0.0, str(d.get("reasoning", ""))


async def run_one(client: anthropic.AsyncAnthropic, q: str, t_open: str, t_resolve: str) -> dict:
    prompt = _PROMPT.format(question=q, t_open=t_open[:10], t_resolve=t_resolve[:10])
    try:
        resp = await client.messages.create(
            model=_MODEL_HAIKU,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        date, conf, reason = _parse(text)
        in_tok  = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = in_tok * _HAIKU_IN + out_tok * _HAIKU_OUT
        return {"date": date, "confidence": conf, "reasoning": reason,
                "cost": cost, "in_tok": in_tok, "out_tok": out_tok}
    except Exception as exc:
        return {"date": None, "confidence": 0.0, "reasoning": str(exc), "cost": 0.0}


async def main() -> None:
    parquet = Path("datasets/polymarket-resolution-typology/data/typology-v1.parquet")
    df = pd.read_parquet(parquet)
    df = df[df["resolved_at"].notna()].copy()

    checkpoint_path = Path("data/paper3a/t_event_checkpoint.jsonl")
    done_ids: set[str] = set()
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["market_id"])
                except Exception:
                    pass

    # Exclude already-done markets
    remaining = df[~df["market_id"].isin(done_ids)]
    print(f"Total remaining: {len(remaining)} markets (checkpoint has {len(done_ids)})")

    # Sample 20 spread across years
    sample = remaining.sample(20, random_state=42)

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    results = []
    for _, row in sample.iterrows():
        q  = row["question"]
        t0 = str(row["created_at"])
        tr = str(row["resolved_at"])
        r  = await run_one(client, q, t0, tr)
        r["question"] = q[:70]
        r["t_resolve"] = tr[:10]
        results.append(r)
        icon = "✓" if r["date"] else "✗"
        print(f"  {icon} [{r['date'] or 'null':10}] conf={r['confidence']:.1f} ${r['cost']:.4f}  {q[:60]}")

    hits   = sum(1 for r in results if r["date"])
    total_cost = sum(r["cost"] for r in results)
    avg_conf   = sum(r["confidence"] for r in results if r["date"]) / max(hits, 1)

    print(f"\n{'='*60}")
    print(f"Hit rate:     {hits}/20 = {hits/20*100:.0f}%")
    print(f"Avg conf:     {avg_conf:.2f} (hits only)")
    print(f"Total cost:   ${total_cost:.4f} for 20 markets")
    print(f"Per-market:   ${total_cost/20:.4f}")
    print(f"Proj 1093:    ${total_cost/20*1093:.2f}")

    null_markets = [r for r in results if not r["date"]]
    if null_markets:
        print(f"\nMissed ({len(null_markets)}):")
        for r in null_markets:
            print(f"  • {r['question'][:65]}")


if __name__ == "__main__":
    asyncio.run(main())
