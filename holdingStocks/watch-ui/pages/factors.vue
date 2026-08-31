<script setup lang="ts">
const { factors, loading, error, fetchFactors } = useRegistry()

onMounted(() => {
  fetchFactors()
})

useHead({ title: '因子说明 · 持仓盯盘' })
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4">
    <header class="mb-6">
      <h1 class="text-2xl font-bold">因子说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        卡片样式与持仓 Tab 一致；鼠标悬停 <strong>1 秒</strong> 后显示规则摘要与挂载策略。
      </p>
    </header>

    <RegistryAnchorNav
      v-if="factors.length"
      :items="factors.map((f) => ({ id: f.id }))"
      aria-label="因子锚点"
    />

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <div v-else class="grid gap-3 overflow-visible md:grid-cols-2 xl:grid-cols-3">
      <FactorCard v-for="f in factors" :key="f.id" :factor="f" />
    </div>

    <p v-if="!loading && !error && !factors.length" class="text-sm text-ui-text-2">暂无注册因子。</p>
  </div>
</template>
