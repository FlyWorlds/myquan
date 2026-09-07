<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, fmtSignedPct, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'

defineProps<{ rows: HoldingRow[]; phase?: string; slotMeta?: { max?: number; occupiedCount?: number; free?: number; weight?: number } }>()

const steps = [
  ['9:15', '竞价·可撤'],
  ['9:20', '不可撤'],
  ['9:25', '阈值/过门'],
  ['9:30', '信号触发'],
]

const legend = [
  { cls: 'signal-badge signal-badge-hold-real', label: '实仓持有' },
  { cls: 'signal-badge signal-badge-hold-paper', label: '策略持有' },
  { cls: 'signal-badge signal-badge-warn-buy', label: '买入预警' },
  { cls: 'signal-badge signal-badge-trigger-buy', label: '已触买（含策略持有叠买）' },
  { cls: 'signal-badge signal-badge-warn-sell', label: '卖出预警' },
  { cls: 'signal-badge signal-badge-trigger-sell', label: '已触止损' },
  { cls: 'signal-badge signal-badge-flat', label: '空仓' },
]
</script>

<template>
  <div>
    <div class="card mb-4 p-3">
      <div class="flex flex-wrap gap-2 text-xs">
        <span v-for="[t, l] in steps" :key="t" class="rounded-full bg-accent/10 px-2 py-1 text-accent">{{ t }} {{ l }}</span>
      </div>
      <div class="mt-2 text-sm">当前：<strong>{{ phase || '-' }}</strong></div>
      <div v-if="slotMeta" class="mt-1 text-xs text-ui-text-2">
        三槽持仓 {{ slotMeta.occupiedCount ?? 0 }}/{{ slotMeta.max ?? 3 }}
        · 空槽 {{ slotMeta.free ?? '-' }}
        · 每槽约 {{ Math.round((slotMeta.weight ?? 0.3) * 100) }}%
        · 列表按距买点升序
      </div>
      <div class="mt-1 text-xs text-ui-text-3">
        策略收益自 {{ rows[0]?.策略起算 || '2026-09-01' }} 起算（因子1 回放·含费用）
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <span v-for="item in legend" :key="item.label" class="text-xs text-ui-text-3">
          <span :class="item.cls" class="mx-0.5">{{ item.label }}</span>
        </span>
      </div>
    </div>
    <div class="watch-table-wrap">
        <table class="watch-sticky-table">
          <thead>
            <tr>
              <th class="px-3 py-2.5">标的</th>
              <th class="min-w-[5.5rem] px-3 py-2.5">状态</th>
              <th class="px-3 py-2.5">距买点</th>
              <th class="px-3 py-2.5">竞价/开盘</th>
              <th class="px-3 py-2.5">现价</th>
              <th class="px-3 py-2.5">日内涨跌</th>
              <th class="px-3 py-2.5">策略收益</th>
              <th class="px-3 py-2.5">前日</th>
              <th class="px-3 py-2.5">过门</th>
              <th class="px-3 py-2.5">阈值</th>
              <th class="px-3 py-2.5">买入侧</th>
              <th class="px-3 py-2.5">卖出侧</th>
              <th class="px-3 py-2.5">因子侧</th>
              <th class="px-3 py-2.5">说明</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in rows"
              :key="String(r.代码)"
              class="border-t border-ui-hairline"
              :class="resolveSignalVisual(r).rowClass"
            >
              <td class="px-3 py-2.5 align-top">
                <div class="leading-snug">
                  <a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive font-semibold text-accent hover:underline">{{ stockLabel(r.代码, r.名称) }}</a>
                </div>
              </td>
              <td class="px-3 py-2.5 align-top">
                <span
                  class="inline-block max-w-[7rem] truncate"
                  :class="resolveSignalVisual(r).badgeClass"
                  :title="resolveSignalVisual(r).badgeText"
                >
                  {{ resolveSignalVisual(r).badgeText }}
                </span>
                <div v-if="r.槽位候选" class="mt-1 text-[10px] text-accent">槽位候选</div>
                <div v-if="r.因子触发" class="mt-1 text-[10px] text-ui-text-3">{{ r.因子触发 }}</div>
              </td>
              <td class="sensitive px-3 py-2.5 tabular-nums">
                <span v-if="r['距买点%'] != null && Number(r['距买点%']) < 9000">
                  {{ Number(r['距买点%']).toFixed(2) }}%
                </span>
                <span v-else class="text-ui-text-3">-</span>
              </td>
              <td class="sensitive px-3 py-2.5">{{ r.阈值就绪 ? fmtNum(r.开盘, r['价位小数'] ?? 2) : (r.竞价参考 != null ? fmtNum(r.竞价参考, r['价位小数'] ?? 2) : '待9:25') }}</td>
              <td class="sensitive px-3 py-2.5 font-semibold">{{ fmtNum(r.现价, r['价位小数'] ?? 2) }}</td>
              <td class="sensitive px-3 py-2.5">
                <ChgText :chg="r.当日涨幅">{{ fmtSignedPct(r.当日涨幅) }}</ChgText>
              </td>
              <td class="sensitive px-3 py-2.5">
                <ChgText :chg="r['策略收益%']">{{ fmtSignedPct(r['策略收益%']) }}</ChgText>
              </td>
              <td class="px-3 py-2.5">{{ r.前日形态 || '-' }}</td>
              <td class="px-3 py-2.5 font-semibold" :class="r.过门OK ? 'text-up' : 'text-ui-text-2'">{{ r.过门 || '-' }}</td>
              <td class="px-3 py-2.5">{{ r['阈值%'] || '-' }}</td>
              <td class="sensitive px-3 py-2.5 align-top">
                <div v-if="r.阈值就绪" class="font-semibold text-up">
                  {{ fmtNum(r.买入侧价 ?? r.买点, r['价位小数'] ?? 2) }}
                </div>
                <div v-else class="text-ui-text-3">-</div>
                <div v-if="r.已触发因子侧 === '买入' && r.已触发因子价 != null" class="mt-0.5 text-[10px] text-up">
                  已触 {{ fmtNum(r.已触发因子价, r['价位小数'] ?? 2) }}
                </div>
              </td>
              <td class="sensitive px-3 py-2.5 align-top">
                <div v-if="r.阈值就绪" class="font-semibold text-down">
                  {{ fmtNum(r.卖出侧价 ?? r.止损, r['价位小数'] ?? 2) }}
                </div>
                <div v-else class="text-ui-text-3">-</div>
                <div v-if="r.未触发因子侧 === '卖出' && r.未触发因子价 != null" class="mt-0.5 text-[10px] text-down">
                  止损 {{ fmtNum(r.未触发因子价, r['价位小数'] ?? 2) }}
                </div>
              </td>
              <td class="px-3 py-2.5 align-top">
                <div class="font-semibold">{{ r.因子侧 || '-' }}</div>
                <div v-if="r.因子价 != null" class="text-xs text-ui-text-2">
                  {{ r.因子侧 === '卖出' ? '卖出侧' : r.因子侧 === '买入' ? '买入侧' : '参考' }}
                  {{ fmtNum(r.因子价, r['价位小数'] ?? 2) }}
                </div>
              </td>
              <td class="max-w-[220px] px-3 py-2.5 text-xs leading-relaxed text-ui-text-2">{{ r.挂单说明 || r.预警 || '-' }}</td>
            </tr>
          </tbody>
        </table>
    </div>
  </div>
</template>
