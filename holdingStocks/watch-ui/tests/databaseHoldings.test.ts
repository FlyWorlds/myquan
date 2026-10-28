import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeDatabaseHoldings } from '../utils/databaseHoldings.ts'

const raw = () => ({ account: { availableCash: 100, accountTotal: 120, totalPnl: 20 },
  holdings: [{ 代码: '002841', 持仓: 2, 成本: 10, 现价: 11, 浮盈: 2 }] })
const state = () => ({ revision: 2, holdings: { account_cash: 100, account_total: 119,
  positions: { '002841': { qty: 2, cost: 10 } } } })

test('holding profit deducts remaining entry costs while preserving the signal cost', () => {
  const database: any = state()
  database.holdings.positions['002841'].buy_fees_remaining = .5
  const result = mergeDatabaseHoldings(raw() as any, database)
  assert.equal(result.holdings[0].成本, 10)
  assert.equal(result.holdings[0].浮盈, 1.5)
  assert.equal(result.holdings[0].买入剩余费用, .5)
})

test('matching holdings retain the coherent quote-based account summary', () => {
  const result = mergeDatabaseHoldings(raw() as any, state())
  assert.equal(result.account.accountTotal, 120)
  assert.equal(result.account.totalPnl, 20)
})

test('database-only startup positions are pinned to the actual holding section', () => {
  const result = mergeDatabaseHoldings({ account: {}, holdings: [] } as any, state())
  assert.equal(result.holdings[0].置顶, true)
  assert.equal(result.holdings[0].持仓, 2)
  assert.equal(result.holdings[0].现价, undefined)
  assert.equal(result.account.totalPnl, null)
})

test('new holdings do not retain the old account return or holding status', () => {
  const database = state()
  database.holdings.positions['002841'].qty = 0
  const result = mergeDatabaseHoldings(raw() as any, database)
  assert.equal(result.holdings[0].持仓, 0)
  assert.equal(result.holdings[0].持仓状态, '空仓')
  assert.equal(result.holdings[0].浮盈, null)
  assert.equal(result.account.totalPnl, null)
})

test('an older database poll cannot revert a newer WebSocket snapshot', () => {
  const snapshot = { ...raw(), paperRevision: 3 }
  assert.equal(mergeDatabaseHoldings(snapshot as any, state()), snapshot)
})

test('closed-row realized cost survives while missing quotes never invent returns', () => {
  const database = state()
  database.holdings.positions['002841'].qty = 0
  const closed = { ...raw(), holdings: [{ 代码: '002841', 持仓: 0, 成本: 10, 已实现: true, 浮盈: 2 }] }
  assert.equal(mergeDatabaseHoldings(closed as any, database).holdings[0].成本, 10)
  const noQuote = { ...raw(), holdings: [{ 代码: '002841', 持仓: 2, 成本: 10, 现价: 0 }] }
  assert.equal(mergeDatabaseHoldings(noQuote as any, state()).holdings[0].浮盈, null)
})

test('a newer ledger revision invalidates old cycle profit even if cost and quantity match', () => {
  const input = { ...raw(), paperRevision: 1, holdings: [{ 代码: '002841', 持仓: 2, 成本: 10, 现价: 11,
    综合单笔来源: 'database_delivery_cycle_with_adjustments', 综合单笔收入: 99, 综合单笔成本额: 100 }] }
  const result = mergeDatabaseHoldings(input as any, state())
  assert.equal(result.holdings[0].综合单笔收入, null)
  assert.equal(result.holdings[0].综合单笔来源, null)
})

test('database merging rolls unchanged holdings to overnight status and labels new rows by session', () => {
  const database = state()
  Object.assign(database.holdings.positions['002841'], { buy_time: '2026-10-21 09:47:45' })
  const snapshot = { ...raw(), clock: '2026-10-22 09:25:00',
    holdings: [{ ...raw().holdings[0], 持仓状态: '已经买入', 交易日: '2026-10-21' }] }
  assert.equal(mergeDatabaseHoldings(snapshot as any, database).holdings[0].持仓状态, '持有')
  assert.equal(mergeDatabaseHoldings(snapshot as any, database).holdings[0].交易日, '2026-10-22')
  const boot = mergeDatabaseHoldings({ account: {}, holdings: [], clock: snapshot.clock } as any, database)
  assert.equal(boot.holdings[0].持仓状态, '持有')
  assert.equal(boot.holdings[0].交易日, '2026-10-22')
  snapshot.clock = '2026-10-21 10:00:00'
  assert.equal(mergeDatabaseHoldings(snapshot as any, database).holdings[0].持仓状态, '已经买入')
})

test('a replacement cycle does not inherit an old pending sell status with matching shares and cost', () => {
  const database = state()
  Object.assign(database.holdings.positions['002841'], { buy_time: '2026-10-22 09:47:45' })
  const snapshot = { ...raw(), clock: '2026-10-22 10:00:00', holdings: [{ ...raw().holdings[0],
    买入时间: '2026-10-21 10:00:00', 持仓状态: '待卖出' }] }
  assert.equal(mergeDatabaseHoldings(snapshot as any, database).holdings[0].持仓状态, '已经买入')
})

test('today quota and closed signal times come from confirmed database trades, not stale snapshot defaults', () => {
  const database: any = state()
  database.holdings.positions['002841'].qty = 0
  database.trades = [{ code: '001282', side: 'buy', session: '2026-10-22' },
    { code: '002866', side: 'buy', session: '2026-10-22' },
    { code: '001282', side: 'sell', session: '2026-10-22' },
    { code: '000070', side: 'buy', session: '2026-10-22', reset_archived: true }]
  database.holdings.realized_today = { '002841': { session: '2026-10-22', signal_time: '2026-10-22 09:30:10' } }
  const snapshot = { ...raw(), clock: '2026-10-22 09:40:00', slotMeta: { buysToday: 0, maxNewSymbolsPerSession: 2 },
    holdings: [{ 代码: '002841', 持仓: 0, 已实现: true, 信号时间: '2026-10-21 10:18:27' }] }
  const result = mergeDatabaseHoldings(snapshot as any, database)
  assert.equal(result.slotMeta?.buysToday, 2)
  assert.equal(result.slotMeta?.buysLeft, 0)
  assert.equal(result.holdings[0].信号时间, '2026-10-22 09:30:10')
})
