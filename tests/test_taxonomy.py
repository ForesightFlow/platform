"""Taxonomy classifier tests — 10 hand-crafted (question, expected_category) pairs."""

import pytest

from fflow.taxonomy.classifier import classify_market


@pytest.mark.parametrize(
    "question,description,category_raw,expected",
    [
        # Military / Geopolitics
        (
            "Will Israel conduct an airstrike on Iran before June 2025?",
            "Market resolves YES if Israeli aircraft conduct an airstrike on Iranian territory.",
            "geopolitics",
            "military_geopolitics",
        ),
        (
            "Will Russia and Ukraine sign a ceasefire agreement in 2025?",
            None,
            "politics",
            "military_geopolitics",
        ),
        (
            "Will NATO deploy troops to a new country by Q3 2025?",
            "Market covers military deployment decisions by NATO.",
            "",
            "military_geopolitics",
        ),
        # Corporate disclosure
        (
            "Will OpenAI release GPT-5 before July 2025?",
            "Resolves YES if OpenAI publicly launches GPT-5 model.",
            "technology",
            "corporate_disclosure",
        ),
        (
            "Will Apple announce a new product at WWDC 2025?",
            None,
            "tech",
            "corporate_disclosure",
        ),
        (
            "Will Google complete its acquisition of XYZ Corp by end of 2025?",
            "Market on M&A outcome.",
            "business",
            "corporate_disclosure",
        ),
        # Regulatory decision
        (
            "Will the FDA approve drug X by December 2025?",
            "Resolves YES if FDA grants approval for the drug.",
            "health",
            "regulatory_decision",
        ),
        (
            "Will the Fed cut interest rates in the September 2025 meeting?",
            None,
            "economics",
            "regulatory_decision",
        ),
        (
            "Will the Supreme Court rule in favor of plaintiff in case ABC?",
            "Antitrust ruling expected by mid-2025.",
            "law",
            "regulatory_decision",
        ),
        # Other
        (
            "Will the LA Lakers win the NBA championship in 2025?",
            "Basketball championship market.",
            "sports",
            "other",
        ),
    ],
)
def test_classify_market(question, description, category_raw, expected):
    result = classify_market(question, description, category_raw)
    assert result == expected, (
        f"Expected {expected!r} for {question!r}, got {result!r}"
    )
