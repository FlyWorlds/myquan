<script setup lang="ts">
const store = useWatchStore()
const { snapshot, strategies, wsStatus, wsDisconnected, privacyHidden } = storeToRefs(store)

const activeTab = ref('holdings')

if (import.meta.client) {
  activeTab.value = localStorage.getItem('holdings_active_tab') || 'holdings'
}

const strategyTabs = computed(() => {
  if (strategies.value.length) return strategies.value
  return snapshot.value?.strategies || []
})

const validTabIds = computed(() => new Set(['holdings', ...strategyTabs.value.map((t) => t.id)]))

watch(
  strategyTabs,
  () => {
    if (!validTabIds.value.has(activeTab.value)) activeTab.value = 'holdings'
  },
  { immediate: true },
)

watch(activeTab, (v) => {
  if (!import.meta.client) return
  try {
    localStorage.setItem('holdings_active_tab', v)
  } catch {
    /* ignore */
  }
})

function tabLabel(id: string) {
  return strategyTabs.value.find((t) => t.id === id)?.label || id
}

const strategy1Tab = computed(() => strategyTabs.value.find((t) => t.id === 'strategy1'))
const strategy3Tab = computed(() => strategyTabs.value.find((t) => t.id === 'strategy3'))
const strategy8Tab = computed(() => strategyTabs.value.find((t) => t.id === 'strategy8'))
const loading = computed(() => !snapshot.value && wsStatus.value.includes('连接'))
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4" :class="{ 'privacy-hidden': privacyHidden }">
    <header class="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-ui-hairline pb-4">
      <div>
        <h1 class="text-2xl font-bold text-ui-text">持仓盯盘</h1>
        <p class="text-sm text-ui-text-2">
          <span class="sensitive">{{ snapshot?.strategy?.name || '策略一' }}</span>
          · {{ snapshot?.strategy?.factorsLabel }}
          · <span>{{ snapshot?.clock || '—' }}</span>
          <span class="ml-2 rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">{{ snapshot?.phase }}</span>
          ·
          <span
            class="text-xs"
            :class="wsDisconnected ? 'font-semibold text-ui-danger' : 'text-ui-text-3'"
          >
            {{ wsStatus }}
          </span>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn btn-ghost" @click="store.togglePrivacy()">
          {{ privacyHidden ? '显示持仓' : '隐藏持仓' }}
        </button>
      </div>
    </header>

    <nav class="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="盯盘视图">
      <button
        type="button"
        role="tab"
        class="tab-pill"
        :class="activeTab === 'holdings' ? 'tab-pill-active' : 'tab-pill-idle'"
        :aria-selected="activeTab === 'holdings'"
        @click="activeTab = 'holdings'"
      >
        持仓
      </button>
      <button
        v-for="tab in strategyTabs"
        :key="tab.id"
        type="button"
        role="tab"
        class="tab-pill"
        :class="activeTab === tab.id ? 'tab-pill-active' : 'tab-pill-idle'"
        :aria-selected="activeTab === tab.id"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </nav>

    <div v-if="loading" class="card flex items-center justify-center gap-3 p-8 text-sm text-ui-text-2">
      <span class="inline-block h-5 w-5 animate-spin rounded-full border-2 border-ui-text-3 border-t-accent" />
      正在连接盯盘服务…
    </div>

    <template v-else>
      <section v-show="activeTab === 'holdings'" class="space-y-4">
        <IndexBar v-if="snapshot" :indices="snapshot.indices" />
        <AccountSummary v-if="snapshot" :account="snapshot.account" />
        <p v-if="snapshot && !snapshot.holdings?.length" class="text-sm text-ui-text-2">暂无登记持仓，定盘池与实仓会在此展示。</p>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <HoldingCard v-for="row in snapshot?.holdings || []" :key="String(row.代码)" :row="row" />
        </div>
      </section>

      <section v-show="activeTab === 'strategy1'">
        <StrategyInfoPanel v-if="strategy1Tab" :tab="strategy1Tab" class="mb-4" />
        <StrategyPicksPanel :picks="strategy1Tab?.picks" />
        <Strategy1Panel v-if="snapshot" :rows="snapshot.strategy1" :phase="snapshot.phase" class="mt-4" />
      </section>

      <section v-show="activeTab === 'strategy3'">
        <StrategyInfoPanel v-if="strategy3Tab" :tab="strategy3Tab" class="mb-4" />
        <StrategyPicksPanel :picks="strategy3Tab?.picks" />
        <Strategy3Panel
          v-if="snapshot"
          class="mt-4"
          :tab="strategy3Tab"
          :payload="snapshot.strategy3"
          :phase="snapshot.phase"
        />
      </section>

      <section v-show="activeTab === 'strategy8'">
        <StrategyInfoPanel v-if="strategy8Tab" :tab="strategy8Tab" class="mb-4" />
        <StrategyPicksPanel :picks="strategy8Tab?.picks" />
        <Strategy8Panel
          v-if="snapshot"
          class="mt-4"
          :tab="strategy8Tab"
          :payload="snapshot.strategy8"
          :phase="snapshot.phase"
        />
      </section>

      <section
        v-for="tab in strategyTabs.filter((t) => t.id !== 'strategy1' && t.id !== 'strategy3' && t.id !== 'strategy8')"
        :key="tab.id"
        v-show="activeTab === tab.id"
      >
        <StrategyInfoPanel :tab="tab" />
        <StrategyPicksPanel :picks="tab.picks" />
      </section>
    </template>

    <p class="mt-6 text-xs leading-relaxed text-ui-text-3">
      盯盘默认绑定 {{ snapshot?.strategy?.name || '策略一' }}。各策略 Tab 含注册表说明 + 选股/信号（有产物时）；策略1/3/8 另有实时表。
      完整说明见
      <NuxtLink to="/strategies" class="text-accent hover:underline">策略说明</NuxtLink>
      、
      <NuxtLink to="/factors" class="text-accent hover:underline">因子说明</NuxtLink>
      。
      当前 Tab：{{ activeTab === 'holdings' ? '持仓' : tabLabel(activeTab) }}。
    </p>
  </div>
</template>
