<script setup lang="ts">
import type { StrategyEntry, StrategyRegistryKind } from '~/types/registry'

const { strategies, loading, error, fetchStrategies } = useRegistry()

onMounted(() => {
  fetchStrategies()
})

useHead({ title: '策略说明 · 持仓盯盘' })

const REGISTRY_SECTIONS: { kind: StrategyRegistryKind; title: string; hint: string }[] = [
  {
    kind: 'watch',
    title: '盯盘策略',
    hint: '有实时面板，出现在持仓盯盘首页 Tab。',
  },
  {
    kind: 'production',
    title: '完整策略',
    hint: '独立组合与执行逻辑，暂无盯盘实时表。',
  },
  {
    kind: 'combo',
    title: '因子组合',
    hint: '用因子池里的选股/结构因子挂成持有策略（可再叠开盘执行因子）。',
  },
  {
    kind: 'research',
    title: '研究',
    hint: '情绪/宏观对照等研究入口，非日常盯盘。',
  },
]

function sectionItems(kind: StrategyRegistryKind) {
  return strategies.value.filter((s) => (s.registry_kind || 'production') === kind)
}

const hasAny = computed(() => REGISTRY_SECTIONS.some((sec) => sectionItems(sec.kind).length > 0))
</script>

<template>
  <div class="page-shell">
    <header class="mb-6">
      <h1 class="text-2xl font-bold">策略说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        策略 = 因子组合 + 执行。悬停 <strong>0.5 秒</strong> 看绑定因子。
        单因子规则见
        <NuxtLink to="/factors" class="text-accent hover:underline">因子说明</NuxtLink>
        。
      </p>
    </header>

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <template v-else>
      <section
        v-for="sec in REGISTRY_SECTIONS"
        :key="sec.kind"
        class="mb-8"
      >
        <header v-if="sectionItems(sec.kind).length" class="mb-3">
          <h2 class="text-lg font-bold">{{ sec.title }}</h2>
          <p class="text-xs text-ui-text-3">{{ sec.hint }}</p>
        </header>
        <div
          v-if="sectionItems(sec.kind).length"
          class="grid gap-3 overflow-visible md:grid-cols-2 xl:grid-cols-3"
        >
          <StrategyRegistryCard
            v-for="tab in sectionItems(sec.kind)"
            :key="tab.id"
            :tab="tab as StrategyEntry"
          />
        </div>
      </section>
    </template>

    <p v-if="!loading && !error && !hasAny" class="text-sm text-ui-text-2">暂无注册策略。</p>
  </div>
</template>
