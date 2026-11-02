import type { HoldingRow } from '../types/snapshot'

export function alertType(row: HoldingRow, side: 'buy' | 'sell'): string {
  if (side === 'sell') {
    const reason = `${row.卖出原因 || ''} ${row.挂单说明 || ''}`
    if (/峰值|回落|t1_peak_trail|giveback|peak_pullback/.test(reason)) return '阶段回落（峰值）'
    if (/硬保护|成本|hard_from_cost/.test(reason)) return '成本止损'
    if (/竞价|factor29/.test(reason)) return '竞价强度'
    return '卖出保护'
  }
  if (row.预警类型) return row.预警类型
  const source = `${row.信号来源 || ''} ${row.挂单说明 || ''}`
  if (row.信号因子 === 'factor33' || /探底|低点反弹|day_low_rebound|因子33/.test(source)) return '探底回升'
  if (row.信号因子 === 'factor29' || /竞价|auction_open/.test(source)) return '竞价强度'
  return '开盘突破'
}
