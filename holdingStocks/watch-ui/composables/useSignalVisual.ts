import type { HoldingRow } from '~/types/snapshot'

export type SignalTier =
  | 'trigger-buy'
  | 'warn-buy'
  | 'trigger-sell'
  | 'warn-sell'
  | 'hold'
  | 'flat'
  | null

export interface SignalVisual {
  tier: SignalTier
  rowClass: string
  badgeClass: string
  badgeText: string
}

function alertText(row: HoldingRow): string {
  return String(row.预警 || row.挂单说明 || '').trim()
}

function triggerText(row: HoldingRow): string {
  return String(row.因子触发 || '').trim()
}

/** 策略1/持仓：买入红、卖出绿；预警闪烁，已触发强高亮。 */
export function resolveSignalVisual(row: HoldingRow): SignalVisual {
  const bg = String(row.bgClass || '')
  const alert = alertText(row)
  const trig = triggerText(row)
  const pos = String(row.持仓状态 || '')
  const side = String(row.因子侧 || '')

  const isTriggered = trig.startsWith('已触发') || trig.startsWith('策略止损')
  const isNear = trig === '接近' || alert.includes('将买') || alert.includes('将止损') || alert.includes('将卖出')

  if (bg === 'warn-buy' || pos === '待买入' || (side === '买入' && (isTriggered || isNear))) {
    if (isTriggered || alert === '已触买' || (pos === '待买入' && isTriggered)) {
      return {
        tier: 'trigger-buy',
        rowClass: 'signal-row signal-trigger-buy',
        badgeClass: 'signal-badge signal-badge-trigger-buy',
        badgeText: alert || '已触买',
      }
    }
    return {
      tier: 'warn-buy',
      rowClass: 'signal-row signal-warn-buy',
      badgeClass: 'signal-badge signal-badge-warn-buy',
      badgeText: alert || '将买入',
    }
  }

  if (bg === 'warn-sell' || pos === '待卖出' || (side === '卖出' && (isTriggered || isNear))) {
    if (isTriggered || alert.includes('已触止损') || trig.startsWith('策略止损')) {
      return {
        tier: 'trigger-sell',
        rowClass: 'signal-row signal-trigger-sell',
        badgeClass: 'signal-badge signal-badge-trigger-sell',
        badgeText: alert || '已触止损',
      }
    }
    return {
      tier: 'warn-sell',
      rowClass: 'signal-row signal-warn-sell',
      badgeClass: 'signal-badge signal-badge-warn-sell',
      badgeText: alert || '将止损',
    }
  }

  if (bg === 'status-hold' || pos === '持有' || pos === '策略持有') {
    return {
      tier: 'hold',
      rowClass: 'signal-row signal-hold',
      badgeClass: 'signal-badge signal-badge-hold',
      badgeText: alert || pos || '持有',
    }
  }

  if (alert && alert !== '空仓' && alert !== '-') {
    return {
      tier: 'flat',
      rowClass: 'signal-row',
      badgeClass: 'signal-badge signal-badge-flat',
      badgeText: alert,
    }
  }

  return {
    tier: null,
    rowClass: 'signal-row',
    badgeClass: 'signal-badge signal-badge-flat',
    badgeText: pos || '—',
  }
}
