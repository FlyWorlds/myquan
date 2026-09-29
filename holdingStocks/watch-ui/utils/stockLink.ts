export function baiduStockUrl(code?: string, name?: string): string {
  const c = (code || '').replace(/\D/g, '')
  const q = encodeURIComponent(name || '')
  return `https://finance.baidu.com/stock/ab-${c}?name=${q}`
}

// 指数必须走 /index/：000001 在 /stock/ 下是平安银行
export function baiduIndexUrl(code?: string, name?: string): string {
  const c = (code || '').replace(/\D/g, '')
  const q = encodeURIComponent(name || '')
  return `https://finance.baidu.com/index/ab-${c}?name=${q}`
}
