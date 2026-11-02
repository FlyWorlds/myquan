import type { HoldingRow } from '../types/snapshot'
import { sellProtection, stopWarningDistance } from './stopWarning.ts'

export function sellAlerts(holdings: HoldingRow[], closed: HoldingRow[]) {
  const exits = closed.filter(row => Boolean(row.已实现 || row.三槽平仓 || row.槽位留痕))
    .map(row => ({ row, state: '触卖', filled: true, protection: sellProtection(row) }))
  const warnings = holdings.filter(row => Number(row.持仓) > 0).flatMap(row => {
    const protection = sellProtection(row)
    const triggered = row.已触止损 === '是' || row.持仓状态 === '待卖出'
      || (protection != null && typeof row.现价 === 'number' && row.现价 <= protection.price)
    if (!triggered && stopWarningDistance(row) == null) return []
    return [{ row, state: triggered ? '触卖' : '将卖出', filled: false, protection }]
  })
  return [...warnings, ...exits]
}
