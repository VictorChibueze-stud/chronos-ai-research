# Data Contract: Ikenga Engine Output

**Version:** 1.0  
**Owner:** Product Engineer  
**Consumer:** System Architect / Orchestrator Layer  
**Status:** Draft for Review

---

## Overview

This document defines the exact JSON schema produced by Ikenga
technical analysis engine for a single asset setup. The Orchestrator consumes
this output to populate the database, trigger alerts, and manage setup state.

The engine output is produced by running two functions in sequence:

1. `identify_trend(candles, **filter_config)` — identifies the global trend
2. `walk_structure(candles, result, filter_config, max_depth, binance_symbol)` — analyzes the current retracement

---

## 1. Core State

The top-level fields describing the current market state for one asset and timeframe.

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "as_of": "2026-03-22T23:00:00Z",

  "global_trend": {
    "direction": "down",
    "current_phase": "retracement",
    "confirmed_legs": 5,
    "confirmed_impulses": 3,
    "confirmed_retracements": 2
  },

  "status": "IN_RETRACEMENT"
}
```

**Status values:**

| Value | Meaning |
|---|---|
| `IMPULSING` | Market is in an impulse leg in the trend direction |
| `IN_RETRACEMENT` | Market is moving against the trend — analysis active |
| `RANGE` | No clear trend detected |

---

## 2. Walker Output — The Structural State JSON Blob

This is the full nested output of `walk_structure`. This goes directly into
`structural_state_json` on the `MonitoredSetup` table.

```json
{
  "walkable": true,
  "global_trend": "down",
  "total_mitigation_count": 3,
  "max_depth_reached": 3,
  "deepest_termination_reason": "max_depth_reached",
  "waiting_for": "Maximum depth 3 reached. Monitor CHoCH zone at depth 3.",
  "stars_aligned": false,

  "levels": [
    {
      "depth": 1,
      "slice_start": 1321,
      "slice_end": 2399,
      "first_impulse_global_start": 1321,
      "first_impulse_global_end": 1392,
      "first_impulse": {
        "type": "impulse",
        "confirmed": true,
        "start_price": 60000.0,
        "end_price": 72271.41
      },
      "structural_level": {
        "price": 72271.41
      },
      "choch_zone": {
        "lower_boundary": 64500.0,
        "upper_boundary": 66826.5,
        "zone_midpoint": 65663.25,
        "zone_width_pct": 3.61,
        "trend_direction": "up"
      },
      "choch_mitigated": true,
      "crossing_attempt": {
        "start_price": 62510.28,
        "end_price": 74050.0,
        "global_start_index": 1768,
        "global_end_index": 1966
      },
      "internal_tf_used": "current",
      "termination_reason": "max_depth_reached"
    },
    {
      "depth": 2,
      "slice_start": 1768,
      "slice_end": 2399,
      "first_impulse_global_start": 1768,
      "first_impulse_global_end": 1966,
      "first_impulse": {
        "type": "impulse",
        "confirmed": true,
        "start_price": 62510.28,
        "end_price": 74050.0
      },
      "structural_level": {
        "price": 74050.0
      },
      "choch_zone": {
        "lower_boundary": 63030.0,
        "upper_boundary": 69988.83,
        "zone_midpoint": 66509.42,
        "zone_width_pct": 11.04,
        "trend_direction": "up"
      },
      "choch_mitigated": true,
      "crossing_attempt": {
        "start_price": 65618.49,
        "end_price": 74451.03,
        "global_start_index": 2063,
        "global_end_index": 2175
      },
      "internal_tf_used": "current",
      "termination_reason": "max_depth_reached"
    },
    {
      "depth": 3,
      "slice_start": 2063,
      "slice_end": 2399,
      "first_impulse_global_start": 2191,
      "first_impulse_global_end": 2237,
      "first_impulse": {
        "type": "impulse",
        "confirmed": true,
        "start_price": 70622.08,
        "end_price": 74451.03
      },
      "structural_level": {
        "price": 74451.03
      },
      "choch_zone": {
        "lower_boundary": 72270.41,
        "upper_boundary": 73199.0,
        "zone_midpoint": 72734.71,
        "zone_width_pct": 1.28,
        "trend_direction": "up"
      },
      "choch_mitigated": true,
      "crossing_attempt": {
        "start_price": 72888.8,
        "end_price": 74509.52,
        "global_start_index": 2241,
        "global_end_index": 2244
      },
      "internal_tf_used": "5m",
      "termination_reason": "max_depth_reached"
    }
  ]
}
```

---

## 3. Alert Triggers

These are the zones the background daemon must watch. Extracted directly from
the walker output. The daemon fires an alert when live price enters a zone.

```json
{
  "alert_zones": [
    {
      "zone_type": "GLOBAL_CHOCH",
      "depth": null,
      "price_high": 72271.41,
      "price_low": 60000.0,
      "description": "Global CHoCH zone — if price reaches here the global downtrend may resume",
      "is_active": true,
      "watch_condition": "price_enters_zone"
    },
    {
      "zone_type": "DEPTH_CHOCH",
      "depth": 1,
      "price_high": 66826.5,
      "price_low": 64500.0,
      "description": "Depth 1 CHoCH zone — mitigated, tracked for reference",
      "is_active": false,
      "watch_condition": "price_enters_zone"
    },
    {
      "zone_type": "DEPTH_CHOCH",
      "depth": 2,
      "price_high": 69988.83,
      "price_low": 63030.0,
      "description": "Depth 2 CHoCH zone — mitigated, tracked for reference",
      "is_active": false,
      "watch_condition": "price_enters_zone"
    },
    {
      "zone_type": "DEPTH_CHOCH",
      "depth": 3,
      "price_high": 73199.0,
      "price_low": 72270.41,
      "description": "Depth 3 CHoCH zone — active, watching for next impulse",
      "is_active": true,
      "watch_condition": "price_enters_zone"
    },
    {
      "zone_type": "DEPTH_BOS",
      "depth": 3,
      "price_high": 74509.52,
      "price_low": 74451.03,
      "description": "Depth 3 BOS — watching for confirmed break",
      "is_active": true,
      "watch_condition": "price_crosses_above"
    }
  ]
}
```

**Watch condition values:**

| Value | Meaning |
|---|---|
| `price_enters_zone` | Fire alert when live price is between `price_low` and `price_high` |
| `price_crosses_above` | Fire alert when live price closes above `price_high` |
| `price_crosses_below` | Fire alert when live price closes below `price_low` |

**Active zone logic:**

- A CHoCH zone is `is_active: true` only for the deepest unmitigated depth level
- A BOS zone is `is_active: true` only for the deepest depth level
- All higher depth CHoCH zones are `is_active: false` once mitigated — kept for audit trail only

---

## 4. Full Setup Payload

This is the complete object the Orchestrator receives per asset scan cycle.
It combines sections 1, 2, and 3 into one payload.

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "as_of": "2026-03-22T23:00:00Z",
  "global_trend": {
    "direction": "down",
    "current_phase": "retracement",
    "confirmed_legs": 5,
    "confirmed_impulses": 3,
    "confirmed_retracements": 2
  },
  "status": "IN_RETRACEMENT",
  "trend_score": 0.0,
  "structural_state_json": { },
  "alert_zones": [ ]
}
```

**Note on `trend_score`:** The scoring formula is not yet defined. Placeholder
is 0.0. The Architect should define the scoring formula based on:
- Number of depth levels confirmed
- Number of mitigations
- Whether the deepest CHoCH zone is currently being tested
- Distance of current price from the active CHoCH zone

The Product Engineer will implement `trend_score` once the formula is agreed.

---

## 5. What the Orchestrator Must NOT Do

- Must not re-run `identify_trend` or `walk_structure` — these are expensive.
  The engine runs on a schedule. The Orchestrator consumes cached output only.
- Must not modify `price_high` or `price_low` on any zone unless
  `is_manual_override` is set to `true` by Victor via the UI.
- Must not evict a setup with `is_manual_override: true` zones regardless
  of trend score.

---

## 6. Open Questions for Architect

1. What is the scan frequency? How often does the engine re-run per asset?
2. What is the `trend_score` formula? PE needs this to implement scoring.
3. Should mitigated CHoCH zones be stored in the database at all, or only
   the active deepest zone?
4. When a new depth level is detected on the next scan cycle, how does the
   Orchestrator handle the transition — does it create new `AlertZone` rows
   or update existing ones?
