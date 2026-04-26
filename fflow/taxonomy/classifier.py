"""Rule-based market taxonomy classifier (Task 01).

Assigns one of four categories to each market based on question, description,
and category_raw. Priority order: military_geopolitics > corporate_disclosure >
regulatory_decision > other.

TODO Task 03: replace with LLM-based classifier for better recall on edge cases.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import select, update

from fflow.db import AsyncSessionLocal
from fflow.log import get_logger
from fflow.models import Market

log = get_logger(__name__)

_MILITARY_KEYWORDS = re.compile(
    r"\b("
    r"strike|struck|airstrike|bomb|missile|troops|military|ceasefire|cease.fire|"
    r"sanction|treaty|prisoner|hostage|embassy|nuclear|weapon|army|navy|invasion|"
    r"war|warfare|drone|combat|offensive|deployment|brigade|battalion|"
    r"geopolit|ukraine|russia|iran|israel|taiwan|china|nato|hamas|hezbollah|"
    r"gaza|west bank|crimea|donbas|zaporizhzhia"
    r")\b",
    re.IGNORECASE,
)

_CORPORATE_KEYWORDS = re.compile(
    r"\b("
    r"launch|release|acquisition|acqui|merger|earnings|revenue|ipo|"
    r"announce|unveil|partnership|spin.?off|buyout|takeover|"
    r"google|openai|apple|microsoft|anthropic|meta|amazon|nvidia|"
    r"tesla|spacex|samsung|deepmind|grok|gemini|claude|gpt|llm"
    r")\b",
    re.IGNORECASE,
)

_REGULATORY_KEYWORDS = re.compile(
    r"\b("
    r"fda|sec|fcc|cftc|ftc|cfpb|epa|osha|nlrb|"
    r"federal reserve|fed rate|rate cut|rate hike|interest rates?|"
    r"approve|approval|ruling|verdict|antitrust|court|supreme court|"
    r"congress|legislation|bill|act|regulation|comply|"
    r"central bank|ecb|boe|boj|the fed\b"
    r")",
    re.IGNORECASE,
)

_CATEGORY_PRIORITY = [
    ("military_geopolitics", _MILITARY_KEYWORDS),
    ("corporate_disclosure", _CORPORATE_KEYWORDS),
    ("regulatory_decision", _REGULATORY_KEYWORDS),
]


def classify_market(question: str, description: str | None, category_raw: str | None) -> str:
    text = " ".join(filter(None, [question, description, category_raw]))
    for category, pattern in _CATEGORY_PRIORITY:
        if pattern.search(text):
            return category
    return "other"


async def classify_batch(limit: int = 1000, dry_run: bool = False) -> int:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Market.id, Market.question, Market.description, Market.category_raw)
            .where(Market.category_fflow.is_(None))
            .limit(limit)
        )
        markets = rows.all()

        if not markets:
            log.info("taxonomy_nothing_to_classify")
            return 0

        updates: list[dict] = []
        for market_id, question, description, category_raw in markets:
            cat = classify_market(question or "", description, category_raw)
            updates.append({"id": market_id, "cat": cat})

        if not dry_run:
            for u in updates:
                await session.execute(
                    update(Market)
                    .where(Market.id == u["id"])
                    .values(category_fflow=u["cat"])
                )
            await session.commit()

        counts: dict[str, int] = {}
        for u in updates:
            counts[u["cat"]] = counts.get(u["cat"], 0) + 1
        log.info("taxonomy_classified", n=len(updates), **counts)
        return len(updates)
