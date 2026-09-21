<script setup lang="ts">
import type { TradeLedgerEntry, TradeLedgerResponse } from '~/types/trades'
import { fmtNum } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'

const route = useRoute()
const codeFilter = computed(() => {
  const c = String(route.query.code || '').replace(/\D/g, '')
  return c ? c.padStart(6, '0').slice(-6) : ''
})

const loading = ref(true)
const error = ref('')
const payload = ref<TradeLedgerResponse | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const qs = new URLSearchParams()
    if (codeFilter.value) qs.set('code', codeFilter.value)
    qs.set('limit', '500')
    const res = await fetch(`/api/trades?${qs.toString()}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    payload.value = (await res.json()) as TradeLedgerResponse
  } catch (e: any) {
    error.value = String(e?.message || e)
    payload.value = null
  } finally {
    loading.value = false
  }
}

watch(codeFilter, () => load(), { immediate: true })

const entries = computed(() => payload.value?.entries || [])
const summary = computed(() => payload.value?.summary)

function sideLabel(e: TradeLedgerEntry) {
  if (e.side === 'buy') return '买入'
  if (e.action_kind === 'half') return '卖出·半仓'
  return '卖出'
}

function fmtMoney(v?: number | null) {
  if (v == null) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<template>
  <div class="page-shell py-6">
    <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-xl font-bold">交割单 · 买卖明细</h1>
        <p class="mt-1 text-sm text-ui-text-2">
          纸面账本 JSON（每次入槽买入 / 平仓卖出落库）
          <template v-if="codeFilter"> · 筛选 {{ codeFilter }}</template>
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <NuxtLink v-if="codeFilter" to="/trades" class="btn btn-ghost">全部明细</NuxtLink>
        <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">刷新</button>
        <NuxtLink to="/" class="btn btn-ghost">返回盯盘</NuxtLink>
      </div>
    </div>

    <section v-if="summary" class="card mb-4 grid gap-2 p-4 text-sm sm:grid-cols-4">
      <div>
        <div class="text-ui-text-2">笔数</div>
        <div class="sensitive font-semibold">{{ summary.count ?? 0 }}</div>
      </div>
      <div>
        <div class="text-ui-text-2">买入金额</div>
        <div class="sensitive font-semibold">{{ fmtMoney(summary.buy_amount) }}</div>
      </div>
      <div>
        <div class="text-ui-text-2">卖出金额</div>
        <div class="sensitive font-semibold">{{ fmtMoney(summary.sell_amount) }}</div>
      </div>
      <div>
        <div class="text-ui-text-2">卖出盈亏合计</div>
        <div class="sensitive font-semibold">
          <ChgText :chg="summary.sell_pnl">{{ fmtMoney(summary.sell_pnl) }}</ChgText>
        </div>
      </div>
    </section>

    <div v-if="loading" class="card p-6 text-sm text-ui-text-2">加载中…</div>
    <div v-else-if="error" class="card p-6 text-sm text-down">加载失败：{{ error }}</div>
    <div v-else-if="!entries.length" class="card p-6 text-sm text-ui-text-2">暂无成交明细</div>
    <div v-else class="card overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead class="border-b border-ui-hairline text-xs text-ui-text-2">
          <tr>
            <th class="px-3 py-2">时间</th>
            <th class="px-3 py-2">方向</th>
            <th class="px-3 py-2">代码/名称</th>
            <th class="px-3 py-2">价格</th>
            <th class="px-3 py-2">仓位</th>
            <th class="px-3 py-2">金额</th>
            <th class="px-3 py-2">成本</th>
            <th class="px-3 py-2">单笔盈亏</th>
            <th class="px-3 py-2">账户余额</th>
            <th class="px-3 py-2">理由</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="e in entries"
            :key="e.id || `${e.time}-${e.code}-${e.side}-${e.qty}`"
            class="border-b border-ui-hairline/60 align-top"
          >
            <td class="sensitive whitespace-nowrap px-3 py-2 tabular-nums">{{ e.time || '—' }}</td>
            <td class="px-3 py-2">
              <span
                class="rounded-full border px-2 py-0.5 text-xs"
                :class="e.side === 'buy' ? 'border-up/40 text-up' : 'border-down/40 text-down'"
              >{{ sideLabel(e) }}</span>
            </td>
            <td class="px-3 py-2">
              <div class="font-medium">
                <NuxtLink
                  :to="`/trades?code=${e.code}`"
                  class="hover:text-accent hover:underline"
                >{{ e.name || e.code }}</NuxtLink>
              </div>
              <div class="flex flex-wrap items-center gap-2 text-xs text-ui-text-2">
                <span class="sensitive">{{ e.code }}</span>
                <a
                  :href="baiduStockUrl(e.code, e.name)"
                  target="_blank"
                  rel="noopener"
                  class="text-accent hover:underline"
                >价格单</a>
              </div>
            </td>
            <td class="sensitive px-3 py-2 tabular-nums">{{ fmtNum(e.price, 2) }}</td>
            <td class="sensitive px-3 py-2 tabular-nums">
              {{ e.qty }}
              <span class="text-xs text-ui-text-3">→{{ e.after_qty }}</span>
            </td>
            <td class="sensitive px-3 py-2 tabular-nums">{{ fmtMoney(e.amount) }}</td>
            <td class="sensitive px-3 py-2 tabular-nums">{{ e.cost == null ? '—' : fmtNum(e.cost, 4) }}</td>
            <td class="sensitive px-3 py-2 tabular-nums">
              <template v-if="e.pnl != null">
                <ChgText :chg="e.pnl">{{ (e.pnl >= 0 ? '+' : '') + fmtMoney(e.pnl) }}</ChgText>
                <span v-if="e.pnl_pct != null" class="ml-1 text-xs">
                  <ChgText :chg="e.pnl_pct">{{ (e.pnl_pct >= 0 ? '+' : '') + e.pnl_pct.toFixed(2) + '%' }}</ChgText>
                </span>
                <div
                  v-if="e.pnl_kind === 'unrealized' || e.side === 'sell'"
                  class="mt-0.5 text-[10px] text-ui-text-3"
                >{{ e.pnl_kind === 'unrealized' ? '浮动' : '已实现' }}</div>
              </template>
              <template v-else>—</template>
            </td>
            <td class="sensitive px-3 py-2 tabular-nums">{{ fmtMoney(e.account_cash_after) }}</td>
            <td class="max-w-[16rem] px-3 py-2 text-xs text-ui-text-2">
              <div>{{ e.reason || '—' }}</div>
              <div v-if="e.reason_detail && e.reason_detail !== e.reason" class="mt-0.5 text-ui-text-3">
                {{ e.reason_detail }}
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="mt-3 text-xs text-ui-text-3">
      数据文件：holdingStocks/trade_ledger.json · 更新于 {{ payload?.updated_at || '—' }}
    </p>
  </div>
</template>
