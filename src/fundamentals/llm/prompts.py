"""
LLM prompt templates for the 3-call
fundamentals intelligence chain.

Each prompt is designed for a specific task
with enforced JSON output. The prompts are
intentionally written for free-tier models
with limited context — they are concise,
explicit, and provide clear output schemas.
"""

# ============================================
# CALL 1 — RELEVANCE AND SENTIMENT FILTER
# ============================================

FILTER_SYSTEM = """You are a financial news analyst. Your job is to classify news headlines for a specific trading market. You must return ONLY valid JSON with no explanation, no markdown, no preamble."""

FILTER_USER = """Market: {market}
Market description: {market_description}
Analysis date: {analysis_date}

Classify each headline below. For each:

RELEVANCE (choose exactly one):
- Direct: directly about this market or its primary drivers (currency pair, company, commodity)
- Related: covers a related market or secondary driver
- Contextual: macro context that could indirectly affect this market
- Peripheral: loosely connected, low signal value
- Noise: duplicate rephrasing of another headline with no new information

SENTIMENT toward {market} (choose exactly one):
- Strongly Bearish: explicit negative macro signal
- Mildly Bearish: cautious or mildly negative tone
- Neutral: factual reporting with no clear direction
- Mildly Bullish: positive or supportive tone
- Strongly Bullish: explicit positive macro signal

IMPORTANT: Drop all Noise and Peripheral headlines from your output.

Headlines to classify (popularity_count = number of outlets that covered this story):
{headlines_json}

Return this exact JSON structure and nothing else:
{{"filtered": [{{"id": "h_001", "headline": "...", "source": "...", "published_at": "...", "url": "...", "popularity_count": 3, "relevance": "Direct", "sentiment": "Neutral"}}]}}"""


# ============================================
# CALL 2 — STORY CLUSTERING
# ============================================

CLUSTER_SYSTEM = """You are a financial analyst building a structured news brief for a swing trader. Group related headlines into coherent stories like Twitter's Today's News feature. Return ONLY valid JSON with no explanation."""

CLUSTER_USER = """Market: {market}
News window: {window_start} to {window_end}

Classified headlines:
{filtered_json}

Group these headlines into distinct stories. Each story represents one underlying event or theme.

For each story provide:
- story_id: short ID like "s_001"
- story_title: concise title maximum 8 words
- actors: key people or institutions involved, each with their own sentiment and relevance toward {market}
- summary: exactly one sentence explaining what happened and why it matters for {market}
- overall_sentiment: aggregate sentiment of the story toward {market}
- overall_relevance: aggregate relevance to {market}
- timeline: all articles belonging to this story sorted by published_at ascending

Use these exact sentiment values: Strongly Bearish, Mildly Bearish, Neutral, Mildly Bullish, Strongly Bullish
Use these exact relevance values: Direct, Related, Contextual

Return this exact JSON structure and nothing else:
{{"stories": [{{"story_id": "s_001", "story_title": "...", "actors": [{{"name": "...", "role": "...", "sentiment": "...", "relevance": "..."}}], "summary": "...", "overall_sentiment": "...", "overall_relevance": "...", "timeline": [{{"headline": "...", "source": "...", "published_at": "...", "url": "...", "sentiment": "...", "relevance": "...", "popularity_count": 3}}]}}]}}"""


# ============================================
# CALL 3 — VETO ASSESSMENT
# ============================================

VETO_SYSTEM = """You are a risk analyst for an automated swing trading system. Your job is to determine whether current macro news or upcoming events justify blocking new trade entries for a specific market. Be conservative — only flag genuine market-moving shocks, not routine news. Return ONLY valid JSON."""

VETO_USER = """Market: {market}
Current date/time: {now_utc}

Recent news stories (from prime impulse start to now):
{stories_json}

Upcoming economic events (next 30 days):
{upcoming_events_json}

VETO CRITERIA — set critical_veto_flag to true ONLY for:
1. Emergency or surprise central bank decision actively unfolding (not expected/priced-in moves)
2. Geopolitical shock directly involving the base/quote currency country — war, sanctions, political collapse
3. Equity market: earnings release within 24 hours with analyst estimates showing >5% expected move
4. Any unprecedented macro event creating extreme uncertainty that a swing trader should avoid

DO NOT veto for:
- Routine scheduled Fed/ECB/BOE speeches reiterating current policy
- Expected rate decisions already priced in by markets
- Normal CPI/NFP releases unless actual vs forecast divergence is extreme (>3 standard deviations)
- General market uncertainty or geopolitical noise with no direct market impact

If vetoing, set veto_expires_at to when the risk window is expected to clear (ISO format UTC).

Return this exact JSON structure and nothing else:
{{"critical_veto_flag": false, "veto_reason": null, "veto_expires_at": null, "risk_summary": "One sentence overall macro risk assessment for {market}"}}"""


def build_market_description(symbol: str) -> str:
    """Human-readable description of market for LLM context."""
    sym = symbol.upper()
    descriptions = {
        "FRXEURUSD": "Euro vs US Dollar currency pair",
        "FRXGBPUSD": "British Pound vs US Dollar",
        "FRXUSDJPY": "US Dollar vs Japanese Yen",
        "FRXAUDJPY": "Australian Dollar vs Japanese Yen",
        "FRXGBPJPY": "British Pound vs Japanese Yen",
        "XAUUSD": "Gold vs US Dollar (spot gold)",
        "FRXUSDCAD": "US Dollar vs Canadian Dollar",
        "FRXUSDCHF": "US Dollar vs Swiss Franc",
    }
    if sym in descriptions:
        return descriptions[sym]
    if sym.startswith("FRX"):
        base, quote = sym[3:6], sym[6:9]
        return f"{base} vs {quote} currency pair"
    if sym.endswith("USDT"):
        coin = sym.replace("USDT", "")
        return f"{coin} cryptocurrency vs US Dollar"
    return f"{sym} financial instrument"
