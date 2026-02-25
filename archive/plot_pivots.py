# plot_pivots.py
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# --- Helpers: datetime -> matplotlib date numbers ---
def to_num_series(s: pd.Series):
    return mdates.date2num(pd.to_datetime(s).dt.to_pydatetime())

def to_num_scalar(t):
    return mdates.date2num(pd.to_datetime(t).to_pydatetime())

def setup_date_axis(ax):
    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

# --- Load data ---
prices = pd.read_csv("prices.csv", parse_dates=["datetime"]).set_index("datetime")
fr = pd.read_csv("fractal_pivots.csv", parse_dates=["ts","confirmed_at"])
zz = pd.read_csv("zigzag_pivots.csv", parse_dates=["ts","confirmed_at"])
legs = pd.read_csv("zigzag_legs.csv", parse_dates=["start_ts","end_ts"])

# events.csv may be empty or missing
events_path = Path("events.csv")
if events_path.exists() and events_path.stat().st_size > 0:
    events = pd.read_csv("events.csv", parse_dates=["breach_ts","breached_pivot_ts"])
else:
    events = pd.DataFrame()

# Ensure sorted
fr.sort_values("ts", inplace=True)
zz.sort_values("ts", inplace=True)
legs.sort_values("start_ts", inplace=True)
if not events.empty:
    events.sort_values("breach_ts", inplace=True)

# Precompute numeric x for price series
x_price = to_num_series(prices.index.to_series())

# --- 1) Price + FRACTAL pivots ---
fig1, ax1 = plt.subplots(figsize=(12, 5))
ax1.plot(x_price, prices["close"], label="Close")

fr_sh = fr[fr["type"] == "SH"]
fr_sl = fr[fr["type"] == "SL"]

ax1.scatter(to_num_series(fr_sh["ts"]), fr_sh["price"], marker="^", label="FR Swing High")
ax1.scatter(to_num_series(fr_sl["ts"]), fr_sl["price"], marker="v", label="FR Swing Low")

setup_date_axis(ax1)
ax1.set_title("Price with Fractal Pivots (k=2)")
ax1.legend()
fig1.tight_layout()
fig1.savefig("01_price_with_fractals.png")

# --- 2) Price + ZIGZAG pivots & legs ---
fig2, ax2 = plt.subplots(figsize=(12, 5))
ax2.plot(x_price, prices["close"], label="Close")

zz_sh = zz[zz["type"] == "SH"]
zz_sl = zz[zz["type"] == "SL"]

ax2.scatter(to_num_series(zz_sh["ts"]), zz_sh["price"], marker="^", label="ZZ Swing High")
ax2.scatter(to_num_series(zz_sl["ts"]), zz_sl["price"], marker="v", label="ZZ Swing Low")

# draw legs
for _, row in legs.iterrows():
    ax2.plot(
        [to_num_scalar(row["start_ts"]), to_num_scalar(row["end_ts"])],
        [row["start_price"], row["end_price"]],
    )

setup_date_axis(ax2)
ax2.set_title("Price with ZigZag Pivots & Legs")
ax2.legend()
fig2.tight_layout()
fig2.savefig("02_price_with_zigzag.png")

# --- 3) Price + BOTH methods (compare pivots head-to-head) ---
fig3, ax3 = plt.subplots(figsize=(12, 5))
ax3.plot(x_price, prices["close"], label="Close")

# fractal
ax3.scatter(to_num_series(fr_sh["ts"]), fr_sh["price"], marker="^", label="FR SH")
ax3.scatter(to_num_series(fr_sl["ts"]), fr_sl["price"], marker="v", label="FR SL")
# zigzag
ax3.scatter(to_num_series(zz_sh["ts"]), zz_sh["price"], marker="s", label="ZZ SH")
ax3.scatter(to_num_series(zz_sl["ts"]), zz_sl["price"], marker="o", label="ZZ SL")

setup_date_axis(ax3)
ax3.set_title("Comparison: Fractal vs ZigZag Pivots")
ax3.legend(ncols=2)
fig3.tight_layout()
fig3.savefig("03_price_compare.png")

# --- 4) BOS / CHOCH markers (vertical lines) ---
if not events.empty:
    fig4, ax4 = plt.subplots(figsize=(12, 5))
    ax4.plot(x_price, prices["close"], label="Close")
    # draw breach lines & labels
    ymax = prices["close"].max()
    for _, e in events.iterrows():
        x = to_num_scalar(e["breach_ts"])
        ax4.axvline(x, linestyle="--")
        ax4.text(x, ymax, e["event_type"], rotation=90, va="top")

    setup_date_axis(ax4)
    ax4.set_title("BOS / CHOCH Events")
    fig4.tight_layout()
    fig4.savefig("04_events.png")

print("Saved charts: 01_price_with_fractals.png, 02_price_with_zigzag.png, 03_price_compare.png, 04_events.png")
