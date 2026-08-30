<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtSignedMoney, fmtSignedPct } from '~/utils/format'

const props = defineProps<{ row: HoldingRow; block?: boolean }>()

const visible = computed(() => props.row.浮盈 != null && !Number.isNaN(Number(props.row.浮盈)))

const label = computed(() => {
  if (props.row.已实现) return '结算'
  if (props.row.盈亏状态 === '结算') return '结算'
  return '浮盈'
})

const title = computed(() => {
  const note = props.row.盈亏说明
  if (typeof note === 'string' && note) return note
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
    <ChgText :chg="row.浮盈">{{ fmtSignedMoney(row.浮盈) }}</ChgText>
    <ChgText v-if="row['浮盈%'] != null" :chg="row['浮盈%']" class="text-xs font-normal">
      ({{ fmtSignedPct(row['浮盈%']) }})
    </ChgText>
  </span>
</template>
