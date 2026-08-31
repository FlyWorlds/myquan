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
    kind: 'factor_template',
    title: '因子模板',
    hint: '本质是因子 + 固定持有/换池规则，详见因子说明。',
  },
  {
    kind: 'research',
    title: '研究 / 宏观',
    hint: '归因、情绪统计等研究入口，非日常盯盘。',
  },
]

function sectionItems(kind: StrategyRegistryKind) {
  return strategies.value.filter((s) => (s.registry_kind || 'production') === kind)
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4">
    <header class="mb-6">
      <h1 class="text-2xl font-bold">策略说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        卡片样式与持仓 Tab 一致；鼠标悬停 <strong>0.5 秒</strong> 后显示完整说明。
        仅<strong>盯盘策略</strong>出现在首页 Tab，因子模板与研究型条目在此查阅。
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

    <p v-if="!loading && !error && !strategies.length" class="text-sm text-ui-text-2">暂无注册策略。</p>
  </div>
</template>
