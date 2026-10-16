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
