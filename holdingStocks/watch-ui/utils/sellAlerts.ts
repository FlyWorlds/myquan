import type { HoldingRow } from '../types/snapshot'
import { sellProtection, stopWarningDistance } from './stopWarning.ts'

export function sellAlerts(holdings: HoldingRow[], closed: HoldingRow[]) {
  const seenCodes = new Set<string>()
  const warnings: Array<{ row: HoldingRow; state: '触卖' | '将卖出'; filled: boolean; protection: ReturnType<typeof sellProtection> }> = []
  for (const row of holdings) {
    if (Number(row.持仓) <= 0) continue
    const code = String(row.代码 || '')
    if (seenCodes.has(code)) continue
    const protection = sellProtection(row)
    const triggered = row.已触止损 === '是' || row.持仓状态 === '待卖出'
      || (protection != null && typeof row.现价 === 'number' && row.现价 <= protection.price)
    if (!triggered && stopWarningDistance(row) == null) continue
    warnings.push({ row, state: triggered ? '触卖' : '将卖出', filled: false, protection })
    seenCodes.add(code)
  }

  const exits: typeof warnings = []
  for (const row of closed) {
    if (!row.已实现 && !row.三槽平仓 && !row.槽位留痕) continue
    const code = String(row.代码 || '')
    if (seenCodes.has(code)) continue
    exits.push({ row, state: '触卖', filled: true, protection: sellProtection(row) })
    seenCodes.add(code)
  }

  return [...warnings, ...exits]
}
