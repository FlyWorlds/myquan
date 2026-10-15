import test from 'node:test'
import assert from 'node:assert/strict'
import { strategyBookSingleReturn } from '../utils/strategyBookReturn.ts'

test('open strategy single return is the entry-to-mark price difference, not the weighted cycle', () => {
  assert.equal(strategyBookSingleReturn({ 策略虚拟股数: 600, '单笔收入%': 20, '综合单笔收入%': 16 }), 20)
})
test('closed strategy single return freezes the complete cycle including partial sells', () => {
  assert.equal(strategyBookSingleReturn({ 策略虚拟股数: 0, '单笔收入%': 99, '综合单笔收入%': 16 }), 16)
})
test('missing strategy return is not zero', () => {
  assert.equal(strategyBookSingleReturn({ 策略虚拟股数: 600, '综合单笔收入%': 16 }), null)
})
