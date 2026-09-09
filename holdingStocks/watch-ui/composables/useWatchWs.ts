import type { WatchSnapshot } from '~/types/snapshot'

/** 开发模式直连 Python :8765，绕过 Vite/Nuxt WS 代理（易 ECONNRESET 导致整站重启）。 */
function wsUrl(): string {
  const config = useRuntimeConfig()
  if (import.meta.dev) {
    const host = String(config.public.watchApiHost || '127.0.0.1')
    const port = String(config.public.watchApiPort || '8765')
    return `ws://${host}:${port}/ws`
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

let ws: WebSocket | null = null
let retry = 0
let reconnectTimer: number | undefined
let fallbackTimer: number | undefined
let pingTimer: number | undefined
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
      const config = useRuntimeConfig()
      const base = import.meta.dev
        ? `http://${config.public.watchApiHost || '127.0.0.1'}:${config.public.watchApiPort || '8765'}`
        : ''
      const data = await $fetch<WatchSnapshot>(`${base}/api/snapshot`, {
        query: { t: Date.now() },
        cache: 'no-store',
      })
      applySnapshot(data)
      if (data.boot) {
        store.setWsStatus('行情加载中…')
        return
      }
      store.setWsStatus('兜底同步 ' + (data.updatedAt || ''))
    } catch {
      if (ws?.readyState === WebSocket.OPEN) {
        store.setWsStatus('行情加载中…')
        return
      }
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
      if (pingTimer) window.clearInterval(pingTimer)
      // 浏览器端不发帧时，部分代理/服务端会 idle 断连；轻量 ping 保活
      pingTimer = window.setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          try {
            ws.send('ping')
          } catch {
            /* ignore */
          }
        }
      }, 25000)
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
      if (pingTimer) {
        window.clearInterval(pingTimer)
        pingTimer = undefined
      }
      if (!started) return
      store.setWsStatus('推送断开，HTTP 兜底中…')
      void fallbackSync()
      scheduleReconnect()
    }
    ws.onerror = () => {
      ws?.close()
    }
  }

  function snapshotAgeMs(): number {
    const raw = lastUpdatedAt || store.snapshot?.updatedAt || store.snapshot?.clock
    if (!raw) return Number.POSITIVE_INFINITY
    const t = Date.parse(String(raw).replace(/-/g, '/'))
    if (Number.isNaN(t)) return Number.POSITIVE_INFINITY
    return Date.now() - t
  }

  function resetFallbackTimer(refreshSec = 5) {
    if (fallbackTimer) window.clearInterval(fallbackTimer)
    fallbackTimer = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        void fallbackSync()
        return
      }
      // WS 假连接（热更新后常见）：超过 15s 没新快照则 HTTP 拉一次
      if (snapshotAgeMs() > 15000) void fallbackSync()
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
    if (pingTimer) {
      window.clearInterval(pingTimer)
      pingTimer = undefined
    }
    ws?.close()
    ws = null
  }

  if (import.meta.hot) {
    import.meta.hot.dispose(() => {
      stop()
    })
  }

  if (import.meta.client && !started) {
    void start()
  }

  return { start, stop }
}
