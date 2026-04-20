# IKENGA Research Sandbox

Isolated environment for algorithm development.
Changes here do NOT affect the live system.

## Workflow

1. Edit files in sandbox/algorithms/
2. Run sandbox/research.ipynb to test changes
3. Run sandbox/diff_tool.py to review what changed
4. Run sandbox/push_to_live.py to push to live (asks for confirmation)
5. Restart the live server

## Files

- algorithms/       — sandbox copies of live algorithms
- research.ipynb    — main research notebook
- diff_tool.py      — shows what changed vs live
- push_to_live.py   — pushes confirmed changes to live
- plots/            — saved chart outputs

## Important

- Never import from src/ in research.ipynb for algorithm files
- Always import from sandbox/algorithms/ instead
- DB access (SessionLocal, get_candles) always reads live data
- This is intentional — you test algorithms on real live data
