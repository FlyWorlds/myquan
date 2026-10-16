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
