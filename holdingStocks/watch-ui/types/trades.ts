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
  summary?: {
    buy_amount?: number
    sell_amount?: number
    sell_pnl?: number
    count?: number
  }
  entries?: TradeLedgerEntry[]
  error?: string
}
