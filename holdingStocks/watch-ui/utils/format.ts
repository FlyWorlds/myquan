export function fmtSignalClock(v?: string | null): string {
  if (v == null) return ''
  const s = String(v).trim()
  if (!s) return ''
  const clock = s.includes(' ') ? s.split(' ').pop() || s : s
  return clock.slice(0, 8)
}

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

/** 名称（代码）；无名称时仅显示代码。也接受 { code, name } 对象。 */
export function stockLabel(
  codeOrRow?: string | null | { code?: string | null; name?: string | null },
  name?: string | null,
): string {
  if (codeOrRow != null && typeof codeOrRow === 'object') {
    return stockLabel(codeOrRow.code, codeOrRow.name)
  }
  const c = String(codeOrRow || '').trim()
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
