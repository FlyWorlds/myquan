export function baiduStockUrl(code?: string, name?: string): string {
  const c = (code || '').replace(/\D/g, '')
  const q = encodeURIComponent(name || '')
  return `https://finance.baidu.com/stock/ab-${c}?name=${q}`
}
