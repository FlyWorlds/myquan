<script setup lang="ts">
import type { StrategyPicks } from '~/types/snapshot'
import { stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'

defineProps<{ picks?: StrategyPicks | null }>()

const kindLabel: Record<string, string> = {
  locked: '锁定名单',
  pool: '宽宇宙换池',
  weekly: '周频选股',
  daily: '日频选股',
  signals: '事件信号',
  none: '无截面选股',
}
</script>

<template>
  <div v-if="picks" class="card mt-3 p-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 class="text-sm font-bold">选股 / 信号</h3>
      <span class="rounded-full bg-ui-surface-2 px-2 py-0.5 text-xs text-ui-text-2">
        {{ kindLabel[picks.kind] || picks.kind }}
      </span>
    </div>
    <p v-if="picks.note" class="mt-1 text-xs text-ui-text-3">{{ picks.note }}</p>
    <p class="mt-1 text-xs text-ui-text-3">
      <span v-if="picks.asOf">截至 {{ picks.asOf }}</span>
      <span v-if="picks.source" class="ml-2">来源 {{ picks.source }}</span>
    </p>

    <div v-if="picks.items?.length" class="mt-3 overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead class="text-left text-ui-text-2">
          <tr>
            <th class="px-2 py-1">#</th>
            <th class="px-2 py-1">标的</th>
            <th class="px-2 py-1">附加</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="it in picks.items" :key="`${it.symbol}-${it.rank}`" class="border-t border-ui-hairline">
            <td class="px-2 py-1">{{ it.rank ?? '—' }}</td>
            <td class="px-2 py-1 sensitive">
              <a
                v-if="it.code"
                :href="baiduStockUrl(it.code, it.name)"
                target="_blank"
                rel="noopener"
                class="text-accent hover:underline"
              >{{ stockLabel(it.code, it.name) }}</a>
              <span v-else>{{ stockLabel(it.symbol, it.name) }}</span>
            </td>
            <td class="px-2 py-1 text-xs text-ui-text-3">
              <template v-if="it.thr != null && it.oos_pl_ratio != null">
                阈值 ±{{ (Number(it.thr) * 100).toFixed(1) }}% · 盈亏比 {{ Number(it.oos_pl_ratio).toFixed(2) }}
                <span v-if="it.oos_win_rate_pct != null"> · 胜率 {{ Number(it.oos_win_rate_pct).toFixed(1) }}%</span>
              </template>
              <template v-else-if="it.thr != null">阈值 ±{{ (Number(it.thr) * 100).toFixed(1) }}%</template>
              <template v-else-if="it.theme != null">{{ it.theme }} · lu {{ it.theme_lu }}</template>
              <template v-else-if="it.score != null">score {{ Number(it.score).toFixed(2) }}</template>
              <template v-else-if="it.gap_pct != null">gap {{ it.gap_pct }}% · 量比 {{ it.vol_ratio }}</template>
              <template v-else>—</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="mt-2 text-xs text-ui-text-2">暂无选股条目。</p>
  </div>
</template>
