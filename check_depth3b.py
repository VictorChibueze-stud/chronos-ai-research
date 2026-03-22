import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from src.adapters.binance_data import fetch_binance_ohlc_sync
from datetime import datetime, timezone, timedelta

start_time = datetime.now(timezone.utc) - timedelta(days=100)
candles = fetch_binance_ohlc_sync('BTCUSDT', '1h', start_time=start_time)

# depth 2 first move ends around candle 1962 (March 4)
# BOS is 73760
first_move_end = 1962
bos_price = 73760.0
choch_lower = 63030.0
choch_upper = 69988.0
scan_end = len(candles) - 1

print('Scanning from', candles[first_move_end].timestamp, 'to', candles[scan_end].timestamp)
print('BOS price:', bos_price)
print()

# Find first crossing
crossing_index = None
for i in range(first_move_end + 1, scan_end + 1):
    if candles[i].high >= bos_price:
        crossing_index = i
        print('First BOS touch at:', candles[i].timestamp, 'high:', candles[i].high)
        break

if crossing_index is None:
    print('No crossing found')
else:
    # Find extreme
    extreme_index = crossing_index
    extreme_price = candles[crossing_index].high
    for i in range(crossing_index + 1, scan_end + 1):
        if candles[i].high > extreme_price:
            extreme_price = candles[i].high
            extreme_index = i
        else:
            if candles[i].low < candles[i-1].low and candles[i].high < candles[i-1].high:
                break
    print('Extreme at:', candles[extreme_index].timestamp, 'high:', extreme_price)
    print()

    # Backward scan for move start
    lowest_price = float('inf')
    move_start_index = first_move_end
    for i in range(first_move_end, crossing_index):
        if candles[i].low < lowest_price:
            lowest_price = candles[i].low
            move_start_index = i
    print('Move start at:', candles[move_start_index].timestamp, 'low:', lowest_price)
    print('In CHoCH zone (', choch_lower, '-', choch_upper, '):', choch_lower <= lowest_price <= choch_upper)
