<script setup lang="ts">
import type { Strategy8Payload, StrategyTab } from '~/types/snapshot'
import { fmtNum, fmtSignedPct, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'

const props = defineProps<{
  tab?: StrategyTab
  payload?: Strategy8Payload
  phase?: string
}>()

const sentiment = computed(() => props.payload?.sentiment)
const rows = computed(() => props.payload?.rows || [])
const nameMap = computed(() => props.payload?.nameMap || {})

function rowLabel(code?: string | null, name?: string | null) {
  const c = String(code || '').trim()
  const n = String(name || '').trim() || String(nameMap.value[c] || '').trim()
  return stockLabel(c, n)
}
const hotThemes = computed(() => props.payload?.hotThemes || [])
const backtest = computed(() => props.payload?.backtest || props.tab?.backtest || [])
const poolCount = computed(() => props.payload?.poolCount ?? rows.value.length)
const poolDate = computed(() => props.payload?.themeDate ?? props.payload?.poolDate)
const gateOk = computed(() => sentiment.value?.gateOk === true)

const luPhaseClass = computed(() => {
  const p = sentiment.value?.luPhase
  if (p === 'ice') return 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
  if (p === 'climax') return 'bg-orange-500/15 text-orange-700 dark:text-orange-300'
  if (p === 'normal') return 'bg-up/15 text-up'
  return 'bg-ui-surface-2 text-ui-text-2'
})
</script>

<template>
  <div class="space-y-4">
    <div v-if="sentiment" class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-bold">T-1 市场情绪（今日可否做）</h3>
        <span
          class="rounded-full px-2 py-0.5 text-xs font-semibold"
          :class="gateOk ? 'bg-up/15 text-up' : 'bg-ui-surface-2 text-ui-text-2'"
        >
          {{ gateOk ? '今日可做' : '今日不做' }}
        </span>
      </div>
      <p class="mt-1 text-xs text-ui-text-3">
        参照日 {{ sentiment.sentimentDate || '—' }} · {{ payload?.rules || sentiment.rules }}
      </p>
      <p class="mt-1 text-xs text-ui-text-2">
        <strong>当日涨停</strong>定题材（{{ payload?.luCount ?? '—' }} 只涨停，随盘中涨停变化重算）→ 题材内<strong>直接</strong>因子1 ±阈值，不要求昨日涨停。
        <span v-if="payload?.themeUpdatedAt"> · 刷新 {{ payload.themeUpdatedAt }}</span>
      </p>
      <div class="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div class="rounded-lg border border-ui-hairline p-3">
          <div class="text-xs text-ui-text-3">涨停家数（T-1）</div>
          <div class="mt-1 flex flex-wrap items-center gap-2">
            <div class="text-lg font-semibold">{{ sentiment.mkt_lu ?? '—' }}</div>
            <span
              v-if="sentiment.luPhaseLabel && sentiment.luPhaseLabel !== '—'"
              class="rounded-full px-2 py-0.5 text-xs font-semibold"
              :class="luPhaseClass"
            >
              {{ sentiment.luPhaseLabel }}
            </span>
          </div>
        </div>
        <div class="rounded-lg border border-ui-hairline p-3">
          <div class="text-xs text-ui-text-3">连板家数</div>
          <div class="text-lg font-semibold">{{ sentiment.mkt_lianban ?? '—' }}</div>
        </div>
        <div class="rounded-lg border border-ui-hairline p-3">
          <div class="text-xs text-ui-text-3">最高板</div>
          <div class="text-lg font-semibold">{{ sentiment.mkt_max_height ?? '—' }}</div>
        </div>
        <div class="rounded-lg border border-ui-hairline p-3">
          <div class="text-xs text-ui-text-3">热题材数</div>
          <div class="text-lg font-semibold">{{ hotThemes.length }}</div>
        </div>
      </div>
    </div>

    <div v-if="hotThemes.length" class="card p-4">
      <h3 class="text-base font-bold">热题材（当日涨停共振 ≥3）</h3>
      <p class="mt-1 text-xs text-ui-text-3">
        题材日 {{ payload?.themeDate || poolDate || '—' }}
        <span v-if="payload?.live"> · 实时涨停集合</span>
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <span
          v-for="t in hotThemes"
          :key="t.name"
          class="rounded-full border border-ui-hairline px-3 py-1 text-xs"
        >
          {{ t.name }} · {{ t.luCount }}涨停
        </span>
      </div>
    </div>

    <div v-if="backtest.length" class="card p-4">
      <h3 class="text-base font-bold">回测摘要（2025→ · 研究）</h3>
      <p class="mt-1 text-xs text-ui-text-3">当日涨停定题材 · 联动±阈值 · T+1 出场 · 非投资建议</p>
      <div class="mt-3 overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead class="text-left text-ui-text-2">
            <tr>
              <th class="px-2 py-2">阈值</th>
              <th class="px-2 py-2">总收益</th>
              <th class="px-2 py-2">回撤</th>
              <th class="px-2 py-2">夏普</th>
              <th class="px-2 py-2">胜率</th>
              <th class="px-2 py-2">笔数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in backtest" :key="String(row.entry_pct)">
              <td class="px-2 py-2">±{{ ((row.entry_pct || 0) * 100).toFixed(1) }}%</td>
              <td class="px-2 py-2" :class="(row.total_return_pct || 0) >= 0 ? 'text-up' : 'text-down'">
                {{ fmtSignedPct(row.total_return_pct) }}
              </td>
              <td class="px-2 py-2">{{ fmtSignedPct(row.max_drawdown_pct) }}</td>
              <td class="px-2 py-2">{{ fmtNum(row.sharpe_ratio, 2) }}</td>
              <td class="px-2 py-2">{{ fmtNum((row.win_rate || 0) * 100, 1) }}%</td>
              <td class="px-2 py-2">{{ row.n_trades }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card overflow-x-auto p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-base font-bold">题材联动候选池</h3>
        <span class="text-xs text-ui-text-3">{{ poolCount }} 只 · 题材日 {{ poolDate || '—' }}</span>
      </div>
      <table class="min-w-full text-sm">
        <thead class="text-left text-ui-text-2">
          <tr>
            <th class="px-2 py-2">标的</th>
            <th class="px-2 py-2">题材</th>
            <th class="px-2 py-2">类型</th>
            <th class="px-2 py-2">题材涨停</th>
            <th class="px-2 py-2">可操作</th>
            <th class="px-2 py-2">买点</th>
            <th class="px-2 py-2">止损</th>
            <th class="px-2 py-2">因子侧</th>
            <th class="px-2 py-2">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.代码)" class="border-t border-ui-hairline">
            <td class="px-2 py-2 whitespace-nowrap">
              <a
                :href="baiduStockUrl(row.代码, row.名称)"
                target="_blank"
                rel="noopener"
                class="text-accent hover:underline"
              >
                {{ rowLabel(row.代码, row.名称) }}
              </a>
            </td>
            <td class="px-2 py-2 max-w-[8rem] truncate" :title="String(row.题材)">{{ row.题材 }}</td>
            <td class="px-2 py-2">{{ row.类型 }}</td>
            <td class="px-2 py-2">{{ row.题材涨停数 }}</td>
            <td class="px-2 py-2">{{ row.可操作 ? '是' : '否' }}</td>
            <td class="px-2 py-2">{{ row.买点 ?? '—' }}</td>
            <td class="px-2 py-2">{{ row.止损 ?? '—' }}</td>
            <td class="px-2 py-2">{{ row.因子侧 }}</td>
            <td class="px-2 py-2 text-xs text-ui-text-2">{{ row.挂单说明 }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!rows.length" class="py-6 text-center text-sm text-ui-text-3">暂无题材共振候选</p>
    </div>
  </div>
</template>
