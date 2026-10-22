import test from 'node:test'
import assert from 'node:assert/strict'
import { holdingStatus, holdingT1Locked } from '../utils/holdingStatus.ts'
import { resolveSignalVisual, collectLegendIds } from '../composables/useSignalVisual.ts'

const tiantong = { 持仓: 2500, 可用: 2500, 买入时间: '2026-10-21 09:47:45',
  交易日: '2026-10-22', 持仓状态: '已经买入', 预警: '' }

test('overnight holding badge rolls over even with a stale bought status or alert', () => {
  for (const alert of ['', '已经买入', '持有']) {
    const row = { ...tiantong, 预警: alert }
    assert.equal(holdingStatus(row), '持有')
    assert.equal(resolveSignalVisual(row).badgeText, '持有')
    assert.equal(resolveSignalVisual(row).tier, 'hold')
  }
})

test('same-day purchases, T+1, pending sells and closed positions remain distinct', () => {
  const bought = { ...tiantong, 交易日: '2026-10-21', 可用: 0 }
  assert.equal(holdingStatus(bought), '已经买入')
  assert.equal(holdingT1Locked(bought), true)
  assert.equal(resolveSignalVisual({ ...bought, 已触止损: '是', 预警: '持有·T+1·止损已记' }).badgeText,
    '持有·T+1·止损已记')
  assert.equal(collectLegendIds({ ...bought, 已触止损: '是' }).includes('trigger-sell'), false)
  const sell = { ...tiantong, 持仓状态: '待卖出', 预警: '低开峰值回落·待开盘卖出' }
  assert.equal(holdingStatus(sell), '待卖出')
  assert.equal(resolveSignalVisual(sell).badgeText, sell.预警)
  assert.equal(holdingStatus({ 持仓: 0, 持仓状态: '今日平仓' }), '今日平仓')
})

test('unknown purchase date is holding and never implies a same-day purchase or T+1', () => {
  assert.equal(holdingStatus({ 持仓: 100 }), '持有')
  assert.equal(holdingT1Locked({ ...tiantong, 可用: null }), false)
  assert.equal(holdingT1Locked({ ...tiantong, 可用: 0 }), false)
})
