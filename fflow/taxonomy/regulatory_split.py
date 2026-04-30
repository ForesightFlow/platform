"""Regulatory sub-categorization classifier.

Splits regulatory_decision markets into two subtypes (Paper 3a §4.1):

  regulatory_decision_announcement:
    Scheduled events with publicly known timing. The informed-trading window
    is hours-to-days before the announced date. Examples: FOMC meetings,
    FDA PDUFA dates, NFP/CPI/PPI releases, quarterly earnings.

  regulatory_decision_formal:
    Formal deliberation outcomes with endogenous timing. The relevant window
    is days-to-weeks. Examples: DOJ indictment timing, Senate confirmations,
    antitrust/merger rulings, civil-suit verdicts.

Markets that match neither set of rules → 'regulatory_decision_formal'
(conservative default, since these are typically open-ended deliberations).
"""

from __future__ import annotations

import re

_ANNOUNCEMENT_PATTERNS = [
    # Macroeconomic data releases
    r"\b(CPI|PPI|PCE|GDP|NFP|jobs?[ -]report|nonfarm|unemployment)\b",
    r"\binflation\b.*\b(report|data|release|print)\b",
    r"\b(FOMC|Federal Reserve|Fed)\b.*\b(meeting|decision|rate|statement|minutes)\b",
    r"\binterest rate\b.*\b(decision|hike|cut|hold)\b",
    # Scheduled earnings / corporate events
    r"\b(earnings|quarterly results?|revenue|guidance|EPS)\b",
    r"\b(IPO|direct listing)\b",
    r"\blaunch(es)?\b.*\b(by|before|on)\b",
    # FDA / drug approvals with known calendar
    r"\bFDA\b.*\bapproval\b",
    r"\bFDA\b.*\bapproves?\b",
    r"\bFDA\b.*\b(PDUFA|decision|ruling)\b",
    r"\bPDUFA\b",
    r"\bdrug\b.*\bapprova",
    # Congressional / legislative calendar votes
    r"\b(vote|pass|sign)\b.*\b(bill|act|legislation|resolution|amendment)\b",
    r"\b(Senate|House)\b.*\b(vote|confirmation|hearing)\b",
    # International scheduled events
    r"\b(election|referendum|ballot)\b",
    r"\bcentral bank\b.*\b(meeting|rate|decision)\b",
    r"\b(ECB|BOE|BOJ|RBA|SNB|PBOC)\b.*\b(rate|meeting|decision)\b",
    # Price / index releases
    r"\b(gold|oil|bitcoin|crypto|ETF)\b.*\b(above|below|reach|hit|price)\b",
    r"\bmarket cap\b",
    r"\bstock price\b",
    r"\b\$[0-9,]+[BKM]?\b.*\b(by|before|on)\b",  # price targets with deadlines
    # Regulatory calendar — SEC with known dates
    r"\bSEC\b.*\b(approv|decision|ruling|ETF)\b",
    r"\bETF\b.*\b(approv|launch|list)\b",
]

_FORMAL_PATTERNS = [
    # Law enforcement / criminal
    r"\b(indicted?|charged?|arrested?|convicted?|acquitted?|sentenced?|verdict)\b",
    r"\b(DOJ|FBI|prosecutor|grand jury|indictment)\b",
    r"\b(guilty|not guilty|plea)\b",
    r"\btrial\b",
    r"\b(prison|jail|probation|parole)\b",
    # Civil / regulatory enforcement
    r"\b(antitrust|merger|acquisition)\b.*\b(approv|block|clear|review)",
    r"\b(FTC|CFPB|CFTC|FERC)\b.*\b(approv|sue|block|fine|order)",
    r"\blawsuit\b",
    r"\bsettlement\b",
    r"\b(sanction|fine|penalty)\b",
    # Confirmations / appointments with uncertain timing
    r"\b(confirm|nominate|appoint|resign|fired?|dismiss)\b.*\b(Secretary|Director|Chair|Ambassador|Judge|Justice)\b",
    r"\b(resign|impeach|remov)\b",
    # International formal outcomes
    r"\b(war|ceasefire|peace|treaty|agreement|accord)\b",
    r"\b(sanction|embargo)\b",
    r"\b(UN|NATO|EU|WTO)\b.*\b(vote|ruling|decision|approve)\b",
]

_ANNOUNCEMENT_RE = [re.compile(p, re.IGNORECASE) for p in _ANNOUNCEMENT_PATTERNS]
_FORMAL_RE = [re.compile(p, re.IGNORECASE) for p in _FORMAL_PATTERNS]


def classify_regulatory(question: str, description: str | None = None) -> str:
    """Return 'regulatory_decision_announcement' or 'regulatory_decision_formal'.

    Uses keyword rules on question + description. Defaults to 'formal' when
    neither set matches (conservative: treats uncertain timing as formal).

    Args:
        question:    Polymarket question text.
        description: Market description (optional, may be None or empty).

    Returns:
        Subcategory string.
    """
    text = question
    if description:
        text = f"{question} {description}"

    ann_score = sum(1 for pat in _ANNOUNCEMENT_RE if pat.search(text))
    formal_score = sum(1 for pat in _FORMAL_RE if pat.search(text))

    if ann_score > formal_score:
        return "regulatory_decision_announcement"
    return "regulatory_decision_formal"


def classify_batch(
    questions: list[str],
    descriptions: list[str | None],
) -> list[str]:
    """Vectorised wrapper for classify_regulatory."""
    return [
        classify_regulatory(q, d)
        for q, d in zip(questions, descriptions)
    ]
