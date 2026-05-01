"""Resolution type classifier for Polymarket prediction markets.

Determines whether a market uses a deadline-based resolution (the question
commits to a specific date by which something must occur) or falls through to
the conservative 'unclassifiable' bucket.

'event_resolved' detection (oracle decides timing with no pre-committed date)
is intentionally deferred to Phase 1 — Phase 0 only needs correct
deadline_resolved identification.
"""

import re
from typing import Literal

ResolutionType = Literal["deadline_resolved", "event_resolved", "unclassifiable"]

# Matches:  "by/before/prior to/no later than [optional: 'end of'] <date>"
# Date formats covered:
#   - "[Month] [Day][st/nd/rd/th]" and "[Month] [Day][st/nd/rd/th], [Year]"
#   - "[Month]" alone (full or abbreviated)
#   - bare year:      "by 2026"
#   - quarter:        "by Q2 2026"
#   - numeric date:   "by 4/30", "by 04-30-2026"
_DEADLINE_RE = re.compile(
    r"\b(?:by|before|prior\s+to|no\s+later\s+than)\s+"
    r"(?:(?:the\s+)?end\s+of\s+)?"
    r"(?:"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:\s+\d{1,2}(?:st|nd|rd|th)?)?"  # optional day with ordinal
    r"(?:,?\s*\d{4})?"                  # optional year
    r"|\d{4}"                           # bare year: "by 2026"
    r"|Q[1-4](?:\s+\d{4})?"             # quarter: "by Q2 2026"
    r"|\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?"  # numeric: "4/30", "04-30-2026"
    r")",
    re.IGNORECASE,
)


def classify_resolution_type(
    question: str,
    description: str | None = None,
) -> ResolutionType:
    """Classify market resolution type from question and optional description."""
    rtype, _ = classify_resolution_type_detailed(question, description)
    return rtype


def classify_resolution_type_detailed(
    question: str,
    description: str | None = None,
) -> tuple[ResolutionType, bool]:
    """Classify and flag description-only matches.

    Returns:
        (resolution_type, description_only_match)
        description_only_match=True when the deadline pattern was found in the
        description but NOT in the question alone — potential false positive worth
        auditing (e.g. the question has no date but description mentions one).
    """
    if _DEADLINE_RE.search(question):
        return "deadline_resolved", False
    if description and _DEADLINE_RE.search(description):
        return "deadline_resolved", True
    return "unclassifiable", False
