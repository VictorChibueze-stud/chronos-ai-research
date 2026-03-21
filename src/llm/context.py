from __future__ import annotations
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from src.core.features import compute_price_features, Candle
from src.llm.schemas import (
    MarketSnapshot, TrendState, VolatilityState, StructureState, MomentumState,
    LongTermSummary, InstrumentInfo
)

def build_snapshot(candles: List[Candle], timeframe: str) -> MarketSnapshot:
    """
    Converts raw OHLC candles into a token-efficient MarketSnapshot.
    """
    # 1. Compute technical features
    # Guard against empty candle lists to ensure snapshot building never crashes.
    if not candles:
        # build a minimal MarketSnapshot using safe defaults
        trend = TrendState(direction="sideways", strength=0.0, ema_alignment="mixed")
        momentum = MomentumState(rsi=50.0, state="neutral")
        volatility = VolatilityState(atr_value=0.0, regime="low")
        structure = StructureState(recent_swing_high=None, recent_swing_low=None, dist_to_support_pct=0.0)
        return MarketSnapshot(
            symbol="UNKNOWN",
            timeframe=timeframe,
            timestamp="",
            price=0.0,
            trend=trend,
            momentum=momentum,
            volatility=volatility,
            structure=structure,
            recent_events=[],
        )

    features = compute_price_features(candles, timeframe)

    # Extract helpers safely (some callers/tests may provide minimal dicts)
    now = features.get("now_panel", {})
    struct = features.get("structure_map", {})
    meta = features.get("meta", {})
    tags = features.get("regime_tags", {})
    events = features.get("ict_events", [])
    
    # 2. Build Sub-States
    
    # Trend
    # mapping 'regime_tags' boolean/str to schema enum
    # features.py returns regime_tags as a dict of booleans usually, or we derive it.
    # Let's check features.py output structure from memory/systemspec:
    # regime_tags keys: 'is_trending_up', 'is_trending_down', 'is_range', 'adx'
    
    direction = "sideways"
    if tags.get("is_trending_up"):
        direction = "up"
    elif tags.get("is_trending_down"):
        direction = "down"
        
    # EMA Alignment
    # features.py 'now_panel' usually has 'ema_fast', 'ema_slow'
    ema_fast = now.get("ema_fast", now.get("ema20", 0.0))
    ema_slow = now.get("ema_slow", now.get("ema50", 0.0))
    price = float(now.get("close", 0.0))
    
    ema_align = "mixed"
    if price > ema_fast > ema_slow:
        ema_align = "bullish"
    elif price < ema_fast < ema_slow:
        ema_align = "bearish"
        
    trend = TrendState(
        direction=direction,
        strength=float(tags.get("adx", tags.get("adx14", 0.0)) or 0.0),
        ema_alignment=ema_align,
    )
    
    # Momentum (New)
    # support both 'rsi' and 'rsi14' keys
    rsi_val = float(now.get("rsi", now.get("rsi14", 50.0)))
    mom_state = "neutral"
    if rsi_val > 70:
        mom_state = "overbought"
    elif rsi_val < 30:
        mom_state = "oversold"
        
    momentum = MomentumState(
        rsi=rsi_val,
        state=mom_state
    )
    
    # Volatility
    atr_val = float(now.get("atr", now.get("atr14", 0.0)))
    # Heuristic for regime: compare to some baseline or use tag
    vol_regime = "normal"
    if tags.get("is_vol_spike"):
        vol_regime = "high"
    elif tags.get("is_low_vol"):
        vol_regime = "low"
        
    volatility = VolatilityState(
        atr_value=atr_val,
        regime=vol_regime
    )
    
    # Structure
    # structure_map keys: 'swing_highs', 'swing_lows' (lists of (idx, price))
    # We want the most recent ones.
    recent_high = None
    recent_low = None
    # structure_map may provide 'swings' list with dicts, or 'swing_highs' tuples
    swings = struct.get("swings") or []
    if swings:
        # find last SH and SL
        for s in reversed(swings):
            if s.get("type") == "SH" and recent_high is None:
                recent_high = s.get("price")
            if s.get("type") == "SL" and recent_low is None:
                recent_low = s.get("price")
            if recent_high is not None and recent_low is not None:
                break

    # fallbacks for legacy keys (defensive)
    if recent_high is None:
        swing_highs = struct.get("swing_highs") or []
        if swing_highs and isinstance(swing_highs[-1], (list, tuple)) and len(swing_highs[-1]) > 1:
            recent_high = swing_highs[-1][1]

    if recent_low is None:
        swing_lows = struct.get("swing_lows") or []
        if swing_lows and isinstance(swing_lows[-1], (list, tuple)) and len(swing_lows[-1]) > 1:
            recent_low = swing_lows[-1][1]
        
    # Distance to support/resistance logic would go here
    # For v1 simple implementation:
    structure = StructureState(
        recent_swing_high=recent_high,
        recent_swing_low=recent_low,
        dist_to_support_pct=0.0,
    )
    
    # Events
    # ict_events is dict of boolean arrays: 'bos_high', 'bos_low', etc.
    # Scan last 3 bars
    recent_events = []
    lookback = 3
    event_keys = ["bos_high", "bos_low", "choch_high", "choch_low", "fvg_up", "fvg_down", "liquidity_sweep_high", "liquidity_sweep_low"]
    
    for key in event_keys:
        arr = events if isinstance(events, list) else events.get(key) if isinstance(events, dict) else None
        if isinstance(arr, list) and len(arr) > 0:
            recent_events.append(key)
        elif arr is not None and len(arr) > 0:
            subset = arr[-lookback:]
            if np.any(subset):
                recent_events.append(key)
                
    # 3. Assemble Snapshot
    return MarketSnapshot(
        symbol=meta.get("symbol", "UNKNOWN"),
        timeframe=timeframe,
        timestamp=str(meta.get("end_time", now.get("time", ""))),
        price=price,
        trend=trend,
        momentum=momentum,
        volatility=volatility,
        structure=structure,
        recent_events=recent_events,
    )

def build_long_term_summary(daily_candles: List[Candle]) -> LongTermSummary:
    """
    Compresses daily history into regimes and key levels.
    """
    if not daily_candles:
        return LongTermSummary(regime_history=[], key_levels={}, volatility_context={})
        
    # Convert to DataFrame for easier resampling
    df = pd.DataFrame([c.__dict__ for c in daily_candles])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('timestamp', inplace=True)
    
    # Key Levels
    high_52w = float(df['high'].max())
    low_52w = float(df['low'].min())
    # YTD high (assuming data covers YTD)
    current_year = df.index[-1].year
    ytd_df = df[df.index.year == current_year]
    ytd_high = float(ytd_df['high'].max()) if not ytd_df.empty else high_52w
    
    key_levels = {
        "52w_high": high_52w,
        "52w_low": low_52w,
        "ytd_high": ytd_high
    }
    
    # Regimes (Monthly Resample)
    monthly = df.resample('M').agg({
        'open': 'first',
        'close': 'last',
        'high': 'max',
        'low': 'min'
    })
    
    regime_history = []
    for date, row in monthly.iterrows():
        period_str = date.strftime("%Y-%b")
        change_pct = ((row['close'] - row['open']) / row['open']) * 100
        label = "uptrend" if change_pct > 0 else "downtrend"
        if abs(change_pct) < 1.0: # arbitrary 1% threshold for monthly range
            label = "sideways"
            
        regime_history.append({
            "period": period_str,
            "label": label,
            "change_pct": round(change_pct, 2)
        })
        
    # Volatility Context
    # Compare last 20d ATR vs 180d ATR
    # Quick approx using TR
    df['tr'] = np.maximum(df['high'] - df['low'], 
                          np.abs(df['high'] - df['close'].shift(1)))
    
    current_vol = df['tr'].tail(20).mean()
    long_vol = df['tr'].tail(180).mean()
    
    ratio = 1.0
    if long_vol > 0:
        ratio = current_vol / long_vol
        
    vol_comment = "normal"
    if ratio > 1.5:
        vol_comment = "high"
    elif ratio < 0.7:
        vol_comment = "low"
        
    vol_context = {
        "current_vs_6m_avg": round(ratio, 2),
        "comment": vol_comment
    }
    
    return LongTermSummary(
        regime_history=regime_history[-6:], # Last 6 months
        key_levels=key_levels,
        volatility_context=vol_context
    )

def get_instrument_info(symbol: str) -> InstrumentInfo:
    """
    Returns static metadata for the instrument.
    In a real app, this would query a config or DB.
    """
    # Dummy defaults for now
    return InstrumentInfo(
        symbol=symbol,
        pip_size=0.01,
        pip_value_per_lot=1.0,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01
    )

def build_multi_snapshot(candles_map: Dict[str, List[Candle]]) -> Dict[str, MarketSnapshot]:
    """
    Helper to build snapshots for multiple timeframes at once.
    candles_map: {"15m": [candles...], "1h": [candles...]}
    """
    return {
        tf: build_snapshot(candles, tf) 
        for tf, candles in candles_map.items()
    }

# Backwards compatibility alias if needed by legacy tests
build_single_snapshot = build_snapshot