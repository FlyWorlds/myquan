<script setup lang="ts">
import type { FactorEntry } from '~/types/registry'
import { FACTOR_CATEGORY_CATALOG, withResolvedCategory } from '~/utils/factorCategories'

const { factors, factorCategories, loading, error, fetchFactors } = useRegistry()

onMounted(() => {
  fetchFactors()
})

useHead({ title: '因子说明 · 持仓盯盘' })

const activeCat = ref<string>('all')

const normalized = computed(() => factors.value.map(withResolvedCategory))

const catalog = computed(() => {
  const fromApi = factorCategories.value.filter((c) => c.id && c.label)
  return fromApi.length ? fromApi : FACTOR_CATEGORY_CATALOG
})

function countOf(catId: string) {
  return normalized.value.filter((f) => f.category === catId).length
}

const visibleSections = computed(() => {
  const cats = catalog.value.filter((c) => countOf(c.id) > 0)
  if (activeCat.value === 'all') return cats
  return cats.filter((c) => c.id === activeCat.value)
})

function itemsOf(catId: string): FactorEntry[] {
  return normalized.value.filter((f) => f.category === catId)
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4">
    <header class="mb-5">
      <h1 class="text-2xl font-bold">因子说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        按开盘执行 / 回撤补仓 / 止盈 / 动量 / 反转 / 缠论 / 情绪题材 / 选股质量分组。
        悬停 <strong>0.5 秒</strong> 查看规则。
      </p>
    </header>

    <nav v-if="normalized.length" class="factor-cat-nav" aria-label="因子分类">
      <button
        type="button"
        class="factor-cat-chip"
        :class="activeCat === 'all' ? 'factor-cat-chip-active' : ''"
        @click="activeCat = 'all'"
      >
        全部 <span class="opacity-70">{{ normalized.length }}</span>
      </button>
      <button
        v-for="c in catalog.filter((x) => countOf(x.id))"
        :key="c.id"
        type="button"
        class="factor-cat-chip"
        :class="activeCat === c.id ? 'factor-cat-chip-active' : ''"
        @click="activeCat = c.id"
      >
        {{ c.label }} <span class="opacity-70">{{ countOf(c.id) }}</span>
      </button>
    </nav>

    <p v-if="loading" class="text-sm text-ui-text-2">加载中…</p>
    <p v-else-if="error" class="text-sm text-ui-danger">{{ error }}</p>

    <template v-else>
      <section v-for="sec in visibleSections" :key="sec.id" class="mb-8">
        <header class="factor-cat-head" :class="`factor-cat-head--${sec.id}`">
          <h2 class="text-lg font-bold">{{ sec.label }}</h2>
          <p class="text-xs text-ui-text-3">{{ sec.hint }}</p>
        </header>
        <div class="grid gap-3 overflow-visible md:grid-cols-2 xl:grid-cols-3">
          <FactorCard v-for="f in itemsOf(sec.id)" :key="f.id" :factor="f" />
        </div>
      </section>
    </template>

    <p v-if="!loading && !error && !normalized.length" class="text-sm text-ui-text-2">暂无注册因子。</p>
  </div>
</template>
