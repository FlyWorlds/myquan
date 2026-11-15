export function baiduStockUrl(code?: string | number | null, name?: string | null): string {
  const raw = String(code || '').trim()
  const c = raw.replace(/\D/g, '')
  const padded = c.length > 0 && c.length < 6 ? c.padStart(6, '0') : c
  const q = encodeURIComponent(name || '')
  return `https://finance.baidu.com/stock/ab-${padded}?name=${q}`
}

// 指数必须走 /index/：000001 在 /stock/ 下是平安银行
export function baiduIndexUrl(code?: string | number | null, name?: string | null): string {
  const raw = String(code || '').trim()
  const c = raw.replace(/\D/g, '')
  const padded = c.length > 0 && c.length < 6 ? c.padStart(6, '0') : c
  const q = encodeURIComponent(name || '')
  return `https://finance.baidu.com/index/ab-${padded}?name=${q}`
}
