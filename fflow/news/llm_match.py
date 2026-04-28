"""Tier 3 T_news / T_event recovery via Anthropic Claude with web search.

Requires:
  - FFLOW_ANTHROPIC_API_KEY set
  - Caller passes --confirm to acknowledge per-call cost (~$0.05-0.20 with web search)
  - Hard cap: 50 LLM calls per CLI invocation

Two recovery modes (paper §7.2):
  - "t_news": event_resolved markets — when was this event first publicly reported?
  - "t_event": deadline_resolved YES markets — when did the event actually happen?

Web search (web_search_20250305) enables post-training-cutoff event recovery.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

import structlog

log = structlog.get_logger()

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024  # web search synthesis needs more tokens than plain completion
_CALL_CAP = 50
_CONFIDENCE_SEARCH = 0.80
_CONFIDENCE_NO_SEARCH = 0.60

_SYSTEM_T_NEWS = """\
You are a research assistant identifying when a prediction market event was first publicly reported.

Use web search to find the EARLIEST date a credible news outlet (Reuters, AP, CNN, BBC, \
Al Jazeera, NYT, Washington Post, Guardian, etc.) published a story about the underlying event.

Respond with EXACTLY this format:
DATE: <ISO-8601 date, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ>
SOURCES: <comma-separated list of outlets>
REASON: <one sentence>

If you cannot find a confident date after searching, respond with:
DATE: UNKNOWN
SOURCES: none
REASON: <why you couldn't find it>\
"""

_SYSTEM_T_EVENT = """\
You are a research assistant identifying when a real-world event actually occurred and became \
publicly observable.

Use web search to find WHEN the underlying event happened — not when markets opened or when \
committees resolved the question, but when the event itself was publicly confirmed. \
Cross-check at least two independent sources: Reuters, AP, CNN, BBC, Al Jazeera, \
local news outlets, or official government sources.

Respond with EXACTLY this format:
DATE: <ISO-8601 date, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ>
SOURCES: <comma-separated list of outlets that confirmed the event>
REASON: <one sentence: what happened and when>

If you cannot find the event date after searching, respond with:
DATE: UNKNOWN
SOURCES: none
REASON: <why you couldn't determine it>\
"""


class LLMTimestamp(NamedTuple):
    t_news: datetime
    confidence: float
    notes: str
    sources: tuple[str, ...] = ()


_call_counter = 0


def reset_call_counter() -> None:
    global _call_counter
    _call_counter = 0


async def llm_extract_date(
    question: str,
    description: str | None,
    api_key: str,
    *,
    confirmed: bool = False,
    recovery_mode: Literal["t_news", "t_event"] = "t_news",
) -> LLMTimestamp | None:
    """Call Claude with web search to recover a date from market text.

    Args:
        question:      Market question text.
        description:   Market description (may be None).
        api_key:       Anthropic API key.
        confirmed:     Must be True to make the API call (--confirm gate).
        recovery_mode: "t_news" → earliest news report date.
                       "t_event" → when the event actually happened.

    Returns None if: confirmed is False, call cap exceeded, LLM returns UNKNOWN,
    or API error.
    """
    global _call_counter

    if not confirmed:
        log.info("llm_tier3_skipped", reason="--confirm not passed")
        return None

    if _call_counter >= _CALL_CAP:
        log.warning("llm_call_cap_reached", cap=_CALL_CAP)
        return None

    try:
        import anthropic
    except ImportError:
        log.warning("llm_unavailable", reason="anthropic package not installed")
        return None

    system_prompt = _SYSTEM_T_EVENT if recovery_mode == "t_event" else _SYSTEM_T_NEWS

    desc_section = f"\n\nDescription: {description}" if description else ""
    mode_label = "when the event actually occurred" if recovery_mode == "t_event" else "when news first broke"
    user_msg = (
        f"Market question: {question}{desc_section}\n\n"
        f"Find: {mode_label}. Search for credible sources and cross-check dates."
    )

    _call_counter += 1
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        log.warning("llm_api_error", error=str(exc))
        _call_counter -= 1
        return None

    # With web search, response is split across many text blocks interleaved with
    # server_tool_use / web_search_tool_result blocks. Concatenate all text blocks.
    text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )

    log.debug(
        "llm_raw_response",
        question=question[:60],
        mode=recovery_mode,
        stop_reason=response.stop_reason,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    date_match = re.search(r"DATE:\s*(\S+)", text)
    sources_match = re.search(r"SOURCES:\s*(.+)", text)
    reason_match = re.search(r"REASON:\s*(.+)", text)

    if not date_match or "UNKNOWN" in date_match.group(1).upper():
        log.info("llm_no_date", question=question[:80], mode=recovery_mode)
        return None

    raw_date = date_match.group(1).strip().rstrip(".,;")
    notes = reason_match.group(1).strip() if reason_match else ""
    sources_raw = sources_match.group(1).strip() if sources_match else ""
    sources = tuple(s.strip() for s in sources_raw.split(",") if s.strip() and s.strip().lower() != "none")

    dt: datetime | None = None
    # Try formats longest-first; do NOT slice by fmt length (format len ≠ output len)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw_date, fmt)
            dt = parsed.replace(tzinfo=UTC)
            break
        except ValueError:
            continue

    if dt is None:
        log.warning("llm_unparseable_date", raw=raw_date)
        return None

    confidence = _CONFIDENCE_SEARCH if sources else _CONFIDENCE_NO_SEARCH
    log.info(
        "llm_date_recovered",
        question=question[:60],
        mode=recovery_mode,
        date=dt.isoformat(),
        sources=sources,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return LLMTimestamp(t_news=dt, confidence=confidence, notes=notes, sources=sources)
