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
export interface MarketRadar {
  status: string; source?: string; trade_date?: string; fetched_at?: string; source_at?: string
  refreshing?: boolean; historical?: boolean; stale?: boolean; error?: string; errors?: string[]
  stocks?: RadarStock[]; broken?: RadarStock[]; themes?: RadarTheme[]; industries?: RadarTheme[]
  reason_coverage?: number
  summary?: { sealed: number; broken?: number; down?: number; break_rate?: number; max_height: number; grade_a: number | null }
}
