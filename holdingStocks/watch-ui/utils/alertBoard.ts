type AlertRow = {
  代码?: string
  现价?: number | null
  当日涨幅?: number | null
  '距买点%'?: number | null
  买入侧价?: number | null
  买点?: number | null
  更新?: string | null
  已触买?: string
  预警?: string
  预警线内?: boolean
}

const QUOTE_KEYS = ['现价', '当日涨幅', '更新'] as const

function codeOf(row: AlertRow): string {
  return String(row.代码 || '')
}

function quotePatch<T extends AlertRow>(row: Partial<T> | undefined): Partial<T> {
  const patch: Partial<T> = {}
  if (!row) return patch
  for (const key of QUOTE_KEYS) {
    const value = row[key]
    if (value != null && value !== '') patch[key] = value as T[typeof key]
  }
  return patch
}

export function isTouchBuy(row: { 已触买?: string; 预警?: string }): boolean {
  const alert = String(row.预警 || '')
  return String(row.已触买 || '') === '是' || alert === '触买' || alert.includes('已触买')
}

function touchBuyClock(row: { 买信号时间?: string | null; 信号时间?: string | null; 信号时刻?: string | null }): string {
  return String(row.买信号时间 || row.信号时间 || row.信号时刻 || '99:99:99')
}

/** 触买按触发时间从早到晚，其余卡片保持原顺序。 */
export function orderTouchBuys<T extends { 代码?: string; 已触买?: string; 预警?: string; 买信号时间?: string | null; 信号时间?: string | null; 信号时刻?: string | null }>(
  rows: T[],
): T[] {
  const hits: T[] = []
  const rest: T[] = []
  for (const row of rows) (isTouchBuy(row) ? hits : rest).push(row)
  hits.sort(
    (a, b) => touchBuyClock(a).localeCompare(touchBuyClock(b)) || String(a.代码 || '').localeCompare(String(b.代码 || '')),
  )
  return [...hits, ...rest]
}

/** 进过预警线的代码留在原位。本帧还在名单里算线内，暂时离开算线外。 */
export function stickAlertRows<T extends AlertRow>(
  previous: T[],
  incoming: T[],
  occupied: Iterable<string>,
  quotes?: Map<string, Partial<T>>,
): Array<T & { 预警线内: boolean }> {
  const taken = new Set(occupied)
  const live = new Map<string, T & { 预警线内: boolean }>()
  for (const row of incoming) {
    const code = codeOf(row)
    if (!code || taken.has(code) || live.has(code)) continue
    live.set(code, { ...row, 预警线内: true })
  }
  const out: Array<T & { 预警线内: boolean }> = []
  const seen = new Set<string>()
  for (const prev of previous) {
    const code = codeOf(prev)
    if (!code || taken.has(code) || seen.has(code)) continue
    seen.add(code)
    const still = live.get(code)
    const row = still ?? { ...prev, ...quotePatch(quotes?.get(code)) }
    if (isTouchBuy(row) || isTouchBuy(prev)) {
      out.push({ ...row, 已触买: '是', 预警线内: true })
      continue
    }
    out.push({ ...row, 预警线内: Boolean(still) })
  }
  for (const [code, row] of live) {
    if (seen.has(code)) continue
    out.push(row)
  }
  return out
}

const DEBOUNCED_STATUS_KEYS = [
  '持仓状态',
  '预警',
  '预警线内',
  '近买点',
  '近止损',
  'bgClass',
  '因子触发',
  '因子侧',
  '策略状态',
  '策略展示状态',
] as const

type StatusPatch = Partial<Record<(typeof DEBOUNCED_STATUS_KEYS)[number], unknown>>

function extractStatusPatch(row: Record<string, any>): StatusPatch {
  const patch: StatusPatch = {}
  for (const key of DEBOUNCED_STATUS_KEYS) {
    if (key in row) patch[key] = row[key]
  }
  return patch
}

function statusSignature(row: Record<string, any>): string {
  return DEBOUNCED_STATUS_KEYS.map((key) => `${key}:${String(row[key] ?? '')}`).join('|')
}

function isImmediateStatusTransition(prev: Record<string, any>, next: Record<string, any>): boolean {
  const prevHeld = Number(prev.持仓 || 0) > 0
  const nextHeld = Number(next.持仓 || 0) > 0
  if (prevHeld !== nextHeld) return true
  if (!prev.已实现 && next.已实现) return true
  if (!prev.三槽平仓 && next.三槽平仓) return true
  if (!isTouchBuy(prev) && isTouchBuy(next)) return true
  return false
}

/** 状态变化 3s 防抖：新状态需持续满 3s 才切换展示与触发状态重排，成交/触买等终态立即生效。 */
export function createStatusDebouncer(debounceMs = 3_000) {
  const committed = new Map<string, { sig: string; patch: StatusPatch; rowSnapshot: Record<string, any> }>()
  const pending = new Map<string, { sig: string; since: number; patch: StatusPatch }>()

  return {
    remaining(now: number): number {
      let minWait = Infinity
      for (const item of pending.values()) {
        const wait = Math.max(0, item.since + debounceMs - now)
        if (wait < minWait) minWait = wait
      }
      return Number.isFinite(minWait) ? minWait : 0
    },
    update<T extends AlertRow & Record<string, any>>(rows: T[], now: number): T[] {
      const activeCodes = new Set<string>()
      const out: T[] = []

      for (const row of rows) {
        const code = codeOf(row)
        if (!code) {
          out.push(row)
          continue
        }
        activeCodes.add(code)
        const sig = statusSignature(row)
        const patch = extractStatusPatch(row)
        const current = committed.get(code)

        if (!current || isImmediateStatusTransition(current.rowSnapshot, row)) {
          committed.set(code, { sig, patch, rowSnapshot: row })
          pending.delete(code)
          out.push(row)
          continue
        }

        if (sig === current.sig) {
          committed.set(code, { sig, patch, rowSnapshot: row })
          pending.delete(code)
          out.push(row)
          continue
        }

        const cand = pending.get(code)
        if (!cand || cand.sig !== sig) {
          pending.set(code, { sig, since: now, patch })
          out.push({ ...row, ...current.patch })
          continue
        }

        if (now - cand.since >= debounceMs) {
          committed.set(code, { sig, patch, rowSnapshot: row })
          pending.delete(code)
          out.push(row)
        } else {
          out.push({ ...row, ...current.patch })
        }
      }

      for (const code of [...committed.keys()]) {
        if (!activeCodes.has(code)) {
          committed.delete(code)
          pending.delete(code)
        }
      }
      return out
    },
  }
}

/** Throttle price-driven movement (10s) and debounce status changes (3s); membership and row values always update immediately. */
export function createAlertPriceOrder(intervalMs = 10_000, statusDebounceMs = 3_000) {
  let order: string[] = []
  let lastSortedAt = -Infinity
  const statusDebouncer = createStatusDebouncer(statusDebounceMs)

  function distance(row: AlertRow): number {
    const last = Number(row.现价)
    const buy = Number(row.买入侧价 ?? row.买点)
    if (last > 0 && buy > 0) return Math.abs(last / buy - 1)
    const stored = row['距买点%']
    return stored != null && Number.isFinite(Number(stored)) ? Math.abs(Number(stored)) / 100 : Infinity
  }

  return {
    remaining(now: number) {
      const sortWait = Math.max(0, lastSortedAt + intervalMs - now)
      const statusWait = statusDebouncer.remaining(now)
      if (statusWait > 0) return sortWait > 0 ? Math.min(sortWait, statusWait) : statusWait
      return sortWait
    },
    update<T extends AlertRow>(rows: T[], now: number): T[] {
      if (!rows.length) {
        order = []
        lastSortedAt = -Infinity
        statusDebouncer.update([], now)
        return []
      }
      const stabilized = statusDebouncer.update(rows as Array<T & Record<string, any>>, now) as T[]
      const previous = new Map(order.map((code, i) => [code, i]))
      let next = [...stabilized].sort((a, b) => {
        const band = Number(a.预警线内 === false) - Number(b.预警线内 === false)
        if (band) return band
        return (previous.get(codeOf(a)) ?? Infinity) - (previous.get(codeOf(b)) ?? Infinity)
      })
      if (now - lastSortedAt >= intervalMs) {
        // Stable ties retain the previous order; touch-buy priority is applied separately.
        next = next.sort((a, b) => {
          const band = Number(a.预警线内 === false) - Number(b.预警线内 === false)
          if (band) return band
          const da = distance(a), db = distance(b)
          return da === db ? 0 : da < db ? -1 : 1
        })
        lastSortedAt = now
      }
      order = next.map(codeOf)
      return next
    },
  }
}

function holdingBuyTime(row: { 买入时间?: string | null; buy_time?: string | null; 策略入场时间?: string | null }): string {
  return String(row.买入时间 || row.buy_time || row.策略入场时间 || '').trim().replace('T', ' ')
}

function compareByBuyTimeDesc(
  a: { 代码?: string; 买入时间?: string | null; buy_time?: string | null; 策略入场时间?: string | null },
  b: { 代码?: string; 买入时间?: string | null; buy_time?: string | null; 策略入场时间?: string | null },
  fallbackDiff = 0,
): number {
  const ta = holdingBuyTime(a)
  const tb = holdingBuyTime(b)
  if (ta && tb && ta !== tb) return tb.localeCompare(ta)
  if (ta && !tb) return -1
  if (!ta && tb) return 1
  return fallbackDiff || String(a.代码 || '').localeCompare(String(b.代码 || ''))
}

/** 纸面持仓/策略持有：按买入时间降序（最近买入排最前）+ 10s 防抖排序 + 状态变化 3s 防抖。 */
export function createHoldingPriceOrder(intervalMs = 10_000, statusDebounceMs = 3_000) {
  let order: string[] = []
  let lastSortedAt = -Infinity
  const statusDebouncer = createStatusDebouncer(statusDebounceMs)

  return {
    remaining(now: number) {
      const sortWait = Math.max(0, lastSortedAt + intervalMs - now)
      const statusWait = statusDebouncer.remaining(now)
      if (statusWait > 0) return sortWait > 0 ? Math.min(sortWait, statusWait) : statusWait
      return sortWait
    },
    update<T extends AlertRow & { 持仓状态?: string; 买入时间?: string | null; buy_time?: string | null; 策略入场时间?: string | null }>(
      rows: T[],
      now: number,
    ): T[] {
      if (!rows.length) {
        order = []
        lastSortedAt = -Infinity
        statusDebouncer.update([], now)
        return []
      }
      const stabilizedRows = statusDebouncer.update(rows, now)
      if (now - lastSortedAt >= intervalMs) {
        const incomingIndex = new Map(stabilizedRows.map((row, i) => [codeOf(row), i]))
        const sorted = [...stabilizedRows].sort((a, b) =>
          compareByBuyTimeDesc(a, b, (incomingIndex.get(codeOf(a)) ?? 0) - (incomingIndex.get(codeOf(b)) ?? 0)),
        )
        lastSortedAt = now
        order = sorted.map(codeOf)
        return sorted
      }
      const previous = new Map(order.map((code, i) => [code, i]))
      const incomingIndex = new Map(stabilizedRows.map((row, i) => [codeOf(row), i]))
      const next = [...stabilizedRows].sort((a, b) => {
        const pa = previous.get(codeOf(a)) ?? Infinity
        const pb = previous.get(codeOf(b)) ?? Infinity
        if (pa !== pb) return pa - pb
        return compareByBuyTimeDesc(a, b, (incomingIndex.get(codeOf(a)) ?? 0) - (incomingIndex.get(codeOf(b)) ?? 0))
      })
      order = next.map(codeOf)
      return next
    },
  }
}



/** 预警列表保留实际持仓并立即置顶；其余沿用触买优先顺序。 */
export function orderAlertCards<T extends AlertRow & { 持仓?: number; 买入时间?: string | null }>(rows: T[]): T[] {
  const held = rows.filter(row => Number(row.持仓 || 0) > 0)
  const alerts = rows.filter(row => Number(row.持仓 || 0) <= 0)
  held.sort((a, b) => compareByBuyTimeDesc(a, b))
  return [...held, ...orderTouchBuys(alerts)]
}
