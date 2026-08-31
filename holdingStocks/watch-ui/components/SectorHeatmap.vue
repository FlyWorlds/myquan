<script setup lang="ts">
import type { SectorKindPayload } from '~/types/sectors'
import { formatMetricValue } from '~/composables/useSectorsLive'

const props = defineProps<{
  kind: SectorKindPayload
  topN: number
  metric: string
}>()

const emit = defineEmits<{
  select: [name: string]
  drill: [name: string]
}>()

const selected = ref<string | null>(null)

function fmtVal(metric: string, v: number | null | undefined) {
  return formatMetricValue(metric, v)
}

function clsNum(v: number | null | undefined) {
  const x = Number(v)
  if (!Number.isFinite(x) || x === 0) return 'flat'
  return x > 0 ? 'up' : 'down'
}

function cellClass(rank: number, isTop: boolean, name: string) {
  const parts = ['sector-cell']
  if (isTop && rank === 1) parts.push('r1')
  else if (isTop && rank === 2) parts.push('r2')
  else if (isTop && rank === 3) parts.push('r3')
  if (selected.value === name) parts.push('hl')
  return parts.join(' ')
}

function onPick(name: string) {
  if (!name) return
  if (selected.value === name) {
    emit('drill', name)
    return
  }
  selected.value = name
  emit('select', name)
}

function clearSelection() {
  selected.value = null
}

defineExpose({ clearSelection, selected })
</script>

<template>
  <div class="sector-heatmap-wrap overflow-auto rounded-xl border border-ui-hairline bg-ui-surface">
    <table class="sector-heat w-full min-w-[720px] border-collapse text-xs">
      <thead>
        <tr>
          <th class="rank-h" />
          <th v-for="d in kind.dates" :key="d">{{ d }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in topN" :key="`t-${r}`">
          <td class="rank">{{ r }}</td>
          <td v-for="(di) in kind.dates.length" :key="`t-${r}-${di - 1}`">
            <button
              v-if="kind.by_metric[metric]?.top?.[di - 1]?.[r - 1]"
              type="button"
              :class="cellClass(r, true, kind.by_metric[metric].top[di - 1][r - 1].name)"
              @click="onPick(kind.by_metric[metric].top[di - 1][r - 1].name)"
            >
              <span class="n">{{ kind.by_metric[metric].top[di - 1][r - 1].name }}</span>
              <span class="v" :class="clsNum(kind.by_metric[metric].top[di - 1][r - 1].value)">
                {{ fmtVal(metric, kind.by_metric[metric].top[di - 1][r - 1].value) }}
              </span>
            </button>
            <span v-else class="sector-cell empty">-</span>
          </td>
        </tr>
        <tr class="sep">
          <td :colspan="kind.dates.length + 1" />
        </tr>
        <tr v-for="i in topN" :key="`b-${i}`">
          <td class="rank bot">{{ topN - i + 1 }}</td>
          <td v-for="(di) in kind.dates.length" :key="`b-${i}-${di - 1}`">
            <button
              v-if="kind.by_metric[metric]?.bottom?.[di - 1]?.[i - 1]"
              type="button"
              :class="cellClass(topN - i + 1, false, kind.by_metric[metric].bottom[di - 1][i - 1].name)"
              @click="onPick(kind.by_metric[metric].bottom[di - 1][i - 1].name)"
            >
              <span class="n">{{ kind.by_metric[metric].bottom[di - 1][i - 1].name }}</span>
              <span class="v" :class="clsNum(kind.by_metric[metric].bottom[di - 1][i - 1].value)">
                {{ fmtVal(metric, kind.by_metric[metric].bottom[di - 1][i - 1].value) }}
              </span>
            </button>
            <span v-else class="sector-cell empty">-</span>
          </td>
        </tr>
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
  padding: 6px 4px;
  white-space: nowrap;
}
.rank-h,
.rank {
  position: sticky;
  left: 0;
  z-index: 3;
  background: var(--ui-surface);
  width: 28px;
  min-width: 28px;
  color: var(--ui-text-2);
  font-weight: 700;
}
.rank-h { z-index: 4; }
.rank.bot { color: var(--watch-down); }
.sector-cell {
  display: block;
  width: 100%;
  min-width: 88px;
  padding: 6px 4px;
  cursor: pointer;
  background: var(--ui-surface);
  border: 0;
  font: inherit;
  color: inherit;
  text-align: center;
}
.sector-cell:hover { filter: brightness(0.97); }
.sector-cell .n {
  display: block;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 96px;
  margin: 0 auto;
}
.sector-cell .v { display: block; font-size: 0.75rem; margin-top: 2px; }
.sector-cell .v.up { color: var(--watch-up); }
.sector-cell .v.down { color: var(--watch-down); }
.sector-cell.r1 { background: #e11d2e; color: #fff; }
.sector-cell.r1 .v { color: #fff; }
.sector-cell.r2 { background: #f05a28; color: #fff; }
.sector-cell.r2 .v { color: #fff; }
.sector-cell.r3 { background: #f5a623; color: #fff; }
.sector-cell.r3 .v { color: #fff; }
.sector-cell.hl { background: #ff8c3a !important; color: #fff !important; }
.sector-cell.hl .v { color: #fff !important; }
.sector-cell.empty { color: var(--ui-text-3); cursor: default; }
tr.sep td { background: var(--ui-fill-hover); height: 6px; padding: 0; border-left: 0; border-right: 0; }
</style>
