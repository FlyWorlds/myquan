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
        数据来自 <code>strategy</code> 注册表，与 <code>/api/strategies</code> 同源；新增或改策略后重启 watch 即可同步。
      </p>
    </header>

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <div v-else class="space-y-4">
      <div
        v-for="tab in strategies"
        :id="tab.id"
        :key="tab.id"
        class="scroll-mt-24"
      >
        <StrategyInfoPanel :tab="tab" />
        <p v-if="tab.aliases?.length" class="mt-2 text-xs text-ui-text-3">
          别名：{{ tab.aliases.join('、') }}
        </p>
        <p v-if="tab.implemented === false" class="mt-1 text-xs text-ui-text-3">（尚未完整实现）</p>
      </div>
    </div>

    <p v-if="!loading && !error && !strategies.length" class="text-sm text-ui-text-2">暂无注册策略。</p>
  </div>
</template>
