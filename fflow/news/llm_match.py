"""Tier 3 T_news recovery: LLM-assisted date extraction via Anthropic Claude.

Requires:
  - FFLOW_ANTHROPIC_API_KEY set
  - Caller passes --confirm to acknowledge per-call cost (~$0.01-0.05)
  - Hard cap: 50 LLM calls per CLI invocation

The LLM is given the market question + description and asked to identify
the earliest public news date for the underlying event.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import NamedTuple

import structlog

log = structlog.get_logger()

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 400
_CALL_CAP = 50
_CONFIDENCE = 0.60

_SYSTEM = """You are a research assistant helping identify when news first broke about a prediction market's topic.

Given a market question, description, and optional context notes, identify the most likely date the underlying event FIRST became public knowledge. This is the "T_news" anchor — the moment the event was first observable by the public.

Key rules:
- Return the EARLIEST date when the news/event first became public, not the market resolution date
- If the context notes provide a specific date with sourcing, prefer that
- For events near or after 2025, use the resolution date as an upper bound
- Respond with ONLY a date in ISO-8601 format (YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DD) and a one-sentence explanation
- If you cannot determine a date, respond with "UNKNOWN"

Format:
DATE: <ISO-8601 date>
REASON: <one sentence>"""


class LLMTimestamp(NamedTuple):
    t_news: datetime
    confidence: float
    notes: str


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
    extra_context: str = "",
) -> LLMTimestamp | None:
    """Call Claude to extract a T_news date from the market text.

    Args:
        question:    Market question text
        description: Market description (may be None)
        api_key:     Anthropic API key
        confirmed:   Must be True to actually make the call (--confirm gate)

    Returns None if:
        - confirmed is False
        - call cap exceeded
        - LLM returns UNKNOWN
        - API error
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

    desc_section = f"\n\nDescription: {description}" if description else ""
    ctx_section = f"\n\nContext notes: {extra_context}" if extra_context else ""
    user_msg = f"Question: {question}{desc_section}{ctx_section}"

    _call_counter += 1
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        log.warning("llm_api_error", error=str(exc))
        _call_counter -= 1
        return None

    text = response.content[0].text if response.content else ""
    date_match = re.search(r"DATE:\s*(\S+)", text)
    reason_match = re.search(r"REASON:\s*(.+)", text)

    if not date_match or "UNKNOWN" in date_match.group(1).upper():
        log.info("llm_no_date", question=question[:80])
        return None

    raw_date = date_match.group(1).strip()
    notes = reason_match.group(1).strip() if reason_match else ""

    # Parse date
    dt: datetime | None = None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw_date[:len(fmt)], fmt).replace(tzinfo=UTC)
            break
        except ValueError:
            continue

    if dt is None:
        log.warning("llm_unparseable_date", raw=raw_date)
        return None

    return LLMTimestamp(t_news=dt, confidence=_CONFIDENCE, notes=notes)
