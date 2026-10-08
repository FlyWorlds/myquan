<script setup lang="ts">
import type { HoldingRow, WatchAccount } from '~/types/snapshot'
import { fmtPositionPct, positionPctOf } from '~/utils/position'

const props = defineProps<{ account: WatchAccount; holdings?: HoldingRow[] }>()
const { resetting, resetPaper } = usePaperReset()

async function onReset() {
  await resetPaper()
}

function fmt(v?: number | null, d = 2) {
  if (v == null) return '-'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}

const stockPositions = computed(() =>
  (props.holdings || [])
    .map((r) => ({ code: String(r.代码 || ''), name: String(r.名称 || r.代码 || ''), pct: positionPctOf(r, props.account.accountTotal) }))
    .filter((x): x is { code: string; name: string; pct: number } => x.pct != null)
    .sort((a, b) => b.pct - a.pct),
)

const totalPct = computed(() => props.account.positionPct ?? null)
const cashPct = computed(() => {
  const total = Number(props.account.accountTotal || 0)
  const cash = props.account.availableCash
  if (!(total > 0) || cash == null) return null
  return (Number(cash) / total) * 100
})
</script>

<template>
  <section class="card relative z-20 px-4 py-3.5">
    <div class="flex flex-wrap items-center justify-between gap-3 sm:flex-nowrap">
      <div class="min-w-0 flex-1 space-y-2.5">
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span
            class="text-xs text-ui-text-2"
            :title="`自 ${account.totalPnlStart || '2026-09-09'} · 日初+今日盈亏`"
          >总收益</span>
          <span class="sensitive text-2xl font-bold tabular-nums">
            <ChgText :chg="account.totalPnl">{{ account.totalPnl == null ? '-' : `${account.totalPnl >= 0 ? '+' : ''}${fmt(account.totalPnl)}` }}</ChgText>
            <ChgText v-if="account.totalPnlPct != null" class="ml-1 text-sm font-semibold" :chg="account.totalPnlPct">{{ (account.totalPnlPct >= 0 ? '+' : '') + account.totalPnlPct.toFixed(2) + '%' }}</ChgText>
          </span>
          <span class="text-sm" title="持仓+今日平仓">
            <span class="text-xs text-ui-text-2">今日 </span>
            <span class="sensitive font-semibold tabular-nums">
              <ChgText :chg="account.dayPnl">{{ account.dayPnl == null ? '-' : `${account.dayPnl >= 0 ? '+' : ''}${fmt(account.dayPnl)}` }}</ChgText>
              <ChgText v-if="account.dayPnlPct != null" :chg="account.dayPnlPct"> {{ (account.dayPnlPct >= 0 ? '+' : '') + account.dayPnlPct.toFixed(2) + '%' }}</ChgText>
            </span>
          </span>
          <span class="group relative self-center" tabindex="0">
            <span
              class="flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-ui-hairline-strong text-[10px] leading-none text-ui-text-3 group-hover:border-accent group-hover:text-accent group-focus:border-accent group-focus:text-accent"
              aria-label="账户明细"
            >?</span>
            <span
              class="card invisible absolute left-0 top-full z-50 mt-1.5 w-80 p-3 text-xs leading-relaxed text-ui-text-2 opacity-0 transition-opacity group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100"
            >
              <span class="sensitive grid grid-cols-2 gap-x-3 gap-y-0.5">
                <span>总资产 <b class="tabular-nums text-ui-text">{{ fmt(account.accountTotal) }}</b></span>
                <span>可用 <b class="tabular-nums text-ui-text">{{ fmt(account.availableCash) }}</b></span>
                <span>市值 <b class="tabular-nums text-ui-text">{{ fmt(account.marketValue) }}</b></span>
                <span>持仓成本 <b class="tabular-nums text-ui-text">{{ fmt(account.cost) }}</b></span>
                <span v-if="account.todayOpened">当日开仓 <b class="tabular-nums text-ui-text">{{ fmt(account.todayOpened) }}</b></span>
                <span v-if="account.settledCount">今日平仓 <b class="tabular-nums text-ui-text">{{ account.settledCount }} 笔</b></span>
                <span v-if="account.equityDayPnl != null">权益日变 <b class="tabular-nums text-ui-text">{{ fmt(account.equityDayPnl) }}</b></span>
              </span>
              <span v-if="account.factor2Summary" class="mt-2 block border-t border-ui-hairline pt-2">{{ account.factor2Summary }}</span>
              <span class="mt-2 block border-t border-ui-hairline pt-2 text-[11px] text-ui-text-3">
                总收益自 {{ account.totalPnlStart || '2026-09-09' }}，日初 + 今日盈亏；今日 = 持仓 + 今日平仓；仓位 = Σ市值 / 总资产
              </span>
            </span>
          </span>
          <NuxtLink to="/trades" class="self-center text-xs text-accent hover:underline">交割单 →</NuxtLink>
          <button
            type="button"
            class="self-center text-xs text-down hover:underline disabled:opacity-50"
            :disabled="resetting"
            title="清空全部纸面持仓并重置账户到默认资金"
            @click="onReset"
          >{{ resetting ? '重置中…' : '清空重置' }}</button>
        </div>
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <span class="text-ui-text-2" title="Σ市值 / 总资产">仓位</span>
          <b class="sensitive text-sm tabular-nums" :class="totalPct != null && totalPct > 100 ? 'text-ui-danger' : ''">{{ fmtPositionPct(totalPct) }}</b>
          <span class="h-1.5 w-24 overflow-hidden rounded-full bg-ui-hairline">
            <span class="sensitive block h-full rounded-full bg-accent transition-all" :style="{ width: `${Math.min(100, Math.max(0, totalPct ?? 0))}%` }" />
          </span>
          <span class="sensitive text-ui-text-3">现金 {{ fmtPositionPct(cashPct) }}</span>
          <span
            v-for="s in stockPositions"
            :key="s.code"
            class="rounded-full border border-ui-hairline px-1.5 leading-5"
            :title="`${s.name}(${s.code}) 市值/总资产`"
          >
            <StockNameHover :code="s.code" :name="s.name">
              <span class="sensitive">{{ s.name }}</span>
            </StockNameHover>
            <b class="sensitive ml-1 tabular-nums">{{ fmtPositionPct(s.pct) }}</b>
          </span>
        </div>
      </div>
      <div v-if="$slots.aside" class="ml-auto shrink-0">
        <slot name="aside" />
      </div>
    </div>
  </section>
</template>
