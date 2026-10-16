import test from 'node:test'
import assert from 'node:assert/strict'
import { stabilizeRows } from '../utils/stableRowOrder.ts'

test('later distance changes do not reshuffle cards that are already on screen', () => {
  const first = stabilizeRows([], [{ 代码: '600330' }, { 代码: '600552' }], (r) => r.代码)
  const next = stabilizeRows(first.map((r) => r.代码), [{ 代码: '600552' }, { 代码: '600330' }], (r) => r.代码)
  assert.deepEqual(next.map((r) => r.代码), ['600330', '600552'])
})

test('a new code is appended and a removed code leaves the others in place', () => {
  const next = stabilizeRows(['600330', '600552'], [{ 代码: '002636' }, { 代码: '600552' }], (r) => r.代码)
  assert.deepEqual(next.map((r) => r.代码), ['600552', '002636'])
})
