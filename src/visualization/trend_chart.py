"""Standalone trend chart visualization for Ikenga.

This module contains the draw_trend_chart function extracted from notebook 08.
Pure visualization layer — no business logic.
"""
from __future__ import annotations

from typing import Any, List, Optional

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from src.core.features import compute_ema
from src.core.trend_id import filter_crossovers_in_impulses
from src.core.structure_levels import compute_all_structure_levels


def draw_trend_chart(
    candles: List[Any],
    result: dict[str, Any],
    title: str,
    use_datetime_axis: bool = False,
    figsize: tuple[int, int] = (28, 8),
    ax: Optional[Any] = None,
) -> Any:
    """Draw a comprehensive trend structure chart with all structural levels.

    Args:
        candles: List of Candle objects with timestamp, close, high, low, open.
        result: Result dict from identify_trend with legs and current_phase.
        title: Chart title (string).
        use_datetime_axis: If True, use datetime x-axis; else use numeric indices.
        figsize: Figure size as (width, height).
        ax: Optional existing axes; if None, creates new figure.

    Returns:
        The axes object (for chaining additional drawing operations).
    """
    display = candles

    if ax is None:
        _, ax = plt.subplots(figsize=figsize)

    x_values = [c.timestamp for c in display] if use_datetime_axis else list(range(len(display)))

    # OHLC bars: draw wicks first (zorder=1), then bodies (zorder=2) so all
    # structural lines, BOS/CHoCH levels, and EMA markers render on top.
    for candle, ts in zip(display, x_values):
        ax.plot([ts, ts], [float(candle.low), float(candle.high)],
                color='#9E9E9E', linewidth=0.6, alpha=0.7, zorder=1)
        body_color = '#26A69A' if float(candle.close) >= float(candle.open) else '#EF5350'
        ax.plot([ts, ts], [float(candle.open), float(candle.close)],
                color=body_color, linewidth=2.2, alpha=0.85, zorder=2)

    def x_at(index):
        return display[index].timestamp if use_datetime_axis else index

    def diff_sign(value):
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    chart_end_x = x_at(len(candles) - 1)

    # Draw outer legs
    for leg in result["legs"]:
        start_idx = leg["start_index"]
        end_idx = leg["end_index"] if leg["end_index"] is not None else len(display) - 1

        start_x = x_at(start_idx)
        end_x = x_at(end_idx)

        start_y = leg["start_price"]
        end_y = leg["end_price"] if leg["end_price"] is not None else display[-1].close

        if result["trend"] == "down":
            color = "red" if leg["type"] == "impulse" else "green"
        else:
            color = "green" if leg["type"] == "impulse" else "red"

        if not leg["confirmed"]:
            ax.plot([start_x, end_x], [start_y, end_y], color='grey', linestyle='--', linewidth=2)
        else:
            ax.plot([start_x, end_x], [start_y, end_y], color=color, linewidth=3)
            ax.scatter(end_x, end_y, color=color, s=100, zorder=5)

    # Draw internal structure only within the parent impulse span.
    for leg in result["legs"]:
        internal = leg.get("internal_structure")
        parent_start = leg["start_index"]
        parent_end = leg["end_index"]

        if internal is None or parent_end is None:
            continue

        for internal_leg in internal["legs"]:
            relative_start = internal_leg["start_index"]
            relative_end = internal_leg["end_index"] if internal_leg["end_index"] is not None else parent_end - parent_start

            start_idx = parent_start + relative_start
            end_idx = parent_start + relative_end
            end_idx = min(end_idx, parent_end)

            start_x = x_at(start_idx)
            end_x = x_at(end_idx)

            start_y = internal_leg["start_price"]
            if internal_leg["end_price"] is not None:
                end_y = internal_leg["end_price"]
            else:
                end_y = display[end_idx].close

            ax.plot([start_x, end_x], [start_y, end_y], color='black', linestyle='--', linewidth=2)

    def annotate_retracement_depth_label(leg, index_offset=0, max_end_index=None):
        depth = leg.get("retracement_depth")
        if depth is None:
            return
        if leg.get("type") != "retracement" or leg.get("confirmed") is not True:
            return
        if leg.get("start_index") is None or leg.get("end_index") is None:
            return

        start_index = leg["start_index"] + index_offset
        end_index = leg["end_index"] + index_offset
        if max_end_index is not None:
            end_index = min(end_index, max_end_index)

        mid_index = (start_index + end_index) // 2
        start_price = float(leg["start_price"])
        end_price = float(leg["end_price"])
        mid_price = (start_price + end_price) / 2.0
        ax.text(
            x_at(mid_index),
            mid_price,
            f"{depth['depth_pct']}%",
            fontsize=8,
            color="#888780",
            ha="center",
            va="center",
            zorder=8,
        )

    def annotate_leg_metrics_label(leg, index_offset=0, max_end_index=None):
        metrics = leg.get("metrics")
        if metrics is None:
            return
        if leg.get("confirmed") is not True:
            return
        if leg.get("start_index") is None or leg.get("end_index") is None:
            return

        start_index = leg["start_index"] + index_offset
        end_index = leg["end_index"] + index_offset
        if max_end_index is not None:
            end_index = min(end_index, max_end_index)

        mid_index = (start_index + end_index) // 2
        start_price = float(leg["start_price"])
        end_price = float(leg["end_price"]) if leg["end_price"] is not None else display[end_index].close
        mid_price = (start_price + end_price) / 2.0

        price_move = metrics.get("price_move_pct")
        duration_human = metrics.get("duration_human")
        if price_move is None or duration_human is None:
            return

        label = f"{abs(price_move):.2f}% / {duration_human}"
        color = "red" if leg["type"] == "impulse" else "green"
        if result["trend"] == "up":
            color = "green" if leg["type"] == "impulse" else "red"

        ax.text(
            x_at(mid_index),
            mid_price,
            label,
            fontsize=7,
            color=color,
            ha="center" ,
            va="center" ,
            alpha=0.7,
            zorder=9,
        )

    for leg in result["legs"]:
        annotate_retracement_depth_label(leg)
        annotate_leg_metrics_label(leg)

    for parent_leg in result["legs"]:
        internal = parent_leg.get("internal_structure")
        if (
            internal is None
            or parent_leg.get("start_index") is None
            or parent_leg.get("end_index") is None
        ):
            continue

        parent_start = parent_leg["start_index"]
        parent_end = parent_leg["end_index"]
        for internal_leg in internal["legs"]:
            annotate_retracement_depth_label(
                internal_leg,
                index_offset=parent_start,
                max_end_index=parent_end,
            )
            annotate_leg_metrics_label(
                internal_leg,
                index_offset=parent_start,
                max_end_index=parent_end,
            )

    ema9 = compute_ema(display, 9)
    ema21 = compute_ema(display, 21)
    crossover_indices = []
    for index in range(1, len(display)):
        previous_ema9 = ema9[index - 1]
        previous_ema21 = ema21[index - 1]
        current_ema9 = ema9[index]
        current_ema21 = ema21[index]
        if (
            previous_ema9 is None
            or previous_ema21 is None
            or current_ema9 is None
            or current_ema21 is None
        ):
            continue

        previous_diff = previous_ema9 - previous_ema21
        current_diff = current_ema9 - current_ema21
        if diff_sign(previous_diff) != diff_sign(current_diff):
            crossover_indices.append(index)

    # Tier 1: keep only crossovers inside confirmed global impulses and
    # suppress any that fall inside confirmed internal retracement zones.
    internal_retracement_indices = set()
    internal_impulse_legs = []

    for leg in result["legs"]:
        if (
            leg.get("type") != "impulse"
            or leg.get("confirmed") is not True
            or leg.get("start_index") is None
            or leg.get("end_index") is None
        ):
            continue

        internal = leg.get("internal_structure")
        if internal is None:
            continue

        parent_start = leg["start_index"]
        parent_end = leg["end_index"]

        for internal_leg in internal["legs"]:
            if (
                internal_leg.get("confirmed") is not True
                or internal_leg.get("start_index") is None
                or internal_leg.get("end_index") is None
            ):
                continue

            global_start = parent_start + internal_leg["start_index"]
            global_end = min(parent_start + internal_leg["end_index"], parent_end)

            if internal_leg.get("type") == "retracement":
                for retrace_index in range(global_start, global_end + 1):
                    internal_retracement_indices.add(retrace_index)
            elif internal_leg.get("type") == "impulse":
                internal_impulse_legs.append(
                    {
                        "type": "impulse",
                        "confirmed": True,
                        "start_index": global_start,
                        "end_index": global_end,
                    }
                )

    global_crossover_indices = set(
        filter_crossovers_in_impulses(
            crossover_indices,
            result["legs"],
            suppress_indices=internal_retracement_indices,
        )
    )

    # Tier 2: local markers only inside confirmed internal impulse legs.
    internal_crossover_indices = set(
        filter_crossovers_in_impulses(crossover_indices, internal_impulse_legs)
    )

    for index in sorted(global_crossover_indices):
        ax.plot(
            [x_at(index)],
            [display[index].close],
            marker='x',
            linestyle='None',
            color='#FF8C00',
            markersize=12,
            markeredgewidth=2.5,
            zorder=5,
        )

    for index in sorted(internal_crossover_indices):
        ax.plot(
            [x_at(index)],
            [display[index].close],
            marker='x',
            linestyle='None',
            color='#FFA500',
            markersize=8,
            markeredgewidth=2.5,
            zorder=6,
        )

    # Add global BOS and CHoCH horizontal structure levels.
    levels = compute_all_structure_levels(candles, result["legs"], result["trend"])
    bos_levels = levels["bos_levels"]

    for bos in bos_levels:
        print(f"BOS | price={bos['price']:.2f} | start={bos['start_index']} ({x_at(bos['start_index'])}) | end={bos['end_index']} ({x_at(bos['end_index'])}) | broken={bos['broken']}")

    for bos in bos_levels:
        bos_start_x = x_at(bos["start_index"])
        bos_label = "BOS ✗" if bos["broken"] else "BOS"
        bos_linewidth = 1.0 if bos["broken"] else 1.5
        bos_linestyle = ":" if bos["broken"] else "--"
        bos_alpha = 0.5 if bos["broken"] else 1.0
        ax.hlines(
            y=bos["price"],
            xmin=bos_start_x,
            xmax=chart_end_x,
            colors="#2196F3",
            linewidth=bos_linewidth,
            linestyles=bos_linestyle,
            alpha=bos_alpha,
            zorder=3,
        )
        ax.annotate(
            bos_label,
            xy=(bos_start_x, bos["price"]),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=8,
            color="#2196F3",
        )

    choch = levels["choch_level"]
    if choch is not None:
        choch_start_x = x_at(choch["start_index"])
        choch_label = "CHoCH ✗" if choch["broken"] else "CHoCH"
        choch_linewidth = 1.0 if choch["broken"] else 1.5
        choch_linestyle = ":" if choch["broken"] else "-"
        choch_alpha = 0.5 if choch["broken"] else 1.0
        ax.hlines(
            y=choch["price"],
            xmin=choch_start_x,
            xmax=chart_end_x,
            colors="#E91E63",
            linewidth=choch_linewidth,
            linestyles=choch_linestyle,
            alpha=choch_alpha,
            zorder=4,
        )
        ax.annotate(
            choch_label,
            xy=(choch_start_x, choch["price"]),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=8,
            color="#E91E63",
        )

    # Add internal BOS and CHoCH levels in lighter dotted styles.
    for leg in result["legs"]:
        internal_bos_levels = leg.get("internal_bos_levels") or []
        for bos in internal_bos_levels:
            bos_start_x = x_at(bos["start_index"])
            bos_label = "BOS ✗" if bos["broken"] else "BOS"
            bos_linewidth = 0.8 if bos["broken"] else 0.9
            bos_linestyle = ":" if bos["broken"] else "--"
            bos_alpha = 0.4 if bos["broken"] else 1.0
            ax.hlines(
                y=bos["price"],
                xmin=bos_start_x,
                xmax=chart_end_x,
                colors="#64B5F6",
                linewidth=bos_linewidth,
                linestyles=bos_linestyle,
                alpha=bos_alpha,
                zorder=2,
            )
            ax.annotate(
                bos_label,
                xy=(bos_start_x, bos["price"]),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=7,
                color="#64B5F6",
            )

        internal_choch = leg.get("internal_choch_level")
        if internal_choch is not None:
            choch_start_x = x_at(internal_choch["start_index"])
            choch_label = "CHoCH ✗" if internal_choch["broken"] else "CHoCH"
            choch_linewidth = 0.8 if internal_choch["broken"] else 0.9
            choch_linestyle = ":" if internal_choch["broken"] else "-"
            choch_alpha = 0.4 if internal_choch["broken"] else 1.0
            ax.hlines(
                y=internal_choch["price"],
                xmin=choch_start_x,
                xmax=chart_end_x,
                colors="#F48FB1",
                linewidth=choch_linewidth,
                linestyles=choch_linestyle,
                alpha=choch_alpha,
                zorder=2,
            )
            ax.annotate(
                choch_label,
                xy=(choch_start_x, internal_choch["price"]),
                xytext=(3, 3),
                textcoords="offset points",
                fontsize=7,
                color="#F48FB1",
            )

    if use_datetime_axis:
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.AutoDateFormatter(locator))
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    else:
        tick_step = max(1, len(display) // 20)
        tick_pos = list(range(0, len(display), tick_step))
        tick_lbl = [display[i].timestamp.strftime("%b %d\n%H:%M") for i in tick_pos]

        ax.set_xticks(tick_pos)
        ax.set_xticklabels(tick_lbl, fontsize=7, rotation=45)

    ax.set_title(f"{title} | Trend: {result['trend']} | {len(result['legs'])} legs | Phase: {result['current_phase']}")
    ax.grid(True, alpha=0.3)
    
    return ax
