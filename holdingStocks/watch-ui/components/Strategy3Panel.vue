<script setup lang="ts">
import type { Strategy3Payload, StrategyTab } from '~/types/snapshot'
import { fmtNum, fmtSignedPct, stockLabel } from '~/utils/format'
import { baiduStockUrl } from '~/utils/stockLink'

const props = defineProps<{
  tab?: StrategyTab
  payload?: Strategy3Payload
  phase?: string
}>()

const sentiment = computed(() => props.payload?.sentiment)
const rows = computed(() => props.payload?.rows || [])
const backtest = computed(() => props.payload?.backtest || props.tab?.backtest || [])
const poolCount = computed(() => props.payload?.poolCount ?? rows.value.length)
const poolDate = computed(() => props.payload?.poolDate)
const cacheNote = computed(() => props.payload?.cacheNote || sentiment.value?.cacheNote)

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
        参照日 {{ sentiment.sentimentDate || '—' }} · 规则：{{ sentiment.rules }}
      </p>
      <p class="mt-1 text-xs text-ui-text-2">
        股池=昨日收盘涨停；买卖仅看因子1 ±阈值，<strong>不过</strong>前日阴/小阳过门。
      </p>
      <div class="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
        <div class="rounded-lg border border-ui-hairline p-3">
          <div class="text-xs text-ui-text-3">涨停家数</div>
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
          <p v-if="sentiment.luPhaseHint" class="mt-1 text-[10px] leading-snug text-ui-text-3">
            {{ sentiment.luPhaseHint }}
          </p>
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
          <div class="text-xs text-ui-text-3">梯度得分</div>
          <div class="text-lg font-semibold">{{ sentiment.mkt_ladder_score ?? '—' }}</div>
        </div>
      </div>
      <p v-if="sentiment.luPhaseRanges" class="mt-2 text-[10px] text-ui-text-3">
        情绪分段（T-1 中证1000 涨停家数）：{{ sentiment.luPhaseRanges }}
      </p>
      <p v-if="cacheNote" class="mt-1 text-xs text-amber-600 dark:text-amber-400">
        {{ cacheNote }}
      </p>
      <p v-if="!gateOk && sentiment.gateReasons?.length" class="mt-2 text-xs text-ui-text-2">
        未过：{{ sentiment.gateReasons.join('；') }}
      </p>
    </div>

    <div v-if="backtest.length" class="card p-4">
      <h3 class="text-base font-bold">回测摘要（中证1000 · 研究）</h3>
      <p class="mt-1 text-xs text-ui-text-3">2020-01 → 最新缓存 · 首板+gap/量比过滤 · T+1 出场 · 非投资建议</p>
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
            <tr v-for="b in backtest" :key="String(b.entry_pct)" class="border-t border-ui-hairline">
              <td class="px-2 py-2">±{{ ((b.entry_pct || 0) * 100).toFixed(1) }}%</td>
              <td class="px-2 py-2" :class="(b.total_return_pct || 0) >= 0 ? 'text-up' : 'text-down'">
                {{ fmtSignedPct(b.total_return_pct) }}
              </td>
              <td class="px-2 py-2">{{ (b.max_drawdown_pct ?? 0).toFixed(1) }}%</td>
              <td class="px-2 py-2">{{ (b.sharpe_ratio ?? 0).toFixed(2) }}</td>
              <td class="px-2 py-2">{{ ((b.win_rate ?? 0) * 100).toFixed(1) }}%</td>
              <td class="px-2 py-2">{{ b.n_trades ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card mb-2 p-3 text-sm">
      当前：<strong>{{ phase || '-' }}</strong>
      · 中证1000 <strong>昨日涨停股池</strong>（{{ poolCount }} 只{{ poolDate ? ` · 涨停日 ${poolDate}` : '' }}）
      · 因子1 ±阈值
      · 情绪：<strong :class="gateOk ? 'text-up' : 'text-ui-text-2'">{{ gateOk ? '可做' : '不做' }}</strong>
      <template v-if="sentiment?.luPhaseLabel && sentiment.luPhaseLabel !== '—'">
        · 涨停家数阶段：<strong>{{ sentiment.luPhaseLabel }}</strong>（{{ sentiment.mkt_lu ?? '—' }} 家）
      </template>
    </div>

    <div class="watch-table-wrap">
      <table class="watch-sticky-table">
        <thead>
          <tr>
            <th class="px-2 py-2">标的</th>
            <th class="px-2 py-2">连板</th>
            <th class="px-2 py-2">首板</th>
            <th class="px-2 py-2">晋级低开%</th>
            <th class="px-2 py-2">量比</th>
            <th class="px-2 py-2">可操作</th>
            <th class="px-2 py-2">买点</th>
            <th class="px-2 py-2">止损</th>
            <th class="px-2 py-2">因子侧</th>
            <th class="px-2 py-2">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in rows"
            :key="String(r.代码)"
            class="border-t border-ui-hairline"
            :class="!r.可操作 ? 'opacity-60' : ''"
          >
            <td class="px-2 py-2 sensitive">
              <a :href="baiduStockUrl(r.代码, r.名称)" target="_blank" rel="noopener" class="text-accent hover:underline">{{ stockLabel(r.代码, r.名称) }}</a>
            </td>
            <td class="px-2 py-2">{{ r.连板 ?? '—' }}</td>
            <td class="px-2 py-2" :class="r.昨日首板 ? 'font-semibold text-up' : ''">{{ r.昨日首板 ? '是' : '否' }}</td>
            <td class="px-2 py-2">{{ r['晋级低开%'] != null ? r['晋级低开%'] + '%' : '—' }}</td>
            <td class="px-2 py-2">{{ r.量比 ?? '—' }}</td>
            <td class="px-2 py-2" :class="r.可操作 ? 'font-semibold text-up' : 'text-ui-text-2'">
              {{ r.可操作 ? '是' : '否' }}
            </td>
            <td class="px-2 py-2 sensitive">{{ fmtNum(r.买点, 2) }}</td>
            <td class="px-2 py-2 sensitive">{{ fmtNum(r.止损, 2) }}</td>
            <td class="px-2 py-2">{{ r.因子侧 || '—' }}</td>
            <td class="max-w-[200px] px-2 py-2 text-xs text-ui-text-2">{{ r.挂单说明 || '—' }}</td>
          </tr>
          <tr v-if="!rows.length" class="border-t border-ui-hairline">
            <td colspan="10" class="px-2 py-6 text-center text-ui-text-3">暂无昨日涨停（或日线缓存未就绪）</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
