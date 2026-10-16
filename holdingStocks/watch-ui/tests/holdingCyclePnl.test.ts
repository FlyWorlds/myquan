import test from 'node:test'
import assert from 'node:assert/strict'
import { holdingCyclePnl } from '../utils/holdingCyclePnl.ts'
const row = (extra = {}) => ({ 持仓: 600, 成本: 10, 现价: 11,
  综合单笔来源: 'database_delivery_cycle_with_adjustments', 综合单笔收入: 1400,
  综合单笔成本额: 10000, 综合单笔卖出数量: 400, 综合单笔持仓数量: 600, ...extra })
test('buy 1000 at 10, sell 400 at 12, mark 600 at 11 gives 1400 and 14%', () => {
  assert.deepEqual(holdingCyclePnl(row()), { amount: 1400, pct: 14, realized: 800, unrealized: 600, soldQty: 400 })
})
test('multiple sales remain in total even when the remaining position loses money', () => {
  const result = holdingCyclePnl(row({ 持仓: 300, 现价: 9, 综合单笔持仓数量: 300, 综合单笔卖出数量: 700, 综合单笔收入: 800 }))!
  assert.equal(result.realized, 1100)
  assert.equal(result.unrealized, -300)
  assert.equal(result.pct, 8)
})
test('fully closed cycle requires no live quote and freezes all realized PnL', () => {
  assert.deepEqual(holdingCyclePnl(row({ 持仓: 0, 现价: null, 成本: null, 综合单笔持仓数量: 0, 综合单笔卖出数量: 1000 })),
    { amount: 1400, pct: 14, realized: 1400, unrealized: 0, soldQty: 1000 })
})
test('no reduction measures the entire original purchase against the current quote', () => {
  assert.deepEqual(holdingCyclePnl(row({ 持仓: 1000, 综合单笔持仓数量: 1000, 综合单笔卖出数量: 0, 综合单笔收入: 1000 })),
    { amount: 1000, pct: 10, realized: 0, unrealized: 1000, soldQty: 0 })
})
test('strategy results, incomplete history, stale quantities, missing quote never masquerade as holding profit', () => {
  for (const extra of [{ 综合单笔来源: 'strategy_simulator_cycle' }, { 综合单笔收入: null },
    { 综合单笔持仓数量: 1000 }, { 现价: null }, { 综合单笔卖出数量: null }]) assert.equal(holdingCyclePnl(row(extra)), null)
})
