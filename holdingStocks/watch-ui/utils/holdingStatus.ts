/** Use the server session, never the browser's local timezone or quote date. */
export function heldPositionStatus(buyTime: unknown, session: unknown): string {
  const bought = String(buyTime || '').slice(0, 10)
  const day = String(session || '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(day) && bought === day ? '已经买入' : '持有'
}

export function holdingStatus(row: Record<string, unknown>, session?: unknown): string {
  const status = String(row.持仓状态 || '').trim()
  if (Number(row.持仓 || 0) <= 0) return status || '空仓'
  if (status === '待卖出') return status
  return heldPositionStatus(row.买入时间, session || row.交易日)
}

export function holdingT1Locked(row: Record<string, unknown>): boolean {
  if (Number(row.持仓) <= 0 || row.t0 || row.可用 == null || Number(row.可用) > 0) return false
  const bought = String(row.买入时间 || '').slice(0, 10)
  const session = String(row.交易日 || '').slice(0, 10)
  if (bought && session) return bought === session
  return String(row.预警 || '').includes('T+1') || row.持仓状态 === '持有·T+1'
}
