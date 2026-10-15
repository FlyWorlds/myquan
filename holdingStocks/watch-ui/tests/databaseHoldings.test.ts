import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeDatabaseHoldings } from '../utils/databaseHoldings.ts'

const raw = () => ({ account: { availableCash: 100, accountTotal: 120, totalPnl: 20 },
  holdings: [{ 代码: '002841', 持仓: 2, 成本: 10, 现价: 11, 浮盈: 2 }] })
const state = () => ({ revision: 2, holdings: { account_cash: 100, account_total: 119,
  positions: { '002841': { qty: 2, cost: 10 } } } })

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
