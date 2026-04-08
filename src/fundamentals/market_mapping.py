from sqlalchemy import text

from src.db.session import SessionLocal


def _load_active_symbols() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT DISTINCT symbol FROM candle_cache")).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        db.close()


_ACTIVE_SYMBOLS = [str(s).upper() for s in _load_active_symbols() if s]
_SYNTHETIC_MARKERS = ("1HZ", "R_", "BOOM", "CRASH", "STEP", "JUMP", "RANGE")


def _is_synthetic(symbol: str) -> bool:
    s = symbol.upper()
    return any(marker in s for marker in _SYNTHETIC_MARKERS)


def get_affected_markets(currency: str) -> list[str]:
    cur = (currency or "").upper()
    if not cur:
        return []

    live_symbols = {s for s in _ACTIVE_SYMBOLS if not _is_synthetic(s)}
    usdt_symbols = [s for s in live_symbols if s.endswith("USDT")]

    mapping = {
        "USD": usdt_symbols + ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "USDCHF"],
        "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURCAD"],
        "GBP": ["GBPUSD", "EURGBP", "GBPJPY", "GBPCHF"],
        "JPY": ["USDJPY", "GBPJPY", "EURJPY", "CADJPY"],
        "XAU": ["XAUUSD"],
        "CAD": ["USDCAD", "CADJPY", "EURCAD"],
        "CHF": ["USDCHF", "EURCHF", "GBPCHF"],
    }

    candidates = mapping.get(cur, [])
    if not candidates:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for symbol in candidates:
        sym = symbol.upper()
        if sym in seen:
            continue
        if sym in live_symbols:
            seen.add(sym)
            out.append(sym)
    return out


def get_category_from_event_name(event_name: str) -> str:
    name = (event_name or "").lower()

    if any(k in name for k in ["non-farm", "nonfarm", "employment change", "nfp"]):
        return "NFP"
    if any(k in name for k in ["interest rate", "rate decision", "fed funds", "bank rate", "cash rate"]):
        return "RATE_DECISION"
    if any(k in name for k in ["consumer price", "cpi", "inflation rate"]):
        return "CPI"
    if any(k in name for k in ["gross domestic", "gdp"]):
        return "GDP"
    if any(k in name for k in ["purchasing managers", "pmi", "business activity"]):
        return "PMI"
    if "retail sales" in name:
        return "RETAIL_SALES"
    if any(k in name for k in ["trade balance", "current account"]):
        return "TRADE_BALANCE"
    if any(k in name for k in ["unemployment", "jobless claims", "claimant count"]):
        return "UNEMPLOYMENT"
    if any(k in name for k in ["speech", "testimony", "press conference", "statement", "minutes"]):
        return "CENTRAL_BANK_SPEECH"
    if any(k in name for k in ["earnings", "eps", "revenue"]):
        return "EARNINGS"
    return "UNKNOWN"
