<script setup lang="ts">
import type { SectorKindPayload } from '~/types/sectors'
import { formatDateShort, formatMetricValue } from '~/composables/useSectorsLive'

const props = defineProps<{
  kind: SectorKindPayload
  topN: number
  metric: string
  selectedName?: string | null
  showBottom?: boolean
  loading?: boolean
}>()

const displayKind = computed(() => {
  const values = props.kind.by_metric[props.metric]
  const keep = props.kind.dates.map((_, i) => i).filter(i =>
    [...(values?.top?.[i] || []), ...(values?.bottom?.[i] || [])]
      .some(cell => cell.value != null && Number.isFinite(Number(cell.value))),
  )
  const dates = keep.map(i => props.kind.dates[i])
  const count = Math.max(8, dates.length)
  const by_metric = Object.fromEntries(Object.entries(props.kind.by_metric).map(([metric, columns]) => [
    metric, { top: keep.map(i => columns.top?.[i] || []), bottom: keep.map(i => columns.bottom?.[i] || []) },
  ]))
  while (dates.length < count) dates.push('')
  return { ...props.kind, dates, by_metric }
})

const emit = defineEmits<{
  select: [name: string]
  drill: [name: string]
}>()

const internalSelected = ref<string | null>(null)
const activeName = computed(() =>
  props.selectedName !== undefined ? props.selectedName : internalSelected.value,
)

function fmtVal(metric: string, v: number | null | undefined) {
  return formatMetricValue(metric, v)
}

function fmtDate(d: string) {
  return formatDateShort(d)
}

function clsNum(v: number | null | undefined) {
  const x = Number(v)
  if (!Number.isFinite(x) || x === 0) return 'flat'
  return x > 0 ? 'up' : 'down'
}

function rankBadgeClass(rank: number, isTop = true) {
  if (!isTop) return 'rank-badge bot'
  if (rank === 1) return 'rank-badge r1'
  if (rank === 2) return 'rank-badge r2'
  if (rank === 3) return 'rank-badge r3'
  return 'rank-badge r-other'
}

function cellClass(name: string) {
  const parts = ['sector-cell']
  if (activeName.value && activeName.value === name) parts.push('hl')
  return parts.join(' ')
}

function onPick(name: string) {
  if (!name) return
  if (activeName.value === name) {
    emit('drill', name)
    return
  }
  internalSelected.value = name
  emit('select', name)
}

function clearSelection() {
  internalSelected.value = null
}

defineExpose({ clearSelection, selected: activeName })
</script>

<template>
  <div class="sector-heatmap-wrap overflow-auto rounded-xl border border-ui-hairline bg-ui-surface shadow-sm">
    <table
      class="sector-heat w-full border-collapse text-xs"
      :aria-busy="loading"
      :style="{ minWidth: `${52 + displayKind.dates.length * 124}px`, tableLayout: 'fixed' }"
    >
      <colgroup>
        <col style="width: 52px">
        <col v-for="(_, i) in displayKind.dates" :key="i">
      </colgroup>
      <thead>
        <tr>
          <th class="rank-h">排名</th>
          <th v-for="(d, i) in displayKind.dates" :key="i">
            {{ d ? fmtDate(d) : (loading ? '加载中' : '—') }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in topN" :key="`t-${r}`">
          <td class="rank">
            <span :class="rankBadgeClass(r, true)">{{ r }}</span>
          </td>
          <td v-for="di in displayKind.dates.length" :key="`t-${r}-${di - 1}`">
            <button
              v-if="displayKind.by_metric[metric]?.top?.[di - 1]?.[r - 1]"
              type="button"
              :class="cellClass(displayKind.by_metric[metric].top[di - 1][r - 1].name)"
              @click="onPick(displayKind.by_metric[metric].top[di - 1][r - 1].name)"
            >
              <span class="n">{{ displayKind.by_metric[metric].top[di - 1][r - 1].name }}</span>
              <span class="v" :class="clsNum(displayKind.by_metric[metric].top[di - 1][r - 1].value)">
                {{ fmtVal(metric, displayKind.by_metric[metric].top[di - 1][r - 1].value) }}
              </span>
            </button>
            <span v-else class="sector-cell empty" :class="{ skeleton: loading }">
              {{ loading ? '···' : '—' }}
            </span>
          </td>
        </tr>
        <template v-if="showBottom">
          <tr class="sep">
            <td :colspan="displayKind.dates.length + 1" />
          </tr>
          <tr v-for="i in topN" :key="`b-${i}`">
            <td class="rank">
              <span :class="rankBadgeClass(topN - i + 1, false)">{{ topN - i + 1 }}</span>
            </td>
            <td v-for="di in displayKind.dates.length" :key="`b-${i}-${di - 1}`">
              <button
                v-if="displayKind.by_metric[metric]?.bottom?.[di - 1]?.[i - 1]"
                type="button"
                :class="cellClass(displayKind.by_metric[metric].bottom[di - 1][i - 1].name)"
                @click="onPick(displayKind.by_metric[metric].bottom[di - 1][i - 1].name)"
              >
                <span class="n">{{ displayKind.by_metric[metric].bottom[di - 1][i - 1].name }}</span>
                <span class="v" :class="clsNum(displayKind.by_metric[metric].bottom[di - 1][i - 1].value)">
                  {{ fmtVal(metric, displayKind.by_metric[metric].bottom[di - 1][i - 1].value) }}
                </span>
              </button>
              <span v-else class="sector-cell empty" :class="{ skeleton: loading }">
                {{ loading ? '···' : '—' }}
              </span>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.sector-heat th,
.sector-heat td {
  border: 1px solid var(--ui-hairline);
  padding: 0;
  text-align: center;
  vertical-align: middle;
}
.sector-heat th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--ui-surface);
  color: var(--ui-text-2);
  font-weight: 600;
  padding: 8px 4px;
  white-space: nowrap;
  font-size: 0.8rem;
}
.rank-h,
.rank {
  position: sticky;
  left: 0;
  z-index: 3;
  background: var(--ui-surface);
  width: 52px;
  min-width: 52px;
  color: var(--ui-text-2);
  font-weight: 600;
}
.rank-h {
  z-index: 4;
}
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 5px;
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1;
}
.rank-badge.r1 {
  background: #e11d2e;
  color: #fff;
}
.rank-badge.r2 {
  background: #f06428;
  color: #fff;
}
.rank-badge.r3 {
  background: #ebb024;
  color: #fff;
}
.rank-badge.r-other {
  background: var(--ui-fill-hover);
  color: var(--ui-text-2);
}
.rank-badge.bot {
  background: rgba(16, 185, 129, 0.14);
  color: var(--watch-down);
}
.sector-cell {
  display: block;
  width: 100%;
  min-width: 106px;
  padding: 10px 6px;
  cursor: pointer;
  background: var(--ui-surface);
  border: 2px solid transparent;
  font: inherit;
  color: inherit;
  text-align: center;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.sector-cell:hover {
  background: var(--ui-fill-hover);
}
.sector-cell .n {
  display: block;
  font-weight: 600;
  font-size: 0.85rem;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 108px;
  margin: 0 auto;
}
.sector-cell .v {
  display: block;
  font-size: 0.85rem;
  font-weight: 700;
  margin-top: 4px;
}
.sector-cell .v.up {
  color: var(--watch-up);
}
.sector-cell .v.down {
  color: var(--watch-down);
}
.sector-cell .v.flat {
  color: var(--ui-text-2);
}
.sector-cell.hl {
  border-color: #e11d2e !important;
  background: rgba(225, 29, 46, 0.08) !important;
}
.sector-cell.skeleton {
  min-height: 54px;
  background: var(--ui-fill-hover);
}
.sector-cell.empty {
  color: var(--ui-text-3);
  cursor: default;
}
tr.sep td {
  background: var(--ui-fill-hover);
  height: 6px;
  padding: 0;
  border-left: 0;
  border-right: 0;
}
</style>
