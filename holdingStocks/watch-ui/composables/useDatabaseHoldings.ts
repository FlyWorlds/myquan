interface DatabasePosition {
  qty: number
  available?: number | null
  cost?: number | null
  name?: string
  market?: string
  buy_time?: string | null
  peak_high?: number | null
  buy_fees_remaining?: number
}

export interface DatabasePaperState {
  revision: number
  holdings: {
    positions: Record<string, DatabasePosition>
    account_cash?: number | null
    account_total?: number | null
    updated_at?: string | null
    realized_today?: Record<string, { session?: string; signal_time?: string; first_hit_ts?: string }>
  }
  trades?: Array<{ code?: string; side?: string; session?: string; time?: string; reset_archived?: boolean }>
}

export function useDatabaseHoldings() {
  const store = useWatchStore()
  const error = ref('')
  let timer: ReturnType<typeof setInterval> | undefined
  let pending = false
  let stopped = false
  async function refresh() {
    if (pending || stopped) return
    pending = true
    try {
      const data = await $fetch<DatabasePaperState>('/api/holdings/state', { cache: 'no-store' })
      if (!stopped) {
        store.setPaperState(data)
        error.value = ''
      }
    } catch {
      if (!stopped) error.value = '数据库持仓不可用，当前为上次数据'
    } finally {
      pending = false
    }
  }
  onMounted(() => {
    void refresh()
    timer = setInterval(() => void refresh(), 5000)
  })
  onBeforeUnmount(() => {
    stopped = true
    if (timer) clearInterval(timer)
  })
  return { error, refresh }
}
