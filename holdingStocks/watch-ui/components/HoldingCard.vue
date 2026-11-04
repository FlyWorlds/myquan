<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtBuyDistance, fmtNum, fmtSignedPct, fmtSignalClock, fmtSignedMoney } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'
import { fmtPositionPct, positionPctOf } from '~/utils/position'
import { alertType } from '~/utils/alertType'
import { sellProtection } from '~/utils/stopWarning'
import { holdingCyclePnl } from '~/utils/holdingCyclePnl'
import { buySignalTooltip } from '~/utils/buySignalTooltip'

const props = defineProps<{ row: HoldingRow; accountTotal?: number | null; dense?: boolean; band?: 'inside' | 'outside'; sellState?: string; sellFilled?: boolean }>()

const stickyNote = ref('')
const noteText = computed(() => {
  const parts = String(props.row.挂单说明 || '')
    .split('；')
    .map((part) => part.trim())
    .filter(
      (part) =>
        part &&
        !part.startsWith('条件买单@') &&
        !part.startsWith('报价条件单') &&
        !part.startsWith('买入信号已触发') &&
        !part.includes('当日新增额度已满') &&
        !part.includes('槽满') &&
        !part.includes('未入槽') &&
        !/^(FILLED|ARMED|TRIGGERED|CANCELLED|BLOCKED|failed)$/i.test(part),
    )
  const text = [...new Set(parts)].join('；')
  if (text) stickyNote.value = text
  return stickyNote.value
})

const protection = computed(() => sellProtection(props.row))

const cyclePnl = computed(() => holdingCyclePnl(props.row))

const positionPct = computed(() => positionPctOf(props.row, props.accountTotal))

const pdg = props.row['价位小数'] ?? 2
const visual = computed(() => resolveSignalVisual(props.row))

const posStatus = computed(() => String(props.row.持仓状态 || '').trim() || '-')
const pinned = computed(
  () => Boolean(props.row.置顶) && Number(props.row.持仓) > 0,
)
const slotTrace = computed(
  () =>
    Boolean(props.row.槽位留痕) ||
    (Number(props.row.持仓) <= 0 &&
      (Boolean(props.row.已实现) ||
        posStatus.value === '今日平仓' ||
        posStatus.value === '已平仓' ||
        posStatus.value === '已触止损平仓' ||
        posStatus.value === '已止损')),
)

const displayFactorSide = computed(() => {
  const isClosed = slotTrace.value || Boolean(props.row.已实现) || Boolean(props.row.三槽平仓)
  if (isClosed) return '卖出'
  const qty = Number(props.row.持仓 || 0)
  if (qty > 0) {
    const bought = String(props.row.买入时间 || props.row.buy_time || props.row.策略入场时间 || '').slice(0, 10)
    const session = String(props.row.交易日 || '').slice(0, 10)
    const isToday = Boolean(bought && session && bought === session) || props.row.持仓状态 === '已经买入'
    return isToday ? '买入' : '持有'
  }
  return String(props.row.因子侧 || '').trim()
})

/** 持仓最高 = holdings.peak_high，与自动卖出 trailing SoT 同源；≠ 今日最高 */
const hwmTitle = computed(() => {
  const at = props.row.持仓最高时间
  return at
    ? `本轮持仓最高价，更新于 ${at}`
    : '买入后最高价'
})

const triggerTimeClass = computed(() => {
  if (!fmtSignalClock(props.row.信号时间)) return 'text-ui-text-3'
  const sell = slotTrace.value || String(props.row.已触止损 || '') === '是'
    || props.row.已触发因子侧 === '卖出' || visual.value.tier === 'trigger-sell'
  return sell ? 'text-down' : 'text-up'
})

const touchClock = computed(() => fmtSignalClock(props.row.买信号时间 || props.row.信号时间))

const alertClock = computed(() => props.sellState === '触卖'
  ? fmtSignalClock(props.row.卖出时间 || props.row.卖信号时间 || props.row.信号时间)
  : !props.sellState && visual.value.tier === 'trigger-buy' ? touchClock.value : '')
const denseNote = computed(() => {
  if (!props.sellState) return noteText.value
  const details = [protection.value?.reason]
  if (props.sellFilled) details.push(`已模拟卖出 · 平仓价 ${fmtNum(props.row.成交价, pdg)}`)
  else if (Number(props.row.可用) === 0) details.push('暂无可卖数量／T+1不可卖')
  return details.filter(Boolean).join('；')
})

const buyTooltip = computed(() => buySignalTooltip(props.row, visual.value.tier, pdg))

const buyAlertPx = computed(() => {
  const px = props.row.买入侧价 ?? props.row.买点
  const n = Number(px)
  return Number.isFinite(n) && n > 0 ? n : null
})

const cardClass = computed(() => {
  if (visual.value.tier === 'trigger-buy') return 'signal-trigger-buy-fixed border-up/50'
  if (props.band === 'outside') return 'border-ui-hairline'
  const map: Record<string, string> = {
    'trigger-buy': 'signal-trigger-buy border-up/50',
    'warn-buy': 'signal-warn-buy border-up/40',
    'trigger-sell': 'signal-trigger-sell border-down/50',
    'warn-sell': 'signal-warn-sell border-down/40',
    hold: 'signal-hold-real border-hold/40',
    'paper-hold': 'signal-hold-paper border-hold-paper/40',
    'ban-buy': 'signal-ban-buy border-ui-hairline',
    flat: 'signal-flat border-ui-hairline',
  }
  const tier = visual.value.tier
  if (tier && map[tier]) return map[tier]
  if (Number(props.row.持仓) > 0) return 'signal-hold-real border-hold/40'
  return 'signal-flat border-ui-hairline'
})
</script>

<template>
  <article class="holding-card card overflow-hidden p-0 transition" :class="cardClass">
    <div :class="dense ? 'px-3 py-2' : 'p-4'">
      <header class="flex items-start justify-between gap-4">
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h2 class="flex flex-wrap items-baseline gap-x-2 gap-y-1 font-bold">
              <StockNameHover :code="row.代码" :name="row.名称">
                <a :href="baiduStockUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="sensitive hover:text-accent" :class="dense ? 'text-sm' : 'text-base'">{{ row.名称 }}</a>
              </StockNameHover>
              <a :href="baiduStockUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="sensitive font-mono text-xs font-normal tabular-nums text-ui-text-2 hover:text-accent">{{ row.代码 }}</a>
              <span class="text-[10px] font-normal text-ui-text-3">{{ row.市场 }}</span>
            </h2>
            <div class="flex flex-wrap items-center gap-1.5">
              <SignalTooltip :text="buyTooltip">
                <span :class="[sellState ? (sellState === '触卖' ? 'signal-badge signal-badge-trigger-sell' : 'signal-badge signal-badge-warn-sell') : band === 'outside' && visual.tier !== 'trigger-buy' ? 'signal-badge signal-badge-flat' : visual.badgeClass, buyTooltip ? 'cursor-help' : '']" :title="buyTooltip ? undefined : posStatus">{{ sellState || (band === 'outside' && visual.tier !== 'trigger-buy' ? '线外' : visual.badgeText) }}</span>
              </SignalTooltip>
              <span v-if="alertClock" class="font-mono text-[11px] tabular-nums" :class="sellState ? 'text-down' : 'text-up'">{{ alertClock }}</span>
              <span v-if="!dense && pinned" class="rounded-full border border-ui-hairline px-2 py-0.5 text-[10px] text-ui-text-2">置顶持仓</span>
              <span v-else-if="!dense && slotTrace" class="rounded-full border border-ui-hairline px-2 py-0.5 text-[10px] text-ui-text-2">今日平仓 · 不占槽</span>
              <span v-if="!dense && positionPct != null" class="sensitive text-xs tabular-nums text-ui-text-2" title="仓位占比 = 市值 / 总资产">仓位 {{ fmtPositionPct(positionPct) }}</span>
            </div>
          </div>
        </div>
        <div class="sensitive shrink-0 text-right tabular-nums">
          <div class="text-[10px] text-ui-text-3">现价</div>
          <b class="leading-tight" :class="dense ? 'text-base' : 'text-xl'">{{ fmtNum(row.现价, pdg) }}</b>
          <ChgText v-if="row.现价 != null && row.昨收 != null && row.昨收 > 0" class="ml-2 text-xs" :chg="row.现价 - row.昨收">{{ fmtSignedMoney(row.现价 - row.昨收, pdg) }}</ChgText>
          <ChgText title="今日涨跌幅" class="ml-2 text-xs font-semibold" :chg="row.当日涨幅">{{ fmtSignedPct(row.当日涨幅) }}</ChgText>
        </div>
      </header>

      <div v-if="!dense && (Number(row.持仓) > 0 || slotTrace || row.当日盈亏 != null)" class="mt-3 border-y border-ui-hairline py-2.5">
        <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span v-if="Number(row.持仓) > 0 || slotTrace" class="sensitive inline-flex items-baseline gap-x-1 text-xs font-semibold tabular-nums"
            :title="cyclePnl ? `已实现 ${fmtSignedMoney(cyclePnl.realized)}，浮动 ${fmtSignedMoney(cyclePnl.unrealized)}；已减仓 ${cyclePnl.soldQty} 股。收益率按本轮买入金额计算。` : '成交或行情待核对'">
            <span class="text-[10px] font-normal text-ui-text-3">买入后盈亏</span>
            <template v-if="cyclePnl">
              <ChgText :chg="cyclePnl.amount">{{ fmtSignedMoney(cyclePnl.amount) }}</ChgText>
              <ChgText :chg="cyclePnl.pct" class="text-[11px] font-normal">({{ fmtSignedPct(cyclePnl.pct) }})</ChgText>
            </template>
            <span v-else class="text-ui-text-3">—</span>
          </span>
          <FloatPnlInline :row="row" class="holding-day-pnl" />
        </div>
      </div>
      <p v-if="row.error" class="mt-3 text-sm text-up">{{ row.error }}</p>
      <template v-else>
        <dl v-if="!dense" class="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div><dt class="text-ui-text-3">{{ slotTrace ? '卖出数量' : '持仓数量' }}</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ slotTrace ? (row.卖出数量 ?? cyclePnl?.soldQty ?? '—') : (row.持仓 ?? 0) }} 股</dd></div>
          <div><dt class="text-ui-text-3">{{ slotTrace ? '平仓价' : '买入成本' }}</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(slotTrace ? row.成交价 : row.成本, pdg) }}</dd></div>
          <div title="当日行情开盘价"><dt class="text-ui-text-3">今开</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(row.开盘, pdg) }}</dd></div>
          <div :title="hwmTitle"><dt class="text-ui-text-3">峰值</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(row.持仓最高 ?? row.峰值, pdg) }}</dd></div>
        </dl>
        <dl v-if="!dense && (row.阈值就绪 || slotTrace || protection)" class="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-ui-hairline p-3 text-xs sm:grid-cols-4">
          <div><dt class="text-ui-text-3">买入侧</dt><dd class="sensitive mt-1 font-semibold tabular-nums text-up">{{ fmtNum(row.买入侧价 ?? row.买点, pdg) }}</dd></div>
          <div :title="row.回落止损价说明 || protection?.reason"><dt class="text-ui-text-3">卖出侧</dt><dd class="sensitive mt-1 font-semibold tabular-nums text-down">{{ fmtNum(protection?.price, pdg) }}</dd></div>
          <div title="当日行情最低价"><dt class="text-ui-text-3">今日最低</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(row.今日最低 ?? row.最低, pdg) }}</dd></div>
          <div title="当日行情最高价"><dt class="text-ui-text-3">今日最高</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(row.今日最高 ?? row.最高, pdg) }}</dd></div>
        </dl>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" :class="dense ? 'mt-1.5' : 'mt-3'">
          <span v-if="dense" class="text-ui-text-2">{{ sellState ? '卖出侧' : '买入预警价' }} <b class="tabular-nums" :class="sellState ? 'text-down' : band === 'outside' ? 'text-ui-text-3' : 'text-up'">{{ fmtNum(sellState ? protection?.price : buyAlertPx, pdg) }}</b></span>
          <span v-if="!sellState && !Number(row.持仓) && !slotTrace && buyAlertPx != null && Number(row.现价) > 0" class="text-ui-text-2">距买点 <b class="tabular-nums">{{ fmtBuyDistance(row.现价, buyAlertPx) }}</b></span>
          <template v-if="!dense">
            <span v-if="displayFactorSide && displayFactorSide !== '-'" class="text-ui-text-2">因子侧 {{ displayFactorSide }}</span>
            <span v-if="!Number(row.持仓) && !slotTrace && row.因子触发 && row.因子触发 !== '-' && row.因子触发 !== '不可用'" class="text-ui-text-2">{{ row.因子触发 }}</span>
            <span v-if="row.槽位候选" class="text-accent">槽位候选</span>
            <span v-if="row.当日预警 && !row.持仓" class="text-accent">当日预警 · 未登记持仓</span>
          </template>
        </div>
        <p v-if="dense" class="mt-1 text-[11px] text-ui-text-2">预警类型：{{ alertType(row, sellState ? 'sell' : 'buy') }}</p>
        <p v-if="!dense && protection" class="mt-2 text-xs text-ui-text-2">卖出原因：{{ protection.reason }}</p>
        <p v-if="dense ? denseNote : noteText" :title="dense ? denseNote : undefined" class="text-ui-text-3" :class="dense ? 'mt-1 truncate text-[11px]' : 'mt-2 break-words text-xs leading-relaxed text-ui-text-2'">{{ dense ? denseNote : noteText }}</p>
        <footer v-if="!dense" class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-ui-hairline pt-2 text-[10px] text-ui-text-3">
          <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span class="inline-flex items-baseline gap-1.5">触发时间 <time class="font-mono font-semibold tabular-nums" :class="triggerTimeClass">{{ fmtSignalClock(row.信号时间) || '—' }}</time></span>
            <span>更新 {{ row.更新 || '—' }}</span>
          </div>
          <div class="flex items-center gap-3">
            <a :href="baiduStockUrl(row.代码, row.名称)" target="_blank" rel="noopener" class="hover:text-accent">行情 ↗</a>
            <NuxtLink :to="`/trades?code=${row.代码}`" class="hover:text-accent">交割 ↗</NuxtLink>
          </div>
        </footer>
      </template>
    </div>
  </article>
</template>
<style scoped>
.holding-card.signal-hold-real {
  background: linear-gradient(135deg, color-mix(in srgb, var(--watch-hold) 12%, var(--ui-surface)), color-mix(in srgb, var(--watch-hold) 4%, var(--ui-surface)));
}
.holding-day-pnl { margin-left: 0; font-size: .75rem; }
.holding-day-pnl :deep(.text-xs) { font-size: 11px; }
</style>
