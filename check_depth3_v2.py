import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from src.adapters.binance_data import fetch_binance_ohlc_sync
from datetime import datetime, timezone, timedelta

start_time = datetime.now(timezone.utc) - timedelta(days=100)
candles = fetch_binance_ohlc_sync('BTCUSDT', '1h', start_time=start_time)

# depth 2 first move ends around index 1962 (March 4)
# scan forward from there
first_move_end = 1962
bos = 73760.0
choch_lower = 63030.0
choch_upper = 69988.0

print('Scanning from', candles[first_move_end].timestamp)
print('Looking for price to cross BOS at', bos)
print('Move must start from CHoCH zone', choch_lower, '-', choch_upper)
print()

for i in range(first_move_end + 1, len(candles)):
    if candles[i].high >= bos:
        print('First BOS cross at:', candles[i].timestamp, 'high:', candles[i].high)
        # find move start - lowest low before this
        lowest = float('inf')
        lowest_idx = first_move_end
        for j in range(first_move_end, i):
            if candles[j].low < lowest:
                lowest = candles[j].low
                lowest_idx = j
        print('Move started at:', candles[lowest_idx].timestamp, 'low:', lowest)
        print('Is start in CHoCH zone?', choch_lower <= lowest <= choch_upper)
        break
