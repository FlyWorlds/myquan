<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtSignedMoney, fmtSignedPct } from '~/utils/format'

const props = defineProps<{ row: HoldingRow; block?: boolean }>()

const closed = computed(() => {
  const qty = Number(props.row.持仓 || 0)
  const pos = String(props.row.持仓状态 || '')
  return (
    Boolean(props.row.已实现) ||
    Boolean(props.row.槽位留痕) ||
    (qty <= 0 &&
      (pos === '已平仓' ||
        pos === '已触止损平仓' ||
        pos === '已止损' ||
        pos === '当日禁买'))
  )
})

const dayPnl = computed(() => {
  const v = props.row.当日盈亏
  if (v == null || Number.isNaN(Number(v))) return null
  return Number(v)
})

const amount = computed(() => {
  if (closed.value && dayPnl.value != null) return dayPnl.value
  const v = props.row.浮盈
  if (v == null || Number.isNaN(Number(v))) return null
  return Number(v)
})

const pct = computed(() => {
  if (closed.value && dayPnl.value != null) {
    const v = props.row['当日盈亏%']
    return v == null || Number.isNaN(Number(v)) ? null : Number(v)
  }
  const v = props.row['浮盈%']
  return v == null || Number.isNaN(Number(v)) ? null : Number(v)
})

const visible = computed(() => amount.value != null)

const label = computed(() => {
  if (closed.value) {
    const v = dayPnl.value
    if (v != null && v < 0) return '当日浮亏'
    if (v != null && v > 0) return '当日浮盈'
    return '当日'
  }
  if (props.row.已实现) return '结算'
  if (props.row.盈亏状态 === '结算') return '结算'
  return '浮盈'
})

const title = computed(() => {
  const note = props.row.盈亏说明
  if (typeof note === 'string' && note) return note
    if (closed.value) {
    const qty = props.row.卖出数量 ?? props.row.持仓
    const openPx = props.row.开盘
    const fill = props.row.成交价
    if (openPx != null && fill != null && qty != null) {
      return `今开 ${openPx} → 平仓 ${fill} × ${qty} 股，锁定不再随现价`
    }
    if (fill != null) return `已平仓成交价 ${fill}，相对今开锁定`
    return '已平仓·今开至平仓价锁定'
  }
  if (props.row.已实现) return '按卖出成交价锁定'
  const cost = props.row.成本
  const qty = props.row.持仓
  if (cost != null && qty != null && Number(qty) > 0) {
    return `买入 ${cost} × ${qty} 股，现价动态`
  }
  return '相对策略买入价'
})
</script>

<template>
  <span
    v-if="visible"
    class="text-sm font-semibold"
    :class="block ? 'mt-0.5 block' : 'ml-1.5 inline-flex flex-wrap items-baseline gap-x-1'"
    :title="title"
  >
    <span class="text-[10px] font-normal text-ui-text-3">{{ label }}</span>
    <ChgText :chg="amount">{{ fmtSignedMoney(amount) }}</ChgText>
    <ChgText v-if="pct != null" :chg="pct" class="text-xs font-normal">
      ({{ fmtSignedPct(pct) }})
    </ChgText>
  </span>
</template>
