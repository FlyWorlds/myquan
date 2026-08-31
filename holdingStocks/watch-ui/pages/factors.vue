<script setup lang="ts">
import type { FactorEntry } from '~/types/registry'

const { factors, factorCategories, loading, error, fetchFactors } = useRegistry()

onMounted(() => {
  fetchFactors()
})

useHead({ title: '因子说明 · 持仓盯盘' })

const activeCat = ref<string>('all')

const fallbackCats = [
  { id: 'execution', label: '开盘执行', hint: '开盘突破买卖与止损' },
  { id: 'drawdown', label: '回撤补仓', hint: '回撤加减仓预警' },
  { id: 'take_profit', label: '止盈持股', hint: '牛市持股 / 止盈叠加' },
  { id: 'momentum', label: '动量', hint: '动量、近高、ETF 轮动' },
  { id: 'reversal', label: '反转', hint: '超跌与流动性反转' },
  { id: 'chan', label: '缠论', hint: '结构买卖点与笔盈亏比' },
  { id: 'sentiment', label: '情绪题材', hint: '涨停情绪、题材、主题' },
  { id: 'quality', label: '选股质量', hint: '契合池、熊盾、龙头' },
]

const catalog = computed(() => (factorCategories.value.length ? factorCategories.value : fallbackCats))

function countOf(catId: string) {
  return factors.value.filter((f) => (f.category || 'momentum') === catId).length
}

const visibleSections = computed(() => {
  const cats = catalog.value.filter((c) => countOf(c.id) > 0)
  if (activeCat.value === 'all') return cats
  return cats.filter((c) => c.id === activeCat.value)
})

function itemsOf(catId: string): FactorEntry[] {
  return factors.value.filter((f) => (f.category || 'momentum') === catId)
}
</script>

<template>
  <div class="mx-auto max-w-7xl px-4 py-4">
    <header class="mb-5">
      <h1 class="text-2xl font-bold">因子说明</h1>
      <p class="mt-1 text-sm text-ui-text-2">
        因子按经济含义分类；策略是因子组合。悬停 <strong>0.5 秒</strong> 查看规则与挂载策略。
      </p>
    </header>

    <nav v-if="factors.length" class="factor-cat-nav" aria-label="因子分类">
      <button
        type="button"
        class="factor-cat-chip"
        :class="activeCat === 'all' ? 'factor-cat-chip-active' : ''"
        @click="activeCat = 'all'"
      >
        全部 <span class="opacity-70">{{ factors.length }}</span>
      </button>
      <button
        v-for="c in catalog.filter((x) => countOf(x.id))"
        :key="c.id"
        type="button"
        class="factor-cat-chip"
        :class="[`factor-cat-chip--${c.id}`, activeCat === c.id ? 'factor-cat-chip-active' : '']"
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

    <p v-if="!loading && !error && !factors.length" class="text-sm text-ui-text-2">暂无注册因子。</p>
  </div>
</template>
