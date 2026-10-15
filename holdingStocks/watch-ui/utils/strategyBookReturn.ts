export function strategyBookSingleReturn(row: Record<string, unknown>): number | null {
  const value = Number(row['策略虚拟股数']) > 0 ? row['单笔收入%'] : row['综合单笔收入%']
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}
