<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, fmtSignedPct, fmtSignalClock, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual, collectLegendIds } from '~/composables/useSignalVisual'

const props = defineProps<{
  rows: HoldingRow[]
  phase?: string
  slotMeta?: { max?: number; occupiedCount?: number; free?: number; weight?: number }
  poolCategory?: string
}>()

const steps = [
  ['9:15', '竞价·可撤'],
  ['9:20', '不可撤'],
  ['9:25', '阈值/可挂单'],
  ['9:30', '信号触发'],
]

const legend = [
  { id: 'hold-real', cls: 'signal-badge signal-badge-hold-real', label: '已经买入' },
  { id: 'hold-paper', cls: 'signal-badge signal-badge-hold-paper', label: '策略持有' },
  { id: 'ban-buy', cls: 'signal-badge signal-badge-ban-buy', label: '今日平仓' },
  { id: 'warn-buy', cls: 'signal-badge signal-badge-warn-buy', label: '买入预警' },
  { id: 'trigger-buy', cls: 'signal-badge signal-badge-trigger-buy', label: '已触买（含策略持有叠买）' },
  { id: 'warn-sell', cls: 'signal-badge signal-badge-warn-sell', label: '卖出预警' },
  { id: 'trigger-sell', cls: 'signal-badge signal-badge-trigger-sell', label: '已触止损' },
  { id: 'flat', cls: 'signal-badge signal-badge-flat', label: '空仓' },
] as const

type LegendId = (typeof legend)[number]['id']

const selectedFilters = ref<LegendId[]>([])

/** 表头排序：默认无（后端距买点升序）；点列头 desc→asc→清 */
type SortKey = 'dayChg' | 'strategyPnl'
type SortDir = 'desc' | 'asc'
const sortKey = ref<SortKey | null>(null)
const sortDir = ref<SortDir>('desc')

const decoratedRows = computed(() =>
  (props.rows || []).map((row) => {
    const visual = resolveSignalVisual(row)
    const tags = collectLegendIds(row) as LegendId[]
    return { row, visual, tags }
  }),
)

const filterCounts = computed(() => {
  const counts = Object.fromEntries(legend.map((x) => [x.id, 0])) as Record<LegendId, number>
  for (const x of decoratedRows.value) {
    for (const id of x.tags) {
      if (id in counts) counts[id] += 1
    }
  }
  return counts
})

function sortValue(row: HoldingRow, key: SortKey): number | null {
  if (key === 'dayChg') return asNum(row.当日涨幅)
  return asNum(row['策略收益%'])
}

const filteredRows = computed(() => {
  let list = decoratedRows.value
  if (selectedFilters.value.length) {
    const on = new Set(selectedFilters.value)
    list = list.filter((x) => x.tags.some((id) => on.has(id)))
  }
  const key = sortKey.value
  if (!key) return list
  const dir = sortDir.value === 'desc' ? -1 : 1
  return [...list].sort((a, b) => {
    const va = sortValue(a.row, key)
    const vb = sortValue(b.row, key)
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    if (va === vb) return 0
    return va < vb ? -dir : dir
  })
})

function toggleFilter(id: LegendId) {
  const cur = selectedFilters.value
  selectedFilters.value = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
}

function resetFilters() {
  selectedFilters.value = []
}

function isFilterOn(id: LegendId) {
  return selectedFilters.value.includes(id)
}

function toggleSort(key: SortKey) {
  if (sortKey.value !== key) {
    sortKey.value = key
    sortDir.value = 'desc'
    return
  }
  if (sortDir.value === 'desc') {
    sortDir.value = 'asc'
    return
  }
  sortKey.value = null
  sortDir.value = 'desc'
}

function sortMark(key: SortKey): string {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'desc' ? ' ↓' : ' ↑'
}

function sortTitle(key: SortKey, label: string): string {
  if (sortKey.value !== key) return `按${label}排序（高→低）`
  if (sortDir.value === 'desc') return `当前：${label}高→低，再点改为低→高`
  return `当前：${label}低→高，再点恢复默认（距买点）`
}

function categoryOf(r: HoldingRow): string {
  if (r.pool_src === 'self' || r.池来源 === '自选') return '自选'
  if (r.pool_src === 'factor27' || r.池来源 === '因子27') return '因子27'
  if (r.池来源) return String(r.池来源)
  return props.poolCategory || '策略池'
}

function asNum(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function buyPx(r: HoldingRow): number | null {
  const cost = asNum(r.成本)
  if (cost != null && cost > 0) return cost
  if (r.已触发因子侧 === '买入') {
    const p = asNum(r.已触发因子价)
    if (p != null && p > 0) return p
  }
  return null
}

/** 单笔收入%：(现价或成交价)/买入成本 − 1。 */
function tradeIncomePct(r: HoldingRow): number | null {
  const buy = buyPx(r)
  if (buy == null) return null
  const qty = Number(r.持仓 || 0)
  const pos = String(r.持仓状态 || '')
  const sold =
    Boolean(r.已实现) ||
    Boolean(r.槽位留痕) ||
    (qty <= 0 &&
      (pos.includes('平仓') ||
        pos.includes('已止损') ||
        pos === '当日禁买' ||
        asNum(r.成交价) != null))
  const mark = sold ? asNum(r.成交价) : asNum(r.现价)
  const useMark =
    mark != null && mark > 0
      ? mark
      : sold
        ? asNum(r.现价)
        : null
  if (useMark == null || useMark <= 0) return null
  if (!sold) {
    const holding =
      qty > 0 ||
      pos.includes('持有') ||
      pos === '已经买入' ||
      pos === '待卖出'
    if (!holding) return null
  }
  return (useMark / buy - 1) * 100
}
</script>

<template>
  <div>
    <div class="card mb-4 p-3">
      <div class="flex flex-wrap gap-2 text-xs">
        <span v-for="[t, l] in steps" :key="t" class="rounded-full bg-accent/10 px-2 py-1 text-accent">{{ t }} {{ l }}</span>
      </div>
      <div class="mt-2 text-sm">当前：<strong>{{ phase || '-' }}</strong></div>
      <div v-if="slotMeta" class="mt-1 text-xs text-ui-text-2">
        四槽持仓 {{ slotMeta.occupiedCount ?? 0 }}/{{ slotMeta.max ?? 4 }}
        · 空槽 {{ slotMeta.free ?? '-' }}
        · 每槽约 {{ Math.round((slotMeta.weight ?? 0.3) * 100) }}%
        · 默认按距买点升序（自选优先）
        <template v-if="sortKey === 'dayChg'"> · 已按日内涨跌{{ sortDir === 'desc' ? '高→低' : '低→高' }}</template>
        <template v-else-if="sortKey === 'strategyPnl'"> · 已按策略收益{{ sortDir === 'desc' ? '高→低' : '低→高' }}</template>
      </div>
      <div class="mt-1 text-xs text-ui-text-3">
        策略收益自 {{ rows[0]?.策略起算 || '2026-09-01' }} 起算（因子1 回放·含费用）；
        单笔收入%=(现价或成交价)/成本−1（含策略持有/实仓）；图例可点筛选，可多选。
        点「日内涨跌 / 策略收益」表头可排序。已经买入=四槽实仓；已触买含今日已入槽；T+1 止损已记不算已触止损。
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <button
          v-for="item in legend"
          :key="item.id"
          type="button"
          class="text-xs"
          :title="`筛选：${item.label}`"
          :aria-pressed="isFilterOn(item.id)"
          @click="toggleFilter(item.id)"
        >
          <span
            :class="[
              item.cls,
              'mx-0.5 cursor-pointer transition-opacity',
              selectedFilters.length && !isFilterOn(item.id) ? 'opacity-35' : 'opacity-100',
              isFilterOn(item.id) ? 'ring-2 ring-white/70' : '',
            ]"
          >{{ item.label }} {{ filterCounts[item.id] }}</span>
        </button>
        <button
          type="button"
          class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-ui-text-2 hover:border-accent hover:text-accent"
          :disabled="!selectedFilters.length"
          :class="selectedFilters.length ? 'opacity-100' : 'opacity-40'"
          @click="resetFilters"
        >
          重置
        </button>
        <span v-if="selectedFilters.length" class="text-[10px] text-ui-text-3">
          {{ filteredRows.length }}/{{ decoratedRows.length }}
        </span>
      </div>
    </div>
    <div class="watch-table-wrap">
        <table class="watch-sticky-table">
          <thead>
            <tr>
              <th class="px-3 py-2.5">分类</th>
              <th class="px-3 py-2.5">标的</th>
              <th class="min-w-[5.5rem] px-3 py-2.5">状态</th>
              <th class="px-3 py-2.5">距买点</th>
              <th class="px-3 py-2.5">竞价/开盘</th>
              <th class="px-3 py-2.5">现价</th>
              <th class="px-3 py-2.5">
                <button
                  type="button"
                  class="inline-flex items-center gap-0.5 font-semibold hover:text-accent"
                  :class="sortKey === 'dayChg' ? 'text-accent' : ''"
                  :title="sortTitle('dayChg', '日内涨跌')"
                  @click="toggleSort('dayChg')"
                >
                  日内涨跌<span class="tabular-nums text-[10px]">{{ sortMark('dayChg') }}</span>
                </button>
              </th>
              <th class="px-3 py-2.5">
                <button
                  type="button"
                  class="inline-flex items-center gap-0.5 font-semibold hover:text-accent"
                  :class="sortKey === 'strategyPnl' ? 'text-accent' : ''"
                  :title="sortTitle('strategyPnl', '策略收益')"
                  @click="toggleSort('strategyPnl')"
                >
                  策略收益<span class="tabular-nums text-[10px]">{{ sortMark('strategyPnl') }}</span>
                </button>
              </th>
              <th class="px-3 py-2.5">单笔收入</th>
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
            <tr v-if="!filteredRows.length">
              <td colspan="16" class="px-3 py-8 text-center text-sm text-ui-text-3">
                无匹配标的
                <button
                  v-if="selectedFilters.length"
                  type="button"
                  class="ml-2 text-accent hover:underline"
                  @click="resetFilters"
                >重置筛选</button>
              </td>
            </tr>
            <tr
              v-for="{ row: r, visual } in filteredRows"
              :key="String(r.代码)"
              class="border-t border-ui-hairline"
              :class="visual.rowClass"
            >
              <td class="px-3 py-2.5 align-top">
                <span
                  class="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                  :class="categoryOf(r) === '自选' ? 'bg-accent/15 text-accent' : 'bg-ui-ink/30 text-ui-text-3'"
                >{{ categoryOf(r) }}</span>
              </td>
              <td class="px-3 py-2.5 align-top">
                <div class="leading-snug">
                  <a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive font-semibold text-accent hover:underline">{{ stockLabel(r.代码, r.名称) }}</a>
                </div>
              </td>
              <td class="px-3 py-2.5 align-top">
                <span
                  class="inline-block max-w-[7rem] truncate"
                  :class="visual.badgeClass"
                  :title="visual.badgeText"
                >
                  {{ visual.badgeText }}
                </span>
                <div v-if="Number(r.持仓) > 0 && String(r.已触买 || '') === '是'" class="mt-1 text-[10px] font-semibold text-up">今日触买</div>
                <div v-if="r.槽位候选" class="mt-1 text-[10px] text-accent">槽位候选</div>
                <div v-if="r.因子触发" class="mt-1 text-[10px] text-ui-text-3">{{ r.因子触发 }}</div>
                <div v-if="r.信号时间" class="mt-0.5 font-mono text-[11px] font-semibold tabular-nums text-accent">{{ fmtSignalClock(r.信号时间) }}</div>
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
              <td class="sensitive px-3 py-2.5 tabular-nums">
                <ChgText :chg="tradeIncomePct(r)">{{ fmtSignedPct(tradeIncomePct(r)) }}</ChgText>
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
                  上次 {{ fmtNum(r.已触发因子价, r['价位小数'] ?? 2) }}
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
