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

/** 名称（代码）；无名称时仅显示代码 */
export function stockLabel(code?: string | null, name?: string | null): string {
  const c = String(code || '').trim()
  const n = String(name || '').trim()
  if (!c) return n || '—'
  const badName =
    !n ||
    n === c ||
    n.toLowerCase() === c.toLowerCase() ||
    n.startsWith('SYN') ||
    n.startsWith('sh') ||
    n.startsWith('sz') ||
    (/^\d+$/.test(n) && n.padStart(6, '0') === c.padStart(6, '0'))
  if (badName) return c
  return `${n}（${c}）`
}
