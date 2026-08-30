import type { StrategyFactor, StrategyPicks, StrategyPickItem, StrategyTab } from '~/types/snapshot'

export type { StrategyFactor, StrategyPicks, StrategyPickItem, StrategyTab }

export interface FactorUsedBy {
  id: string
  name: string
  label: string
  role: string
  filter_desc?: string
}

export interface FactorEntry {
  id: string
  name: string
  description?: string
  rules_text?: string
  implemented?: boolean
  meta?: Record<string, unknown>
  used_by?: FactorUsedBy[]
}

export interface StrategyBacktestRow {
  entry_pct?: number
  total_return_pct?: number
  max_drawdown_pct?: number
  sharpe_ratio?: number
  win_rate?: number
  n_trades?: number
}

export type StrategyEntry = StrategyTab & {
  backtest?: StrategyBacktestRow[]
  reportPath?: string
}
