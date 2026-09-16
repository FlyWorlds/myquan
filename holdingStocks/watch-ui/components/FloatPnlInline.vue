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
      (pos === '今日平仓' ||
        pos === '已平仓' ||
        pos === '已触止损平仓' ||
        pos === '已止损' ||
        pos === '当日禁买'))
  )
})

const boughtToday = computed(() => {
  const buy = String(props.row.买入时间 || '').slice(0, 10)
  const sess = String(props.row.交易日 || '').slice(0, 10)
  return Boolean(buy && sess && buy === sess)
})

/** 后端当日盈亏；跨日缺失时昨仓按昨收本地补算，绝不回退到成本浮盈。 */
const dayPnl = computed(() => {
  const v = props.row.当日盈亏
  if (v != null && !Number.isNaN(Number(v))) return Number(v)
  const qty = Number(props.row.持仓 || 0)
  if (qty <= 0) return null
  const last = Number(props.row.现价)
  if (!Number.isFinite(last) || last <= 0) return null
  if (boughtToday.value) {
    const cost = Number(props.row.成本)
    if (!Number.isFinite(cost) || cost <= 0) return null
    return Math.round((last - cost) * qty * 100) / 100
  }
  const prev = Number(props.row.昨收)
  if (!Number.isFinite(prev) || prev <= 0) return null
  return Math.round((last - prev) * qty * 100) / 100
})

const amount = computed(() => dayPnl.value)

const pct = computed(() => {
  const v = props.row['当日盈亏%']
  if (v != null && !Number.isNaN(Number(v))) return Number(v)
  const qty = Number(props.row.持仓 || 0)
  if (qty <= 0 || dayPnl.value == null) return null
  const last = Number(props.row.现价)
  if (!Number.isFinite(last) || last <= 0) return null
  if (boughtToday.value) {
    const cost = Number(props.row.成本)
    if (!Number.isFinite(cost) || cost <= 0) return null
    return Math.round((last / cost - 1) * 10000) / 100
  }
  const prev = Number(props.row.昨收)
  if (!Number.isFinite(prev) || prev <= 0) return null
  return Math.round((last / prev - 1) * 10000) / 100
})

const visible = computed(() => amount.value != null)

const label = computed(() => {
  const v = amount.value
  if (v != null && v < 0) return '今日浮亏'
  if (v != null && v > 0) return '今日浮盈'
  return '今日盈亏'
})

const title = computed(() => {
  const note = props.row.盈亏说明
  if (typeof note === 'string' && note) return note
  if (closed.value) {
    const qty = props.row.卖出数量 ?? props.row.持仓
    const fill = props.row.成交价
    if (boughtToday.value) {
      const cost = props.row.成本
      if (cost != null && fill != null && qty != null) {
        return `今买 ${cost} → 平仓 ${fill} × ${qty} 股`
      }
    }
    const prev = props.row.昨收
    if (prev != null && fill != null && qty != null) {
      return `昨收 ${prev} → 平仓 ${fill} × ${qty} 股，锁定不再随现价`
    }
    if (fill != null) return `今日平仓成交价 ${fill}`
    return '今日平仓锁定'
  }
  if (boughtToday.value) {
    const cost = props.row.成本
    const qty = props.row.持仓
    if (cost != null && qty != null) return `今买 ${cost} × ${qty} 股，现价相对买入价`
  }
  const prev = props.row.昨收
  const qty = props.row.持仓
  if (prev != null && qty != null) return `昨收 ${prev} × ${qty} 股，现价相对昨收`
  return '今日盈亏：今买相对买入价，昨仓相对昨收'
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
