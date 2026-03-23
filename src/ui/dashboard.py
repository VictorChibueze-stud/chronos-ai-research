from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import streamlit as st

from src.db.session import SessionLocal
from src.ui.data_access import add_manual_override, drop_setup, get_all_setups, get_setup_detail


DEPTH_COLORS = {
    1: "#0F8B8D",
    2: "#F4A261",
    3: "#E76F51",
    4: "#6D597A",
}


def _hex_to_rgba(color: str, alpha: float) -> str:
    color = color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def build_zone_map_figure(
    structural_state_json: dict[str, Any] | None,
    *,
    symbol: str,
    timeframe: str,
) -> go.Figure:
    state = structural_state_json or {}
    levels = state.get("levels") or []
    figure = go.Figure()

    if not levels:
        figure.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            text="No structural levels available",
            showarrow=False,
            font={"size": 16},
        )
        figure.update_layout(title=f"{symbol} {timeframe} - Zone Map")
        return figure

    max_index = max(int(level.get("slice_end", 0) or 0) for level in levels)
    min_index = min(int(level.get("slice_start", 0) or 0) for level in levels)

    for level in sorted(levels, key=lambda item: int(item.get("depth", 0))):
        depth = int(level.get("depth", 0))
        color = DEPTH_COLORS.get(depth, "#457B9D")
        start_index = int(level.get("first_impulse_global_start") or level.get("slice_start") or 0)
        end_index = int(level.get("slice_end") or max_index)

        choch_zone = level.get("choch_zone") or {}
        if choch_zone:
            lower = float(choch_zone["lower_boundary"])
            upper = float(choch_zone["upper_boundary"])
            figure.add_trace(
                go.Scatter(
                    x=[start_index, end_index, end_index, start_index, start_index],
                    y=[lower, lower, upper, upper, lower],
                    fill="toself",
                    mode="lines",
                    line={"color": color, "width": 1},
                    fillcolor=_hex_to_rgba(color, 0.16),
                    name=f"Depth {depth} CHoCH",
                    hovertemplate=(
                        f"Depth {depth} CHoCH<br>"
                        f"Low: {lower:.2f}<br>"
                        f"High: {upper:.2f}<extra></extra>"
                    ),
                )
            )

        structural_level = level.get("structural_level") or {}
        if "price" in structural_level:
            bos_price = float(structural_level["price"])
            bos_start = int(level.get("first_impulse_global_end") or start_index)
            figure.add_trace(
                go.Scatter(
                    x=[bos_start, end_index],
                    y=[bos_price, bos_price],
                    mode="lines",
                    line={"color": color, "width": 2, "dash": "dash"},
                    name=f"Depth {depth} BOS",
                    hovertemplate=(
                        f"Depth {depth} BOS<br>"
                        f"Price: {bos_price:.2f}<extra></extra>"
                    ),
                )
            )

    figure.update_layout(
        title=f"{symbol} {timeframe} - Zone Map",
        xaxis_title="Structure Index",
        yaxis_title="Price",
        template="plotly_white",
        hovermode="closest",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        margin={"l": 40, "r": 20, "t": 80, "b": 40},
        annotations=[
            {
                "x": 0.01,
                "y": 0.99,
                "xref": "paper",
                "yref": "paper",
                "text": (
                    f"Waiting for: {state.get('waiting_for', 'n/a')}"
                    f"<br>Mitigations: {state.get('total_mitigation_count', 0)}"
                ),
                "showarrow": False,
                "align": "left",
                "bgcolor": "rgba(255,255,255,0.7)",
            }
        ],
    )
    figure.update_xaxes(range=[min_index, max_index])
    return figure


def _render_command_center() -> None:
    with SessionLocal() as db:
        setups = get_all_setups(db)
        st.title("Chronos-AI Command Center")
        if setups.empty:
            st.info("No monitored setups found in the local database.")
            return

        st.dataframe(setups, use_container_width=True, hide_index=True)

        selected_setup_id = st.selectbox(
            "Select setup",
            setups["setup_id"].tolist(),
            format_func=lambda setup_id: f"{int(setup_id)} - {setups.loc[setups['setup_id'] == setup_id, 'symbol'].iloc[0]}",
        )

        detail = get_setup_detail(db, int(selected_setup_id))
        if detail is None:
            st.warning("Selected setup no longer exists.")
            return

        left, right = st.columns(2)
        with left:
            if st.button("Drop Setup", type="secondary"):
                drop_setup(db, int(selected_setup_id))
                st.rerun()

        with right:
            with st.form("manual_override_form"):
                zone_type = st.selectbox("Zone type", ["MANUAL_OVERRIDE", "DEPTH_CHOCH", "DEPTH_BOS"])
                price_low = st.number_input("Price low", value=0.0, format="%.2f")
                price_high = st.number_input("Price high", value=0.0, format="%.2f")
                depth = st.number_input("Depth", value=1, min_value=1, step=1)
                submitted = st.form_submit_button("Add Manual Override")
                if submitted:
                    add_manual_override(
                        db,
                        setup_id=int(selected_setup_id),
                        zone_type=zone_type,
                        price_low=float(price_low),
                        price_high=float(price_high),
                        depth=int(depth),
                    )
                    st.rerun()


def _render_deep_dive() -> None:
    with SessionLocal() as db:
        setups = get_all_setups(db)
        st.title("Deep Dive")
        if setups.empty:
            st.info("No monitored setups available for structural inspection.")
            return

        selected_setup_id = st.selectbox(
            "Setup",
            setups["setup_id"].tolist(),
            format_func=lambda setup_id: (
                f"{int(setup_id)} - "
                f"{setups.loc[setups['setup_id'] == setup_id, 'symbol'].iloc[0]} "
                f"({setups.loc[setups['setup_id'] == setup_id, 'timeframe'].iloc[0]})"
            ),
        )
        detail = get_setup_detail(db, int(selected_setup_id))
        if detail is None:
            st.warning("Selected setup no longer exists.")
            return

        figure = build_zone_map_figure(
            detail.structural_state_json,
            symbol=detail.symbol,
            timeframe=detail.htf_timeframe,
        )
        st.plotly_chart(figure, use_container_width=True)
        st.json(detail.structural_state_json)


def run_dashboard() -> None:
    st.set_page_config(page_title="Chronos-AI Command Center", layout="wide")
    page = st.sidebar.radio("View", ["Command Center", "Deep Dive"])
    if page == "Command Center":
        _render_command_center()
    else:
        _render_deep_dive()


if __name__ == "__main__":
    run_dashboard()