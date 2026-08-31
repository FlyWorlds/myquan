<script setup lang="ts">
const { strategies, loading, error, fetchStrategies } = useRegistry()

onMounted(() => {
  fetchStrategies()
})

useHead({ title: '策略说明 · 持仓盯盘' })
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4">
    <header class="mb-6">
      <h1 class="text-2xl font-bold">策略说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        卡片样式与持仓 Tab 一致；鼠标悬停 <strong>1 秒</strong> 后显示完整说明、因子绑定与选股信号。
      </p>
    </header>

    <RegistryAnchorNav
      v-if="strategies.length"
      :items="strategies.map((s) => ({ id: s.id }))"
      aria-label="策略锚点"
    />

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <div v-else class="grid gap-3 overflow-visible md:grid-cols-2 xl:grid-cols-3">
      <StrategyRegistryCard v-for="tab in strategies" :key="tab.id" :tab="tab" />
    </div>

    <p v-if="!loading && !error && !strategies.length" class="text-sm text-ui-text-2">暂无注册策略。</p>
  </div>
</template>
