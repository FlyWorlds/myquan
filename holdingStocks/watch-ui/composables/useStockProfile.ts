import type { StockProfile } from '~/types/stockProfile'

const cache = new Map<string, StockProfile>()
const inflight = new Map<string, Promise<StockProfile>>()
const SS_PREFIX = 'watch_sp_'

function digitsOf(code?: string | number | null): string {
  const d = String(code || '').replace(/\D/g, '')
  if (d.length < 6) return ''
  return d.slice(-6).padStart(6, '0')
}

function readSession(code: string): StockProfile | null {
  if (!import.meta.client) return null
  try {
    const raw = sessionStorage.getItem(SS_PREFIX + code)
    if (!raw) return null
    const data = JSON.parse(raw) as StockProfile
    if (!data || data.error) return null
    cache.set(code, data)
    return data
  } catch {
    return null
  }
}

function writeSession(code: string, data: StockProfile) {
  if (!import.meta.client || data.error) return
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
    return cache.get(c) || readSession(c)
  }

  async function load(code?: string | number | null): Promise<StockProfile | null> {
    const c = digitsOf(code)
    if (!c) return null
    const hit = peek(c)
    if (hit) return hit
    const pending = inflight.get(c)
    if (pending) return pending
    const req = $fetch<StockProfile>('/api/stock/profile', { query: { code: c } })
      .then((data) => {
        cache.set(c, data)
        writeSession(c, data)
        inflight.delete(c)
        return data
      })
      .catch((err) => {
        inflight.delete(c)
        const failed: StockProfile = {
          code: c,
          name: c,
          error: err instanceof Error ? err.message : 'profile unavailable',
        }
        return failed
      })
    inflight.set(c, req)
    return req
  }

  return { load, peek, digitsOf }
}
