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
let renderAcknowledged = false
let renderPending = false
let renderAttemptAt = 0

const STALE_PAGE_MS = 20000

export function useWatchWs() {
  const store = useWatchStore()
  const renderConfig = useRuntimeConfig()
  const nuxtApp = useNuxtApp()
  const { activeAccountId } = useAccounts()

  async function notifyRendered(data: WatchSnapshot) {
    if (data.boot) {
      renderAcknowledged = false
      return
    }
    if (renderAcknowledged || renderPending || Date.now() - renderAttemptAt < 5000) return
    renderPending = true
    renderAttemptAt = Date.now()
    try {
      if (nuxtApp.isHydrating) {
        await new Promise<void>((resolve) => nuxtApp.hook('app:mounted', () => resolve()))
      }
      await nextTick()
      // Let the browser paint the committed Vue tree before allowing background IO.
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
      if (!started) return
      const base = import.meta.dev
        ? `http://${renderConfig.public.watchApiHost || '127.0.0.1'}:${renderConfig.public.watchApiPort || '8765'}`
        : ''
      const result = await $fetch<{ ready: boolean }>(`${base}/api/front-rendered`, {
        method: 'POST', retry: 0, timeout: 3000,
      })
      renderAcknowledged = result.ready
    } catch {
      // Optional cache warming must never interfere with snapshot rendering.
    } finally {
      renderPending = false
    }
  }

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

    const curAid =
      activeAccountId.value ||
      (import.meta.client ? localStorage.getItem('myquan_active_account_id') : null) ||
      'acc_default'

    // 如果用户当前切换在子账户，且推送未指定子账户或推送的是默认账户，保护子账户持仓与资产不被覆盖
    if (curAid !== 'acc_default') {
      if (!data.active_account_id || data.active_account_id !== curAid) {
        const curSnap = store.rawSnapshot
        if (curSnap && curSnap.holdings) {
          data = {
            ...data,
            active_account_id: curAid,
            holdings: curSnap.holdings,
            closedHoldings: curSnap.closedHoldings,
            account: curSnap.account,
            slotMeta: curSnap.slotMeta,
          }
        }
      }
    }

    const sameTs = data.ts != null && lastTs != null && data.ts === lastTs
    const sameAt =
      data.updatedAt != null &&
      lastUpdatedAt != null &&
      data.updatedAt === lastUpdatedAt
    if (sameTs && sameAt) {
      applyStatus(data)
      void notifyRendered(data)
      return
    }
    lastTs = data.ts ?? lastTs
    lastUpdatedAt = data.updatedAt ?? lastUpdatedAt
    store.setSnapshot(data)
    applyStatus(data)
    void notifyRendered(data)
  }

  async function fallbackSync(accountId?: string) {
    try {
      const config = useRuntimeConfig()
      const base = import.meta.dev
        ? `http://${config.public.watchApiHost || '127.0.0.1'}:${config.public.watchApiPort || '8765'}`
        : ''
      const query: Record<string, any> = { t: Date.now() }
      const aid = accountId || (import.meta.client ? localStorage.getItem('myquan_active_account_id') : null)
      if (aid) query.account_id = aid
      const data = await $fetch<WatchSnapshot>(`${base}/api/snapshot`, {
        query,
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

  async function reloadSnapshot(accountId?: string) {
    lastTs = null
    lastUpdatedAt = null
    await fallbackSync(accountId)
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
      renderAcknowledged = false
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

  return { start, stop, reloadSnapshot }
}
