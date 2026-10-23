export interface ReturnRecord {
  day_pnl?: number | string | null
  day_pnl_pct?: number | string | null
}

function finiteNumber(value: unknown): number | null {
  if (value == null || (typeof value === 'string' && !value.trim())) return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function aggregateReturns(items: ReturnRecord[]) {
  const amounts = items.map(r => finiteNumber(r.day_pnl)).filter((v): v is number => v != null)
  const rates = items.map(r => finiteNumber(r.day_pnl_pct)).filter((v): v is number => v != null)
  return {
    amount: amounts.length ? amounts.reduce((sum, value) => sum + value, 0) : null,
    rate: rates.length ? (rates.reduce((product, rate) => product * (1 + rate / 100), 1) - 1) * 100 : null,
    partial: rates.length > 0 && rates.length < items.length,
  }
}
