import type { MarketRadar } from '~/types/marketRadar'

export function useMarketRadar() {
  const data = useState<MarketRadar | null>('market-radar', () => null)
  const loading = ref(false)
  const error = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false
  async function refresh(force = false) {
    if (loading.value) return
    loading.value = true
    try {
      const response = await fetch(`/api/market-radar${force ? '?refresh=1' : ''}`, { cache: 'no-store', signal: AbortSignal.timeout(12000) })
      if (!response.ok) throw new Error(`数据服务暂不可用（${response.status}）`)
      data.value = await response.json()
      error.value = ''
    } catch (e) { data.value = null; error.value = e instanceof Error ? e.message : '数据读取失败' }
    finally {
      loading.value = false
      if (!stopped) {
        if (timer) clearTimeout(timer)
        timer = setTimeout(() => refresh(), data.value?.refreshing ? 2000 : 15000)
      }
    }
  }
  onMounted(() => { void refresh() })
  onBeforeUnmount(() => { stopped = true; if (timer) clearTimeout(timer) })
  return { data, loading, error, refresh }
}
