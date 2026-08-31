import type { FactorCategory, FactorEntry, StrategyEntry } from '~/types/registry'

export function useRegistry() {
  const strategies = ref<StrategyEntry[]>([])
  const factors = ref<FactorEntry[]>([])
  const factorCategories = ref<FactorCategory[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchStrategies() {
    loading.value = true
    error.value = null
    try {
      strategies.value = await $fetch<StrategyEntry[]>('/api/strategies', { cache: 'no-store' })
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载策略失败'
    } finally {
      loading.value = false
    }
  }

  async function fetchFactors() {
    loading.value = true
    error.value = null
    try {
      const data = await $fetch<{ categories?: FactorCategory[]; factors?: FactorEntry[] } | FactorEntry[]>(
        '/api/factors',
        { cache: 'no-store' },
      )
      if (Array.isArray(data)) {
        factors.value = data
        factorCategories.value = []
      } else {
        factorCategories.value = data.categories || []
        factors.value = data.factors || []
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载因子失败'
    } finally {
      loading.value = false
    }
  }

  return { strategies, factors, factorCategories, loading, error, fetchStrategies, fetchFactors }
}
