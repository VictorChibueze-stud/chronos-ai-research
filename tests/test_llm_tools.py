from src.llm.tools import propose_trade_levels, position_size


def test_propose_trade_levels_long_sl_below_entry():
    entry = 100.0
    atr = 1.0
    out = propose_trade_levels("long", entry, atr)
    assert out["direction"] == "long"
    assert out["stop_loss"] < out["entry"]
    assert out["take_profit"] > out["entry"]


def test_position_size_clamps_risk():
    equity = 10000.0
    # unrealistic high risk -> should be clamped to 2%
    out = position_size(equity=equity, risk_pct=50.0, entry_price=100.0, stop_loss_price=95.0)
    assert out["capped_risk"] is True
    # cash at risk should be 2% of equity
    assert out["cash_at_risk"] == 10000.0 * (2.0 / 100.0)
    assert out["volume"] >= 0.0
