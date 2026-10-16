import type { HoldingRow, WatchSnapshot } from '~/types/snapshot'
import type { DatabasePaperState } from '~/composables/useDatabaseHoldings'

export function mergeDatabaseHoldings(raw: WatchSnapshot, state: DatabasePaperState): WatchSnapshot {
  // An older HTTP poll must not undo a more recent committed WebSocket snapshot.
  if (raw.paperRevision != null && raw.paperRevision > state.revision) return raw
  const positions = state.holdings.positions
  let compatible = raw.account.availableCash === state.holdings.account_cash
  const rows: HoldingRow[] = (raw.holdings || []).map((row) => {
    const pos = positions[String(row.代码 || '')]
    const qty = Number(pos?.qty || 0)
    const unchanged = qty === Number(row.持仓 || 0)
      && (qty <= 0 || Math.abs(Number(pos?.cost) - Number(row.成本)) < 0.000001)
    if (!unchanged) compatible = false
    const sameCycleRevision = raw.paperRevision === state.revision
    const cost = qty <= 0 && row.已实现 && unchanged ? row.成本 ?? null : pos?.cost ?? null
    const mark = row.现价
    const pnl = qty > 0 && cost != null && mark != null && mark > 0 ? (mark - cost) * qty : null
    return { ...row, 持仓: qty, 可用: pos?.available ?? null, 成本: cost,
      买入时间: pos?.buy_time ?? null, 名称: pos?.name || row.名称,
      ...(!unchanged ? { 持仓状态: qty > 0 ? '已经买入' : '空仓', 已实现: false,
        当日盈亏: null, '当日盈亏%': null, 综合单笔收入: null, '综合单笔收入%': null } : {}),
      ...(!sameCycleRevision ? { 综合单笔收入: null, '综合单笔收入%': null,
        综合单笔成本额: null, 综合单笔卖出数量: null, 综合单笔持仓数量: null, 综合单笔来源: null } : {}),
      ...(qty > 0 ? { 浮盈: pnl, '浮盈%': cost && mark != null && mark > 0 ? (mark / cost - 1) * 100 : null }
        : row.已实现 && unchanged ? {} : { 浮盈: null, '浮盈%': null }) }
  })
  const known = new Set(rows.map((row) => row.代码))
  for (const [code, pos] of Object.entries(positions)) {
    if (pos.qty <= 0 || known.has(code)) continue
    compatible = false
    rows.unshift({ 代码: code, 名称: pos.name || code, 市场: pos.market, 持仓: pos.qty,
      置顶: true,
      可用: pos.available ?? null, 成本: pos.cost ?? null, 买入时间: pos.buy_time ?? null,
      持仓状态: '已经买入' })
  }
  const account = compatible ? raw.account : { ...raw.account,
    availableCash: state.holdings.account_cash, accountTotal: state.holdings.account_total,
    totalPnl: null, totalPnlPct: null, dayPnl: null, dayPnlPct: null,
    equityDayPnl: null, rowDayPnl: null, dayPnlVsRows: null,
    marketValue: null, cost: null, positionPct: null, todayOpened: null,
    settledPnl: null, settledDayPnl: null, settledCount: undefined }
  return { ...raw, holdings: rows, account }
}
