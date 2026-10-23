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

import { createAlertPriceOrder, createHoldingPriceOrder, createStatusDebouncer } from '../utils/alertBoard.ts'

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

test('paper holdings sort by buy time descending (most recently bought first) with 10s sort throttle and 3s status debounce', () => {
  const order = createHoldingPriceOrder(10_000, 3_000)
  const initial = [
    { 代码: '600552', 现价: 15.2, 买入时间: '2026-10-20 09:35:00', 持仓状态: '已经买入', 预警: '持有' },
    { 代码: '000049', 现价: 22.1, 买入时间: '2026-10-21 09:42:00', 持仓状态: '已经买入', 预警: '持有' },
  ]
  // At t=0: sorted by buy time descending -> 000049 (Oct 21) before 600552 (Oct 20)
  assert.deepEqual(order.update(initial, 0).map(r => r.代码), ['000049', '600552'])

  const withNewBuy = [
    { 代码: '600552', 现价: 15.1, 买入时间: '2026-10-20 09:35:00', 持仓状态: '待卖出', 预警: '将止损' },
    { 代码: '000049', 现价: 22.5, 买入时间: '2026-10-21 09:42:00', 持仓状态: '已经买入', 预警: '持有' },
    { 代码: '002636', 现价: 8.8, 买入时间: '2026-10-21 10:15:00', 持仓状态: '已经买入', 预警: '持有' },
  ]
  // Within 3s/10s window: existing order stays ['000049', '600552'], new buy appended, status debounced
  const before3s = order.update(withNewBuy, 1000)
  assert.deepEqual(before3s.map(r => r.代码), ['000049', '600552', '002636'])
  assert.equal(before3s[1].持仓状态, '已经买入')

  // After 3s (at 4000ms): status of 600552 commits to '待卖出'
  const after3s = order.update(withNewBuy, 4000)
  assert.equal(after3s[1].持仓状态, '待卖出')

  // After 10s (at 10000ms): re-sorted by buy time descending -> 002636 (10:15) -> 000049 (09:42) -> 600552 (Oct 20)
  const after10s = order.update(withNewBuy, 10_000)
  assert.deepEqual(after10s.map(r => r.代码), ['002636', '000049', '600552'])
})

test('status debouncer suppresses transient <3s status flickers while passing immediate fills', () => {
  const debouncer = createStatusDebouncer(3_000)
  const t0 = debouncer.update([{ 代码: '600330', 持仓状态: '待买入', 预警: '将买入', 预警线内: true, 现价: 8.3 }], 0)
  assert.equal(t0[0].预警线内, true)

  // Flickers outside at t=500ms
  const t500 = debouncer.update([{ 代码: '600330', 持仓状态: '空仓', 预警: '空仓', 预警线内: false, 现价: 8.25 }], 500)
  assert.equal(t500[0].预警线内, true)
  assert.equal(t500[0].现价, 8.25)
  assert.equal(debouncer.remaining(500), 3000)

  // Bounces back inside at t=2000ms -> pending status cancelled
  const t2000 = debouncer.update([{ 代码: '600330', 持仓状态: '待买入', 预警: '将买入', 预警线内: true, 现价: 8.31 }], 2000)
  assert.equal(t2000[0].预警线内, true)
  assert.equal(debouncer.remaining(2000), 0)
})



import { orderAlertCards } from '../utils/alertBoard.ts'

test('filled holdings stay on the alert board and pin above unfilled touch buys immediately', () => {
  const before = [{ 代码: '002253', 持仓: 0, 已触买: '是', 买点: 8.28 }]
  const latest = stickAlertRows(before, [
    { 代码: 'OTHER', 持仓: 0, 已触买: '是', 买入时间: '', 买点: 10 },
    { 代码: '002253', 持仓: 6800, 已触买: '是', 买入时间: '2026-10-23 09:41:17', 买点: 8.28 },
  ], [])
  const ordered = orderAlertCards(latest)
  assert.deepEqual(ordered.map(row => row.代码), ['002253', 'OTHER'])
  assert.equal(ordered[0].持仓, 6800)
  assert.equal(ordered[0].预警线内, true)
  assert.equal(ordered.filter(row => row.代码 === '002253').length, 1)
})

test('held alerts sort newest buy first and a closed holding leaves the board', () => {
  const rows = [
    { 代码: 'OLD', 持仓: 100, 买入时间: '2026-10-22 10:00:00' },
    { 代码: 'ALERT', 持仓: 0 },
    { 代码: 'NEW', 持仓: 200, 买入时间: '2026-10-23 10:00:00' },
  ]
  assert.deepEqual(orderAlertCards(rows).map(row => row.代码), ['NEW', 'OLD', 'ALERT'])
  const next = stickAlertRows(rows, rows.slice(0, 2), ['NEW'])
  assert.deepEqual(orderAlertCards(next).map(row => row.代码), ['OLD', 'ALERT'])
})
