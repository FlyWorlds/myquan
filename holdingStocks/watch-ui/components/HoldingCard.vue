<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, fmtSignedPct, fmtSignalClock, fmtSignedMoney } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'
import { resolveSignalVisual } from '~/composables/useSignalVisual'
import { fmtPositionPct, positionPctOf } from '~/utils/position'
import { holdingCyclePnl } from '~/utils/holdingCyclePnl'

const props = defineProps<{ row: HoldingRow; accountTotal?: number | null; dense?: boolean; band?: 'inside' | 'outside' }>()

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
              <span :class="band === 'outside' && visual.tier !== 'trigger-buy' ? 'signal-badge signal-badge-flat' : visual.badgeClass" :title="posStatus">{{ band === 'outside' && visual.tier !== 'trigger-buy' ? '线外' : visual.badgeText }}</span>
              <span v-if="visual.tier === 'trigger-buy' && touchClock" class="font-mono text-[11px] tabular-nums text-up">{{ touchClock }}</span>
              <span v-if="pinned" class="rounded-full border border-ui-hairline px-2 py-0.5 text-[10px] text-ui-text-2">置顶持仓</span>
              <span v-else-if="slotTrace" class="rounded-full border border-ui-hairline px-2 py-0.5 text-[10px] text-ui-text-2">今日平仓 · 不占槽</span>
              <span v-if="positionPct != null" class="sensitive text-xs tabular-nums text-ui-text-2" title="仓位占比 = 市值 / 总资产">仓位 {{ fmtPositionPct(positionPct) }}</span>
            </div>
          </div>
        </div>
        <div class="sensitive shrink-0 text-right tabular-nums">
          <div class="text-[10px] text-ui-text-3">现价</div>
          <b class="leading-tight" :class="dense ? 'text-base' : 'text-xl'">{{ fmtNum(row.现价, pdg) }}</b>
          <ChgText class="ml-2 text-xs font-semibold" :chg="row.当日涨幅">{{ fmtSignedPct(row.当日涨幅) }}</ChgText>
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
        <dl v-if="!dense && row.阈值就绪" class="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-ui-hairline p-3 text-xs sm:grid-cols-4">
          <div><dt class="text-ui-text-3">买入侧</dt><dd class="sensitive mt-1 font-semibold tabular-nums text-up">{{ fmtNum(row.买入侧价 ?? row.买点, pdg) }}</dd></div>
          <div><dt class="text-ui-text-3">卖出侧</dt><dd class="sensitive mt-1 font-semibold tabular-nums text-down">{{ fmtNum(row.卖出侧价 ?? row.止损, pdg) }}</dd></div>
          <div title="当日行情最低价"><dt class="text-ui-text-3">今日最低</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(row.今日最低 ?? row.最低, pdg) }}</dd></div>
          <div title="当日行情最高价"><dt class="text-ui-text-3">今日最高</dt><dd class="sensitive mt-1 font-semibold tabular-nums">{{ fmtNum(row.今日最高 ?? row.最高, pdg) }}</dd></div>
        </dl>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" :class="dense ? 'mt-1.5' : 'mt-3'">
          <span v-if="dense" class="text-ui-text-2">买入预警价 <b class="tabular-nums" :class="band === 'outside' ? 'text-ui-text-3' : 'text-up'">{{ buyAlertPx == null ? '—' : fmtNum(buyAlertPx, pdg) }}</b></span>
          <span v-if="row['距买点%'] != null && Number(row['距买点%']) < 9000" class="text-ui-text-2">距买点 <b class="tabular-nums">{{ Number(row['距买点%']).toFixed(2) }}%</b></span>
          <template v-if="!dense">
            <span v-if="row.因子侧 && row.因子侧 !== '-'" class="text-ui-text-2">因子侧 {{ row.因子侧 }}</span>
            <span v-if="row.因子触发 && row.因子触发 !== '-' && row.因子触发 !== '不可用'" class="text-ui-text-2">{{ row.因子触发 }}</span>
            <span v-if="row.槽位候选" class="text-accent">槽位候选</span>
            <span v-if="row.当日预警 && !row.持仓" class="text-accent">当日预警 · 未登记持仓</span>
          </template>
        </div>
        <p v-if="noteText" class="text-ui-text-3" :class="dense ? 'mt-1 truncate text-[11px]' : 'mt-2 break-words text-xs leading-relaxed text-ui-text-2'">{{ noteText }}</p>
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
