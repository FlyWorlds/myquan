<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, fmtSignedPct } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'

const props = defineProps<{ row: HoldingRow }>()

const pdg = props.row['价位小数'] ?? 2
const visual = computed(() => resolveSignalVisual(props.row))

const posStatus = computed(() => String(props.row.持仓状态 || '').trim() || '-')
const pinned = computed(
  () => Boolean(props.row.置顶) && Number(props.row.持仓) > 0,
)
const slotTrace = computed(
  () =>
    Boolean(props.row.槽位留痕) ||
    (Number(props.row.持仓) <= 0 &&
      (Boolean(props.row.已实现) ||
        posStatus.value === '已平仓' ||
        posStatus.value === '已触止损平仓' ||
        posStatus.value === '已止损')),
)

const posChipStyle = computed(() => {
  const s = posStatus.value
  if (s === '已经买入' || s === '持有' || s === '持有·T+1') {
    return {
      color: 'var(--watch-hold)',
      borderColor: 'color-mix(in srgb, var(--watch-hold) 45%, transparent)',
      background: 'color-mix(in srgb, var(--watch-hold) 14%, transparent)',
    }
  }
  if (s === '待卖出') {
    return {
      color: 'var(--watch-down)',
      borderColor: 'color-mix(in srgb, var(--watch-down) 45%, transparent)',
      background: 'color-mix(in srgb, var(--watch-down) 12%, transparent)',
    }
  }
  if (s === '已平仓' || s === '已触止损平仓' || s === '已止损' || s === '当日禁买') {
    return {
      color: 'var(--ui-text-2)',
      borderColor: 'var(--ui-hairline)',
      background: 'color-mix(in srgb, var(--ui-text-2) 10%, transparent)',
    }
  }
  if (s === '待买入') {
    return {
      color: 'var(--watch-up)',
      borderColor: 'color-mix(in srgb, var(--watch-up) 45%, transparent)',
      background: 'color-mix(in srgb, var(--watch-up) 12%, transparent)',
    }
  }
  if (s === '策略持有') {
    return {
      color: 'var(--watch-hold-paper)',
      borderColor: 'color-mix(in srgb, var(--watch-hold-paper) 40%, transparent)',
      background: 'color-mix(in srgb, var(--watch-hold-paper) 12%, transparent)',
    }
  }
  return {
    color: 'var(--ui-text-2)',
    borderColor: 'var(--ui-hairline)',
    background: 'transparent',
  }
})

const cardClass = computed(() => {
  const map: Record<string, string> = {
    'trigger-buy': 'signal-trigger-buy border-up/50',
    'warn-buy': 'signal-warn-buy border-up/40',
    'trigger-sell': 'signal-trigger-sell border-down/50',
    'warn-sell': 'signal-warn-sell border-down/40',
    hold: 'signal-hold-real border-hold/40',
    'paper-hold': 'signal-hold-paper border-hold-paper/40',
    'ban-buy': 'signal-ban-buy border-ui-hairline',
    flat: 'signal-flat border-ui-hairline',
  }
  const tier = visual.value.tier
  if (tier && map[tier]) return map[tier]
  if (Number(props.row.持仓) > 0) return 'signal-hold-real border-hold/40'
  return 'signal-flat border-ui-hairline'
})
</script>

<template>
  <article class="card overflow-hidden p-0 transition" :class="cardClass">
    <div class="p-3">
      <header class="mb-2 flex items-start justify-between gap-2">
        <div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-accent">{{ row.市场 }}</span>
            <span
              v-if="pinned"
              class="rounded-full px-2 py-0.5 text-xs font-medium"
              style="color: var(--watch-hold); border: 1px solid color-mix(in srgb, var(--watch-hold) 50%, transparent); background: color-mix(in srgb, var(--watch-hold) 16%, transparent)"
            >置顶·三槽</span>
            <span
              v-else-if="slotTrace"
              class="rounded-full px-2 py-0.5 text-xs font-medium text-ui-text-2"
              style="border: 1px solid var(--ui-hairline); background: color-mix(in srgb, var(--ui-text-2) 8%, transparent)"
            >已平仓·不占槽</span>
            <span
              class="rounded-full border px-2 py-0.5 text-xs font-medium"
              :style="posChipStyle"
            >{{ posStatus }}</span>
          </div>
          <h2 class="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-base font-bold">
            <a :href="baiduStockUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="sensitive hover:text-accent hover:underline">{{ row.名称 }}</a>
            <b class="sensitive tabular-nums">{{ fmtNum(row.现价, pdg) }}</b>
            <ChgText class="sensitive text-sm font-semibold tabular-nums" :chg="row.当日涨幅">{{ fmtSignedPct(row.当日涨幅) }}</ChgText>
            <FloatPnlInline :row="row" />
          </h2>
          <a :href="baiduStockUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="sensitive text-xs text-ui-text-2 hover:text-accent">{{ row.代码 }}</a>
        </div>
        <span :class="visual.badgeClass" :title="visual.badgeText">{{ visual.badgeText }}</span>
      </header>
      <p v-if="row.当日预警 && !(row.持仓)" class="mb-2 text-xs text-accent">当日预警 · 未登记持仓</p>
      <p v-if="row.error" class="text-sm text-up">{{ row.error }}</p>
      <div v-else class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <div><span class="text-ui-text-2">持仓状态</span> <b>{{ posStatus }}</b></div>
        <div>
          <span class="text-ui-text-2">{{ slotTrace && row.卖出数量 ? '卖出' : '持仓' }}</span>
          <b class="sensitive">{{ slotTrace && row.卖出数量 ? row.卖出数量 : (row.持仓 ?? 0) }}</b>
        </div>
        <div><span class="text-ui-text-2">成本</span> <b class="sensitive">{{ row.成本 != null ? fmtNum(row.成本, pdg) : '-' }}</b></div>
        <div><span class="text-ui-text-2">因子侧</span> <b>{{ row.因子侧 || '-' }}</b></div>
        <div><span class="text-ui-text-2">因子触发</span> <b>{{ row.因子触发 || '-' }}</b></div>
        <div v-if="row.阈值就绪" class="col-span-2 grid grid-cols-2 gap-x-3 text-sm">
          <div>
            <span class="text-ui-text-2">买入侧</span>
            <b class="sensitive ml-1 text-up">{{ fmtNum(row.买入侧价 ?? row.买点, pdg) }}</b>
          </div>
          <div>
            <span class="text-ui-text-2">卖出侧</span>
            <b class="sensitive ml-1 text-down">{{ fmtNum(row.卖出侧价 ?? row.止损, pdg) }}</b>
          </div>
        </div>
        <div v-if="row['距买点%'] != null && Number(row['距买点%']) < 9000" class="col-span-2 text-sm">
          <span class="text-ui-text-2">距买点</span>
          <b class="ml-1 tabular-nums">{{ Number(row['距买点%']).toFixed(2) }}%</b>
          <span v-if="row.槽位候选" class="ml-2 text-xs text-accent">槽位候选</span>
          <span v-if="row.已实现" class="ml-2 text-xs text-ui-text-3">当日留痕</span>
        </div>
        <div class="col-span-2 text-xs leading-relaxed text-ui-text-2">{{ row.挂单说明 || row.预警 }}</div>
        <footer class="col-span-2 text-xs text-ui-text-3">更新 {{ row.更新 || '-' }}</footer>
      </div>
    </div>
  </article>
</template>
