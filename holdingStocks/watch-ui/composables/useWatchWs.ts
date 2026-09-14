import type { WatchSnapshot } from '~/types/snapshot'
import { parseSnapshotClockMs, wsStatusFromSnapshot } from '~/utils/format'

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

const STALE_PAGE_MS = 20000

export function useWatchWs() {
  const store = useWatchStore()

  function applyStatus(data: WatchSnapshot) {
    const alert = wsStatusFromSnapshot(data)
    if (alert) {
      store.setWsStatus(alert)
      return
    }
    store.setWsStatus('实时 ' + (data.updatedAt || data.clock || ''))
  }

  function applySnapshot(data: WatchSnapshot) {
    if (data.type !== 'snapshot') return
    const sameTs = data.ts != null && lastTs != null && data.ts === lastTs
    const sameAt =
      data.updatedAt != null &&
      lastUpdatedAt != null &&
      data.updatedAt === lastUpdatedAt
    if (sameTs && sameAt) {
      applyStatus(data)
      return
    }
    lastTs = data.ts ?? lastTs
    lastUpdatedAt = data.updatedAt ?? lastUpdatedAt
    store.setSnapshot(data)
    applyStatus(data)
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
    } catch {
      if (ws?.readyState === WebSocket.OPEN) {
        store.setWsStatus('网络异常，HTTP 拉快照失败')
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
      if (!wsStatusFromSnapshot(store.snapshot)) {
        store.setWsStatus('WebSocket 已连接')
      }
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
    const t = parseSnapshotClockMs(raw)
    if (t == null) return Number.POSITIVE_INFINITY
    return Date.now() - t
  }

  function resetFallbackTimer(refreshSec = 5) {
    if (fallbackTimer) window.clearInterval(fallbackTimer)
    fallbackTimer = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        void fallbackSync()
        return
      }
      const age = snapshotAgeMs()
      if (age > 15000) void fallbackSync()
      if (age > STALE_PAGE_MS && !wsStatusFromSnapshot(store.snapshot)) {
        const stopped = lastUpdatedAt || store.snapshot?.clock || ''
        store.setWsStatus('服务停滞，数据停在 ' + stopped)
      }
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
