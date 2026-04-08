from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyser = SentimentIntensityAnalyzer()

_FINANCE_SENTIMENT_WEIGHTS: dict[str, float] = {
    # Positive market context
    "surge": 0.55,
    "surges": 0.55,
    "rally": 0.5,
    "rallies": 0.5,
    "all-time high": 0.65,
    "etf inflow": 0.45,
    "etf inflows": 0.45,
    "beats": 0.4,
    "stronger": 0.3,
    # Negative market context
    "inflation concern": -0.5,
    "inflation concerns": -0.5,
    "hawkish": -0.45,
    "rate hike": -0.6,
    "raises rates": -0.6,
    "selloff": -0.6,
    "slump": -0.5,
    "plunge": -0.65,
    "recession": -0.65,
}


def _finance_fallback_compound(text: str) -> float:
    lowered = text.lower()
    score = 0.0
    for phrase, weight in _FINANCE_SENTIMENT_WEIGHTS.items():
        if phrase in lowered:
            score += weight
    if score > 0.95:
        return 0.95
    if score < -0.95:
        return -0.95
    return score


def classify_headline(text: str) -> tuple[str, float]:
    normalized = (text or "").strip()
    scores = _analyser.polarity_scores(normalized)
    compound = float(scores["compound"])

    # Keep VADER as source-of-truth and only apply domain fallback on near-neutral text.
    if normalized and -0.05 < compound < 0.05:
        fallback = _finance_fallback_compound(normalized)
        if fallback != 0.0:
            compound = fallback

    if compound >= 0.05:
        return ("positive", compound)
    elif compound <= -0.05:
        return ("negative", compound)
    else:
        return ("neutral", compound)
