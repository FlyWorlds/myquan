<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { stabilizeRows } from '~/utils/stableRowOrder'
import { createStatusDebouncer } from '~/utils/alertBoard'
import { fmtNum, fmtSignedPct, fmtSignalClock, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual, collectLegendIds } from '~/composables/useSignalVisual'
import { strategyBookSingleReturn } from '~/utils/strategyBookReturn'

const props = defineProps<{
  rows: HoldingRow[]
  phase?: string
  slotMeta?: { max?: number; occupiedCount?: number; free?: number; weight?: number }
  poolCategory?: string
  statusMode?: 'paper' | 'strategy'
  signalPriority?: boolean
  hidePositionHigh?: boolean
  hideBuyDistance?: boolean
  dayChangeAfterName?: boolean
  tradeSidesAfterDayHigh?: boolean
}>()

const steps = [
  ['9:15', '竞价·可撤'],
  ['9:20', '不可撤'],
  ['9:25', '阈值/可挂单'],
  ['9:30', '信号触发'],
]

const legend = [
  { id: 'hold-real', cls: 'signal-badge signal-badge-hold-real', label: '实际持仓' },
  { id: 'hold-paper', cls: 'signal-badge signal-badge-hold-paper', label: '策略持有' },
  { id: 'ban-buy', cls: 'signal-badge signal-badge-ban-buy', label: '今日平仓' },
  { id: 'warn-buy', cls: 'signal-badge signal-badge-warn-buy', label: '买入预警' },
  { id: 'trigger-buy', cls: 'signal-badge signal-badge-trigger-buy', label: '触买' },
  { id: 'warn-sell', cls: 'signal-badge signal-badge-warn-sell', label: '卖出预警' },
  { id: 'trigger-sell', cls: 'signal-badge signal-badge-trigger-sell', label: '已触止损' },
  { id: 'flat', cls: 'signal-badge signal-badge-flat', label: '空仓' },
] as const

type LegendId = (typeof legend)[number]['id']

const selectedFilters = ref<LegendId[]>([])
const hoverExplanationKey = ref('')
const pinnedExplanationKey = ref('')

/** 表头排序：点列头 desc→asc→恢复默认；策略16默认按信号优先级。 */
type SortKey = 'dayChg' | 'strategyPnl'
type SortDir = 'desc' | 'asc'
const sortKey = ref<SortKey | null>(null)
const sortDir = ref<SortDir>('desc')
/** 排序态冻结整张表；取消排序后再接回实时快照。 */
type DecoratedRow = {
  row: HoldingRow
  visual: ReturnType<typeof resolveSignalVisual>
  tags: LegendId[]
}
const sortedRowsSnapshot = ref<DecoratedRow[] | null>(null)
const pinnedOrder = ref<string[]>([])
const statusDebouncer = createStatusDebouncer(3_000)
const debouncedRows = ref<HoldingRow[]>([])
let statusTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => {
  if (statusTimer != null) clearTimeout(statusTimer)
})

function armStatusTimer(now: number) {
  if (!import.meta.client || statusTimer != null || !debouncedRows.value.length) return
  const wait = statusDebouncer.remaining(now)
  if (wait <= 0) return
  statusTimer = setTimeout(() => {
    statusTimer = undefined
    const t = performance.now()
    debouncedRows.value = statusDebouncer.update(props.rows || [], t)
    armStatusTimer(t)
  }, wait)
}

watch(
  () => props.rows,
  (rows) => {
    const now = performance.now()
    debouncedRows.value = statusDebouncer.update(rows || [], now)
    armStatusTimer(now)
  },
  { immediate: true },
)

const decoratedRows = computed<DecoratedRow[]>(() =>
  (debouncedRows.value || []).map((row) => {
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
  return asNum(row['综合策略收益%'] ?? row['策略收益%'])
}

function rowCode(row: HoldingRow): string {
  return String(row.代码 || '')
}

function visibleDecorated() {
  let list = decoratedRows.value
  if (selectedFilters.value.length) {
    const on = new Set(selectedFilters.value)
    list = list.filter((x) => x.tags.some((id) => on.has(id)))
  }
  return list
}

function compareSorted(
  a: { row: HoldingRow },
  b: { row: HoldingRow },
  key: SortKey,
  dir: number,
): number {
  const va = sortValue(a.row, key)
  const vb = sortValue(b.row, key)
  if (va == null && vb == null) return rowCode(a.row).localeCompare(rowCode(b.row))
  if (va == null) return 1
  if (vb == null) return -1
  if (va !== vb) return va < vb ? -dir : dir
  return rowCode(a.row).localeCompare(rowCode(b.row))
}

function snapshotOrder() {
  const key = sortKey.value
  if (!key) {
    sortedRowsSnapshot.value = null
    return
  }
  const dir = sortDir.value === 'desc' ? -1 : 1
  sortedRowsSnapshot.value = [...visibleDecorated()].sort((a, b) => compareSorted(a, b, key, dir))
}

watch([sortKey, sortDir, selectedFilters], () => {
  snapshotOrder()
})

watch(
  () => (props.rows || []).map((row) => String(row.代码 || '')).join('|'),
  () => {
    const next = stabilizeRows(pinnedOrder.value, props.rows || [], (row) => String(row.代码 || '')).map((row) =>
      String(row.代码 || ''),
    )
    if (next.join('|') !== pinnedOrder.value.join('|')) pinnedOrder.value = next
  },
  { immediate: true },
)

function defaultSignalRank(item: DecoratedRow): number {
  if (item.tags.includes('warn-buy') || item.tags.includes('warn-sell')) return 0
  if (item.tags.includes('trigger-buy') || item.row.策略展示状态 === '已触买') return 1
  if (strategyStatusLabel(item.row) === '策略持有' || Number(item.row.持仓 || 0) > 0) return 2
  return 3
}

/** 买入时间优先，避免后续卖出信号覆盖通用信号时间。缺失时间排在组末。 */
function buyTriggerTime(row: HoldingRow): number | null {
  for (const raw of [row.首次触买时间, row.买信号时间, row.策略入场时间, row.信号时刻, row.信号时间]) {
    const match = String(raw || '').match(/(?:^|[T\s])(\d{2}):(\d{2})(?::(\d{2}))?/)
    if (!match) continue
    const [, hh, mm, ss = '0'] = match
    if (Number(hh) < 24 && Number(mm) < 60 && Number(ss) < 60)
      return Number(hh) * 3600 + Number(mm) * 60 + Number(ss)
  }
  return null
}

function compareDefaultSignals(a: DecoratedRow, b: DecoratedRow): number {
  if (!props.signalPriority) return 0
  const rankA = defaultSignalRank(a)
  const rankB = defaultSignalRank(b)
  if (rankA !== rankB) return rankA - rankB
  if (rankA !== 1) return 0
  const timeA = buyTriggerTime(a.row)
  const timeB = buyTriggerTime(b.row)
  if (timeA == null) return timeB == null ? 0 : 1
  if (timeB == null) return -1
  return timeA - timeB
}

const filteredRows = computed(() => {
  const list = visibleDecorated()
  const key = sortKey.value
  if (key) {
    const frozen = sortedRowsSnapshot.value
    if (frozen != null) return frozen
    const dir = sortDir.value === 'desc' ? -1 : 1
    return [...list].sort((a, b) => compareSorted(a, b, key, dir))
  }
  const index = new Map(pinnedOrder.value.map((code, i) => [code, i]))
  return [...list].sort(
    (a, b) =>
      compareDefaultSignals(a, b) ||
      (index.get(rowCode(a.row)) ?? 1_000_000) - (index.get(rowCode(b.row)) ?? 1_000_000) ||
      rowCode(a.row).localeCompare(rowCode(b.row)),
  )
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
  return `当前：${label}低→高，再点恢复默认${props.signalPriority ? '（预警→触买→持有）' : props.hideBuyDistance ? '' : '（距买点）'}`
}

function categoryOf(r: HoldingRow): string {
  if (r.pool_src === 'self' || r.池来源 === '自选') return '自选'
  if (r.pool_src === 'strategy1_pool' || r.池来源 === '策略池') return '策略池'
  if (r.pool_src === 'factor27' || r.池来源 === '因子27') return '因子27'
  if (r.池来源) return String(r.池来源)
  return props.poolCategory || '策略池'
}

function asNum(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function rowKey(r: HoldingRow): string {
  return String(r.代码 || r.名称 || '')
}

function explanationText(r: HoldingRow): string {
  return String(r.挂单说明 || '')
    .split('；')
    .map((part) => part.trim())
    .filter(
      (part) =>
        part &&
        !part.startsWith('买入信号已触发') &&
        !part.includes('当日新增额度已满') &&
        !part.includes('槽满') &&
        !part.includes('未入槽'),
    )
    .join('；')
}

function toggleExplanation(r: HoldingRow) {
  const key = rowKey(r)
  pinnedExplanationKey.value = pinnedExplanationKey.value === key ? '' : key
}

function isExplanationOpen(r: HoldingRow): boolean {
  const key = rowKey(r)
  return hoverExplanationKey.value === key || pinnedExplanationKey.value === key
}

function closeHoverExplanation() {
  hoverExplanationKey.value = ''
}

function closePinnedExplanation() {
  pinnedExplanationKey.value = ''
}

/** 正式 BUY 信号触发价：已触发因子价（冻结）；不得用开盘价冒充。 */
function signalTriggerPx(r: HoldingRow): number | null {
  if (r.已触发因子侧 === '买入') {
    const p = asNum(r.已触发因子价)
    if (p != null && p > 0) return p
  }
  const hit =
    String(r.已触买 || '') === '是' ||
    String(r.预警 || '').startsWith('已触买') ||
    (String(r.持仓状态 || '') === '待买入' && String(r.因子触发 || '').startsWith('已触发'))
  if (hit) {
    const p = asNum(r.买点) ?? asNum(r.买入侧价) ?? asNum(r.已触发因子价)
    if (p != null && p > 0) return p
  }
  return null
}

/**
 * 综合单笔收入优先用整笔纸面交易：分批卖出 realized + 剩余仓 MTM。
 * 无纸面成交时展示后端计算的策略整笔收益。
 */
function tradeIncomePct(r: HoldingRow): number | null {
  if (r.收益账本 === 'strategy16_database') return strategyBookSingleReturn(r)
  const comprehensive = asNum(r['综合单笔收入%'])
  if (comprehensive != null) return comprehensive
  const strategy = asNum(r['策略单笔收益%'])
  if (strategy != null) return strategy
  return null
}

/** 策略主状态：来自 Strategy Simulator（空仓/策略持有），不跟纸面 qty。 */
function strategyStatusLabel(r: HoldingRow): string {
  if (r.策略展示状态 === '已触买') return '已触买'
  const sim = String(r.策略状态 || '').trim()
  if (sim === '策略持有' || sim === '空仓') return sim
  if (r.策略模拟持有 || r.策略累计持有) return '策略持有'
  return '空仓'
}

/** debug：纸面仓位（不作为 Strategy Tab 主状态）。 */
function paperStatusLabel(r: HoldingRow): string {
  const qty = Number(r.持仓 || 0)
  const pos = String(r.持仓状态 || '').trim()
  if (qty > 0) {
    if (pos === '待卖出') return '待卖出'
    if (pos.includes('T+1')) return pos
    return pos && pos !== '-' ? pos : '已经买入'
  }
  if (pos && pos !== '-') return pos
  return '空仓'
}

function primaryStatusLabel(r: HoldingRow): string {
  return props.statusMode === 'paper' ? paperStatusLabel(r) : strategyStatusLabel(r)
}

function primaryStatusClass(r: HoldingRow, visual: { badgeClass: string }): string {
  if (props.statusMode === 'paper') return visual.badgeClass
  if (strategyStatusLabel(r) === '已触买') return 'signal-badge signal-badge-trigger-buy'
  return strategyStatusLabel(r) === '策略持有'
    ? 'signal-badge signal-badge-hold-paper'
    : 'signal-badge signal-badge-flat'
}

function primaryStatusTitle(r: HoldingRow): string {
  return props.statusMode === 'paper'
    ? `纸面：${paperStatusLabel(r)}；策略：${strategyStatusLabel(r)}`
    : `策略：${strategyStatusLabel(r)}；纸面：${paperStatusLabel(r)}`
}

function showPaperDebug(r: HoldingRow): boolean {
  return props.statusMode !== 'paper' && (Number(r.持仓) > 0 || paperStatusLabel(r) !== '空仓')
}

function statusClock(r: HoldingRow): string {
  return fmtSignalClock(r.策略入场时间) || fmtSignalClock(r.信号时间) || ''
}

function statusTitle(r: HoldingRow): string {
  const bits = [primaryStatusTitle(r)]
  const clock = statusClock(r)
  if (clock) bits.push(clock)
  if (showPaperDebug(r)) bits.push(`纸面 ${paperStatusLabel(r)}`)
  if (Number(r.持仓) > 0 && String(r.已触买 || '') === '是') bits.push('今日触买')
  if (r.槽位候选) bits.push('槽位候选')
  if (r.因子触发) bits.push(String(r.因子触发))
  return bits.join(' · ')
}

/** 策略收益 tooltip。 */
function strategyCumTitle(r: HoldingRow): string {
  if (r.策略收益来源 === 'database_strategy_book') {
    const warning = r.策略历史状态 === 'legacy_checkpoint_unverified' ? ' 旧历史检查点待核验；新成交逐笔记账。' : ''
    return `数据库策略账本：历次已实现盈亏＋当前浮盈，收益率以该股票策略初始资金为分母；盈亏金额 ${fmtNum(r.综合策略收益, 2)}；入库后增量 ${fmtNum(r.策略入库后增量盈亏, 2)}；估值 ${r.策略估值时刻 || '未知'}。${warning}`
  }
  const start = String(r.策略起算 || '回放起点')
  const amount = asNum(r.综合策略收益 ?? r.策略收益)
  const amountText = amount == null ? '' : ` 盈利金额 ${fmtNum(amount, 2)}；`
  const base =
    `单票策略虚拟账本自 ${start} 的综合收益；${amountText}按权益金额/初始资金计算，含回测买卖与当前持有 MTM，与纸面账户实际持仓独立。`
  if (strategyStatusLabel(r) === '策略持有') {
    return `${base} 当前收益包含现价 MTM。`
  }
  return `${base} 累计收益已冻结到最近一次虚拟平仓。`
}

const SINGLE_SIGNAL_TITLE =
  '综合单笔收入：（本轮已实现盈亏＋剩余仓位浮盈）÷本轮买入成本额；以行内账本来源为准'
const usesDatabaseStrategyBooks = computed(() => props.rows.some(r => r.收益账本 === 'strategy16_database'))

/** 当前可见股票的等权平均，缺失值不参与，零值和负值正常参与。 */
function meanReturn(getValue: (row: HoldingRow) => number | null): number | null {
  const values = filteredRows.value.map(({ row }) => getValue(row)).filter((v): v is number => v != null && Number.isFinite(v))
  return values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null
}
const averageStrategyReturn = computed(() => meanReturn(row => asNum(row['综合策略收益%'] ?? row['策略收益%'])))
const averageTradeReturn = computed(() => meanReturn(tradeIncomePct))

function fmtReturnPct(value: unknown): string {
  const number = asNum(value)
  if (number == null) return '—'
  const rounded = number.toFixed(1)
  return `${rounded === '-0.0' ? '0.0' : rounded}%`
}

function tradeIncomeTitle(r: HoldingRow): string {
  if (r.收益账本 === 'strategy16_database' && Number(r.策略虚拟股数) > 0) {
    return `本次买入 ${fmtNum(r.策略入场价, 2)}，数据库估值价 ${fmtNum(r.策略估值价格, 2)}；剩余浮盈 ${fmtNum(r.本轮浮动盈亏, 2)}。综合本轮盈亏 ${fmtNum(r.综合单笔收入, 2)}，包含已分批卖出收益。`
  }
  const source = r.综合单笔来源 === 'database_strategy_cycle' ? '数据库策略本轮交易' : r.综合单笔来源 === 'trades_jsonl_cycle' ? '纸面实际成交' : '策略回测成交'
  const pnl = asNum(r.综合单笔收入)
  const base = asNum(r.综合单笔成本额)
  if (pnl == null || base == null) return '尚无完整的整笔成交成本和盈亏记录'
  return `${source}：整笔盈亏 ${fmtNum(pnl, 2)} / 买入成本额 ${fmtNum(base, 2)}；含分批卖出和剩余持仓浮盈`
}
</script>

<template>
  <div>
    <div
      class="card mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2"
      title="状态与纸面仓独立。策略收益=历次已实现盈亏＋当前浮盈。点表头可按该列排序，未点时行序保持。"
    >
      <div class="flex flex-wrap items-center gap-1.5 text-xs">
        <span v-for="[t, l] in steps" :key="t" class="rounded-full bg-accent/10 px-2 py-0.5 text-accent">{{ t }} {{ l }}</span>
        <strong class="ml-1 text-sm text-ui-text">{{ phase || '-' }}</strong>
        <span v-if="slotMeta" class="text-ui-text-2">
          四槽 {{ slotMeta.occupiedCount ?? 0 }}/{{ slotMeta.max ?? 4 }}
          · 空槽 {{ slotMeta.free ?? '-' }}
        </span>
        <span v-if="sortKey === 'dayChg'" class="text-ui-text-3">日内涨跌{{ sortDir === 'desc' ? '高→低' : '低→高' }}</span>
        <span v-else-if="sortKey === 'strategyPnl'" class="text-ui-text-3">策略收益{{ sortDir === 'desc' ? '高→低' : '低→高' }}</span>
      </div>
      <div class="flex flex-wrap items-center gap-2">
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
        <table class="watch-sticky-table strategy-fixed-table">
          <thead>
            <tr>
              <th class="whitespace-nowrap px-3 py-1.5">分类</th>
              <th class="whitespace-nowrap px-3 py-1.5">标的</th>
              <th v-if="dayChangeAfterName" class="whitespace-nowrap px-3 py-1.5">
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
              <th
                class="whitespace-nowrap px-3 py-1.5"
                :title="props.statusMode === 'paper' ? '纸面仓位/预警状态；悬停可看策略状态' : '策略模拟器状态（空仓/策略持有）；与纸面仓独立'"
              >状态</th>
              <th v-if="!hideBuyDistance" class="whitespace-nowrap px-3 py-1.5">距买点</th>
              <th class="whitespace-nowrap px-3 py-1.5">竞价/开盘</th>
              <th class="whitespace-nowrap px-3 py-1.5">现价</th>
              <th
                class="whitespace-nowrap px-3 py-1.5"
                title="行情 API dayHigh；≠ trailing HWM"
              >今日最高</th>
              <template v-if="tradeSidesAfterDayHigh">
              <th class="whitespace-nowrap px-3 py-1.5">买入侧</th>
              <th class="whitespace-nowrap px-3 py-1.5">卖出侧</th>
              </template>
              <th
                v-if="!hidePositionHigh"
                class="whitespace-nowrap px-3 py-1.5"
                title="positions.peak_high；与自动卖出 trailing 同源"
              >持仓最高</th>
              <th v-if="!dayChangeAfterName" class="whitespace-nowrap px-3 py-1.5">
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
              <th class="whitespace-nowrap px-3 py-1.5">
                <button
                  type="button"
                  class="inline-flex items-center gap-0.5 font-semibold hover:text-accent"
                  :class="sortKey === 'strategyPnl' ? 'text-accent' : ''"
                  :title="sortTitle('strategyPnl', '策略收益') + '；括号内为当前可见股票有效收益率的算术平均，含负值'"
                  @click="toggleSort('strategyPnl')"
                >
                  策略收益（{{ fmtReturnPct(averageStrategyReturn) }}）<span class="tabular-nums text-[10px]">{{ sortMark('strategyPnl') }}</span>
                </button>
              </th>
              <th class="whitespace-nowrap px-3 py-1.5" :title="(usesDatabaseStrategyBooks ? '持有按本次买入价与数据库现价计算；全清后冻结本轮实际成交收益' : SINGLE_SIGNAL_TITLE) + '；括号内为当前可见股票有效单笔收益率的算术平均，含负值'">单笔收益（{{ fmtReturnPct(averageTradeReturn) }}）</th>
              <th class="whitespace-nowrap px-3 py-1.5">前日</th>
              <th class="whitespace-nowrap px-3 py-1.5">过门</th>
              <th class="whitespace-nowrap px-3 py-1.5">阈值</th>
              <template v-if="!tradeSidesAfterDayHigh">
              <th class="whitespace-nowrap px-3 py-1.5">买入侧</th>
              <th class="whitespace-nowrap px-3 py-1.5">卖出侧</th>
              </template>
              <th class="whitespace-nowrap px-3 py-1.5">因子侧</th>
              <th class="whitespace-nowrap px-3 py-1.5">说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!filteredRows.length">
              <td :colspan="18 - Number(!!hidePositionHigh) - Number(!!hideBuyDistance)" class="px-3 py-8 text-center text-sm text-ui-text-3">
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
              class="strategy-fixed-row border-t border-ui-hairline"
              :class="visual.rowClass"
            >
              <td class="whitespace-nowrap px-3 py-1.5 align-middle">
                <span
                  class="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                  :class="categoryOf(r) === '自选' ? 'bg-accent/15 text-accent' : 'bg-ui-ink/30 text-ui-text-3'"
                >{{ categoryOf(r) }}</span>
              </td>
              <td class="whitespace-nowrap px-3 py-1.5 align-middle">
                <div class="leading-snug">
                  <span v-if="r.信号因子 === 'factor29'" class="text-xs font-semibold text-accent">因子29·竞价</span>
          <StockNameHover :code="r.代码" :name="r.名称">
                    <a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="sensitive font-semibold text-accent hover:underline">{{ stockLabel(r.代码, r.名称) }}</a>
                  </StockNameHover>
                </div>
              </td>
              <td v-if="dayChangeAfterName" class="sensitive whitespace-nowrap px-3 py-1.5 align-middle">
                <ChgText :chg="r.当日涨幅">{{ fmtSignedPct(r.当日涨幅) }}</ChgText>
              </td>
              <td class="whitespace-nowrap px-3 py-1.5 align-middle" :title="statusTitle(r)">
                <span class="inline-flex items-center gap-1.5">
                  <span :class="primaryStatusClass(r, visual)">{{ primaryStatusLabel(r) }}</span>
                  <span v-if="statusClock(r)" class="font-mono text-[11px] tabular-nums text-accent">{{ statusClock(r) }}</span>
                </span>
              </td>
              <td v-if="!hideBuyDistance" class="sensitive whitespace-nowrap px-3 py-1.5 align-middle tabular-nums">
                <span v-if="r['距买点%'] != null && Number(r['距买点%']) < 9000">
                  {{ Number(r['距买点%']).toFixed(2) }}%
                </span>
                <span v-else class="text-ui-text-3">-</span>
              </td>
              <td class="sensitive whitespace-nowrap px-3 py-1.5 align-middle">{{ r.阈值就绪 ? fmtNum(r.开盘, r['价位小数'] ?? 2) : (r.竞价参考 != null ? fmtNum(r.竞价参考, r['价位小数'] ?? 2) : '待9:25') }}</td>
              <td class="sensitive whitespace-nowrap px-3 py-1.5 align-middle font-semibold">{{ fmtNum(r.现价, r['价位小数'] ?? 2) }}</td>
              <td
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle tabular-nums"
                title="行情 dayHigh"
              >{{ fmtNum(r.今日最高 ?? r.最高, r['价位小数'] ?? 2) }}</td>
              <template v-if="tradeSidesAfterDayHigh">
              <td
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle"
                :title="r.已触发因子侧 === '买入' && r.已触发因子价 != null ? `上次 ${fmtNum(r.已触发因子价, r['价位小数'] ?? 2)}` : undefined"
              >
                <span v-if="r.阈值就绪" class="font-semibold text-up">{{ fmtNum(r.买入侧价 ?? r.买点, r['价位小数'] ?? 2) }}</span>
                <span v-else class="text-ui-text-3">-</span>
              </td>
              <td
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle"
                :title="r.未触发因子侧 === '卖出' && r.未触发因子价 != null ? `止损 ${fmtNum(r.未触发因子价, r['价位小数'] ?? 2)}` : undefined"
              >
                <span v-if="r.阈值就绪" class="font-semibold text-down">{{ fmtNum(r.卖出侧价 ?? r.止损, r['价位小数'] ?? 2) }}</span>
                <span v-else class="text-ui-text-3">-</span>
              </td>
              </template>
              <td
                v-if="!hidePositionHigh"
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle tabular-nums"
                :title="r.持仓最高时间 ? `peak_high @ ${r.持仓最高时间}` : 'positions.peak_high'"
              >{{ fmtNum(r.持仓最高 ?? r.峰值, r['价位小数'] ?? 2) }}</td>
              <td v-if="!dayChangeAfterName" class="sensitive whitespace-nowrap px-3 py-1.5 align-middle">
                <ChgText :chg="r.当日涨幅">{{ fmtSignedPct(r.当日涨幅) }}</ChgText>
              </td>
              <td
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle"
                :title="strategyCumTitle(r)"
              >
                <ChgText :chg="r['综合策略收益%'] ?? r['策略收益%']">{{ fmtReturnPct(r['综合策略收益%'] ?? r['策略收益%']) }}</ChgText>
              </td>
              <td class="sensitive whitespace-nowrap px-3 py-1.5 align-middle tabular-nums" :title="tradeIncomeTitle(r)">
                <ChgText :chg="tradeIncomePct(r)">{{ fmtReturnPct(tradeIncomePct(r)) }}</ChgText>
              </td>
              <td class="whitespace-nowrap px-3 py-1.5 align-middle">{{ r.前日形态 || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-1.5 align-middle font-semibold" :class="r.过门OK ? 'text-up' : 'text-ui-text-2'">{{ r.过门 || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-1.5 align-middle">{{ r['阈值%'] || '-' }}</td>
              <template v-if="!tradeSidesAfterDayHigh">
              <td
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle"
                :title="r.已触发因子侧 === '买入' && r.已触发因子价 != null ? `上次 ${fmtNum(r.已触发因子价, r['价位小数'] ?? 2)}` : undefined"
              >
                <span v-if="r.阈值就绪" class="font-semibold text-up">{{ fmtNum(r.买入侧价 ?? r.买点, r['价位小数'] ?? 2) }}</span>
                <span v-else class="text-ui-text-3">-</span>
              </td>
              <td
                class="sensitive whitespace-nowrap px-3 py-1.5 align-middle"
                :title="r.未触发因子侧 === '卖出' && r.未触发因子价 != null ? `止损 ${fmtNum(r.未触发因子价, r['价位小数'] ?? 2)}` : undefined"
              >
                <span v-if="r.阈值就绪" class="font-semibold text-down">{{ fmtNum(r.卖出侧价 ?? r.止损, r['价位小数'] ?? 2) }}</span>
                <span v-else class="text-ui-text-3">-</span>
              </td>
              </template>
              <td
                class="whitespace-nowrap px-3 py-1.5 align-middle"
                :title="r.因子价 != null ? `${r.因子侧 === '卖出' ? '卖出侧' : r.因子侧 === '买入' ? '买入侧' : '参考'} ${fmtNum(r.因子价, r['价位小数'] ?? 2)}` : undefined"
              >{{ r.因子侧 || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-1.5 align-middle">
                <div
                  v-if="explanationText(r)"
                  class="relative inline-flex"
                  @mouseleave="closeHoverExplanation"
                >
                  <button
                    type="button"
                    class="inline-flex h-6 w-6 items-center justify-center rounded-full border border-ui-hairline bg-ui-surface-2 text-xs font-bold text-ui-text-2 shadow-sm transition hover:border-accent hover:text-accent focus:outline-none focus:ring-2 focus:ring-accent/40"
                    :aria-expanded="isExplanationOpen(r)"
                    :aria-label="`查看${stockLabel(r.代码, r.名称)}说明`"
                    :title="explanationText(r)"
                    @mouseenter="hoverExplanationKey = rowKey(r)"
                    @focus="hoverExplanationKey = rowKey(r)"
                    @blur="closeHoverExplanation"
                    @click.stop="toggleExplanation(r)"
                    @keydown.esc.stop="closePinnedExplanation"
                  >
                    ?
                  </button>
                  <div
                    v-show="isExplanationOpen(r)"
                    role="tooltip"
                    class="absolute right-0 top-8 z-30 w-[min(28rem,70vw)] rounded-md border border-ui-hairline bg-ui-surface p-3 text-left text-xs leading-relaxed text-ui-text shadow-xl"
                  >
                    {{ explanationText(r) }}
                  </div>
                </div>
                <span v-else class="text-xs text-ui-text-3">-</span>
              </td>
            </tr>
          </tbody>
        </table>
    </div>
  </div>
</template>
<style scoped>
.strategy-fixed-table :deep(thead th) {
  height: 2.75rem;
  padding-top: 0;
  padding-bottom: 0;
  vertical-align: middle;
}
.strategy-fixed-row {
  height: 3.5rem;
}
.strategy-fixed-row :deep(td) {
  height: 3.5rem;
  max-height: 3.5rem;
  padding-top: 0;
  padding-bottom: 0;
  vertical-align: middle;
  overflow: hidden;
}
</style>
