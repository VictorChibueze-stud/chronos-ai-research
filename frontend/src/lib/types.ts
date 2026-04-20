/** Setup summary CHoCH band (price only). */
export interface ChochZoneBounds {
  lower_boundary: number;
  upper_boundary: number;
}

/** CHoCH zone overlay from GET /api/analysis/:symbol */
export interface ChochZone {
  depth: number;
  lower_boundary: number;
  upper_boundary: number;
  start_timestamp: string;
  end_timestamp: string;
  color: string;
}
export interface BOS { price: number; break_type: "true" | "false" | "pending" | "broken"; }
export type MTFAlignment = Record<string, string>;
export interface ActiveZone {
  zone_type: string;
  price_high: number;
  price_low: number;
  is_manual_override: boolean;
}
export type ReadinessState = "FULL" | "PARTIAL" | "ERROR" | "UNSCANNED";

export type MarketState =
  | "WAITING"
  | "RETRACEMENT"
  | "DEPTH_BUILDING"
  | "CHOCH_ZONE_ACTIVE"
  | "CHOCH_TESTED"
  | "CANDIDATE_ACTIVE"
  | "CANDIDATE_CHOCH_TESTED"
  | "ENTRY_ZONE"
  | "CANDIDATE_CONFIRMED"
  | "STRUCTURE_BROKEN";

export interface MarketStateHistoryItem {
  id: number;
  symbol: string;
  state: string;
  previous_state: string | null;
  transitioned_at: string;
  score: number | null;
  trend_score: number | null;
  notes: string | null;
}

export interface ReadinessCoverage {
  available: string[];
  missing: string[];
}

export interface Setup {
  setup_id: number | null; symbol: string; broker: string; category: string;
  display_name?: string | null;
  sector?: string | null;
  universe?: string | null;
  timeframe: string;
  trend: "up" | "down" | "range"; current_phase: "impulse" | "retracement" | "range";
  fsm_state: string; trend_score: number; pullback_depth: number; total_mitigation_count: number;
  waiting_for: string; active_choch_zone: ChochZoneBounds | null; active_bos: BOS | null;
  active_zones?: ActiveZone[];
  mtf_alignment: MTFAlignment;
  structural_state?: StructuralState;
  last_checked_at: string;
  created_at?: string | null;
  updated_at?: string | null;
  id?: number;
  htf_timeframe?: string;
  htf_trend_direction?: string;
  status?: string;
  ema_signal?: "LONG" | "SHORT" | "WAITING" | null;
  structural_state_json?: StructuralState;
  readiness_state?: ReadinessState;
  readiness_coverage?: ReadinessCoverage;
  readiness_error?: string | null;
  score_components?: {
    state_score?: number;
    opportunity_score?: number;
    structure_score?: number;
    market_state?: string;
    price_ratio?: number;
    opp_detail?: string;
    profile?: string;
  };
  universe_rank?: number | null;
  total_score?: number;
  timeframe_basis?: "weekly" | "daily";
  market_state?: string | null;
}

export interface UniverseScore {
  symbol: string;
  timeframe_basis: "weekly" | "daily";
  trend_direction: "up" | "down" | "range";
  confirmed_leg_count: number;
  impulse_price_ratio: number;
  impulse_velocity_ratio: number;
  retracement_phase_bonus: number;
  candidate_impulse_bonus: number;
  total_score: number;
  universe_rank: number | null;
  last_computed_at: string;
}

export interface ScanJobLog {
  id: number;
  job_type: "universe_ranking" | "active_refresh";
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  total_symbols: number;
  success_count: number;
  failure_count: number;
  status: "running" | "complete" | "failed";
  error_message: string | null;
}

export interface UniverseRankingStatus {
  in_progress: boolean;
  total_symbols: number;
  symbols_scored: number;
  current_symbol: string | null;
  started_at: string | null;
  completed_at: string | null;
  last_error: string | null;
  estimated_seconds_remaining: number | null;
  /** Batch global-structure job (from ranking-status payload). */
  global_structure_in_progress?: boolean;
  /** Batch prime-impulse job (from ranking-status payload). */
  prime_impulse_in_progress?: boolean;
  /** Depth / walker batch job when enabled server-side (from ranking-status payload). */
  walker_in_progress?: boolean;
}

export interface ScanScoreWeights {
  price_ratio_weight: number;
  bar_ratio_weight: number;
}

export type UniverseScanFrequency = "hourly" | "daily" | "weekly" | "monthly";

export type ActiveRefreshHours = 1 | 2 | 4 | 8 | 12 | 24;

export interface CategoryMinSlots {
  forex: number;
  commodity: number;
  indices: number;
  synthetic: number;
  crypto: number;
  equities: number;
}

export interface UniverseSettings {
  universe_name: string;
  capacity: number;
  rank_frequency: string;
  refresh_offset_hours: number;
  refresh_interval_hours: number;
  top_n: number;
  non_top_n_depth: string;
  category_min_slots: Record<string, number>;
  is_active: boolean;
}

export interface ScanSettings {
  binance_top_n: number;
  brokers: Array<"binance" | "deriv" | "yfinance">;
  deriv_categories: string[];
  include_symbols: string[];
  exclude_symbols: string[];
  score_weights: ScanScoreWeights;
  scoring_profile: "aggressive" | "balanced" | "conservative" | "custom";
  scoring_layer_weights: {
    state_weight: number;
    opportunity_weight: number;
    structure_weight: number;
  };
  retracement_bonus: number;
  deriv_category_overrides: Record<string, string>;
  universe_scan_frequency: UniverseScanFrequency;
  active_refresh_hours: ActiveRefreshHours;
  deep_analysis_refresh_hours: number;
  non_top50_analysis_depth: string;
  category_min_slots: CategoryMinSlots;
}

export interface ScanSettingsHistoryRow {
  id: number;
  scope: string;
  settings: ScanSettings;
  created_at: string | null;
}
export interface SystemState {
  active_trends: number; in_retracement: number; high_conviction: number; in_impulse: number;
  capacity_used: number; capacity_max: number; killswitch_active: boolean; last_scan: string; next_scan: string;
}
export interface UniverseStats {
  total_monitored: number;
  by_category: Record<string, { count: number; trending_up: number; trending_down: number }>;
  by_phase: { impulse: number; retracement: number; range: number };
  by_depth: { depth_1: number; depth_2: number; depth_3: number };
}

export interface DepthLevel {
  depth: number;
  internal_tf_used?: string;
  choch_mitigated?: boolean;
  first_impulse_global_start?: number;
  first_impulse_global_end?: number;
  first_impulse?: {
    start_price?: number;
    end_price?: number;
  };
  structural_level?: {
    price?: number;
    source_leg_end_index?: number;
  };
  choch_zone?: {
    lower_boundary?: number;
    upper_boundary?: number;
    zone_midpoint?: number;
  };
  termination_reason?: string;
  crossing_attempt?: {
    global_start_index?: number;
    global_end_index?: number;
    start_price?: number;
    end_price?: number;
  } | null;
}

export interface WalkerLevel {
  depth: number;
  slice_start?: number;
  slice_end?: number;
  choch_zone?: {
    lower_boundary: number;
    upper_boundary: number;
  } | null;
  structural_level?: {
    price: number;
    classification?: string;
  } | null;
  first_impulse_global_start?: number | null;
  first_impulse_global_end?: number | null;
  first_impulse?: {
    start_price: number;
    end_price: number;
  } | null;
  crossing_attempt?: {
    global_start_index?: number;
    global_end_index?: number;
    start_price?: number;
    end_price?: number;
  } | null;
  termination_reason?: string | null;
  choch_mitigated?: boolean;
  is_mitigated?: boolean;
  mitigation_count?: number;
}

export interface StructuralState {
  walkable?: boolean;
  global_trend?: string;
  max_depth_reached?: number;
  total_mitigation_count?: number;
  waiting_for?: string;
  levels?: DepthLevel[];
  [key: string]: unknown;
}

export interface SetupSummary {
  symbol: string;
  broker: string;
  timeframe: string;
  trend: string;
  fsm_state: string;
  trend_score: number;
  category: "FOREX" | "CRYPTO" | "COMMODITIES" | "INDICES" | "SYNTHETIC";
}

export interface AlertZone {
  id: number;
  setup_id: number;
  symbol: string;
  zone_type: string;
  depth: number | null;
  price_high: number;
  price_low: number;
  is_active: boolean;
  watch_condition: string;
  is_manual_override: boolean;
  created_at?: string | null;
}

export interface HealthResponse {
  status: string;
  active_setups: number;
  max_capacity: number;
  last_scan: string | null;
  next_scan: string | null;
  scan_in_progress: boolean;
  killswitch_active?: boolean;
}

export interface ScanStartResponse {
  status: string;
  total_symbols?: number;
}

export interface ExecutionStatusResponse {
  execution_enabled: boolean;
  execution_paper_only: boolean;
  execution_provider: string;
}

export interface ExecutionOrderSummary {
  id: number;
  client_order_id: string;
  provider: string;
  symbol: string;
  side: string;
  status: string;
  provider_order_id: string | null;
  error_message: string | null;
  created_at: string | null;
}

export interface ExecutionOrderListResponse {
  items: ExecutionOrderSummary[];
}

export interface ExecutionEventItem {
  id: number;
  event_type: string;
  message: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface ExecutionOrderEventsResponse {
  order_id: number;
  items: ExecutionEventItem[];
}

export interface ExecutionEventRecord {
  event_type: string;
  message?: string | null;
  payload?: Record<string, unknown>;
  created_at: string;
}

export interface OrderSubmissionResponse {
  ok: boolean;
  client_order_id: string;
  status: string;
  provider: string;
  provider_order_id?: string | null;
  message?: string | null;
  events: ExecutionEventRecord[];
}

export type ExecutionProviderId = "deriv" | "stub";

export type DerivDurationUnit = "t" | "s" | "m" | "h" | "d";

/** POST /api/execution/orders body (subset; server fills defaults). */
export interface NormalizedOrderIntent {
  symbol: string;
  side: "long" | "short";
  stake_amount: number;
  client_order_id?: string;
  provider?: ExecutionProviderId;
  basis?: "stake" | "payout";
  currency?: string;
  duration?: number;
  duration_unit?: DerivDurationUnit;
  contract_type?: "CALL" | "PUT";
  metadata?: Record<string, unknown>;
}

/** POST /api/execution/from-signal body */
export interface FromSignalRequest {
  symbol: string;
  timeframe?: string;
  stake_amount?: number;
}

export interface KillswitchResponse {
  killswitch_active: boolean;
}

export interface TrendLeg {
  type: "impulse" | "retracement";
  start_price: number;
  end_price: number | null;
  start_index: number;
  end_index: number | null;
  start_timestamp: string | null;
  end_timestamp: string | null;
  confirmed: boolean;
  /** Timeframe used for internal structure when finer TF deepening ran (e.g. "5m"); else "current". */
  internal_tf_used?: string;
  /** Optional chart hint for special rendering styles (e.g. cached candidate structure). */
  render_style?: "candidate" | string;
  internal_legs?: TrendLeg[];
}

/** Global / internal CHoCH band from analysis (not walker depth zones). */
export interface StructureChochZone {
  lower_boundary: number;
  upper_boundary: number;
  start_timestamp: string;
  end_timestamp: string;
  broken?: boolean;
  trend_direction?: string;
  color?: string;
}

export interface BosLevel {
  price: number;
  start_index: number;
  start_timestamp: string;
  end_timestamp?: string;
  /** Index of break bar when broken; else same as last bar for segment end. */
  end_index?: number;
  broken: boolean;
  trend_direction: string;
  /** When set (e.g. candidate-move stack), chart uses this instead of default BOS blue. */
  color?: string;
}

export interface ChochLevel {
  price: number;
  start_index: number;
  start_timestamp: string;
  broken: boolean;
  trend_direction?: string;
}

export interface TrendWindowStructure {
  trend: string;
  current_phase: string | null;
  trend_start_price: number;
  trend_start_timestamp: string;
  legs: TrendLeg[];
  bos_levels: BosLevel[];
  choch_level: ChochLevel | null;
  choch_zone: ChochZone | null;
}

/** Serialized sub-trend on slice from CHoCH candidate pivot (teal overlays). */
export interface CandidateMoveTealStructure {
  render_style?: "candidate" | string;
  legs?: TrendLeg[];
  bos_levels?: BosLevel[];
  global_choch_zone?: StructureChochZone | null;
  internal_choch_zone?: StructureChochZone | null;
}

export interface CandidateMovePayload {
  pivot_index: number | null;
  pivot_price: number;
  move_start_timestamp: string;
  reference_bos_price: number | null;
  reference_bos_start_index: number | null;
  structure_broken: boolean | null;
  teal_structure: CandidateMoveTealStructure | null;
  candidate_ichoch_reached?: boolean | null;
  candidate_new_move_active?: boolean;
  choch_source?: "global" | "prime_internal" | "both" | string;
  candidate_legs?: TrendLeg[];
  candidate_bos_levels?: BosLevel[];
  candidate_choch_zone?: StructureChochZone | null;
  candidate_prime_impulse?: TrendLeg | null;
  candidate_prime_choch_zone?: StructureChochZone | null;
  candidate_walker?: {
    levels?: WalkerLevel[];
    max_depth_reached?: number;
    waiting_for?: string;
    global_choch_zone?: { lower_boundary: number; upper_boundary: number } | null;
  } | null;
  trend?: string;
  phase?: string | null;
}

export interface NewMoveAnalysis {
  trend: string | null;
  current_phase: string | null;
  leg_count: number;
  legs: TrendLeg[];
  bos_levels: BosLevel[];
  choch_zone: ChochZone | null;
  choch_reached: boolean;
  move_start_timestamp: string;
  entry_price: number;
  stop_loss: number;
  target: number | null;
}

/** Optional debug overrides for GET /api/analysis (omit server defaults). */
export interface AnalysisDevParams {
  use_parent_relative_filter: boolean;
  min_impulse_parent_ratio: number;
  use_momentum_filter: boolean;
  min_momentum_ratio: number;
  use_dominance_filter: boolean;
  min_dominance_ratio: number;
  /** When set, sent as min_swing_candles; otherwise omitted (server default 3). */
  min_swing_candles: number | null;
  /** When set, sent as trend_confirmation_pct; otherwise omitted (server default 0.03 outer). */
  trend_confirmation_pct: number | null;
  /** When set, sent as max_walk_depth; otherwise omitted (server default 3). */
  max_walk_depth: number | null;
  rmt_use_parent_relative_filter: boolean | null;
  rmt_min_impulse_parent_ratio: number | null;
  rmt_use_momentum_filter: boolean | null;
  rmt_min_momentum_ratio: number | null;
  rmt_use_dominance_filter: boolean | null;
  rmt_min_dominance_ratio: number | null;
}

export interface PaperAccount {
  id: number;
  name: string;
  account_type: string;
  balance_usd: number;
  initial_balance_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  open_positions: number;
  total_closed_trades: number;
  win_rate_pct: number;
  drawdown_limit_pct: number;
  risk_per_trade_pct: number;
  max_concurrent_positions: number;
  scale_by_score: boolean;
  entry_ema_fast: number;
  entry_ema_slow: number;
  entry_timeframe: string;
  min_market_state: string;
  tp_mode: string;
  time_exit_days: number | null;
  is_active: boolean;
  is_paused_drawdown: boolean;
  universe?: string | null;
}

export interface PaperTrade {
  id: number;
  account_id: number;
  symbol: string;
  direction: "long" | "short" | "up" | "down";
  entry_price: number;
  stop_price: number;
  take_profit_price: number | null;
  lot_size: number;
  risk_amount_usd: number;
  market_state_at_entry: string | null;
  score_at_entry: number | null;
  entry_timeframe: string | null;
  status: "open" | "closed_tp" | "closed_sl" | "closed_manual" | "closed_time";
  open_at: string;
  close_at: string | null;
  close_price: number | null;
  pnl_usd: number | null;
  pnl_pct: number | null;
}

export interface PaperPerformance {
  total_closed_trades: number;
  open_trades: number;
  total_pnl_usd: number;
  win_rate_pct: number;
  avg_win_usd: number;
  avg_loss_usd: number;
  risk_reward_ratio: number;
  max_drawdown_usd: number;
  open_exposure_usd: number;
  sharpe_ratio?: number;
  sortino_ratio?: number;
  calmar_ratio?: number;
  max_drawdown_pct?: number;
  max_drawdown_duration_days?: number;
  profit_factor?: number;
  pnl_curve: Array<{
    timestamp: string;
    cumulative_pnl: number;
    trade_pnl: number | null;
    symbol: string;
  }>;
}

export interface AccountTargets {
  sharpe_target?: number;
  sortino_target?: number;
  calmar_target?: number;
  profit_factor_target?: number;
  max_dd_pct_target?: number;
  win_rate_target?: number;
  risk_reward_target?: number;
}

export interface PaperTradeLevels {
  entry_price: number;
  stop_price: number;
  take_profit_price: number | null;
  direction: string;
  status: string;
}

export const DEFAULT_ANALYSIS_DEV_PARAMS: AnalysisDevParams = {
  use_parent_relative_filter: true,
  min_impulse_parent_ratio: 0.15,
  use_momentum_filter: true,
  min_momentum_ratio: 0.5,
  use_dominance_filter: true,
  min_dominance_ratio: 1.5,
  min_swing_candles: null,
  trend_confirmation_pct: null,
  max_walk_depth: null,
  rmt_use_parent_relative_filter: null,
  rmt_min_impulse_parent_ratio: null,
  rmt_use_momentum_filter: null,
  rmt_min_momentum_ratio: null,
  rmt_use_dominance_filter: null,
  rmt_min_dominance_ratio: null,
};

export interface ManualOverride {
  id?: number;
  symbol: string;
  override_type:
    | "trend_bounds"
    | "global_choch"
    | "ichoch"
    | "depth_choch"
    | "candidate_choch"
    | "candidate_ichoch";
  lower_boundary?: number | null;
  upper_boundary?: number | null;
  start_timestamp?: string | null;
  end_timestamp?: string | null;
  trend_start_timestamp?: string | null;
  trend_end_timestamp?: string | null;
  depth_index?: number | null;
  is_active?: boolean;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
  reset_at?: string | null;
}

export interface AnalysisResponse {
  status: string;
  symbol: string;
  timeframe?: string;
  /** Global structure cache reference: "daily" | "weekly" when served from GlobalStructureCache. */
  reference_timeframe?: string | null;
  structural_state?: {
    levels?: WalkerLevel[];
    max_depth_reached?: number;
    total_mitigation_count?: number;
    waiting_for?: string;
    global_choch_zone?: { lower_boundary: number; upper_boundary: number } | null;
  } | null;
  global_trend?: string;
  total_mitigation_count?: number;
  max_depth_reached?: number;
  waiting_for?: string;
  legs?: TrendLeg[];
  bos_levels?: BosLevel[];
  choch_level?: ChochLevel | null;
  choch_zones?: ChochZone[];
  global_choch_zone?: StructureChochZone | null;
  internal_choch_zone?: StructureChochZone | null;
  new_move?: NewMoveAnalysis | null;
  candidate_move?: CandidateMovePayload | null;
  bos_classifications?: Record<string, string>;
  prime_impulse_structure?: {
    legs: TrendLeg[];
    source_tf?: string;
    choch_zone?: StructureChochZone | null;
  } | null;
  market_state?: string | null;
  open_paper_trade?: PaperTradeLevels | null;
  manual_overrides?: Record<string, ManualOverride> | null;
}

export interface SymbolParamsResponse {
  symbol: string;
  params: Partial<AnalysisDevParams>;
  is_default: boolean;
  recomputing?: boolean;
}

export interface ChartZone {
  price: number;
  color: string;
  title: string;
}

export interface CandleBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type IntegrationHealth = "healthy" | "degraded" | "offline" | "unknown";

export interface BrokerCredentialsInput {
  api_key?: string;
  api_secret?: string;
  token?: string;
}

export interface BrokerAccountSnapshot {
  account_id?: string;
  balance?: number | null;
  currency?: string | null;
  challenge_status?: string | null;
  raw?: Record<string, unknown>;
}

export interface BrokerIntegrationStatus {
  broker: "binance" | "deriv" | "ftmo";
  connected: boolean;
  health: IntegrationHealth;
  last_sync: string | null;
  message: string;
  account?: BrokerAccountSnapshot | null;
}

export interface IntegrationsStatusResponse {
  status: string;
  generated_at: string;
  brokers: BrokerIntegrationStatus[];
}

export interface FundamentalEvent {
  name: string;
  category: string;
  scheduled_at: string;
  impact_level: "high" | "medium" | "low";
  rank: number | null;
  currency: string;
}

export interface FundamentalEventsResponse {
  symbol: string;
  blackout_active: boolean;
  blackout_reason: string | null;
  next_events: FundamentalEvent[];
}

export interface FundamentalNewsArticle {
  headline: string;
  source_name: string;
  published_at: string;
  sentiment_label: "positive" | "negative" | "neutral";
  sentiment_score: number;
  url: string;
}

export interface FundamentalNewsResponse {
  symbol: string;
  articles: FundamentalNewsArticle[];
}

export type BrokerConnectionTestRequest = BrokerCredentialsInput;

export interface BrokerConnectionTestResponse {
  ok: boolean;
  broker: "binance" | "deriv" | "ftmo";
  message: string;
  checked_at: string;
  account?: BrokerAccountSnapshot | null;
}

export interface ActiveListResponse {
  symbols: string[];
}

export interface ActiveListMutationResponse {
  ok: boolean;
  symbol: string;
}

export interface SignalHistoryItem {
  id: number;
  symbol: string;
  timeframe: string;
  signal: "LONG" | "SHORT" | string;
  trend_direction: string | null;
  trend_score: number | null;
  emitted_at: string | null;
}

export interface SignalHistoryResponse {
  symbol: string;
  items: SignalHistoryItem[];
}
