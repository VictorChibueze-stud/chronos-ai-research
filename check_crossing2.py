import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.core.trend_id import identify_trend
from src.core.structural_walker import RMT_DEFAULT_FILTER_CONFIG
from datetime import datetime, timezone, timedelta

start_time = datetime.now(timezone.utc) - timedelta(days=100)
candles = fetch_binance_ohlc_sync('BTCUSDT', '1h', start_time=start_time)

# depth 1 first move ends at g_end=1392 (Feb 8)
# post first move scan starts at 1392
post_start = 1392
post_end = len(candles) - 1

post_candles = candles[post_start : post_end + 1]
print('Post first move candles:', len(post_candles))
print('From:', candles[post_start].timestamp)

rmt = identify_trend(post_candles, **RMT_DEFAULT_FILTER_CONFIG)
print('RMT trend:', rmt['trend'])
print('All legs:')
for i, l in enumerate(rmt['legs']):
    ep = round(float(l['end_price']),2) if l.get('end_price') else None
    sp = round(float(l['start_price']),2)
    ts = post_candles[int(l['start_index'])].timestamp
    print(f'  leg[{i}] {l["type"]} confirmed={l["confirmed"]} {sp} -> {ep} | {ts}')
