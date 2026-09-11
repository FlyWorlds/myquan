<script setup lang="ts">
import type { StrategyPickItem, StrategyPicks } from '~/types/snapshot'
import { stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'

const props = defineProps<{ picks?: StrategyPicks | null }>()

const kindLabel: Record<string, string> = {
  locked: '锁定名单',
  pool: '宽宇宙换池',
  weekly: '周频选股',
  daily: '日频选股',
  signals: '事件信号',
  none: '无截面选股',
}

/** 默认折叠，不挡下方/上方实时信号 */
const expanded = ref(false)

function categoryOf(it: StrategyPickItem): string {
  const c = String(it.分类 || it.category || '')
  if (c) return c
  if (it.pool_src === 'self') return '自选'
  return '策略池'
}

const grouped = computed(() => {
  const items = props.picks?.items || []
  const order: string[] = []
  const map = new Map<string, StrategyPickItem[]>()
  for (const it of items) {
    const cat = categoryOf(it)
    if (!map.has(cat)) {
      map.set(cat, [])
      order.push(cat)
    }
    map.get(cat)!.push(it)
  }
  order.sort((a, b) => {
    if (a === '自选') return -1
    if (b === '自选') return 1
    return 0
  })
  return order.map((label) => ({ label, items: map.get(label) || [] }))
})

const totalCount = computed(() =>
  grouped.value.reduce((n, g) => n + g.items.length, 0),
)

/** 默认落在非自选池（因子27/策略池） */
const activeCat = ref('')
watch(
  grouped,
  (gs) => {
    if (!gs.length) {
      activeCat.value = ''
      return
    }
    if (gs.some((g) => g.label === activeCat.value)) return
    const pool = gs.find((g) => g.label !== '自选')
    activeCat.value = (pool || gs[0]).label
  },
  { immediate: true },
)

const activeItems = computed(() => {
  const g = grouped.value.find((x) => x.label === activeCat.value)
  return g?.items || []
})
</script>

<template>
  <div v-if="picks" class="card mt-4 overflow-hidden">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-ui-surface-2/40"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <div class="min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="text-sm font-bold">选股 / 池名单</h3>
          <span class="rounded-full bg-ui-surface-2 px-2 py-0.5 text-xs text-ui-text-2">
            {{ picks.live ? '实时' : (kindLabel[picks.kind] || picks.kind) }}
          </span>
          <span class="text-xs text-ui-text-3">共 {{ totalCount }} 只</span>
        </div>
        <p class="mt-0.5 truncate text-xs text-ui-text-3">
          {{ expanded ? '点击收起' : '默认折叠 · 点击展开查看池内标的' }}
        </p>
      </div>
      <span
        class="shrink-0 text-ui-text-2 transition-transform"
        :class="expanded ? 'rotate-180' : ''"
        aria-hidden="true"
      >▾</span>
    </button>

    <div v-show="expanded" class="border-t border-ui-hairline px-4 pb-4 pt-3">
      <p v-if="picks.note" class="text-xs text-ui-text-3">{{ picks.note }}</p>
      <p class="mt-1 text-xs text-ui-text-3">
        <span v-if="picks.asOf">截至 {{ picks.asOf }}</span>
        <span v-if="picks.source" class="ml-2">来源 {{ picks.source }}</span>
      </p>

      <nav v-if="grouped.length" class="mt-3 flex flex-wrap gap-2" role="tablist" aria-label="池分类">
        <button
          v-for="g in grouped"
          :key="g.label"
          type="button"
          role="tab"
          class="tab-pill"
          :class="activeCat === g.label ? 'tab-pill-active' : 'tab-pill-idle'"
          :aria-selected="activeCat === g.label"
          @click.stop="activeCat = g.label"
        >
          {{ g.label }}
          <span class="ml-1 opacity-70">{{ g.items.length }}</span>
        </button>
      </nav>

      <div v-if="activeItems.length" class="mt-3 max-h-[22rem] overflow-auto">
        <table class="min-w-full text-sm">
          <thead class="sticky top-0 z-[1] bg-ui-surface text-left text-ui-text-2">
            <tr>
              <th class="px-2 py-1">#</th>
              <th class="px-2 py-1">标的</th>
              <th class="px-2 py-1">附加</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="it in activeItems"
              :key="`${activeCat}-${it.symbol}-${it.code}-${it.rank}`"
              class="border-t border-ui-hairline/60"
            >
              <td class="px-2 py-1 text-ui-text-3">{{ it.rank ?? '—' }}</td>
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
                <template v-if="activeCat === '自选'">公共自选 · 全策略共用</template>
                <template v-else-if="it.thr != null && it.oos_pl_ratio != null">
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
  </div>
</template>
