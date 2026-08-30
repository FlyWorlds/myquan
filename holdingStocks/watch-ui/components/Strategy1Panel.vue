<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'

defineProps<{ rows: HoldingRow[]; phase?: string }>()

const steps = [
  ['9:15', '竞价·可撤'],
  ['9:20', '不可撤'],
  ['9:25', '阈值/过门'],
  ['9:30', '信号触发'],
]

function visualOf(row: HoldingRow) {
  return resolveSignalVisual(row)
}
</script>

<template>
  <div>
    <div class="card mb-4 p-3">
      <div class="flex flex-wrap gap-2 text-xs">
        <span v-for="[t, l] in steps" :key="t" class="rounded-full bg-accent/10 px-2 py-1 text-accent">{{ t }} {{ l }}</span>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <span>当前：<strong>{{ phase || '-' }}</strong></span>
        <span class="text-xs text-ui-text-3">买预警<span class="signal-badge signal-badge-warn-buy mx-1">将买入</span>红闪 · 已触买<span class="signal-badge signal-badge-trigger-buy mx-1">已触买</span>飙红</span>
        <span class="text-xs text-ui-text-3">卖预警<span class="signal-badge signal-badge-warn-sell mx-1">将止损</span>绿闪 · 已触发<span class="signal-badge signal-badge-trigger-sell mx-1">已触止损</span>标绿</span>
      </div>
    </div>
    <div class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="sticky top-0 z-10 bg-ui-surface/95 text-left text-ui-text-2 backdrop-blur">
            <tr>
              <th class="px-3 py-2.5">标的</th>
              <th class="px-3 py-2.5">信号</th>
              <th class="px-3 py-2.5">竞价/开盘</th>
              <th class="px-3 py-2.5">现价</th>
              <th class="px-3 py-2.5">前日</th>
              <th class="px-3 py-2.5">过门</th>
              <th class="px-3 py-2.5">阈值</th>
              <th class="px-3 py-2.5">买点</th>
              <th class="px-3 py-2.5">止损</th>
              <th class="px-3 py-2.5">因子侧</th>
              <th class="px-3 py-2.5">说明</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in rows"
              :key="String(r.代码)"
              class="border-t border-ui-hairline"
              :class="visualOf(r).rowClass"
            >
              <td class="px-3 py-2.5 align-top">
                <div class="leading-snug">
                  <a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive font-semibold text-accent hover:underline">{{ stockLabel(r.代码, r.名称) }}</a>
                  <FloatPnlInline :row="r" block />
                </div>
              </td>
              <td class="px-3 py-2.5 align-top">
                <span :class="visualOf(r).badgeClass" :title="visualOf(r).badgeText">{{ visualOf(r).badgeText }}</span>
                <div v-if="r.因子触发 && r.因子触发 !== visualOf(r).badgeText" class="mt-1 text-[10px] text-ui-text-3">{{ r.因子触发 }}</div>
              </td>
              <td class="sensitive px-3 py-2.5">{{ r.阈值就绪 ? fmtNum(r.开盘, r['价位小数'] ?? 2) : (r.竞价参考 != null ? fmtNum(r.竞价参考, r['价位小数'] ?? 2) : '待9:25') }}</td>
              <td class="sensitive px-3 py-2.5 font-semibold">{{ fmtNum(r.现价, r['价位小数'] ?? 2) }}</td>
              <td class="px-3 py-2.5">{{ r.前日形态 || '-' }}</td>
              <td class="px-3 py-2.5 font-semibold" :class="r.过门OK ? 'text-up' : 'text-ui-text-2'">{{ r.过门 || '-' }}</td>
              <td class="px-3 py-2.5">{{ r['阈值%'] || '-' }}</td>
              <td class="sensitive px-3 py-2.5">{{ r.阈值就绪 ? fmtNum(r.买点, r['价位小数'] ?? 2) : '-' }}</td>
              <td class="sensitive px-3 py-2.5">{{ r.阈值就绪 ? fmtNum(r.止损, r['价位小数'] ?? 2) : '-' }}</td>
              <td class="px-3 py-2.5">{{ r.因子侧 || '-' }}</td>
              <td class="max-w-[220px] px-3 py-2.5 text-xs leading-relaxed text-ui-text-2">{{ r.挂单说明 || r.预警 || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
