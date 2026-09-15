<script setup lang="ts">
import type { WatchAccount } from '~/types/snapshot'

defineProps<{ account: WatchAccount }>()

function fmt(v?: number | null, d = 2) {
  if (v == null) return '-'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}
</script>

<template>
  <section class="card p-4">
    <div class="text-sm text-ui-text-2">
      总收益
      <span class="text-[10px] font-normal">自 {{ account.totalPnlStart || '2026-09-09' }} · 相对纸面本金</span>
    </div>
    <div class="sensitive text-3xl font-bold">
      <ChgText :chg="account.totalPnl">{{ account.totalPnl == null ? '-' : `${account.totalPnl >= 0 ? '+' : ''}${fmt(account.totalPnl)}` }}</ChgText>
      <span v-if="account.totalPnlPct != null" class="ml-2 text-lg font-semibold">
        <ChgText :chg="account.totalPnlPct">{{ (account.totalPnlPct >= 0 ? '+' : '') + account.totalPnlPct.toFixed(2) + '%' }}</ChgText>
      </span>
    </div>
    <div class="mt-2 text-sm">
      <span class="text-ui-text-2">今日盈亏 </span>
      <span class="sensitive font-semibold">
        <ChgText :chg="account.dayPnl">{{ account.dayPnl == null ? '-' : `${account.dayPnl >= 0 ? '+' : ''}${fmt(account.dayPnl)}` }}</ChgText>
        <template v-if="account.dayPnlPct != null">
          <ChgText :chg="account.dayPnlPct"> {{ (account.dayPnlPct >= 0 ? '+' : '') + account.dayPnlPct.toFixed(2) + '%' }}</ChgText>
        </template>
      </span>
      <span class="ml-1 text-[10px] text-ui-text-3">持仓+今日平仓</span>
    </div>
    <div class="sensitive mt-2 text-xs text-ui-text-2">
      总资产 {{ fmt(account.accountTotal) }}
      · 可用 {{ fmt(account.availableCash) }}
      · 仓位 {{ account.positionPct == null ? '-' : account.positionPct.toFixed(1) + '%' }}
      · 市值 {{ fmt(account.marketValue) }}
      · 成本 {{ fmt(account.cost) }}
      <template v-if="account.todayOpened"> · 当日开仓 {{ fmt(account.todayOpened) }}</template>
      <template v-if="account.settledCount"> · 今日平仓{{ account.settledCount }}笔</template>
      <template v-if="account.equityDayPnl != null"> · 权益日变 {{ fmt(account.equityDayPnl) }}</template>
    </div>
    <div v-if="account.factor2Summary" class="mt-2 text-xs text-ui-text-2">{{ account.factor2Summary }}</div>
  </section>
</template>
