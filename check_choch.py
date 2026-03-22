import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.core.trend_id import identify_trend
from src.core.structural_walker import walk_structure, RMT_DEFAULT_FILTER_CONFIG
from datetime import datetime, timedelta, timezone

start_time = datetime.now(timezone.utc) - timedelta(days=100)
candles = fetch_binance_ohlc_sync('BTCUSDT', '1h', start_time=start_time)
smaller = {}
for tf in ['15m', '5m']:
    try:
        smaller[tf] = fetch_binance_ohlc_sync('BTCUSDT', tf, start_time=start_time)
    except Exception:
        smaller[tf] = []

filter_config = {'use_parent_relative_filter':True,'min_impulse_parent_ratio':0.15,'use_momentum_filter':True,'min_momentum_ratio':0.5,'use_dominance_filter':True,'min_dominance_ratio':1.5}
result = identify_trend(candles, **filter_config)
state = walk_structure(candles, result, filter_config, max_depth=4, smaller_tf_candles=smaller)

lvl = state['levels'][0]
ir = lvl.get('internal_result')
cz = lvl.get('choch_zone')

print('CHoCH zone:', cz)
print()
print('Internal result legs that produced this zone:')
if ir:
    for i, l in enumerate(ir['legs']):
        ep = round(l['end_price'],2) if l['end_price'] else None
        print('  leg['+str(i)+'] '+l['type']+' confirmed='+str(l['confirmed'])+' start='+str(round(l['start_price'],2))+' end='+str(ep))
    print()
    print('Internal result trend:', ir['trend'])

print()
print('First impulse global window:')
print('  start_ts:', candles[lvl['first_impulse_global_start']].timestamp)
print('  end_ts:', candles[lvl['first_impulse_global_end']].timestamp)
print('  start_price:', lvl['first_impulse']['start_price'])
print('  end_price:', lvl['first_impulse']['end_price'])
