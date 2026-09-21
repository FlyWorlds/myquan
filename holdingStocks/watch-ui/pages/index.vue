<script setup lang="ts">
const store = useWatchStore()
const { snapshot, strategies, wsStatus, wsDisconnected, privacyHidden } = storeToRefs(store)

const activeTab = ref('holdings')

if (import.meta.client) {
  activeTab.value = localStorage.getItem('holdings_active_tab') || 'holdings'
}

/** 盯盘首页 Tab：后端 snapshot 仅含 watch_tab=true（strategy1/3/8/15/16） */
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
const strategy15Tab = computed(() => strategyTabs.value.find((t) => t.id === 'strategy15'))
const strategy16Tab = computed(() => strategyTabs.value.find((t) => t.id === 'strategy16'))
const strategy17Tab = computed(() => strategyTabs.value.find((t) => t.id === 'strategy17'))
const loading = computed(() => {
  // 仅「还没有任何快照」时全屏挡；boot 预热中仍展示 Tab，避免午休/收盘卡死在连接页
  if (snapshot.value) return false
  return wsStatus.value.includes('连接') || wsStatus.value.includes('加载')
})
const bootWarming = computed(() => Boolean(snapshot.value?.boot))

const slotHoldings = computed(() =>
  (snapshot.value?.holdings || []).filter(
    (r) => Boolean(r.置顶) && Number(r.持仓) > 0,
  ),
)

const closedHoldings = computed(() =>
  (snapshot.value?.holdings || []).filter((r) => {
    if (Number(r.持仓) > 0) return false
    // 今日平仓：纸面卖出（已实现）或三槽留痕；策略回放止损不进
    return Boolean(r.已实现) || Boolean(r.三槽平仓)
  }),
)

function isPaperHoldRow(r: (typeof slotHoldings.value)[number]) {
  return Number(r.持仓) <= 0 && String(r.持仓状态 || '') === '策略持有'
}

const paperHoldings = computed(() => {
  const taken = new Set(
    [...slotHoldings.value, ...closedHoldings.value].map((r) => String(r.代码 || '')),
  )
  return (snapshot.value?.holdings || []).filter(
    (r) => !taken.has(String(r.代码 || '')) && isPaperHoldRow(r),
  )
})

function alertTriggerSortKey(r: { 交易日?: string; 信号时刻?: string | null; 信号时间?: string | null; 买信号时间?: string | null; 卖信号时间?: string | null }) {
  const sess = String(r.交易日 || '').slice(0, 10)
  for (const k of ['信号时刻', '买信号时间', '卖信号时间', '信号时间'] as const) {
    const v = r[k]
    if (v == null || v === '') continue
    const s = String(v).trim()
    if (!s) continue
    if (!s.includes(' ') && sess && s.length >= 8 && s[2] === ':') return `${sess} ${s.slice(0, 8)}`
    return s
  }
  return '9999-99-99 99:99:99'
}

const otherHoldings = computed(() => {
  const taken = new Set(
    [...slotHoldings.value, ...closedHoldings.value, ...paperHoldings.value].map((r) =>
      String(r.代码 || ''),
    ),
  )
  return (snapshot.value?.holdings || [])
    .filter((r) => !taken.has(String(r.代码 || '')))
    .slice()
    .sort((a, b) => alertTriggerSortKey(a).localeCompare(alertTriggerSortKey(b)))
})
const slotMeta = computed(() => snapshot.value?.slotMeta)
const closedCount = computed(() => closedHoldings.value.length)
</script>

<template>
  <div class="page-shell" :class="{ 'privacy-hidden': privacyHidden }">
    <header class="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-ui-hairline pb-4">
      <div>
        <h1 class="text-2xl font-bold text-ui-text">持仓盯盘</h1>
        <p class="text-sm text-ui-text-2">
          <span class="sensitive">{{ snapshot?.strategy?.name || '策略一' }}</span>
          · {{ snapshot?.strategy?.factorsLabel }}
          · <span :class="wsDisconnected ? 'font-semibold text-ui-danger' : ''">{{ snapshot?.clock || '—' }}</span>
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

    <div
      v-else-if="bootWarming"
      class="mb-3 flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-ui-text-2"
    >
      <span class="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-ui-text-3 border-t-accent" />
      行情预热中（午休/收盘也可用）· 首屏数据稍后自动刷新
    </div>

    <template v-if="!loading">
      <section v-show="activeTab === 'holdings'" class="space-y-4">
        <IndexBar v-if="snapshot" :indices="snapshot.indices" />
        <AccountSummary v-if="snapshot" :account="snapshot.account" />
        <p v-if="snapshot && !snapshot.holdings?.length" class="text-sm text-ui-text-2">暂无持仓/当日预警；实仓登记或定盘池出现买入预警后显示于此。</p>
        <template v-else>
          <div v-if="slotHoldings.length" class="space-y-2">
            <div class="flex flex-wrap items-baseline justify-between gap-2">
              <h2 class="text-sm font-semibold text-ui-text">
                纸面持仓（置顶）
                <span class="ml-1 font-normal text-ui-text-2">
                  占槽 {{ slotMeta?.occupiedCount ?? 0 }}/{{ slotMeta?.max ?? 5 }}
                  <template v-if="slotMeta?.maxNewSymbolsPerSession != null">
                    · 今日新增 {{ slotMeta?.buysToday ?? 0 }}/{{ slotMeta?.maxNewSymbolsPerSession ?? 2 }}
                  </template>
                </span>
              </h2>
              <p class="text-xs text-ui-text-3">已经买入 / 待卖出 · 仅默认策略池入槽</p>
            </div>
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <HoldingCard v-for="row in slotHoldings" :key="'slot-' + String(row.代码)" :row="row" />
            </div>
          </div>
          <div v-if="closedHoldings.length" class="space-y-2">
            <div class="flex flex-wrap items-baseline justify-between gap-2">
              <h2 class="text-sm font-semibold text-ui-text">
                今日平仓
                <span class="ml-1 font-normal text-ui-text-2">
                  {{ closedCount }} · 不占槽
                </span>
              </h2>
              <p class="text-xs text-ui-text-3">仅当日四槽纸面卖出；下一交易日清空</p>
            </div>
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <HoldingCard v-for="row in closedHoldings" :key="'closed-' + String(row.代码)" :row="row" />
            </div>
          </div>
          <div v-if="otherHoldings.length" class="space-y-2">
            <div class="flex flex-wrap items-baseline justify-between gap-2">
              <h2 class="text-sm font-semibold text-ui-text-2">
                {{ slotHoldings.length || closedHoldings.length || paperHoldings.length ? '预警' : '持仓列表' }}
                <span class="ml-1 font-normal text-ui-text-3">{{ otherHoldings.length }}</span>
              </h2>
              <p class="text-xs text-ui-text-3">与策略十六图例同步 · 按触发时间升序（早→晚）</p>
            </div>
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <HoldingCard v-for="row in otherHoldings" :key="'other-' + String(row.代码)" :row="row" />
            </div>
          </div>
          <div v-if="paperHoldings.length" class="space-y-2">
            <div class="flex flex-wrap items-baseline justify-between gap-2">
              <h2 class="text-sm font-semibold text-ui-text-2">
                策略持有
                <span class="ml-1 font-normal text-ui-text-3">{{ paperHoldings.length }}</span>
              </h2>
              <p class="text-xs text-ui-text-3">日线回放仍持有、未入四槽 · 与策略十六「策略持有」同步</p>
            </div>
            <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <HoldingCard v-for="row in paperHoldings" :key="'paper-' + String(row.代码)" :row="row" />
            </div>
          </div>
        </template>
      </section>

      <section v-show="activeTab === 'strategy1'">
        <StrategyInfoPanel v-if="strategy1Tab" :tab="strategy1Tab" class="mb-4" />
        <Strategy1Panel v-if="snapshot" :rows="snapshot.strategy1" :phase="snapshot.phase" :slot-meta="snapshot.slotMeta" pool-category="策略池" />
        <StrategyPicksPanel :picks="strategy1Tab?.picks" />
      </section>

      <section v-show="activeTab === 'strategy3'">
        <StrategyInfoPanel v-if="strategy3Tab" :tab="strategy3Tab" class="mb-4" />
        <Strategy3Panel
          v-if="snapshot"
          :tab="strategy3Tab"
          :payload="snapshot.strategy3"
          :phase="snapshot.phase"
        />
        <StrategyPicksPanel :picks="strategy3Tab?.picks" />
      </section>

      <section v-show="activeTab === 'strategy8'">
        <StrategyInfoPanel v-if="strategy8Tab" :tab="strategy8Tab" class="mb-4" />
        <Strategy8Panel
          v-if="snapshot"
          :tab="strategy8Tab"
          :payload="snapshot.strategy8"
          :phase="snapshot.phase"
        />
        <StrategyPicksPanel :picks="strategy8Tab?.picks" />
      </section>
      <section v-show="activeTab === 'strategy15'">
        <StrategyInfoPanel v-if="strategy15Tab" :tab="strategy15Tab" class="mb-4" />
        <Strategy15Panel
          v-if="snapshot"
          :payload="snapshot.strategy15"
          :phase="snapshot.phase"
        />
        <StrategyPicksPanel :picks="strategy15Tab?.picks" />
      </section>
      <section v-show="activeTab === 'strategy16'">
        <StrategyInfoPanel v-if="strategy16Tab" :tab="strategy16Tab" class="mb-4" />
        <Strategy1Panel
          v-if="snapshot"
          :rows="snapshot.strategy16 || []"
          :phase="snapshot.phase"
          :slot-meta="snapshot.slotMeta"
          pool-category="因子27"
        />
        <StrategyPicksPanel :picks="strategy16Tab?.picks" />
      </section>
      <section v-show="activeTab === 'strategy17'">
        <StrategyInfoPanel v-if="strategy17Tab" :tab="strategy17Tab" class="mb-4" />
        <Strategy1Panel
          v-if="snapshot"
          :rows="snapshot.strategy17 || []"
          :phase="snapshot.phase"
          :slot-meta="snapshot.slotMeta"
          pool-category="紫阳真君"
        />
        <StrategyPicksPanel :picks="strategy17Tab?.picks" />
      </section>
    </template>

    <p class="mt-6 text-xs leading-relaxed text-ui-text-3">
      盯盘 Tab 仅展示有实时面板的策略（策略1 / 3 / 8 / 15 / 16 / 17）。因子持有模板、研究型条目见
      <NuxtLink to="/strategies" class="text-accent hover:underline">策略说明</NuxtLink>
      、
      <NuxtLink to="/factors" class="text-accent hover:underline">因子说明</NuxtLink>
      。
      当前 Tab：{{ activeTab === 'holdings' ? '持仓' : tabLabel(activeTab) }}。
    </p>
  </div>
</template>
