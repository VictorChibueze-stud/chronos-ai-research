import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.core.trend_id import identify_trend
from src.core.structural_walker import RMT_DEFAULT_FILTER_CONFIG
from datetime import datetime, timezone, timedelta

start_time = datetime.now(timezone.utc) - timedelta(days=100)
candles = fetch_binance_ohlc_sync('BTCUSDT', '1h', start_time=start_time)

# depth 2 post-first-move scan starts at global_end_index of crossing attempt
# crossing attempt global_end_index = 1965 (March 4)
# slice_end = end of retracement = len(candles)-1
post_start = 1965
post_end = len(candles) - 1

post_candles = candles[post_start : post_end + 1]
print('Post first move candles:', len(post_candles))
print('From:', candles[post_start].timestamp)
print('To:', candles[post_end].timestamp)

rmt = identify_trend(post_candles, **RMT_DEFAULT_FILTER_CONFIG)
print('RMT trend:', rmt['trend'])
print('RMT legs:')
for i, l in enumerate(rmt['legs']):
    ep = round(float(l['end_price']),2) if l.get('end_price') else None
    print(f'  leg[{i}] {l["type"]} confirmed={l["confirmed"]} {round(float(l["start_price"]),2)} -> {ep}')
    if l.get('start_index') is not None:
        print(f'    start_ts: {post_candles[int(l["start_index"])].timestamp}')
