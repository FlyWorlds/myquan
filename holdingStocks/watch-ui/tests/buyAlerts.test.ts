import test from 'node:test'
import assert from 'node:assert/strict'
import { otherAlertRows } from '../utils/buyAlerts.ts'
import { sellAlerts } from '../utils/sellAlerts.ts'
import { alertType } from '../utils/alertType.ts'

test('sell and rebound buy coexist; only the identical buy event is deduplicated', () => {
  const buy = { 代码: '600330', 持仓: 0, 已触买: '是', 信号因子: 'factor33' }
  const closed = { 代码: '600330', 持仓: 0, 已实现: true, 槽位留痕: true }
  assert.equal(sellAlerts([], [closed]).length, 1)
  assert.equal(otherAlertRows([buy, closed], []).length, 1)
  assert.equal(otherAlertRows([buy, closed], [buy]).length, 0)
  assert.equal(otherAlertRows([{ ...buy, 信号因子: 'factor26' }], [buy]).length, 1)
})
test('alert types distinguish breakout, rebound and peak pullback', () => {
  assert.equal(alertType({ 信号因子: 'factor33' }, 'buy'), '探底回升')
  assert.equal(alertType({ 信号因子: 'factor26' }, 'buy'), '开盘突破')
  assert.equal(alertType({ 卖出原因: '跌破隔夜峰值回落保护线' }, 'sell'), '阶段回落（峰值）')
})
