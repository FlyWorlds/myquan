import type { HoldingRow } from '../types/snapshot'

/** Buy and sell events have independent identities, even for the same symbol. */
export function otherAlertRows(rows: HoldingRow[], buyEvents: HoldingRow[]): HoldingRow[] {
  return rows.filter(row => {
    if (row.已实现 || row.槽位留痕 || row.三槽平仓) return false
    return !buyEvents.some(event => event.代码 === row.代码
      && event.信号因子 === row.信号因子 && row.已触买 === '是')
  })
}
