# IKENGA — Task board

## In progress

- [ ] CHoCH-triggered trend reset logic — implement trend reversal when CHoCH zone is breached [AI]
- [ ] Must-break BOS validation during leg confirmation — ensure BOS is truly broken, not just touched [Fix]
- [ ] Range detection via retracement-depth behavior — identify ranging markets by retracement size patterns [AI]
- [ ] Trend channel lines — draw dynamic support/resistance lines around active trends [UI]
- [ ] Signal gate — macro event blocker for FOMC, NFP, and similar high-impact events [Arch]
- [ ] Snapshot serialization polish — ensure state reports can be written to and restored from JSON [Infra]
- [ ] Frontend pages — finish wiring demo-mode surfaces (analytics, risk, radar) to real data [UI]
- [ ] Paper trading lifecycle — Deriv paper provider end-to-end, then Binance demo [Infra]
- [ ] Universe management — finalize universe + paper_universe seeding and editing flows [Arch]

## Done since last update

- [x] Market scanner — 4-hourly scanning of 350+ Binance + Deriv universe pairs with score-based LRU eviction [Arch]
- [x] Orchestrator and setup lifecycle — trigger → confirm → execute → settle state machine [Arch]
- [x] API endpoints — analysis, setups CRUD, execution, readiness bootstrap, manual overrides, universe ranking [Infra]
- [x] Frontend pages live-driven — scanner, signals, market, universe [UI]
- [x] Manual structure overrides — preserve user-defined zones from eviction [Arch]
- [x] Contract specs + paper trading scaffold — execution provider seeded with instrument metadata [Infra]
- [x] Postgres migration path — alembic migrations, backfill scripts, and validation harness [Infra]

## To do

- [ ] `analyze_impulse_as_trend()` — analyze single impulse leg as standalone trend for recursive fractal analysis [Arch]
- [ ] Range detection via retracement-depth behavior — identify ranging markets by retracement size patterns [AI]
- [ ] Trend channel lines — draw dynamic support/resistance lines around active trends [UI]
- [ ] RSI divergence as confluence factor — add RSI bullish/bearish divergence detection [AI]
- [ ] Correlation bias validation — screen setups against market-wide correlation state [AI]
- [ ] Trade journal — auto-log executed trades with reasoning snapshot at time of entry [Infra]
- [ ] Position sizing engine — risk % per trade, SL-based calculation, max loss clamps [Arch]
- [ ] Multi-market scanner ranking — confluence score for signal prioritization [AI]
- [ ] Telegram alert system — high-score setups pushed to Telegram channel [Infra]
- [ ] Backtesting module against historical structure data — full backtest validation suite [Arch]
- [ ] Equity curve analysis — compute Sharpe ratio, sortino, calmar, max drawdown duration [Infra]
- [ ] Session timezone handling — ensure UTC consistency across DST transitions and multi-region data [Fix]
- [ ] Frontend editable plot parameters — UI controls for filter thresholds and visualization settings [UI]
- [ ] Additional confluence experiments — volume profile, VWAP, order flow analysis [AI]
- [ ] Snapshot serialization polish — ensure state reports can be written to and restored from JSON [Infra]
- [ ] Stress test on edge cases — trend reversal at extreme prices, gap opens, circuit breakers [Fix]
- [ ] Documentation — expand CLAUDE.md and AGENTS.md with examples and workflows [Docs]
- [ ] Performance profiling — optimize candle loading, trend ID computation for large datasets [Infra]
- [ ] Database migration testing — ensure alembic migrations work on production schema [Infra]

## Backlog

- [ ] Live Deriv connector — real order submission (when EXECUTION_ENABLED=1) [Infra]
- [ ] Live Binance connector — paper trading and real execution (with killswitch) [Infra]
- [ ] Model retraining — periodically retrain Gemma sentiment model on fresh financial news [AI]
- [ ] XAI (explainability) layer — break down signal probability by confluence factor [UI]
- [ ] Risk dashboard — equity drawdown, daily/weekly loss tracking, heat map of correlations [UI]
- [ ] Slippage and execution cost models — backtest with realistic fills [Arch]
- [ ] High-frequency microstructure analysis — order book depth, bid/ask spread, liquidity tiers [Research]
- [ ] Multi-instrument portfolio view — surface and risk management across 50+ monitored setups [UI]
- [ ] Webhook system — external app integration for signals and alerts [Infra]
- [ ] GraphQL endpoint — alternative to REST API for flexible data queries [Infra]
- [ ] Mobile app — React Native companion for mobile alerts and monitoring [Frontend]
