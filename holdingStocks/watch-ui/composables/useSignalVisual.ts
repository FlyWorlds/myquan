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

/** 策略1/持仓：买=红、卖=绿、实仓底=#5eead4、策略持有=紫。 */
export function resolveSignalVisual(row: HoldingRow): SignalVisual {
  const bg = String(row.bgClass || '')
  const pos = String(row.持仓状态 || '')
  const alert = String(row.预警 || '').trim()
  const trig = String(row.因子触发 || '').trim()
  const side = String(row.因子侧 || '')
  const qty = qtyOf(row)

  const realHold =
    qty > 0 &&
    (pos === '持有' ||
      pos === '已经买入' ||
      pos === '待卖出' ||
      pos === '持有·T+1' ||
      alert === '持有' ||
      alert === '已经买入' ||
      alert.includes('T+1'))
  const t1Locked = qty > 0 && (alert.includes('T+1') || pos === '已经买入') && Number(row.可用 || 0) <= 0
  const paperHold = pos === '策略持有'
  const empty =
    pos === '空仓' ||
    (!qty &&
      !paperHold &&
      pos !== '待买入' &&
      pos !== '当日禁买' &&
      pos !== '已止损' &&
      pos !== '今日平仓' &&
      pos !== '已平仓' &&
      pos !== '已触止损平仓')

  const buyTriggered =
    qty <= 0 &&
    (alert === '已触买' ||
      alert.includes('已触买') ||
      alert.includes('再触买') ||
      alert.includes('收盘动量可再买') ||
      String(row.已触买 || '') === '是' ||
      (pos === '待买入' &&
        (trig.startsWith('已触发') ||
          trig.includes('已触发') ||
          trig.includes('再触买') ||
          trig.includes('收盘动量'))))
  const stopClosed =
    pos === '今日平仓' ||
    pos === '已平仓' ||
    pos === '已止损' ||
    pos === '已触止损平仓' ||
    alert.includes('已触止损平仓') ||
    alert.includes('今日已止损')
  const sellTriggered =
    !stopClosed &&
    (alert.includes('已触止损') ||
      trig.startsWith('策略止损') ||
      (pos === '待卖出' && (trig.startsWith('已触发') || alert.includes('止损'))))

  const buyWarn =
    bg === 'warn-buy' ||
    pos === '待买入' ||
    alert.includes('将买') ||
    alert.includes('可再买') ||
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

  // 实仓：底色固定持仓青绿 #5eead4；止损/预警只改角标，不换整卡绿底
  // T+1 当日不可卖：角标固定「已经买入/持有·T+1」，止损已记不当成已触止损筛选
  if (qty > 0) {
    const sellHit =
      !t1Locked && (sellTriggered || sellWarn || pos === '待卖出')
    const badgeText = t1Locked
      ? alert && alert !== '-'
        ? alert
        : '持有·T+1'
      : sellHit
        ? alert || '已触止损'
        : alert && alert !== '-'
          ? alert
          : '已经买入'
    return {
      tier: 'hold',
      rowClass: 'signal-row signal-hold-real',
      badgeClass: sellHit
        ? 'signal-badge signal-badge-trigger-sell'
        : 'signal-badge signal-badge-hold-real',
      badgeText,
    }
  }

  // 1. 已触发（空仓侧）
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
  if (sellWarn && !buyWarn && (paperHold || pos === '待卖出')) {
    return mk('warn-sell', alert || '将止损')
  }
  if (buyWarn && sellWarn) {
    return mk('warn-buy', alert || '将买入')
  }

  // 3. 已平仓（角标用信号「已触止损」）/ 策略持有 / 空仓
  if ((stopClosed || pos === '当日禁买') && !buyTriggered && !buyWarn) {
    return mk('ban-buy', stopClosed ? '已触止损' : alert || '当日禁买')
  }
  if (paperHold || bg === 'status-hold') {
    return mk('paper-hold', alert || '策略持有')
  }

  if (empty || bg === 'status-flat' || pos === '空仓') {
    return mk('flat', alert || '空仓')
  }

  if (alert && alert !== '-') {
    return mk('flat', alert)
  }

  return mk('flat', pos || side || '—')
}

export type SignalLegendId =
  | 'hold-real'
  | 'hold-paper'
  | 'ban-buy'
  | 'warn-buy'
  | 'trigger-buy'
  | 'warn-sell'
  | 'trigger-sell'
  | 'flat'

/** 图例筛选可多标签：今日入槽既算已经买入，也算已触买；T+1 止损已记不算已触止损。 */
export function collectLegendIds(row: HoldingRow): SignalLegendId[] {
  const qty = qtyOf(row)
  const pos = String(row.持仓状态 || '')
  const alert = String(row.预警 || '').trim()
  const t1Locked =
    qty > 0 && (alert.includes('T+1') || pos === '已经买入') && Number(row.可用 || 0) <= 0
  const buyHit =
    String(row.已触买 || '') === '是' ||
    alert.includes('已触买') ||
    alert.includes('再触买') ||
    alert.includes('收盘动量可再买')
  const stopClosed =
    pos === '今日平仓' ||
    pos === '已平仓' ||
    pos === '已止损' ||
    pos === '已触止损平仓' ||
    alert.includes('已触止损平仓') ||
    alert.includes('今日已止损')
  const ids: SignalLegendId[] = []

  if (qty > 0) ids.push('hold-real')
  else if (pos === '策略持有') ids.push('hold-paper')
  else if (stopClosed || pos === '当日禁买') ids.push('ban-buy')

  if (buyHit) ids.push('trigger-buy')

  if (
    !t1Locked &&
    !stopClosed &&
    (String(row.已触止损 || '') === '是' ||
      alert.includes('已触止损') ||
      (pos === '待卖出' && alert.includes('止损')))
  ) {
    ids.push('trigger-sell')
  } else if (
    !t1Locked &&
    !stopClosed &&
    qty <= 0 &&
    (pos === '待卖出' || alert.includes('将止损') || alert.includes('将卖出') || Boolean(row.近止损))
  ) {
    ids.push('warn-sell')
  }

  if (qty <= 0 && !buyHit && !stopClosed && pos !== '当日禁买') {
    if (pos === '待买入' || alert.includes('将买') || Boolean(row.近买点)) ids.push('warn-buy')
  }

  if (!ids.length) ids.push('flat')
  return ids
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
