<script setup lang="ts">
import type { HoldingRow, Strategy15Payload } from '~/types/snapshot'
import { fmtNum, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'

defineProps<{ payload?: Strategy15Payload | null; phase?: string }>()

const regimeLabel: Record<string, string> = {
  chop: '震荡·减磨损',
  normal: '常规',
  hot: '高潮·少接回',
}

function categoryOf(r: HoldingRow): string {
  if (r.pool_src === 'self' || r.池来源 === '自选') return '自选'
  if (r.pool_src === 'factor27' || r.池来源 === '因子27') return '因子27'
  return String(r.池来源 || '策略池')
}
</script>

<template>
  <div>
    <div class="card mb-4 grid gap-3 p-3 sm:grid-cols-4">
      <div>
        <div class="text-xs text-ui-text-3">情绪日 / 最高板</div>
        <div class="text-lg font-semibold">
          {{ payload?.sentiment?.sentimentDate || '—' }}
          · {{ payload?.sentiment?.mkt_max_height ?? '—' }}板
        </div>
      </div>
      <div>
        <div class="text-xs text-ui-text-3">连板家数 / 梯度分</div>
        <div class="text-lg font-semibold">
          {{ payload?.sentiment?.mkt_lianban ?? '—' }}
          / {{ payload?.sentiment?.mkt_ladder_score ?? '—' }}
        </div>
      </div>
      <div>
        <div class="text-xs text-ui-text-3">F22 / F25(30m)</div>
        <div class="text-lg font-semibold">
          {{ payload?.policy?.use_factor22 ? '开' : '关' }}
          · {{ payload?.policy?.use_factor25 ? '开' : '关' }}
        </div>
      </div>
      <div>
        <div class="text-xs text-ui-text-3">档位</div>
        <div class="text-lg font-semibold">
          {{ regimeLabel[payload?.policy?.regime || ''] || payload?.policy?.regime || '—' }}
        </div>
      </div>
    </div>
    <p class="mb-3 text-xs leading-relaxed text-ui-text-3">
      {{ payload?.rules || '建仓因子1；震荡用 F25 30m 确认止损/动态半仓/卖飞回补。' }}
      当前：<strong>{{ phase || '-' }}</strong>
      · {{ payload?.policy?.reason }}
    </p>
    <p v-if="payload?.error" class="mb-3 text-sm text-ui-danger">{{ payload.error }}</p>
    <div class="watch-table-wrap">
      <table class="watch-sticky-table">
        <thead>
          <tr>
            <th class="px-3 py-2.5">分类</th>
            <th class="px-3 py-2.5">标的</th>
            <th class="min-w-[5.5rem] px-3 py-2.5">状态</th>
            <th class="px-3 py-2.5">现价</th>
            <th class="px-3 py-2.5">止盈/臂</th>
            <th class="px-3 py-2.5">F22</th>
            <th class="px-3 py-2.5">F25</th>
            <th class="px-3 py-2.5">买入侧</th>
            <th class="px-3 py-2.5">止损</th>
            <th class="px-3 py-2.5">因子侧</th>
            <th class="px-3 py-2.5">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in (payload?.rows || []) as HoldingRow[]"
            :key="String(r.代码)"
            class="border-t border-ui-hairline"
            :class="resolveSignalVisual(r).rowClass"
          >
            <td class="px-3 py-2.5 align-top">
              <span
                class="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                :class="categoryOf(r) === '自选' ? 'bg-accent/15 text-accent' : 'bg-ui-ink/30 text-ui-text-3'"
              >{{ categoryOf(r) }}</span>
            </td>
            <td class="px-3 py-2.5 align-top">
              <a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive font-semibold text-accent hover:underline">{{ stockLabel(r.代码, r.名称) }}</a>
            </td>
            <td class="px-3 py-2.5 align-top">
              <span :class="resolveSignalVisual(r).badgeClass">{{ resolveSignalVisual(r).badgeText }}</span>
              <div v-if="r.情绪档" class="mt-1 text-[10px] text-ui-text-3">{{ r.情绪档 }}</div>
            </td>
            <td class="sensitive px-3 py-2.5">{{ fmtNum(r.现价, r['价位小数'] ?? 2) }}</td>
            <td class="sensitive px-3 py-2.5">{{ fmtNum(r.止盈价 ?? r.F25动态臂, r['价位小数'] ?? 2) }}</td>
            <td class="px-3 py-2.5">{{ r.因子22 || '-' }}</td>
            <td class="px-3 py-2.5">{{ r.因子25 || '-' }}</td>
            <td class="sensitive px-3 py-2.5">{{ fmtNum(r.买入侧价 ?? r.买点, r['价位小数'] ?? 2) }}</td>
            <td class="sensitive px-3 py-2.5">{{ fmtNum(r.卖出侧价 ?? r.止损, r['价位小数'] ?? 2) }}</td>
            <td class="px-3 py-2.5">{{ r.因子侧 || '-' }}</td>
            <td class="max-w-[220px] px-3 py-2.5 text-xs text-ui-text-2">{{ r.F25提示 || r.挂单说明 || r.预警 || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
