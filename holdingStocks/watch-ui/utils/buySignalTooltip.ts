import type { HoldingRow } from '~/types/snapshot'

/** Explain the displayed buy signal, keeping signal price distinct from a fill. */
export function buySignalTooltip(row: HoldingRow, tier: string | null, digits = 2): string {
  if (tier !== 'trigger-buy' && tier !== 'warn-buy') return ''
  const lines = [tier === 'trigger-buy' ? '触买：买入信号已触发' : '将买入：接近买点，等待触发']
  const price = row.条件买入价 ?? row.买入侧价 ?? row.买点
  const value = price == null ? NaN : Number(price)
  lines.push(`买入信号价：${Number.isFinite(value) && value > 0 ? value.toFixed(digits) + ' 元' : '待行情确认'}`)

  const source = String(row.信号来源 || row.买入理由 || '').trim()
  const note = String(row.挂单说明 || '').trim()
  if (source) {
    const factor = String(row.信号因子 || '')
    const rule = factor === 'factor33' ? '（10点后，按当日低点反弹阈值判断）'
      : factor === 'factor26' ? '（按开盘价突破阈值判断）' : ''
    lines.push(`买入理由：${source}${rule}`)
  } else if (note) {
    lines.push(`买入理由：${note}`)
  } else {
    lines.push(tier === 'trigger-buy' ? '买入理由：价格已达到策略买入条件' : '买入理由：价格已进入策略买入预警范围')
  }
  if (row.过门) lines.push(`选股条件：${row.过门}`)
  const at = row.买信号时间 || row.信号时间
  if (tier === 'trigger-buy' && at) lines.push(`信号时间：${at}`)
  const reasons: Record<string, string> = {
    MAX_DAILY_BUY_FILLS: '当日买入笔数已达上限',
    MAX_DAILY_NEW_BUY_FILLS: '当日新买入笔数已达上限',
    MAX_DAILY_REBUY_FILLS: '当日买回笔数已达上限',
    MAX_NEW_SYMBOLS_PER_SESSION: '当日新增股票数量已达上限',
    MAX_POSITION_SYMBOLS: '持仓槽位已满',
    INSUFFICIENT_CASH: '可用资金不足',
    ENTRY_PHASE_QUOTA: '当前时段买入额度已用完',
  }
  const blocked = String(row.条件单原因 || '')
  if (reasons[blocked]) lines.push(`暂未买入：${reasons[blocked]}`)
  if (tier === 'trigger-buy') lines.push('触买为信号，实际成交以持仓和交割记录为准')
  return lines.join('\n')
}
