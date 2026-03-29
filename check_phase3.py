import urllib.request, json
payload = json.dumps({}).encode()
req = urllib.request.Request(
    'http://localhost:8000/api/setups/scan',
    data=payload,
    headers={'Content-Type': 'application/json'},
    method='POST'
)
print('Starting full universe scan with correlation filter...')
with urllib.request.urlopen(req, timeout=300) as r:
    data = json.loads(r.read())
print(f'Setups after correlation filter: {len(data)}')
by_category = {}
for s in data:
    cat = s.get('category', 'unknown')
    by_category[cat] = by_category.get(cat, 0) + 1
print('By category:', json.dumps(by_category, indent=2))
top5 = sorted(data, key=lambda x: x.get('trend_score', 0), reverse=True)[:5]
print('Top 5 by score:')
for s in top5:
    print(s['symbol'], s['trend'], 'depth='+str(s['pullback_depth']), 'score='+str(s['trend_score']))
