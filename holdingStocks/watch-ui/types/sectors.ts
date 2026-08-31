export interface SectorCell {
  name: string
  value: number | null
  rank: number
  label?: string
  metric?: string
}

export interface SectorMember {
  代码: string
  名称: string
  现价?: number | null
  涨跌幅?: number | null
  换手率?: number | null
  成交额?: number | null
}

export interface SectorKindPayload {
  dates: string[]
  by_metric: Record<
    string,
    {
      top: SectorCell[][]
      bottom: SectorCell[][]
    }
  >
  members: Record<string, SectorMember[]>
  fund_note?: string
  board_count?: number
}

export interface SectorMembersPayload {
  name: string
  source?: string
  code?: string
  count: number
  members: SectorMember[]
  error?: string
}

export interface SectorRotationPayload {
  updated_at: string
  session: string
  top_n: number
  days: number
  metrics: string[]
  source?: string
  kinds: Record<string, SectorKindPayload>
}

export interface ConceptKlineBar {
  date: string
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  amount?: number | null
}

export interface ConceptLeader {
  rank: number
  code: string
  name: string
  return_pct: number
}

export interface ConceptRallySegment {
  start_date: string
  end_date: string
  start_idx: number
  end_idx: number
  gain_pct: number
  days: number
  leaders: ConceptLeader[]
}

export interface ConceptDetailPayload {
  concept: string
  code: string
  source: string
  updated_at: string
  months: number
  kline: ConceptKlineBar[]
  segments: ConceptRallySegment[]
  member_count: number
  members_preview: { code: string; name: string }[]
  error?: string
}

export interface ScoredLeaderRow {
  rank: number
  code: string
  name: string
  score_quality: number | null
  f13_pass: boolean
  pl_ratio: number | null
  win_rate: number | null
  profit_factor: number | null
  excess_pct: number | null
  mdd_pct: number | null
  ret_pct: number | null
  sharpe_fit: number | null
  n_trades: number
  chan_pl_ratio: number | null
  chan_win_rate: number | null
  chan_trades: number
}

export interface ConceptLeaderScoresPayload {
  concept: string
  start: string
  end: string
  updated_at?: string
  scoring?: Record<string, string>
  candidate_count?: number
  leaders: ScoredLeaderRow[]
  error?: string
}
