<script setup lang="ts">
import type { HoldingRow, StrategyPicks, StrategyTab } from '~/types/snapshot'

export type StrategyInnerView = 'signal' | 'chg' | 'pnl' | 'pool'

const props = withDefaults(
  defineProps<{
    strategyId: string
    tab?: StrategyTab | null
    picks?: StrategyPicks | null
    /** 供涨幅/收益 Tab 用的行（策略1/15/16） */
    rows?: HoldingRow[] | null
    defaultView?: StrategyInnerView
  }>(),
  { defaultView: 'signal' },
)

const storageKey = computed(() => `holdings_strategy_view_${props.strategyId}`)

const view = ref<StrategyInnerView>(props.defaultView)

if (import.meta.client) {
  try {
    const saved = localStorage.getItem(storageKey.value) as StrategyInnerView | null
    if (saved && ['signal', 'chg', 'pnl', 'pool'].includes(saved)) {
      view.value = saved
    }
  } catch {
    /* ignore */
  }
}

watch(view, (v) => {
  if (!import.meta.client) return
  try {
    localStorage.setItem(storageKey.value, v)
  } catch {
    /* ignore */
  }
})

const hasChg = computed(() =>
  (props.rows || []).some((r) => r.当日涨幅 != null || r.较开盘涨幅 != null),
)
const hasPnl = computed(() =>
  (props.rows || []).some((r) => r['策略收益%'] != null || r.策略收益 != null),
)
const poolCount = computed(() => props.picks?.items?.length ?? 0)

const tabs = computed(() => {
  const list: { id: StrategyInnerView; label: string; hint?: string }[] = [
    { id: 'signal', label: '信号' },
  ]
  if (hasChg.value) list.push({ id: 'chg', label: '股票涨幅' })
  if (hasPnl.value) list.push({ id: 'pnl', label: '策略累计' })
  list.push({
    id: 'pool',
    label: '策略股票池',
    hint: poolCount.value ? String(poolCount.value) : undefined,
  })
  return list
})

watch(
  tabs,
  (list) => {
    if (!list.some((t) => t.id === view.value)) {
      view.value = 'signal'
    }
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <StrategyInfoPanel v-if="tab" :tab="tab" class="mb-3" />

    <nav
      class="mb-3 flex flex-wrap gap-2"
      role="tablist"
      :aria-label="`${tab?.label || strategyId} 内容`"
    >
      <button
        v-for="t in tabs"
        :key="t.id"
        type="button"
        role="tab"
        class="tab-pill"
        :class="view === t.id ? 'tab-pill-active' : 'tab-pill-idle'"
        :aria-selected="view === t.id"
        @click="view = t.id"
      >
        {{ t.label }}
        <span v-if="t.hint" class="ml-1 text-xs font-normal opacity-70">{{ t.hint }}</span>
      </button>
    </nav>

    <div v-show="view === 'signal'">
      <slot name="signal" />
    </div>

    <div v-show="view === 'chg'">
      <slot name="chg">
        <Strategy1Panel
          v-if="rows?.length"
          :rows="rows"
          focus="chg"
          :pool-category="strategyId === 'strategy16' ? '因子27' : '策略池'"
        />
        <p v-else class="text-sm text-ui-text-2">暂无涨幅数据。</p>
      </slot>
    </div>

    <div v-show="view === 'pnl'">
      <slot name="pnl">
        <Strategy1Panel
          v-if="rows?.length"
          :rows="rows"
          focus="pnl"
          :pool-category="strategyId === 'strategy16' ? '因子27' : '策略池'"
        />
        <p v-else class="text-sm text-ui-text-2">暂无策略累计数据。</p>
      </slot>
    </div>

    <div v-show="view === 'pool'">
      <StrategyPicksPanel :picks="picks" title="策略股票池" />
    </div>
  </div>
</template>
