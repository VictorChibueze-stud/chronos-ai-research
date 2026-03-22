import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from src.adapters.binance_data import fetch_binance_ohlc_sync
from src.core.trend_id import identify_trend, compute_internal_structure
from src.core.structural_walker import walk_structure
from datetime import datetime, timedelta, timezone

start_time = datetime.now(timezone.utc) - timedelta(days=100)
candles = fetch_binance_ohlc_sync('BTCUSDT', '1h', start_time=start_time)
filter_config = {'use_parent_relative_filter':True,'min_impulse_parent_ratio':0.15,'use_momentum_filter':True,'min_momentum_ratio':0.5,'use_dominance_filter':True,'min_dominance_ratio':1.5}
result = identify_trend(candles, **filter_config)
state = walk_structure(candles, result, filter_config, max_depth=4)

lvl = state['levels'][0]
print('Depth 1 BOS:', lvl['structural_level']['price'])
print('Depth 1 CHoCH zone:', lvl['choch_zone'])
print('Depth 1 internal_result legs:')
ir = lvl.get('internal_result')
if ir:
    for l in ir['legs']:
        print(' ', l['type'], l['start_price'], '->', l['end_price'], 'confirmed:', l['confirmed'])
else:
    print('  None')
print()
print('Crossing attempt:')
ca = lvl.get('crossing_attempt')
if ca:
    print('  start_price:', ca['start_price'])
    print('  end_price:', ca['end_price'])
    print('  global_start_index:', ca['global_start_index'])
    print('  start_ts:', candles[ca['global_start_index']].timestamp)
else:
    print('  None')
print()
print('All rmt legs after first impulse:')
rmt = lvl.get('rmt_result')
first_imp_idx = None
if rmt:
    for i, l in enumerate(rmt['legs']):
        if l['type'] == 'impulse' and l['confirmed'] and first_imp_idx is None:
            first_imp_idx = i
            continue
        if first_imp_idx is not None and l['type'] == 'impulse' and l['confirmed']:
            ep = round(l['end_price'],2) if l['end_price'] else None
            print(' leg['+str(i)+']', l['type'], round(l['start_price'],2), '->', ep,
                  'confirmed:', l['confirmed'],
                  'ts:', candles[lvl['slice_start']+int(l['start_index'])].timestamp)
