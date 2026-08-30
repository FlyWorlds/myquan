export function fmtNum(v?: number | null, digits = 2): string {
  if (v == null) return '-'
  return v.toFixed(digits)
}

export function fmtSignedPct(v?: number | null, digits = 2): string {
  if (v == null) return '-'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}

export function fmtSignedMoney(v?: number | null, digits = 2): string {
  if (v == null) return '-'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}`
}

export function fmtMoney(v?: number | null): string {
  if (v == null) return '-'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
