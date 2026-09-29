import type { HoldingRow } from '~/types/snapshot'

/** 个股仓位占比% = 市值 / 总资产；与后端 account.positionPct（Σ市值/总资产）同口径。 */
export function positionPctOf(row: HoldingRow, accountTotal?: number | null): number | null {
  const qty = Number(row.持仓 || 0)
  const total = Number(accountTotal || 0)
  if (!(qty > 0) || !(total > 0)) return null
  let mv = row.市值 != null ? Number(row.市值) : NaN
  if (!Number.isFinite(mv)) mv = Number(row.现价 || 0) * qty
  if (!(mv > 0)) return null
  return (mv / total) * 100
}

export function fmtPositionPct(v: number | null | undefined): string {
  return v == null ? '-' : `${v.toFixed(1)}%`
}
