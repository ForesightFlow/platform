"""Multi-tier LLM providers for T_event recovery (Paper 3a §3.2).

Tier 1: Gemini 2.5 Flash + Google Search grounding (FREE, 1,500 RPD)
Tier 2: GPT-4o-mini + web_search_preview (~$0.005/market)
Tier 3: Claude Sonnet 4.6 + web_search_20250305 (~$0.40/market, last resort)

Cascade logic:
  T1 passes  → return T1 result
  T1 fails   → try T2
  T2 passes  → return T2 result
  T1 or T2 ≥ 0.5 → accept best, skip T3
  Both < 0.5 → escalate to T3 (Sonnet)
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime

import httpx
import structlog

from fflow.news.t_event_recovery_v2 import (
    TEventResult,
    _MODEL_SONNET,
    _RECOVERY_PROMPT,
    _SONNET_IN_PER_TOK,
    _SONNET_OUT_PER_TOK,
    recover_t_event_one_shot,
)

log = structlog.get_logger()

_GEMINI_MODEL = "gemini-2.5-flash-preview-04-17"
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{_GEMINI_MODEL}:generateContent"
)
_OPENAI_MODEL = "gpt-4o-mini"
_OPENAI_URL = "https://api.openai.com/v1/responses"

_OPENAI_IN_PER_TOK = 0.15 / 1_000_000
_OPENAI_OUT_PER_TOK = 0.60 / 1_000_000
_OPENAI_SEARCH_FEE = 0.0025  # per web_search_preview call

_GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "T_event": {"type": "string", "nullable": True},
        "confidence": {"type": "number"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "n_sources": {"type": "integer"},
        "reasoning": {"type": "string"},
    },
    "required": ["T_event", "confidence", "sources", "n_sources", "reasoning"],
}


# ── Shared JSON parser ──────────────────────────────────────────────────────────

def _parse_recovery_json(
    text: str,
) -> tuple[datetime | None, float, list[str], int, str]:
    """Parse T_event JSON from LLM text. Returns (dt, confidence, sources, n_sources, reasoning)."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())

    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        return None, 0.0, [], 0, "No JSON in response"

    try:
        parsed = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        return None, 0.0, [], 0, f"JSON parse error: {exc}"

    raw_t = parsed.get("T_event")
    confidence = float(parsed.get("confidence", 0.0))
    sources_list = [str(s) for s in parsed.get("sources", []) if s]
    n_sources = int(parsed.get("n_sources", len(sources_list)))
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
                dt = datetime.strptime(raw_t, fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue

    return dt, confidence, sources_list, n_sources, reasoning


def _build_prompt(
    question: str,
    description: str | None,
    t_open: datetime,
    t_resolve: datetime,
) -> str:
    return _RECOVERY_PROMPT.format(
        question=question,
        desc_section=f"Market description: {description}" if description else "",
        t_open=t_open.strftime("%Y-%m-%dT%H:%MZ"),
        t_resolve=t_resolve.strftime("%Y-%m-%dT%H:%MZ"),
    )


# ── Tier 1: Gemini ─────────────────────────────────────────────────────────────

async def recover_t_event_gemini(
    question: str,
    description: str | None,
    t_open: datetime,
    t_resolve: datetime,
    api_key: str,
    http_client: httpx.AsyncClient,
) -> TEventResult:
    """Gemini 2.5 Flash with Google Search grounding (free tier)."""
    prompt = _build_prompt(question, description, t_open, t_resolve)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _GEMINI_RESPONSE_SCHEMA,
            "temperature": 0.0,
        },
    }
    headers = {"X-goog-api-key": api_key, "Content-Type": "application/json"}

    def _fail(reason: str) -> TEventResult:
        return TEventResult(
            t_event=None, confidence=0.0, n_sources=0, sources=(),
            reasoning=reason, model_used="gemini",
            input_tokens=0, output_tokens=0, web_search_calls=0,
            estimated_cost_usd=0.0, provider="gemini",
        )

    _WAITS = (5, 15, 30, 60, 60)
    last_exc: Exception | None = None
    for attempt, wait in enumerate((*_WAITS, None)):
        try:
            resp = await http_client.post(_GEMINI_URL, json=body, headers=headers, timeout=90.0)
            if resp.status_code == 429:
                if wait is None:
                    return _fail("Gemini rate limit — max retries exhausted")
                log.warning("gemini_rate_limit_retry", question=question[:50], attempt=attempt + 1, wait_s=wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            last_exc = None
            break
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            if wait is None:
                return _fail(f"Gemini request failed: {exc}")
            await asyncio.sleep(wait)
    else:
        return _fail(f"Gemini request failed after retries: {last_exc}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        return _fail("Gemini: no candidates")

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()

    # Sources from grounding metadata (authoritative) — not from model's JSON
    grounding = candidate.get("groundingMetadata", {})
    grounding_sources = [
        chunk["web"]["uri"]
        for chunk in grounding.get("groundingChunks", [])
        if "web" in chunk
    ]
    web_calls = 1 if grounding_sources or grounding.get("webSearchQueries") else 0

    usage = data.get("usageMetadata", {})
    in_tok = usage.get("promptTokenCount", 0)
    out_tok = usage.get("candidatesTokenCount", 0)

    dt, confidence, json_sources, n_sources, reasoning = _parse_recovery_json(text)

    # Override with grounding sources
    final_sources = tuple(grounding_sources) if grounding_sources else tuple(json_sources)
    if grounding_sources:
        n_sources = max(n_sources, len(grounding_sources))

    log.info(
        "t_event_recovered",
        question=question[:60], model="gemini",
        t_event=dt.isoformat() if dt else "NONE",
        confidence=confidence, n_sources=n_sources,
        web_calls=web_calls, cost_usd=0.0,
    )
    return TEventResult(
        t_event=dt, confidence=confidence, n_sources=n_sources,
        sources=final_sources, reasoning=reasoning, model_used="gemini",
        input_tokens=in_tok, output_tokens=out_tok,
        web_search_calls=web_calls, estimated_cost_usd=0.0, provider="gemini",
    )


# ── Tier 2: OpenAI ─────────────────────────────────────────────────────────────

async def recover_t_event_openai(
    question: str,
    description: str | None,
    t_open: datetime,
    t_resolve: datetime,
    api_key: str,
    http_client: httpx.AsyncClient,
) -> TEventResult:
    """GPT-4o-mini with web_search_preview via Responses API."""
    prompt = _build_prompt(question, description, t_open, t_resolve)
    body = {
        "model": _OPENAI_MODEL,
        "tools": [{"type": "web_search_preview"}],
        "input": prompt,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _fail(reason: str) -> TEventResult:
        return TEventResult(
            t_event=None, confidence=0.0, n_sources=0, sources=(),
            reasoning=reason, model_used="openai",
            input_tokens=0, output_tokens=0, web_search_calls=0,
            estimated_cost_usd=0.0, provider="openai",
        )

    _WAITS = (10, 20, 40, 60, 60)
    last_exc: Exception | None = None
    for attempt, wait in enumerate((*_WAITS, None)):
        try:
            resp = await http_client.post(_OPENAI_URL, json=body, headers=headers, timeout=120.0)
            if resp.status_code == 429:
                if wait is None:
                    return _fail("OpenAI rate limit — max retries exhausted")
                log.warning("openai_rate_limit_retry", question=question[:50], attempt=attempt + 1, wait_s=wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            last_exc = None
            break
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            if wait is None:
                return _fail(f"OpenAI request failed: {exc}")
            await asyncio.sleep(wait)
    else:
        return _fail(f"OpenAI request failed after retries: {last_exc}")

    data = resp.json()
    text = ""
    web_calls = 0
    for item in data.get("output", []):
        if item.get("type") == "web_search_call":
            web_calls += 1
        elif item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text += content.get("text", "")

    usage = data.get("usage", {})
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cost = in_tok * _OPENAI_IN_PER_TOK + out_tok * _OPENAI_OUT_PER_TOK + web_calls * _OPENAI_SEARCH_FEE

    dt, confidence, sources_list, n_sources, reasoning = _parse_recovery_json(text)

    log.info(
        "t_event_recovered",
        question=question[:60], model="openai",
        t_event=dt.isoformat() if dt else "NONE",
        confidence=confidence, n_sources=n_sources,
        web_calls=web_calls, cost_usd=round(cost, 4),
    )
    return TEventResult(
        t_event=dt, confidence=confidence, n_sources=n_sources,
        sources=tuple(sources_list), reasoning=reasoning, model_used="openai",
        input_tokens=in_tok, output_tokens=out_tok,
        web_search_calls=web_calls, estimated_cost_usd=cost, provider="openai",
    )


# ── Cascade orchestrator ────────────────────────────────────────────────────────

async def recover_t_event_cascade(
    question: str,
    description: str | None,
    t_open: datetime,
    t_resolve: datetime,
    anthropic_client: "anthropic.AsyncAnthropic",  # type: ignore[name-defined]
    gemini_api_key: str,
    openai_api_key: str,
    http_client: httpx.AsyncClient,
    confidence_threshold: float = 0.7,
) -> TEventResult:
    """Anthropic-only: Claude Sonnet 4.6 with web_search directly."""
    # Gemini T1 and OpenAI T2 both bypassed — going straight to Sonnet.
    r3 = await recover_t_event_one_shot(
        question, description, t_open, t_resolve, anthropic_client, model=_MODEL_SONNET
    )
    return TEventResult(
        t_event=r3.t_event, confidence=r3.confidence,
        n_sources=r3.n_sources, sources=r3.sources,
        reasoning=r3.reasoning,
        model_used=_MODEL_SONNET,
        input_tokens=r3.input_tokens,
        output_tokens=r3.output_tokens,
        web_search_calls=r3.web_search_calls,
        estimated_cost_usd=r3.estimated_cost_usd,
        provider="anthropic",
    )


# ── Batch runner ────────────────────────────────────────────────────────────────

class CostAlertError(RuntimeError):
    """Raised when cumulative LLM cost exceeds the alert threshold."""


async def recover_batch_cascade(
    markets: list[dict],
    anthropic_client: "anthropic.AsyncAnthropic",  # type: ignore[name-defined]
    gemini_api_key: str,
    openai_api_key: str,
    http_client: httpx.AsyncClient,
    concurrency: int = 15,
    confidence_threshold: float = 0.7,
    cost_alert_usd: float = 70.0,
    already_spent_usd: float = 0.0,
    checkpoint_path: "Path | None" = None,  # type: ignore[name-defined]
    checkpoint_every: int = 100,
) -> tuple[dict[str, TEventResult], float]:
    """Async batch T_event recovery using three-tier cascade.

    Args:
        markets: list of dicts with market_id, question, description, t_open, t_resolve.
        checkpoint_path: if provided, append results to this JSONL file every
            checkpoint_every markets (enables resume after interruption).

    Returns:
        (results_dict, total_cost_usd)
    """
    results: dict[str, TEventResult] = {}
    cumulative_cost = already_spent_usd
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    lock = asyncio.Lock()

    async def process_one(market: dict) -> None:
        nonlocal cumulative_cost, completed
        mid = market["market_id"]
        async with sem:
            result = await recover_t_event_cascade(
                question=market["question"],
                description=market.get("description"),
                t_open=market["t_open"],
                t_resolve=market["t_resolve"],
                anthropic_client=anthropic_client,
                gemini_api_key=gemini_api_key,
                openai_api_key=openai_api_key,
                http_client=http_client,
                confidence_threshold=confidence_threshold,
            )

        async with lock:
            results[mid] = result
            cumulative_cost += result.estimated_cost_usd
            completed += 1

            if checkpoint_path is not None and result.t_event is not None and result.confidence > 0:
                _append_checkpoint(checkpoint_path, mid, result)
                if completed % checkpoint_every == 0:
                    log.info("checkpoint_written", completed=completed, total=len(markets))

            if cumulative_cost > cost_alert_usd:
                raise CostAlertError(
                    f"Cumulative LLM cost ${cumulative_cost:.2f} exceeds alert "
                    f"${cost_alert_usd:.2f}. Stopping. Review phase1_log.jsonl."
                )

    await asyncio.gather(*[process_one(m) for m in markets])
    return results, cumulative_cost


def _append_checkpoint(path: "Path", market_id: str, result: TEventResult) -> None:  # type: ignore[name-defined]
    """Append one market result to the checkpoint JSONL (best-effort)."""
    from pathlib import Path as _Path

    try:
        path = _Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "market_id": market_id,
            "t_event": result.t_event.isoformat() if result.t_event else None,
            "confidence": result.confidence,
            "n_sources": result.n_sources,
            "sources": list(result.sources),
            "reasoning": result.reasoning,
            "model_used": result.model_used,
            "provider": result.provider,
            "estimated_cost_usd": result.estimated_cost_usd,
        }
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        log.warning("checkpoint_write_error", error=str(exc))


def load_checkpoint(path: "Path") -> dict[str, TEventResult]:  # type: ignore[name-defined]
    """Load partial results from a checkpoint JSONL. Returns market_id → TEventResult."""
    from pathlib import Path as _Path
    from datetime import UTC, datetime

    path = _Path(path)
    if not path.exists():
        return {}

    results: dict[str, TEventResult] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                raw_t = entry.get("t_event")
                dt = datetime.fromisoformat(raw_t).replace(tzinfo=UTC) if raw_t else None
                results[entry["market_id"]] = TEventResult(
                    t_event=dt,
                    confidence=float(entry.get("confidence", 0.0)),
                    n_sources=int(entry.get("n_sources", 0)),
                    sources=tuple(entry.get("sources", [])),
                    reasoning=entry.get("reasoning", ""),
                    model_used=entry.get("model_used", ""),
                    input_tokens=0,
                    output_tokens=0,
                    web_search_calls=0,
                    estimated_cost_usd=float(entry.get("estimated_cost_usd", 0.0)),
                    provider=entry.get("provider", "unknown"),
                )
            except Exception as exc:
                log.warning("checkpoint_load_error", line=line[:80], error=str(exc))
    log.info("checkpoint_loaded", n_markets=len(results), path=str(path))
    return results
