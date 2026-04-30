"""Optimized T_event recovery for population-scale pipeline (Paper 3a §3.2).

Differences from llm_match.py (Paper 1/2 single-market version):
  - JSON structured output (not freetext DATE:/SOURCES:/REASON:)
  - Granular confidence: 0.9/0.8/0.7/0.5/0.0 based on n_sources
  - No per-invocation call cap (cost tracked externally via phase1_log.jsonl)
  - $40 alert threshold instead of hard cap
  - Event-description cache: cheap Haiku call extracts event label, used to
    deduplicate markets sharing the same underlying event (e.g. "US forces
    enter Iran by March 31" and "...by April 30" → same event, one LLM call)
  - Async concurrency cap (default 20) instead of sequential processing
  - Batch API path tested via --test-batch flag in paper3a_phase1.py

Cost estimates (Anthropic pricing, Haiku 4.5 + web search):
  Event-description call: ~$0.002 (no tools, ~100 input + 20 output tokens)
  T_event recovery call:  ~$0.05-0.12 (with web search, 3-5 tool calls)
  Sonnet escalation:      ~$0.30-0.60 per market
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import NamedTuple

import structlog

log = structlog.get_logger()

_MODEL_HAIKU = "claude-haiku-4-5-20251001"
_MODEL_SONNET = "claude-sonnet-4-6"
_MAX_TOKENS_RECOVERY = 1024
_MAX_TOKENS_DESC = 64
_CONFIDENCE_THRESHOLD = 0.7

# Haiku pricing (per token)
_HAIKU_IN_PER_TOK = 0.80 / 1_000_000
_HAIKU_OUT_PER_TOK = 4.00 / 1_000_000
_SONNET_IN_PER_TOK = 3.00 / 1_000_000
_SONNET_OUT_PER_TOK = 15.00 / 1_000_000


class TEventResult(NamedTuple):
    t_event: datetime | None
    confidence: float       # 0.0 – 1.0
    n_sources: int
    sources: tuple[str, ...]
    reasoning: str
    model_used: str
    input_tokens: int
    output_tokens: int
    web_search_calls: int
    estimated_cost_usd: float


_RECOVERY_PROMPT = """\
You recover the exact timestamp at which a real-world event publicly occurred.
Use web_search to find ≥3 independent news sources (Reuters, AP, BBC, CNN, Al Jazeera,
or official government sources).

Market question: {question}
{desc_section}
Market opened: {t_open}
Market resolved YES: {t_resolve}

Find: the UTC timestamp at which the event this market resolves-on FIRST publicly occurred.
The timestamp must fall within [{t_open}, {t_resolve}].

Output ONLY this JSON (no preamble, no markdown fences):
{{
  "T_event": "<ISO 8601 UTC, e.g. 2026-04-03T08:15:00Z — or null if not recoverable>",
  "confidence": <number 0.0-1.0>,
  "sources": ["<url or outlet name>", ...],
  "n_sources": <integer>,
  "reasoning": "<1-2 sentences: what happened and when>"
}}

Confidence scale:
  0.9 — ≥5 independent major sources agree on the date
  0.8 — ≥3 sources agree
  0.7 — 2 sources agree
  0.5 — 1 source or partial agreement
  0.0 — event date not recoverable
"""

_DESC_PROMPT = """\
In ≤10 words, name the underlying real-world event this Polymarket question resolves on.
Output ONLY the event name (no explanation, no punctuation at the end).

Question: {question}"""


async def get_event_description(
    question: str,
    client: "anthropic.AsyncAnthropic",
) -> str:
    """Return a short (≤10 word) event description for cache-key purposes.

    Uses Haiku with no tools — very cheap (~$0.002).
    Falls back to the first 60 chars of the question on API error.
    """
    try:
        resp = await client.messages.create(
            model=_MODEL_HAIKU,
            max_tokens=_MAX_TOKENS_DESC,
            messages=[{"role": "user", "content": _DESC_PROMPT.format(question=question)}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        return text[:120] if text else question[:60]
    except Exception as exc:
        log.warning("event_desc_error", question=question[:60], error=str(exc))
        return question[:60]


def _normalize_cache_key(desc: str) -> str:
    """Lowercase + strip stop words + strip punctuation for fuzzy matching."""
    _STOPS = {"the", "a", "an", "and", "or", "by", "in", "on", "at", "to", "for",
              "of", "with", "will", "does", "is", "are", "was", "were", "be", "us"}
    words = re.findall(r"\b[a-z0-9]+\b", desc.lower())
    return " ".join(w for w in words if w not in _STOPS)


async def recover_t_event_one_shot(
    question: str,
    description: str | None,
    t_open: datetime,
    t_resolve: datetime,
    client: "anthropic.AsyncAnthropic",
    model: str = _MODEL_HAIKU,
) -> TEventResult:
    """One-shot T_event recovery with web search. JSON structured output."""
    desc_section = f"Market description: {description}" if description else ""
    t_open_s = t_open.strftime("%Y-%m-%dT%H:%MZ")
    t_resolve_s = t_resolve.strftime("%Y-%m-%dT%H:%MZ")

    prompt = _RECOVERY_PROMPT.format(
        question=question,
        desc_section=desc_section,
        t_open=t_open_s,
        t_resolve=t_resolve_s,
    )

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS_RECOVERY,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("t_event_api_error", question=question[:60], model=model, error=str(exc))
        cost = 0.0
        return TEventResult(
            t_event=None, confidence=0.0, n_sources=0, sources=(),
            reasoning=f"API error: {exc}", model_used=model,
            input_tokens=0, output_tokens=0, web_search_calls=0,
            estimated_cost_usd=cost,
        )

    # Count web_search tool calls in the content
    web_calls = sum(
        1 for block in response.content
        if getattr(block, "type", None) == "server_tool_use"
    )

    # Concatenate all text blocks (interleaved with tool results)
    text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()

    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens

    if model == _MODEL_HAIKU:
        cost = in_tok * _HAIKU_IN_PER_TOK + out_tok * _HAIKU_OUT_PER_TOK
    else:
        cost = in_tok * _SONNET_IN_PER_TOK + out_tok * _SONNET_OUT_PER_TOK

    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Extract JSON block
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        log.info("t_event_no_json", question=question[:60])
        return TEventResult(
            t_event=None, confidence=0.0, n_sources=0, sources=(),
            reasoning="No JSON in response", model_used=model,
            input_tokens=in_tok, output_tokens=out_tok,
            web_search_calls=web_calls, estimated_cost_usd=cost,
        )

    try:
        parsed = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        log.warning("t_event_json_parse_error", question=question[:60], error=str(exc))
        return TEventResult(
            t_event=None, confidence=0.0, n_sources=0, sources=(),
            reasoning=f"JSON parse error: {exc}", model_used=model,
            input_tokens=in_tok, output_tokens=out_tok,
            web_search_calls=web_calls, estimated_cost_usd=cost,
        )

    raw_t = parsed.get("T_event")
    confidence = float(parsed.get("confidence", 0.0))
    sources_list = parsed.get("sources", [])
    sources = tuple(str(s) for s in sources_list if s)
    n_sources = int(parsed.get("n_sources", len(sources)))
    reasoning = str(parsed.get("reasoning", ""))

    dt: datetime | None = None
    if raw_t and str(raw_t).lower() not in ("null", "none", ""):
        raw_t = re.sub(r"[*,;.\s]+$", "", str(raw_t).strip())
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%MZ",
            "%Y-%m-%dT%H:%M%z",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
        ):
            try:
                parsed_dt = datetime.strptime(raw_t, fmt)
                dt = parsed_dt.replace(tzinfo=UTC)
                break
            except ValueError:
                continue

    log.info(
        "t_event_recovered",
        question=question[:60],
        model=model,
        t_event=dt.isoformat() if dt else "NONE",
        confidence=confidence,
        n_sources=n_sources,
        web_calls=web_calls,
        cost_usd=round(cost, 4),
    )

    return TEventResult(
        t_event=dt,
        confidence=confidence,
        n_sources=n_sources,
        sources=sources,
        reasoning=reasoning,
        model_used=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        web_search_calls=web_calls,
        estimated_cost_usd=cost,
    )


async def recover_t_event_optimized(
    question: str,
    description: str | None,
    t_open: datetime,
    t_resolve: datetime,
    client: "anthropic.AsyncAnthropic",
    confidence_threshold: float = _CONFIDENCE_THRESHOLD,
) -> TEventResult:
    """Haiku first; escalate to Sonnet when confidence < threshold (~10% of markets).

    Returns combined TEventResult — sonnet_called is reflected in model_used.
    """
    haiku_result = await recover_t_event_one_shot(
        question, description, t_open, t_resolve, client, model=_MODEL_HAIKU
    )

    if haiku_result.confidence >= confidence_threshold and haiku_result.t_event is not None:
        return haiku_result

    log.info(
        "t_event_escalating_to_sonnet",
        question=question[:60],
        haiku_confidence=haiku_result.confidence,
    )
    sonnet_result = await recover_t_event_one_shot(
        question, description, t_open, t_resolve, client, model=_MODEL_SONNET
    )

    # Merge cost: add haiku call cost to sonnet result
    return TEventResult(
        t_event=sonnet_result.t_event,
        confidence=sonnet_result.confidence,
        n_sources=sonnet_result.n_sources,
        sources=sonnet_result.sources,
        reasoning=sonnet_result.reasoning,
        model_used=f"{_MODEL_HAIKU}+{_MODEL_SONNET}",
        input_tokens=haiku_result.input_tokens + sonnet_result.input_tokens,
        output_tokens=haiku_result.output_tokens + sonnet_result.output_tokens,
        web_search_calls=haiku_result.web_search_calls + sonnet_result.web_search_calls,
        estimated_cost_usd=haiku_result.estimated_cost_usd + sonnet_result.estimated_cost_usd,
    )


async def recover_batch_async(
    markets: list[dict],
    client: "anthropic.AsyncAnthropic",
    concurrency: int = 20,
    event_cache: dict[str, TEventResult] | None = None,
    cost_alert_usd: float = 40.0,
    already_spent_usd: float = 0.0,
) -> tuple[dict[str, TEventResult], float]:
    """Process a list of markets with async concurrency cap.

    Args:
        markets:    List of dicts with keys: market_id, question, description,
                    t_open (datetime), t_resolve (datetime).
        client:     Anthropic async client.
        concurrency: Max parallel requests.
        event_cache: Mutable dict mapping normalized_event_key → TEventResult.
                    Cache hits avoid LLM calls.
        cost_alert_usd: Pause and raise if cumulative cost exceeds this.
        already_spent_usd: Running cost from previous stages.

    Returns:
        (results_dict, total_cost_usd)
        results_dict maps market_id → TEventResult
    """
    if event_cache is None:
        event_cache = {}

    results: dict[str, TEventResult] = {}
    cumulative_cost = already_spent_usd
    sem = asyncio.Semaphore(concurrency)

    async def process_one(market: dict) -> None:
        nonlocal cumulative_cost
        mid = market["market_id"]
        question = market["question"]
        description = market.get("description")
        t_open = market["t_open"]
        t_resolve = market["t_resolve"]

        # Event-description cache lookup
        if event_cache is not None:
            desc = await get_event_description(question, client)
            cache_key = _normalize_cache_key(desc)
            if cache_key in event_cache:
                log.debug("t_event_cache_hit", market_id=mid[:16], key=cache_key[:40])
                results[mid] = event_cache[cache_key]
                return
        else:
            cache_key = None

        async with sem:
            result = await recover_t_event_optimized(
                question, description, t_open, t_resolve, client
            )

        cumulative_cost += result.estimated_cost_usd
        if cumulative_cost > cost_alert_usd:
            raise CostAlertError(
                f"Cumulative LLM cost ${cumulative_cost:.2f} exceeds alert threshold "
                f"${cost_alert_usd:.2f}. Stopping. Review phase1_log.jsonl."
            )

        results[mid] = result
        if event_cache is not None and cache_key is not None:
            event_cache[cache_key] = result

    await asyncio.gather(*[process_one(m) for m in markets])
    return results, cumulative_cost


class CostAlertError(RuntimeError):
    """Raised when cumulative LLM cost exceeds the alert threshold."""
