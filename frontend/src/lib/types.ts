export interface ChochZone { lower_boundary: number; upper_boundary: number; }
export interface BOS { price: number; break_type: "true" | "false" | "pending" | "broken"; }
export type MTFAlignment = Record<string, string>;
export interface ActiveZone {
  zone_type: string;
  price_high: number;
  price_low: number;
  is_manual_override: boolean;
}
export interface Setup {
  setup_id: number; symbol: string; broker: string; category: string; timeframe: string;
  trend: "up" | "down" | "range"; current_phase: "impulse" | "retracement" | "range";
  fsm_state: string; trend_score: number; pullback_depth: number; total_mitigation_count: number;
  waiting_for: string; active_choch_zone: ChochZone | null; active_bos: BOS | null;
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

export interface KillswitchResponse {
  killswitch_active: boolean;
}

export interface AnalysisResponse {
  status: string;
  symbol: string;
  timeframe?: string;
  structural_state?: StructuralState;
  global_trend?: string;
  total_mitigation_count?: number;
  max_depth_reached?: number;
  waiting_for?: string;
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

export interface ChartStructuralLevel {
  depth: number;
  color: string;
  chochZone: { lower: number; upper: number } | null;
  bosPrice: number | null;
  bosColor?: string;
  impulseStart: { price: number; time: number } | null;
  impulseEnd: { price: number; time: number } | null;
}