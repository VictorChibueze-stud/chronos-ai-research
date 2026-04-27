import time
import sys

sys.path.insert(0, ".")

from src.db.session import SessionLocal
from src.cache import candle_store

# Time just the DB session acquisition
t0 = time.perf_counter()
db = SessionLocal()
t1 = time.perf_counter()
print(f"Session acquire: {t1-t0:.3f}s")

# Time just the query
t2 = time.perf_counter()
rows = candle_store._query_candles(
    db, "FRXAUDJPY", "1d", 200
)
t3 = time.perf_counter()
print(f"Query ({len(rows)} rows): {t3-t2:.3f}s")

# Time serialization
t4 = time.perf_counter()
result = [
    {
        "time": c.timestamp.isoformat(),
        "open": float(c.open),
        "high": float(c.high),
        "low": float(c.low),
        "close": float(c.close),
        "volume": float(c.volume),
    }
    for c in rows
]
t5 = time.perf_counter()
print(f"Serialize: {t5-t4:.3f}s")
print(f"Total direct: {t5-t0:.3f}s")
db.close()
