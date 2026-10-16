/** 已出现的代码保持原位，新代码按本次到来的顺序接在后面。 */
export function stabilizeRows<T>(previous: string[], rows: T[], codeOf: (row: T) => string): T[] {
  const byCode = new Map<string, T>()
  const incoming: string[] = []
  for (const row of rows) {
    const code = codeOf(row)
    if (!code || byCode.has(code)) continue
    byCode.set(code, row)
    incoming.push(code)
  }
  const seen = new Set<string>()
  const order: string[] = []
  for (const code of previous) {
    if (!byCode.has(code) || seen.has(code)) continue
    seen.add(code)
    order.push(code)
  }
  for (const code of incoming) {
    if (seen.has(code)) continue
    seen.add(code)
    order.push(code)
  }
  return order.map((code) => byCode.get(code)!)
}
