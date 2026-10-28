import test from 'node:test'
import assert from 'node:assert/strict'
import { aggregateReturns } from '../utils/returnsCalendar.ts'

test('missing daily rate does not hide available monthly compounded return', () => {
  const result = aggregateReturns([
    { day_pnl: 10, day_pnl_pct: 10 },
    { day_pnl: 5, day_pnl_pct: null },
    { day_pnl: -11, day_pnl_pct: -10 },
  ])
  assert.ok(Math.abs(result.rate! - (-1)) < 1e-10)
  assert.equal(result.amount, 4)
  assert.equal(result.partial, true)
})

test('no valid rates remain missing, while a recorded zero is valid', () => {
  for (const rows of [[], [{ day_pnl_pct: null }], [{ day_pnl_pct: '' }, { day_pnl_pct: 'bad' }]]) {
    assert.equal(aggregateReturns(rows).rate, null)
    assert.equal(aggregateReturns(rows).partial, false)
  }
  assert.deepEqual(aggregateReturns([{ day_pnl: '0', day_pnl_pct: '0' }]), { amount: 0, rate: 0, partial: false })
})
