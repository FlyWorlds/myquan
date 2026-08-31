export interface WatchAccount {
  totalPnl?: number | null
  totalPnlPct?: number | null
  dayPnl?: number | null
  dayPnlPct?: number | null
  accountTotal?: number | null
  accountOpen?: number | null
  availableCash?: number | null
  positionPct?: number | null
  marketValue?: number | null
  cost?: number | null
  todayOpened?: number | null
  settledCount?: number
  settledPnl?: number | null
  settledDayPnl?: number | null
  factor2Summary?: string
}

export interface IndexQuote {
  code?: string
  name?: string
  market?: string
  price?: number | null
  chgPoints?: number | null
  chgPct?: number | null
  error?: string | null
}

export interface HoldingRow {
  市场?: string
  代码?: string
  名称?: string
  开盘?: number | null
  现价?: number | null
  当日涨幅?: number | null
  较开盘涨幅?: number | null
  持仓?: number
  成本?: number | null
  浮盈?: number | null
  '浮盈%'?: number | null
  盈亏状态?: string | null
  盈亏说明?: string | null
  已实现?: boolean
  当日盈亏?: number | null
  '当日盈亏%'?: number | null
  持仓状态?: string
  因子侧?: string
  因子价?: number | null
  因子触发?: string
  预警?: string
  挂单说明?: string
  买点?: number | null
  止损?: number | null
  '阈值%'?: string
  过门?: string
  过门OK?: boolean
  前日形态?: string
  阈值就绪?: boolean
  竞价参考?: number | null
  bgClass?: string
  价位小数?: number
  更新?: string
  error?: string | null
  [key: string]: unknown
}

export interface StrategyFactor {
  id: string
  name: string
  role: string
  filter_desc?: string
  description?: string
}

export interface StrategyPickItem {
  rank?: number
  symbol?: string
  code?: string
  name?: string
  score?: number
  thr?: number
  gap_pct?: number
  vol_ratio?: number
  mkt_lianban?: number
  trade_date?: string
  theme?: string
  theme_lu?: number
  pool_tag?: string
  weight?: number
}

export interface StrategyPicks {
  kind: 'weekly' | 'daily' | 'locked' | 'signals' | 'none' | string
  asOf?: string | null
  source?: string | null
  note?: string
  items?: StrategyPickItem[]
}

export interface StrategyBacktestRow {
  entry_pct?: number
  total_return_pct?: number
  max_drawdown_pct?: number
  sharpe_ratio?: number
  win_rate?: number
  n_trades?: number
  start?: string
  end?: string
}

export interface Strategy3Sentiment {
  tradeDate?: string
  rawTradeDate?: string | null
  sentimentDate?: string | null
  mkt_lu?: number
  mkt_lianban?: number
  mkt_max_height?: number
  mkt_ladder_score?: number
  luPhase?: 'ice' | 'normal' | 'climax' | null
  luPhaseLabel?: string
  luPhaseHint?: string
  luPhaseRanges?: string
  gateOk?: boolean
  gateReasons?: string[]
  rules?: string
  cacheNote?: string
}

export interface Strategy3Row {
  代码?: string
  名称?: string
  昨日首板?: boolean
  连板?: number
  涨停日?: string | null
  首板日?: string | null
  晋级低开%?: number | null
  量比?: number | null
  可操作?: boolean
  买点?: number | null
  止损?: number | null
  '阈值%'?: string
  因子侧?: string
  挂单说明?: string
  现价?: number | null
  开盘?: number | null
}

export interface Strategy3Payload {
  sentiment?: Strategy3Sentiment
  backtest?: StrategyBacktestRow[]
  rows?: Strategy3Row[]
  poolDate?: string | null
  poolCount?: number
  effectiveTradeDate?: string
  cacheNote?: string
}

export interface Strategy8HotTheme {
  name: string
  luCount: number
  members?: number
}

export interface Strategy8Row {
  代码?: string
  名称?: string
  题材?: string
  题材涨停数?: number
  类型?: string
  当日涨停?: boolean
  可操作?: boolean
  买点?: number | null
  止损?: number | null
  '阈值%'?: string
  因子侧?: string
  挂单说明?: string
  现价?: number | null
  开盘?: number | null
}

export interface Strategy8Payload {
  sentiment?: Strategy3Sentiment
  hotThemes?: Strategy8HotTheme[]
  backtest?: StrategyBacktestRow[]
  rows?: Strategy8Row[]
  themeDate?: string | null
  luCount?: number
  poolDate?: string | null
  poolCount?: number
  rules?: string
  nameMap?: Record<string, string>
}

export interface StrategyTab {
  id: string
  label: string
  name: string
  description?: string
  aliases?: string[]
  implemented?: boolean
  is_watch_default?: boolean
  factors: StrategyFactor[]
  backtest?: StrategyBacktestRow[]
  reportPath?: string
  picks?: StrategyPicks
}

export interface SectorsLiveQuote {
  code: string
  price?: number | null
  chgPct?: number | null
  amount?: number | null
}

export interface SectorsConceptToday {
  code?: string
  name?: string
  涨跌幅?: number | null
  close?: number | null
  资金?: number | null
  资金口径?: string
  涨停数?: number
  涨跌比?: number | null
  上涨家数?: number
  下跌家数?: number
  主力净额?: number | null
  主力净额口径?: string
  强度?: number | null
}

export interface SectorsLivePayload {
  source?: string
  spotAt?: string
  memberStatsAt?: string | null
  conceptToday?: Record<string, SectorsConceptToday>
  focusConcept?: string | null
  conceptIndex?: {
    name?: string
    code?: string
    price?: number | null
    chgPct?: number | null
    amount?: number | null
  }
  quotes?: Record<string, SectorsLiveQuote>
  segmentCount?: number
  error?: string | null
}

export interface WatchSnapshot {
  v: number
  type: 'snapshot'
  ts: number
  updatedAt?: string
  clock?: string
  phase?: string
  phaseKey?: string
  refreshSec?: number
  strategy?: {
    id?: string
    name?: string
    factorsLabel?: string
  }
  account: WatchAccount
  indices: IndexQuote[]
  holdings: HoldingRow[]
  strategy1: HoldingRow[]
  strategy3?: Strategy3Payload
  strategy8?: Strategy8Payload
  sectors?: SectorsLivePayload
  strategies: StrategyTab[]
}
