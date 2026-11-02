import type { HoldingRow } from '../types/snapshot'

export function sellProtection(row: HoldingRow): { price: number; reason: string } | null {
  const closed = Boolean(row.已实现 || row.槽位留痕)
    || ['今日平仓', '已平仓', '已止损', '已触止损平仓'].includes(String(row.持仓状态 || ''))
  const candidates = [
    { price: row.回落止损价, reason: row.卖出原因 || '跌破保护线（峰值回落）' },
    ...(!closed ? [
      { price: row.卖出侧价, reason: row.卖出原因 || '跌破卖出侧保护线' },
      { price: row.止损, reason: row.卖出原因 || '跌破止损保护线' },
    ] : []),
  ].filter((item): item is { price: number; reason: string } =>
    typeof item.price === 'number' && Number.isFinite(item.price) && item.price > 0)
  return candidates.reduce<{ price: number; reason: string } | null>(
    (best, item) => !best || item.price > best.price ? item : best, null)
}

export function stopWarningDistance(row: HoldingRow): number | null {
  if (!(Number(row.持仓) > 0) || row.已实现 || row.槽位留痕) return null
  const price = row.现价
  const protection = sellProtection(row)?.price
  if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0 || protection == null) return null
  const distance = (price / protection - 1) * 100
  return distance > 0 && distance <= 1 + 1e-9 ? distance : null
}
