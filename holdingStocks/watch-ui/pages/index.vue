<script setup lang="ts">
useWatchWs()
const store = useWatchStore()
const { snapshot, strategies, wsStatus, privacyHidden } = storeToRefs(store)

const activeTab = ref('holdings')

if (import.meta.client) {
  activeTab.value = localStorage.getItem('holdings_active_tab') || 'holdings'
}

const strategyTabs = computed(() => {
  if (strategies.value.length) return strategies.value
  return snapshot.value?.strategies || []
})

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
          · <span class="text-xs text-ui-text-3">{{ wsStatus }}</span>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="btn btn-ghost" @click="store.togglePrivacy()">
          {{ privacyHidden ? '显示持仓' : '隐藏持仓' }}
        </button>
      </div>
    </header>

    <nav class="mb-4 flex flex-wrap gap-2">
      <button
        type="button"
        class="tab-pill"
        :class="activeTab === 'holdings' ? 'tab-pill-active' : 'tab-pill-idle'"
        @click="activeTab = 'holdings'"
      >
        持仓
      </button>
      <button
        v-for="tab in strategyTabs"
        :key="tab.id"
        type="button"
        class="tab-pill"
        :class="activeTab === tab.id ? 'tab-pill-active' : 'tab-pill-idle'"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </nav>

    <section v-show="activeTab === 'holdings'" class="space-y-4">
      <IndexBar v-if="snapshot" :indices="snapshot.indices" />
      <AccountSummary v-if="snapshot" :account="snapshot.account" />
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <HoldingCard v-for="row in snapshot?.holdings || []" :key="String(row.代码)" :row="row" />
      </div>
    </section>

    <section v-show="activeTab === 'strategy1'">
      <StrategyInfoPanel v-if="strategy1Tab" :tab="strategy1Tab" class="mb-4" />
      <Strategy1Panel v-if="snapshot" :rows="snapshot.strategy1" :phase="snapshot.phase" />
    </section>

    <section v-for="tab in strategyTabs.filter((t) => t.id !== 'strategy1')" :key="tab.id" v-show="activeTab === tab.id">
      <StrategyInfoPanel :tab="tab" />
    </section>

    <p class="mt-6 text-xs leading-relaxed text-ui-text-3">
      盯盘默认绑定 {{ snapshot?.strategy?.name }}。策略1 Tab 展示早盘过门/阈值实时表；其余 Tab 为注册表因子说明。
      完整说明见
      <NuxtLink to="/strategies" class="text-accent hover:underline">策略说明</NuxtLink>
      、
      <NuxtLink to="/factors" class="text-accent hover:underline">因子说明</NuxtLink>
      。
      当前 Tab：{{ activeTab === 'holdings' ? '持仓' : tabLabel(activeTab) }}。
    </p>
  </div>
</template>
