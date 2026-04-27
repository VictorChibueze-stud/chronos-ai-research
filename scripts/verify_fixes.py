import requests
import time

# Test 1: candle speed
t0 = time.perf_counter()
r = requests.get(
    "http://localhost:8000/api/candles/FRXAUDJPY?timeframe=1d&limit=200",
    timeout=15,
)
t1 = time.perf_counter()
print(f"Candle: {t1-t0:.3f}s", "PASS" if t1-t0 < 0.5 else "SLOW")

# Test 2: analysis cache
url = "http://localhost:8000/api/analysis/R_75?timeframe=1d"
requests.get(url, timeout=30)
time.sleep(2)
r2 = requests.get(url, timeout=15)
d2 = r2.json() if r2.status_code == 200 else {}
cached = d2.get("analysis_is_cached")
print(f"Cache: is_cached={cached}", "PASS" if cached else "FAIL")
