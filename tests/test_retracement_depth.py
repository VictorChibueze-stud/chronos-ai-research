from src.core.retracement_depth import (
    annotate_legs_with_depth,
    compute_retracement_depth,
    summarise_retracement_depths,
)


def _impulse(start_price: float, end_price: float):
    return {
        "type": "impulse",
        "start_price": start_price,
        "end_price": end_price,
        "confirmed": True,
        "start_index": 0,
        "end_index": 5,
    }


def _retracement(start_price: float, end_price, confirmed: bool = True):
    return {
        "type": "retracement",
        "start_price": start_price,
        "end_price": end_price,
        "confirmed": confirmed,
        "start_index": 5,
        "end_index": 8 if end_price is not None else None,
    }


def test_depth_40_pct():
    payload = compute_retracement_depth(
        _retracement(6000, 6400),
        _impulse(7000, 6000),
    )

    assert payload is not None
    assert payload["depth_pct"] == 40.0


def test_depth_100_pct():
    payload = compute_retracement_depth(
        _retracement(6000, 7000),
        _impulse(7000, 6000),
    )

    assert payload is not None
    assert payload["depth_ratio"] == 1.0
    assert payload["exceeds_impulse"] is False


def test_depth_exceeds_impulse():
    payload = compute_retracement_depth(
        _retracement(6000, 7300),
        _impulse(7000, 6000),
    )

    assert payload is not None
    assert payload["exceeds_impulse"] is True


def test_depth_open_retracement():
    payload = compute_retracement_depth(
        _retracement(6000, None, confirmed=False),
        _impulse(7000, 6000),
    )

    assert payload is not None
    assert payload["confirmed"] is False


def test_depth_zero_impulse_range():
    assert compute_retracement_depth(_retracement(6000, 6100), _impulse(7000, 7000)) is None


def test_annotate_legs():
    legs = [
        _impulse(7000, 6000),
        _retracement(6000, 6400),
    ]

    annotate_legs_with_depth(legs)

    assert legs[0]["retracement_depth"] is None
    assert legs[1]["retracement_depth"] is not None


def test_summarise_depths():
    legs = [
        _impulse(7000, 6000),
        _retracement(6000, 6400),
        _impulse(6400, 5800),
        _retracement(5800, 6160),
    ]

    annotate_legs_with_depth(legs)
    summary = summarise_retracement_depths(legs)

    assert summary is not None
    assert summary["mean_depth_pct"] == 50.0
