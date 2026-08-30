import type { StrategyFactor, StrategyTab } from '~/types/snapshot'

export type { StrategyFactor, StrategyTab }

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

export type StrategyEntry = StrategyTab
