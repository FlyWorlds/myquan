import test from 'node:test'
import assert from 'node:assert/strict'
import { selectionRows } from '../utils/selectionRows.ts'

test('loading a different saved pool immediately replaces stale snapshot membership', () => {
  const rows = selectionRows({ items: [{ code: '600002', name: '新股票' }] } as any,
    [{ 代码: '600001', 名称: '旧股票', 现价: 12 }])
  assert.deepEqual(rows.map(r => r.代码), ['600002'])
  assert.equal(rows[0].名称, '新股票')
  assert.equal(rows[0].现价, null)
})
test('matching live rows survive while missing members remain visible in saved order', () => {
  const live = { 代码: '600002', 现价: 15 }
  const rows = selectionRows({ items: [{ code: '600003' }, { code: '600002' }] } as any,
    [{ 代码: '600001' }, live])
  assert.deepEqual(rows.map(r => r.代码), ['600003', '600002'])
  assert.equal(rows[1], live)
})
test('an explicitly empty selection cannot fall back to the previous pool', () => {
  assert.deepEqual(selectionRows({ items: [] } as any, [{ 代码: '600001' }]), [])
})
