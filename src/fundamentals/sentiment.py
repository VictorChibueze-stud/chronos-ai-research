"""
Sentiment classification for fundamentals.

NOTE: vader-based scoring has been removed.
Sentiment classification is now performed by
the LLM intelligence layer in
src/fundamentals/llm/processor.py.

This module is kept as a compatibility shim
so existing imports do not break.
The classify_headline function always returns
neutral — it is only called from legacy paths
that have not yet been migrated.
"""
from __future__ import annotations


def classify_headline(
    text: str,
) -> tuple[str, float]:
    """
    Legacy compatibility shim.
    Returns neutral sentiment.
    Actual classification is done by the
    LLM chain in fundamentals/llm/processor.py.
    """
    return ("neutral", 0.0)
