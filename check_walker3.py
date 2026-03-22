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
compute_internal_structure(candles, result['legs'], **filter_config)
state = walk_structure(candles, result, filter_config, max_depth=4)

print('Global trend:', result['trend'])
print('Retracement leg: start=', result['legs'][-2]['start_price'], 'end=', result['legs'][-2]['end_price'])
print()
for lvl in state['levels']:
    sl = lvl.get('structural_level')
    cz = lvl.get('choch_zone')
    ca = lvl.get('crossing_attempt')
    rmt = lvl.get('rmt_result')
    print('=== Depth', lvl['depth'], '===')
    print('  slice:', lvl['slice_start'], '->', lvl['slice_end'])
    print('  slice_start_ts:', candles[lvl['slice_start']].timestamp)
    print('  slice_end_ts:', candles[lvl['slice_end']].timestamp)
    print('  RMT trend:', rmt['trend'] if rmt else 'None')
    print('  RMT confirmed legs:', [(l['type'], round(l['start_price'],0), round(l['end_price'],0) if l['end_price'] else None, l['confirmed']) for l in rmt['legs']] if rmt else 'None')
    print('  BOS:', round(float(sl['price']),2) if sl else 'None')
    print('  CHoCH zone:', (str(round(float(cz['lower_boundary']),2))+' to '+str(round(float(cz['upper_boundary']),2))) if cz else 'None')
    print('  mitigated:', lvl['choch_mitigated'])
    if ca:
        print('  crossing: start=', round(ca['start_price'],2), 'end=', round(ca['end_price'],2), 'global_start=', ca['global_start_index'], 'global_end=', ca['global_end_index'])
        print('  crossing_start_ts:', candles[ca['global_start_index']].timestamp)
        print('  crossing_end_ts:', candles[ca['global_end_index']].timestamp)
    print('  termination:', lvl['termination_reason'])
    print()
