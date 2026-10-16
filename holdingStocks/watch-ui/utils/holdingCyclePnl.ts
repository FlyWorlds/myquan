import type { HoldingRow } from '../types/snapshot'

function finite(value: unknown): number | null {
  if (value == null || value === '' || typeof value === 'boolean') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/** Paper buy-cycle PnL, including every partial sale; never use a strategy simulator ledger. */
export function holdingCyclePnl(row: HoldingRow) {
  if (!['database_delivery_cycle_with_adjustments', 'trades_jsonl_cycle'].includes(row.综合单笔来源 || '')) return null
  const amount = finite(row.综合单笔收入)
  const base = finite(row.综合单笔成本额)
  const qty = finite(row.持仓)
  const openQty = finite(row.综合单笔持仓数量)
  const soldQty = finite(row.综合单笔卖出数量)
  if (amount == null || base == null || base <= 0 || qty == null || qty < 0
    || qty !== openQty || soldQty == null || soldQty < 0) return null
  const mark = finite(row.现价)
  const cost = finite(row.成本)
  if (qty > 0 && (mark == null || mark <= 0 || cost == null || cost <= 0)) return null
  const unrealized = qty > 0 ? Math.round((mark! - cost!) * qty * 100) / 100 : 0
  return { amount, pct: Math.round(amount / base * 10000) / 100, unrealized,
    realized: Math.round((amount - unrealized) * 100) / 100, soldQty }
}
