import type { StockProfile } from '~/types/stockProfile'

const cache = new Map<string, StockProfile>()
const inflight = new Map<string, Promise<StockProfile>>()
const SS_PREFIX = 'watch_sp_v3_'

function digitsOf(code?: string | number | null): string {
  const d = String(code || '').replace(/\D/g, '')
  if (d.length < 6) return ''
  return d.slice(-6).padStart(6, '0')
}

function hasValuation(data?: StockProfile | null): boolean {
  const v = data?.valuation
  if (!v) return false
  return (
    v.market_cap_yi != null ||
    v.float_cap_yi != null ||
    v.pe != null ||
    v.pe_ttm != null ||
    v.pb != null
  )
}

function readSession(code: string): StockProfile | null {
  if (!import.meta.client) return null
  try {
    const raw = sessionStorage.getItem(SS_PREFIX + code)
    if (!raw) return null
    const data = JSON.parse(raw) as StockProfile
    if (!data || data.error || !hasValuation(data)) return null
    cache.set(code, data)
    return data
  } catch {
    return null
  }
}

function writeSession(code: string, data: StockProfile) {
  if (!import.meta.client || data.error || !hasValuation(data)) return
  try {
    sessionStorage.setItem(SS_PREFIX + code, JSON.stringify(data))
  } catch {
    /* quota / private mode */
  }
}

export function useStockProfile() {
  function peek(code?: string | number | null): StockProfile | null {
    const c = digitsOf(code)
    if (!c) return null
    const mem = cache.get(c)
    if (mem && hasValuation(mem)) return mem
    return readSession(c)
  }

  function clear(code?: string | number | null) {
    const c = digitsOf(code)
    if (!c) return
    cache.delete(c)
    inflight.delete(c)
    if (import.meta.client) {
      try {
        sessionStorage.removeItem(SS_PREFIX + c)
      } catch {
        /* ignore */
      }
    }
  }

  async function fetchWithRetry(code: string, retries = 1, delayMs = 400): Promise<StockProfile> {
    try {
      return await $fetch<StockProfile>('/api/stock/profile', { query: { code } })
    } catch (err) {
      if (retries > 0) {
        await new Promise((r) => setTimeout(r, delayMs))
        return fetchWithRetry(code, retries - 1, delayMs)
      }
      throw err
    }
  }

  async function load(code?: string | number | null): Promise<StockProfile | null> {
    const c = digitsOf(code)
    if (!c) return null
    const hit = peek(c)
    if (hit) return hit
    const pending = inflight.get(c)
    if (pending) return pending
    const req = fetchWithRetry(c, 1, 400)
      .then((data) => {
        if (hasValuation(data)) {
          cache.set(c, data)
          writeSession(c, data)
        }
        inflight.delete(c)
        return data
      })
      .catch((err) => {
        inflight.delete(c)
        const rawMsg = err instanceof Error ? err.message : String(err || '')
        let friendly = '基本面数据暂不可用'
        if (
          rawMsg.includes('Failed to fetch') ||
          rawMsg.includes('NetworkError') ||
          rawMsg.includes('fetch')
        ) {
          friendly = '网络连接波动或服务重连中'
        }
        const failed: StockProfile = {
          code: c,
          name: c,
          error: friendly,
        }
        return failed
      })
    inflight.set(c, req)
    return req
  }

  async function reload(code?: string | number | null): Promise<StockProfile | null> {
    clear(code)
    return load(code)
  }

  return { load, reload, clear, peek, digitsOf, hasValuation }
}
