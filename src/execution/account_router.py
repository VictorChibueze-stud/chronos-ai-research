"""
Maps each monitored symbol to the correct paper account.
Deriv Non-Synthetic: forex, commodity, indices
Deriv Synthetic: synthetic
Binance: crypto
"""
from src.api.routers.setups import _infer_category

ACCOUNT_TYPE_FOR_CATEGORY: dict[str, str] = {
    "forex": "deriv_non_synthetic",
    "commodity": "deriv_non_synthetic",
    "indices": "deriv_non_synthetic",
    "synthetic": "deriv_synthetic",
    "crypto": "binance",
}


def get_account_type_for_symbol(symbol: str) -> str:
    cat = _infer_category(symbol)
    return ACCOUNT_TYPE_FOR_CATEGORY.get(
        cat, "deriv_non_synthetic"
    )
