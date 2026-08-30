<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'

const props = defineProps<{ row: HoldingRow }>()

function baiduUrl(code?: string, name?: string) {
  const c = (code || '').replace(/\D/g, '')
  const q = encodeURIComponent(name || '')
  return `https://finance.baidu.com/stock/ab-${c}?name=${q}`
}

function fmt(v?: number | null, d = 2) {
  if (v == null) return '-'
  return v.toFixed(d)
}

const pdg = props.row['价位小数'] ?? 2

const cardClass = computed(() => {
  if (props.row.bgClass === 'warn-buy') return 'border-up/40 bg-up/10'
  if (props.row.bgClass === 'warn-sell') return 'border-up/50 bg-up/15'
  if (props.row.bgClass === 'status-hold') return 'border-accent/30 bg-accent/10'
  return 'border-ui-hairline bg-ui-surface'
})
</script>

<template>
  <article class="card p-3 transition" :class="cardClass">
    <header class="mb-2 flex items-start justify-between gap-2">
      <div>
        <span class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-accent">{{ row.市场 }}</span>
        <h2 class="mt-1 text-base font-bold">
          <a :href="baiduUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="sensitive hover:text-accent hover:underline">{{ row.名称 }}</a>
        </h2>
        <a :href="baiduUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="sensitive text-xs text-ui-text-2 hover:text-accent">{{ row.代码 }}</a>
      </div>
      <span
        class="rounded-md px-2 py-1 text-xs font-bold"
        :class="{
          'bg-up/20 text-up': ['待买入', '待卖出'].includes(row.持仓状态 || ''),
          'bg-accent/15 text-accent': ['持有', '策略持有'].includes(row.持仓状态 || ''),
          'text-ui-text-2': ['空仓', '当日禁买'].includes(row.持仓状态 || ''),
        }"
      >
        {{ row.预警 || row.持仓状态 || '-' }}
      </span>
    </header>
    <p v-if="row.error" class="text-sm text-up">{{ row.error }}</p>
    <div v-else class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
      <div><span class="text-ui-text-2">现价</span> <b class="sensitive">{{ fmt(row.现价, pdg) }}</b></div>
      <div><span class="text-ui-text-2">当日涨幅</span> <b class="sensitive"><ChgText :chg="row.当日涨幅">{{ row.当日涨幅 == null ? '-' : `${row.当日涨幅 >= 0 ? '+' : ''}${row.当日涨幅.toFixed(2)}%` }}</ChgText></b></div>
      <div><span class="text-ui-text-2">持仓</span> <b class="sensitive">{{ row.持仓 ?? 0 }}</b></div>
      <div><span class="text-ui-text-2">浮盈</span> <b class="sensitive"><ChgText :chg="row.浮盈">{{ row.浮盈 == null ? '-' : `${row.浮盈 >= 0 ? '+' : ''}${fmt(row.浮盈)}` }}</ChgText></b></div>
      <div><span class="text-ui-text-2">因子侧</span> <b>{{ row.因子侧 || '-' }}</b></div>
      <div><span class="text-ui-text-2">因子触发</span> <b>{{ row.因子触发 || '-' }}</b></div>
      <div class="col-span-2 text-xs text-ui-text-2">{{ row.挂单说明 || row.预警 }}</div>
      <footer class="col-span-2 text-xs text-ui-text-3">更新 {{ row.更新 || '-' }}</footer>
    </div>
  </article>
</template>
