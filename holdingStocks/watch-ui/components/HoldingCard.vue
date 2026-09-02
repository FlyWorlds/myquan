<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, fmtSignedPct } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'

const props = defineProps<{ row: HoldingRow }>()

const pdg = props.row['价位小数'] ?? 2
const visual = computed(() => resolveSignalVisual(props.row))

const cardClass = computed(() => {
  const map: Record<string, string> = {
    'trigger-buy': 'signal-trigger-buy border-up/50',
    'warn-buy': 'signal-warn-buy border-up/40',
    'trigger-sell': 'signal-trigger-sell border-down/50',
    'warn-sell': 'signal-warn-sell border-down/40',
    hold: 'signal-hold-real border-sky-400/30',
    'paper-hold': 'signal-hold-paper border-violet-400/30',
    'ban-buy': 'signal-ban-buy border-up/25',
    flat: 'signal-flat border-ui-hairline',
  }
  const tier = visual.value.tier
  if (tier && map[tier]) return map[tier]
  if (Number(props.row.持仓) > 0) return 'signal-hold-real border-sky-400/30'
  return 'signal-flat border-ui-hairline'
})
</script>

<template>
  <article class="card overflow-hidden p-0 transition" :class="cardClass">
    <div class="p-3">
      <header class="mb-2 flex items-start justify-between gap-2">
        <div>
          <span class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-accent">{{ row.市场 }}</span>
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
      <p v-if="row.error" class="text-sm text-up">{{ row.error }}</p>
      <div v-else class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <div><span class="text-ui-text-2">持仓</span> <b class="sensitive">{{ row.持仓 ?? 0 }}</b></div>
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
        <div class="col-span-2 text-xs leading-relaxed text-ui-text-2">{{ row.挂单说明 || row.预警 }}</div>
        <footer class="col-span-2 text-xs text-ui-text-3">更新 {{ row.更新 || '-' }}</footer>
      </div>
    </div>
  </article>
</template>
