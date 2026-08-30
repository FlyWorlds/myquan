import { onMounted, onUnmounted } from 'vue'
import type { StrategyTab, WatchSnapshot } from '~/types/snapshot'

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

export function useWatchWs() {
  const store = useWatchStore()
  let ws: WebSocket | null = null
  let retry = 0
  let timer: number | undefined
  let lastTs: number | null = null

  async function loadStrategies() {
    try {
      const data = await $fetch<StrategyTab[]>('/api/strategies', { cache: 'no-store' })
      store.setStrategies(data)
    } catch {
      /* ignore */
    }
  }

  function applySnapshot(data: WatchSnapshot) {
    if (data.type !== 'snapshot') return
    if (data.ts != null && lastTs != null && data.ts === lastTs) return
    lastTs = data.ts ?? lastTs
    store.setSnapshot(data)
  }

  async function fallbackSync() {
    try {
      const data = await $fetch<WatchSnapshot>('/api/snapshot', {
        query: { t: Date.now() },
        cache: 'no-store',
      })
      applySnapshot(data)
      store.wsStatus = '兜底同步 ' + (data.updatedAt || '')
    } catch {
      store.wsStatus = '推送断开，等待重连…'
    }
  }

  function connect() {
    try {
      ws = new WebSocket(wsUrl())
    } catch {
      store.wsStatus = 'WebSocket 不可用'
      void fallbackSync()
      return
    }
    ws.onopen = () => {
      retry = 0
      store.wsStatus = 'WebSocket 已连接'
    }
    ws.onmessage = (ev) => {
      try {
        applySnapshot(JSON.parse(ev.data || '{}') as WatchSnapshot)
        store.wsStatus = '实时 ' + (store.snapshot?.updatedAt || '')
      } catch {
        /* ignore */
      }
    }
    ws.onclose = () => {
      ws = null
      store.wsStatus = '推送断开，重连中…'
      const delay = Math.min(15000, 1000 * 2 ** retry++)
      window.setTimeout(connect, delay)
    }
    ws.onerror = () => {
      ws?.close()
    }
  }

  onMounted(async () => {
    await loadStrategies()
    await fallbackSync()
    connect()
    timer = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) void fallbackSync()
    }, Math.max(5000, (store.snapshot?.refreshSec || 5) * 1000))
  })

  onUnmounted(() => {
    if (timer) window.clearInterval(timer)
    ws?.close()
  })
}
