import type { HoldingRow } from '~/types/snapshot'

export type SignalTier =
  | 'trigger-buy'
  | 'warn-buy'
  | 'trigger-sell'
  | 'warn-sell'
  | 'hold'
  | 'paper-hold'
  | 'flat'
  | 'ban-buy'
  | null

export interface SignalVisual {
  tier: SignalTier
  rowClass: string
  badgeClass: string
  badgeText: string
}

function qtyOf(row: HoldingRow): number {
  return Number(row.持仓) || 0
}

/** 策略1/持仓：买=红、卖=绿；持有=蓝；空仓=灰。预警闪、触发强高亮。 */
export function resolveSignalVisual(row: HoldingRow): SignalVisual {
  const bg = String(row.bgClass || '')
  const pos = String(row.持仓状态 || '')
  const alert = String(row.预警 || '').trim()
  const trig = String(row.因子触发 || '').trim()
  const side = String(row.因子侧 || '')
  const qty = qtyOf(row)

  const realHold = qty > 0 && (pos === '持有' || pos === '待卖出' || pos === '持有·T+1' || alert === '持有')
  const paperHold = pos === '策略持有'
  const empty = pos === '空仓' || (!qty && !paperHold && pos !== '待买入' && pos !== '当日禁买')

  const buyTriggered =
    alert === '已触买' ||
    String(row.已触买 || '') === '是' ||
    (pos === '待买入' && (trig.startsWith('已触发') || trig.includes('已触发')))
  const sellTriggered =
    alert.includes('已触止损') ||
    trig.startsWith('策略止损') ||
    (pos === '待卖出' && trig.startsWith('已触发'))

  const buyWarn =
    bg === 'warn-buy' ||
    pos === '待买入' ||
    alert.includes('将买') ||
    Boolean(row.近买点) ||
    (side === '买入' && (trig === '接近' || trig.startsWith('已触发')))

  const sellWarn =
    bg === 'warn-sell' ||
    pos === '待卖出' ||
    alert.includes('将止损') ||
    alert.includes('将卖出') ||
    Boolean(row.近止损) ||
    (side === '卖出' && trig === '接近') ||
    (paperHold && trig === '接近') ||
    (realHold && trig === '接近' && bg === 'warn-sell')

  // 1. 已触发（最强）— 持有/策略持有时触买仍优先红闪
  if (buyTriggered && !sellTriggered) {
    const tag = alert === '已触买' ? alert : alert.includes('已触买') ? alert : '已触买'
    return mk('trigger-buy', tag)
  }
  if (sellTriggered && !buyTriggered) {
    return mk('trigger-sell', alert || '已触止损')
  }
  if (buyTriggered && sellTriggered) {
    return mk('trigger-buy', alert.includes('已触买') ? alert : '已触买')
  }

  // 2. 预警带
  if (buyWarn && !sellWarn) {
    return mk('warn-buy', alert || '将买入')
  }
  if (sellWarn && !buyWarn && (realHold || paperHold || pos === '待卖出')) {
    return mk('warn-sell', alert || '将止损')
  }
  if (buyWarn && sellWarn) {
    return mk('warn-buy', alert || '将买入')
  }

  // 3. 持有（无卖出预警）
  if (pos === '当日禁买' || alert.includes('今日已止损')) {
    return mk('ban-buy', alert || '当日禁买')
  }
  if (realHold || (qty > 0 && bg === 'status-hold')) {
    return mk('hold', alert || '持有')
  }
  if (paperHold || bg === 'status-hold') {
    return mk('paper-hold', alert || '策略持有')
  }

  // 4. 空仓观望
  if (empty || bg === 'status-flat' || pos === '空仓') {
    return mk('flat', alert || '空仓')
  }

  if (alert && alert !== '-') {
    return mk('flat', alert)
  }

  return mk('flat', pos || side || '—')
}

function mk(tier: SignalTier, badgeText: string): SignalVisual {
  switch (tier) {
    case 'trigger-buy':
      return {
        tier,
        rowClass: 'signal-row signal-trigger-buy',
        badgeClass: 'signal-badge signal-badge-trigger-buy',
        badgeText,
      }
    case 'warn-buy':
      return {
        tier,
        rowClass: 'signal-row signal-warn-buy',
        badgeClass: 'signal-badge signal-badge-warn-buy',
        badgeText,
      }
    case 'trigger-sell':
      return {
        tier,
        rowClass: 'signal-row signal-trigger-sell',
        badgeClass: 'signal-badge signal-badge-trigger-sell',
        badgeText,
      }
    case 'warn-sell':
      return {
        tier,
        rowClass: 'signal-row signal-warn-sell',
        badgeClass: 'signal-badge signal-badge-warn-sell',
        badgeText,
      }
    case 'hold':
      return {
        tier,
        rowClass: 'signal-row signal-hold-real',
        badgeClass: 'signal-badge signal-badge-hold-real',
        badgeText,
      }
    case 'paper-hold':
      return {
        tier,
        rowClass: 'signal-row signal-hold-paper',
        badgeClass: 'signal-badge signal-badge-hold-paper',
        badgeText,
      }
    case 'ban-buy':
      return {
        tier,
        rowClass: 'signal-row signal-ban-buy',
        badgeClass: 'signal-badge signal-badge-ban-buy',
        badgeText,
      }
    case 'flat':
    default:
      return {
        tier: tier === 'flat' ? 'flat' : null,
        rowClass: 'signal-row signal-flat',
        badgeClass: 'signal-badge signal-badge-flat',
        badgeText,
      }
  }
}
