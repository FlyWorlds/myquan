export interface RadarStock {
  code: string; name: string; price?: number; pct?: number; industry?: string
  amount_yi?: number; float_cap_yi?: number; turnover?: number; limit_days?: number
  first_seal?: string; last_seal?: string; seal_fund_yi?: number; break_times?: number
  zt_stat?: string; reason?: string; reason_detail?: string; themes?: string[]; score?: number; grade?: string
  quote_at?: string; seal_strength?: number; score_reasons?: string[]
}

export interface RadarTheme {
  name: string; count: number; max_height: number; seal_fund_yi: number | null; stocks: RadarStock[]
}

export interface SentimentLadderItem {
  height: number
  label: string
  count: number
  stocks: RadarStock[]
}

export interface SentimentThemeResonance {
  name: string
  count: number
  max_height: number
  resonance_level: string
  resonance_tag: string
  resonance_desc: string
  stocks: RadarStock[]
  ladder_summary: string
}

export interface EmotionCycle {
  temperature: number
  key: 'freeze' | 'chaos' | 'rise' | 'climax'
  name: string
  icon: string
  color: string
  action_guide: string
  detail_guide: string
  suggested_position: string
  is_down_gt_up: boolean
}

export interface PromotionLadderItem {
  stage: string
  count: number
  rate_pct: number
  stocks: string[]
  desc: string
}

export interface BadAppleStock extends RadarStock {
  limit_ceil?: number
  drawdown?: number
  is_severe?: boolean
}

export interface BadDrawdownStats {
  big_drawdown_count: number
  severe_drawdown_count: number
  big_drawdown_rate: number
  top_bad_apples: BadAppleStock[]
}

export interface MarketSentiment {
  sealed: number
  down: number
  broken: number
  break_rate: number
  ratio: number
  ratio_label: string
  is_down_gt_up: boolean
  risk_verdict: string
  risk_level: 'danger' | 'warning' | 'success' | 'info'
  max_height: number
  ladder: SentimentLadderItem[]
  promotion_ladder?: PromotionLadderItem[]
  emotion_cycle?: EmotionCycle
  bad_drawdown_stats?: BadDrawdownStats
  theme_resonance: SentimentThemeResonance[]
  strong_dragons: RadarStock[]
}

export interface SentimentHistoryItem {
  date: string
  sealed: number
  down: number
  broken: number
  ratio: number
  max_height: number
}

export interface SessionContext {
  target_date: string
  is_today: boolean
  is_live: boolean
  phase: 'holiday_closed' | 'pre_market_replay' | 'auction_transition' | 'intraday_live' | 'post_market_closed'
  phase_label: string
  tip: string
  now_str: string
}

export interface MarketRadar {
  status: string; source?: string; trade_date?: string; fetched_at?: string; source_at?: string
  refreshing?: boolean; historical?: boolean; stale?: boolean; error?: string; errors?: string[]
  stocks?: RadarStock[]; broken?: RadarStock[]; themes?: RadarTheme[]; industries?: RadarTheme[]
  reason_coverage?: number
  summary?: { sealed: number; broken?: number; down?: number; break_rate?: number; max_height: number; grade_a: number | null }
  sentiment?: MarketSentiment
  history?: SentimentHistoryItem[]
  session_context?: SessionContext
}
