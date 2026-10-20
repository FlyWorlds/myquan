import test from 'node:test'
import assert from 'node:assert/strict'
import { orderTouchBuys, stickAlertRows } from '../utils/alertBoard.ts'

test('a stock that leaves the warning line stays in place and turns outside', () => {
  const first = stickAlertRows(
    [],
    [{ 代码: '600330', 买点: 8.32 }, { 代码: '600552', 买点: 10 }, { 代码: '002636' }, { 代码: '001266' }],
    [],
  )
  const next = stickAlertRows(first, [{ 代码: '600552', 买点: 10.1 }, { 代码: '001266' }], [])
  assert.deepEqual(
    next.map((row) => [row.代码, row.预警线内, row.买点]),
    [
      ['600330', false, 8.32],
      ['600552', true, 10.1],
      ['002636', false, undefined],
      ['001266', true, undefined],
    ],
  )
})

test('touch buys sort by trigger time and other alerts stay behind them', () => {
  const rows = orderTouchBuys([
    { 代码: '600552', 预警: '将买入' },
    { 代码: '001266', 已触买: '是', 预警: '已触买·当日新增额度已满', 信号时间: '10:02:00' },
    { 代码: '600330', 已触买: '是', 买信号时间: '09:31:00' },
    { 代码: '002636', 预警: '将买入' },
  ])
  assert.deepEqual(rows.map((row) => row.代码), ['600330', '001266', '600552', '002636'])
})

test('a touch buy stays fixed inside after the price leaves the warning line', () => {
  const first = stickAlertRows([], [{ 代码: '001266', 已触买: '是', 买点: 8.32 }], [])
  const next = stickAlertRows(first, [], [])
  assert.equal(next[0].代码, '001266')
  assert.equal(next[0].预警线内, true)
  assert.equal(next[0].已触买, '是')
})

test('a newly entered stock is appended and a filled position leaves the board', () => {
  const next = stickAlertRows(
    [{ 代码: '600330', 预警线内: true }, { 代码: '600552', 预警线内: true }],
    [{ 代码: '002636', 买点: 7 }],
    ['600552'],
  )
  assert.deepEqual(next.map((row) => row.代码), ['600330', '002636'])
  assert.equal(next[0].预警线内, false)
  assert.equal(next[1].预警线内, true)
})

import { createAlertPriceOrder } from '../utils/alertBoard.ts'

test('price values refresh immediately while positions move no more often than every 10 seconds', () => {
  const order = createAlertPriceOrder()
  const rows = [{ 代码: 'A', 现价: 9.9, 买点: 10 }, { 代码: 'B', 现价: 9.5, 买点: 10 }]
  assert.deepEqual(order.update(rows, 0).map(r => r.代码), ['A', 'B'])
  const updated = [{ ...rows[0], 现价: 9 }, { ...rows[1], 现价: 9.99 }]
  const early = order.update(updated, 9999)
  assert.deepEqual(early.map(r => r.代码), ['A', 'B'])
  assert.equal(early[1].现价, 9.99)
  assert.deepEqual(order.update(updated, 10000).map(r => r.代码), ['B', 'A'])
})

test('new alerts enter instantly without triggering a price reshuffle of existing alerts', () => {
  const order = createAlertPriceOrder()
  order.update([{ 代码: 'A', 现价: 9.9, 买点: 10 }, { 代码: 'B', 现价: 9.5, 买点: 10 }], 0)
  const next = order.update([{ 代码: 'B', 现价: 9.99, 买点: 10 }, { 代码: 'A', 现价: 9, 买点: 10 },
    { 代码: 'C', 现价: 9.999, 买点: 10 }], 1000)
  assert.deepEqual(next.map(r => r.代码), ['A', 'B', 'C'])
  assert.equal(order.remaining(1000), 9000)
  assert.deepEqual(order.update(next, 10000).map(r => r.代码), ['C', 'B', 'A'])
})

test('continuous quotes do not postpone sorting and occupied stocks leave immediately', () => {
  const order = createAlertPriceOrder()
  order.update([{ 代码: 'A', 现价: 9.9, 买点: 10 }, { 代码: 'B', 现价: 9, 买点: 10 }], 0)
  const changed = [{ 代码: 'A', 现价: 9, 买点: 10 }, { 代码: 'B', 现价: 9.99, 买点: 10 }]
  for (let now = 1000; now < 10000; now += 1000) order.update(changed, now)
  assert.deepEqual(order.update(changed, 10000).map(r => r.代码), ['B', 'A'])
  assert.deepEqual(order.update([changed[0]], 10001).map(r => r.代码), ['A'])
})
