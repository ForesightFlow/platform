"""Heuristic classification of market resolution types.

Types:
  event_resolved   — outcome determined by a specific observable event
  deadline_resolved — "nothing happened by deadline" markets
  surprise_resolved — price strongly opposed to actual outcome
  unclassifiable   — insufficient signal
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from fflow.models import Market

# Patterns suggesting YES = something happened (event_resolved)
_EVENT_POSITIVE_PATTERNS = re.compile(
    r"\b(win|wins|won|elected|approved|confirmed|passed|signed|launched|"
    r"listed|acquired|merged|arrested|indicted|convicted|sentenced|died|"
    r"resigned|fired|appointed|released|achieved|reached|hit|surpassed|"
    r"breaks|broke|crosses|crossed|topped|sets|set|falls|fell|drops|dropped|"
    r"flips|flipped|declares|declared|announces|announced|completes|completed|"
    r"becomes|became|gets|got|is (?:approved|confirmed|elected|appointed|passed|listed))\b",
    re.IGNORECASE,
)

# Patterns suggesting "nothing happened by date" (deadline_resolved)
_DEADLINE_PATTERNS = re.compile(
    r"\b(by|before|prior to|no later than|within)\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"end of|eoy|eom|q[1-4]|\d{1,2}/\d{1,2}|\d{4})",
    re.IGNORECASE,
)

# Phrases strongly associated with "will X happen" structure
_WILL_HAPPEN_PATTERNS = re.compile(
    r"\b(will .{3,60}(happen|occur|take place|be (?:approved|signed|passed|elected|"
    r"confirmed|appointed|listed|released|launched|completed|resolved|announced|"
    r"implemented|enacted|withdrawn|dismissed)))",
    re.IGNORECASE,
)


def classify_from_text(
    question: str,
    resolution_outcome: int | None,
    last_price: float | None,
) -> str:
    """Pure-function classifier. Used by both sync and async paths."""
    if resolution_outcome is None:
        return "unclassifiable"

    q = question.strip()

    # Heuristic 3: surprise — price strongly opposite to outcome (checked first,
    # independent of question text)
    if last_price is not None:
        gap = abs(last_price - resolution_outcome)
        if gap > 0.7:
            return "surprise_resolved"

    # Heuristic 1: YES outcome + event language → event_resolved
    if resolution_outcome == 1:
        if _EVENT_POSITIVE_PATTERNS.search(q) or _WILL_HAPPEN_PATTERNS.search(q):
            return "event_resolved"

    # Heuristic 2: NO outcome + deadline language → deadline_resolved
    if resolution_outcome == 0:
        if _DEADLINE_PATTERNS.search(q):
            return "deadline_resolved"

    # NO outcome WITHOUT deadline language can still be event_resolved if question
    # asks "will X win/be approved" — the event didn't happen (resolved NO)
    if resolution_outcome == 0:
        if _EVENT_POSITIVE_PATTERNS.search(q) or _WILL_HAPPEN_PATTERNS.search(q):
            return "event_resolved"

    return "unclassifiable"


async def classify_resolution_type(
    market_id: str,
    session: AsyncSession,
    *,
    last_price: float | None = None,
) -> str:
    """Load market from DB and classify its resolution type."""
    market = await session.get(Market, market_id)
    if market is None:
        return "unclassifiable"
    return classify_from_text(
        question=market.question,
        resolution_outcome=market.resolution_outcome,
        last_price=last_price,
    )
