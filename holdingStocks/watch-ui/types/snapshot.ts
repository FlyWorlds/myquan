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
  浮盈?: number | null
  '浮盈%'?: number | null
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

export interface StrategyTab {
  id: string
  label: string
  name: string
  description?: string
  is_watch_default?: boolean
  factors: StrategyFactor[]
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
  strategies: StrategyTab[]
}
