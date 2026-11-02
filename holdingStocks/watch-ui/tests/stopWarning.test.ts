import test from 'node:test'
import assert from 'node:assert/strict'
import { sellProtection, stopWarningDistance } from '../utils/stopWarning.ts'

test('warns above the protection line through the inclusive 1% boundary', () => {
  assert.ok(stopWarningDistance({ 持仓: 100, 现价: 100.5, 卖出侧价: 100 })! > 0)
  assert.ok(stopWarningDistance({ 持仓: 100, 现价: 101, 卖出侧价: 100 }) != null)
  for (const price of [100, 99, 101.01]) {
    assert.equal(stopWarningDistance({ 持仓: 100, 现价: price, 卖出侧价: 100 }), null)
  }
})
test('excludes closed positions and invalid quotes, and prefers the explicit protection price', () => {
  for (const row of [
    { 持仓: 0, 现价: 100.5, 卖出侧价: 100 },
    { 持仓: 100, 现价: null, 卖出侧价: 100 },
    { 持仓: 100, 现价: 100.5, 卖出侧价: 0 },
    { 持仓: 100, 现价: NaN, 卖出侧价: 100 },
  ]) assert.equal(stopWarningDistance(row), null)
  assert.ok(stopWarningDistance({ 持仓: 100, 现价: 100.5, 回落止损价: 100, 卖出侧价: 90 }) != null)
})

test('highest applicable sell line wins and retains its reason', () => {
  const row = { 持仓: 100, 现价: 101.5, 回落止损价: 90, 卖出侧价: 101, 止损: 100 }
  assert.deepEqual(sellProtection(row), { price: 101, reason: '跌破卖出侧保护线' })
  assert.ok(stopWarningDistance(row) != null)
  assert.equal(sellProtection({ ...row, 持仓: 0, 已实现: true })?.price, 90)
})

test('flat candidates retain sell-side display without receiving a position warning', () => {
  const row = { 持仓: 0, 持仓状态: '空仓', 现价: 100.5, 卖出侧价: 100 }
  assert.equal(sellProtection(row)?.price, 100)
  assert.equal(stopWarningDistance(row), null)
})
