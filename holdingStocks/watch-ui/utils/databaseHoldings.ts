import type { HoldingRow, WatchSnapshot } from '~/types/snapshot'
import type { DatabasePaperState } from '~/composables/useDatabaseHoldings'
import { holdingStatus } from './holdingStatus.ts'

export function mergeDatabaseHoldings(raw: WatchSnapshot, state: DatabasePaperState): WatchSnapshot {
  // An older HTTP poll must not undo a more recent committed WebSocket snapshot.
  if (raw.paperRevision != null && raw.paperRevision > state.revision) return raw
  const positions = state.holdings.positions
  const session = raw.clock?.slice(0, 10)
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
    const fee = Number(pos?.buy_fees_remaining || 0)
    const basis = Number(cost || 0)*qty+fee
    const pnl = qty > 0 && cost != null && mark != null && mark > 0 ? (mark - cost) * qty-fee : null
    const status = holdingStatus({ ...row, 持仓: qty, 买入时间: pos?.buy_time,
      ...(!unchanged || (qty > 0 && row.买入时间 && row.买入时间 !== pos?.buy_time)
        ? { 持仓状态: qty > 0 ? '' : '空仓' } : {}) }, session || row.交易日)
    const closed = state.holdings.realized_today?.[String(row.代码 || '')]
    const sellTime = closed?.signal_time || closed?.first_hit_ts
    const confirmedClose = qty <= 0 && row.已实现 && closed?.session === session
      && sellTime && session && sellTime.startsWith(session)
    return { ...row, 持仓: qty, 可用: pos?.available ?? null, 成本: cost,
      持仓状态: status, 交易日: session || row.交易日,
      买入剩余费用: fee,
      ...(confirmedClose ? { 信号时间: sellTime, 卖信号时间: sellTime } : {}),
      买入时间: pos?.buy_time ?? null, 名称: pos?.name || row.名称,
      ...(!unchanged ? { 已实现: false,
        当日盈亏: null, '当日盈亏%': null, 综合单笔收入: null, '综合单笔收入%': null } : {}),
      ...(!sameCycleRevision ? { 综合单笔收入: null, '综合单笔收入%': null,
        综合单笔成本额: null, 综合单笔卖出数量: null, 综合单笔持仓数量: null, 综合单笔来源: null } : {}),
      ...(qty > 0 ? { 浮盈: pnl, '浮盈%': basis > 0 && pnl != null ? pnl/basis*100 : null }
        : row.已实现 && unchanged ? {} : { 浮盈: null, '浮盈%': null }) }
  })
  const known = new Set(rows.map((row) => row.代码))
  for (const [code, pos] of Object.entries(positions)) {
    if (pos.qty <= 0 || known.has(code)) continue
    compatible = false
    rows.unshift({ 代码: code, 名称: pos.name || code, 市场: pos.market, 持仓: pos.qty,
      置顶: true,
      可用: pos.available ?? null, 成本: pos.cost ?? null, 买入时间: pos.buy_time ?? null,
      交易日: session,
      持仓状态: holdingStatus({ 持仓: pos.qty, 买入时间: pos.buy_time }, session) })
  }
  const account = compatible ? raw.account : { ...raw.account,
    availableCash: state.holdings.account_cash, accountTotal: state.holdings.account_total,
    totalPnl: null, totalPnlPct: null, dayPnl: null, dayPnlPct: null,
    equityDayPnl: null, rowDayPnl: null, dayPnlVsRows: null,
    marketValue: null, cost: null, positionPct: null, todayOpened: null,
    settledPnl: null, settledDayPnl: null, settledCount: undefined }
  const opened = state.trades && session ? [...new Set(state.trades
    .filter(t => t.code && t.side?.toLowerCase() === 'buy' && !t.reset_archived
      && (t.session || t.time || '').slice(0, 10) === session).map(t => t.code!))].sort() : null
  const left = opened ? Math.max(0, (raw.slotMeta?.maxNewSymbolsPerSession ?? 2) - opened.length) : null
  return { ...raw, holdings: rows, account,
    ...(opened ? { slotMeta: { ...raw.slotMeta, buysToday: opened.length, newSymbolsToday: opened,
      buysLeft: left!, newSymbolsLeft: left!, session } } : {}) }
}
