export type TradeLedgerEntry = {
  id?: string
  time?: string
  session?: string
  side?: string
  code?: string
  name?: string
  market?: string
  price?: number
  qty?: number
  after_qty?: number
  amount?: number
  cost?: number | null
  pnl?: number | null
  pnl_pct?: number | null
  /** unrealized=仍持仓 BUY 现价盯市；realized=已平仓 SELL */
  pnl_kind?: 'unrealized' | 'realized' | string | null
  mark_price?: number | null
  remaining_qty?: number | null
  pnl_basis?: string | null
  day_pnl?: number | null
  day_pnl_pct?: number | null
  account_cash_after?: number | null
  action_kind?: string
  buy_time?: string | null
  reason?: string
  reason_detail?: string
  note?: string
}

export type TradeLedgerResponse = {
  updated_at?: string | null
  total?: number
  offset?: number
  limit?: number
  month?: string | null
  months?: string[]
  summary?: {
    buy_amount?: number
    sell_amount?: number
    sell_pnl?: number
    realized_pnl?: number
    unrealized_pnl?: number
    total_pnl?: number
    count?: number
    month?: string | null
  }
  entries?: TradeLedgerEntry[]
  lot_matching?: boolean
  error?: string
}
