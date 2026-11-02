import test from 'node:test'
import assert from 'node:assert/strict'
import { sellAlerts } from '../utils/sellAlerts.ts'

test('opening exits remain visible after inventory becomes zero, including after rebuy', () => {
  const closed = { 代码: '600330', 持仓: 0, 已实现: true, 成交价: 18.48, 回落止损价: 18.86 }
  assert.equal(sellAlerts([], [closed])[0].state, '触卖')
  assert.equal(sellAlerts([{ 代码: '600330', 持仓: 100, 现价: 20, 卖出侧价: 18 }], [closed]).length, 1)
})
test('price near the line warns and an opening gap below it triggers without needing a prior warning', () => {
  assert.equal(sellAlerts([{ 持仓: 100, 现价: 100.5, 卖出侧价: 100 }], [])[0].state, '将卖出')
  assert.equal(sellAlerts([{ 持仓: 100, 现价: 98, 卖出侧价: 100 }], [])[0].state, '触卖')
  assert.equal(sellAlerts([{ 持仓: 100, 现价: 102, 卖出侧价: 100 }], []).length, 0)
})
