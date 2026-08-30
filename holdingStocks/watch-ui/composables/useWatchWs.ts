import type { WatchSnapshot } from '~/types/snapshot'

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

let ws: WebSocket | null = null
let retry = 0
let reconnectTimer: number | undefined
let fallbackTimer: number | undefined
let lastTs: number | null = null
let lastUpdatedAt: string | null = null
let started = false

export function useWatchWs() {
  const store = useWatchStore()

  function applySnapshot(data: WatchSnapshot) {
    if (data.type !== 'snapshot') return
    const sameTs = data.ts != null && lastTs != null && data.ts === lastTs
    const sameAt =
      data.updatedAt != null &&
      lastUpdatedAt != null &&
      data.updatedAt === lastUpdatedAt
    if (sameTs && sameAt) return
    lastTs = data.ts ?? lastTs
    lastUpdatedAt = data.updatedAt ?? lastUpdatedAt
    store.setSnapshot(data)
  }

  async function fallbackSync() {
    try {
      const data = await $fetch<WatchSnapshot>('/api/snapshot', {
        query: { t: Date.now() },
        cache: 'no-store',
      })
      applySnapshot(data)
      store.setWsStatus('兜底同步 ' + (data.updatedAt || ''))
    } catch {
      store.setWsStatus('推送断开，等待重连…')
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) window.clearTimeout(reconnectTimer)
    const delay = Math.min(15000, 1000 * 2 ** retry++)
    reconnectTimer = window.setTimeout(connect, delay)
  }

  function connect() {
    if (!started) return
    try {
      ws = new WebSocket(wsUrl())
    } catch {
      store.setWsStatus('WebSocket 不可用')
      void fallbackSync()
      return
    }
    ws.onopen = () => {
      retry = 0
      store.setWsStatus('WebSocket 已连接')
    }
    ws.onmessage = (ev) => {
      try {
        applySnapshot(JSON.parse(ev.data || '{}') as WatchSnapshot)
        store.setWsStatus('实时 ' + (store.snapshot?.updatedAt || ''))
      } catch {
        /* ignore */
      }
    }
    ws.onclose = () => {
      ws = null
      if (!started) return
      store.setWsStatus('推送断开，重连中…')
      scheduleReconnect()
    }
    ws.onerror = () => {
      ws?.close()
    }
  }

  function resetFallbackTimer(refreshSec = 5) {
    if (fallbackTimer) window.clearInterval(fallbackTimer)
    fallbackTimer = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) void fallbackSync()
    }, Math.max(5000, refreshSec * 1000))
  }

  async function start() {
    if (started) return
    started = true
    await fallbackSync()
    connect()
    resetFallbackTimer(store.snapshot?.refreshSec || 5)
    watch(
      () => store.snapshot?.refreshSec,
      (sec) => resetFallbackTimer(sec || 5),
    )
    if (import.meta.client) {
      window.addEventListener('beforeunload', stop)
    }
  }

  function stop() {
    started = false
    if (reconnectTimer) window.clearTimeout(reconnectTimer)
    reconnectTimer = undefined
    if (fallbackTimer) window.clearInterval(fallbackTimer)
    fallbackTimer = undefined
    ws?.close()
    ws = null
  }

  if (import.meta.client && !started) {
    void start()
  }

  return { start, stop }
}
