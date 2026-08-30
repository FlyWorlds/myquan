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
        数据来自 <code>strategy/factors</code> 注册表，与 <code>/api/factors</code> 同源；改因子描述或规则后重启 watch 即可同步。
      </p>
    </header>

    <RegistryAnchorNav
      v-if="factors.length"
      :items="factors.map((f) => ({ id: f.id }))"
      aria-label="因子锚点"
    />

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <div v-else class="space-y-4">
      <FactorCard v-for="f in factors" :key="f.id" :factor="f" />
    </div>

    <p v-if="!loading && !error && !factors.length" class="text-sm text-ui-text-2">暂无注册因子。</p>
  </div>
</template>
