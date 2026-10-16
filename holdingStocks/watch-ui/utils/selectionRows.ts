import type { HoldingRow, StrategyPicks } from '../types/snapshot'

/** An explicit selection owns membership; delayed snapshots must never restore the old pool. */
export function selectionRows(picks: StrategyPicks | null | undefined, rows: HoldingRow[]): HoldingRow[] {
  if (!picks) return rows
  const byCode = new Map(rows.map(row => [String(row.代码 || '').slice(-6), row]))
  return (picks.items || []).map(item => {
    const code = String(item.code || item.symbol || '').slice(-6)
    return byCode.get(code) || {
      代码: code,
      名称: item.name || code,
      pool_src: 'strategy16b',
      池来源: '条件选股',
      // Saved screening quotes are historical; do not label them as current prices.
      现价: null,
      当日涨幅: null,
    }
  })
}
