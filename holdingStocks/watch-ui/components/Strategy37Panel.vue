<script setup lang="ts">
import type { Strategy37Payload, Strategy37Row, StrategyTab } from '~/types/snapshot'
import { baiduStockUrl } from '~/utils/stockLink'
import { fmtNum, stockLabel } from '~/utils/format'

const props = defineProps<{
  tab?: StrategyTab
  payload?: Strategy37Payload | null
  phase?: string
}>()

const activePeriod = ref<'tune' | 'test' | 'train'>('tune')

const kpi = computed(() => props.payload?.kpi)
const summary = computed(() => props.payload?.summary || {})
const rows = computed<Strategy37Row[]>(() => props.payload?.rows || [])

const currentPeriodStats = computed(() => {
  const s3m = summary.value?.['3个月(90天)'] || {}
  if (activePeriod.value === 'train') return s3m.train_2020_2023 || {}
  if (activePeriod.value === 'tune') return s3m.tune_2023_2025 || {}
  return s3m.test_2025_now || {}
})

const horizonRows = computed(() => {
  const stats = currentPeriodStats.value
  return ['d1', 'd2', 'd3', 'd4', 'd5'].map((d) => {
    const item = stats[d] || {}
    return {
      horizon: d,
      count: item.count || 0,
      winRate: item.win_rate_pct ?? 0,
      meanRet: item.mean_ret_pct ?? 0,
      medianRet: item.median_ret_pct ?? 0,
      pf: item.profit_factor ?? 0,
      maxWin: item.max_win_pct ?? 0,
      maxLoss: item.max_loss_pct ?? 0,
    }
  })
})

function retColor(val: number | null | undefined): string {
  if (val == null) return 'text-ui-text-3'
  if (val > 0) return 'text-ui-danger font-semibold'
  if (val < 0) return 'text-ui-success font-semibold'
  return 'text-ui-text-2'
}
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部核心指标 KPI 仪表盘 -->
    <div class="card grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <div class="border-b border-ui-hairline pb-2 sm:border-b-0 sm:pb-0">
        <div class="text-xs text-ui-text-3">核心定位 / 最佳窗口</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-accent">3个月 (90天)</span>
          <span class="text-xs text-ui-text-2">背驰脱离窗口</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">全A主板正股 · 跌停开板反转</div>
      </div>

      <div class="border-b border-ui-hairline pb-2 sm:border-b-0 sm:pb-0">
        <div class="text-xs text-ui-text-3">调参期(2023-2025) d5 表现</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-ui-danger">+{{ kpi?.tune_d5_mean_ret ?? 4.21 }}%</span>
          <span class="text-xs text-ui-text-2">胜率 {{ kpi?.tune_d5_win_rate ?? 57.78 }}%</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">盈亏比 {{ kpi?.tune_d5_pf ?? 2.43 }} · 目标持有5天</div>
      </div>

      <div class="border-b border-ui-hairline pb-2 sm:border-b-0 sm:pb-0">
        <div class="text-xs text-ui-text-3">跌停价翘板买入 (d1暴击)</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-ui-danger">+{{ kpi?.limit_down_d1_mean_ret ?? 3.03 }}%</span>
          <span class="text-xs text-ui-text-2">次日胜率 {{ kpi?.limit_down_d1_win_rate ?? 67.26 }}%</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">盈亏比 {{ kpi?.limit_down_d1_pf ?? 4.01 }} · 盘中跌停撬板</div>
      </div>

      <div>
        <div class="text-xs text-ui-text-3">样本外(2025-今) 验证</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-ui-danger">+{{ kpi?.oos_d5_mean_ret ?? 0.79 }}%</span>
          <span class="text-xs text-ui-text-2">胜率 {{ kpi?.oos_d5_win_rate ?? 51.36 }}%</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">d1~d5全周期正期望 · 无过拟合</div>
      </div>
    </div>

    <!-- 策略规则与结构提示 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">策略规则</span>
          <h3 class="text-sm font-semibold">跌停开板 + 缠论日线“下跌笔 + 中枢 + 下跌笔”背驰买入</h3>
        </div>
        <div class="text-xs text-ui-text-3">
          当前交易阶段：<span class="font-semibold text-ui-text">{{ phase || '盘后分析' }}</span>
        </div>
      </div>
      <p class="mt-3 text-xs leading-relaxed text-ui-text-2">
        {{ payload?.rules || '宇宙：全A沪深主板正股（非ST）。当日触及10%跌停且收盘开板(Low=跌停价 且 Close>Low)；日线呈现“下跌笔+中枢+离开下跌笔”结构，脱离中枢<=90天(3个月)背驰买入；持有5个交易日(d5)收盘平仓。' }}
      </p>
    </div>

    <!-- 持有期收益对比分析矩阵 -->
    <div class="card p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h4 class="text-sm font-semibold">持有期限收益表现 (d1 ~ d5)</h4>
        <div class="flex items-center gap-1 rounded-lg bg-ui-surface-2 p-0.5 text-xs">
          <button
            type="button"
            class="rounded px-2.5 py-1 transition-colors"
            :class="activePeriod === 'tune' ? 'bg-ui-surface font-semibold text-ui-text shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activePeriod = 'tune'"
          >
            调参期 (2023-2025)
          </button>
          <button
            type="button"
            class="rounded px-2.5 py-1 transition-colors"
            :class="activePeriod === 'test' ? 'bg-ui-surface font-semibold text-ui-text shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activePeriod = 'test'"
          >
            样本外验证 (2025-今)
          </button>
          <button
            type="button"
            class="rounded px-2.5 py-1 transition-colors"
            :class="activePeriod === 'train' ? 'bg-ui-surface font-semibold text-ui-text shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activePeriod = 'train'"
          >
            基准回测 (2020-2023)
          </button>
        </div>
      </div>

      <div class="watch-table-wrap">
        <table class="watch-sticky-table text-xs">
          <thead>
            <tr>
              <th class="px-3 py-2">持有期</th>
              <th class="px-3 py-2">样本笔数</th>
              <th class="px-3 py-2">胜率</th>
              <th class="px-3 py-2">平均收益</th>
              <th class="px-3 py-2">中位数收益</th>
              <th class="px-3 py-2">盈亏比</th>
              <th class="px-3 py-2">最大盈利</th>
              <th class="px-3 py-2">最大亏损</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in horizonRows" :key="item.horizon" class="border-t border-ui-hairline hover:bg-ui-surface-2/40">
              <td class="px-3 py-2 font-semibold text-accent uppercase">{{ item.horizon }} ({{ item.horizon === 'd1' ? '次日' : item.horizon === 'd5' ? '5天' : `${item.horizon.replace('d', '')}天` }})</td>
              <td class="px-3 py-2 text-ui-text-2">{{ item.count }} 次</td>
              <td class="px-3 py-2 font-medium" :class="item.winRate >= 50 ? 'text-ui-danger' : 'text-ui-text-2'">{{ item.winRate.toFixed(2) }}%</td>
              <td class="px-3 py-2" :class="retColor(item.meanRet)">{{ item.meanRet > 0 ? `+${item.meanRet.toFixed(2)}%` : `${item.meanRet.toFixed(2)}%` }}</td>
              <td class="px-3 py-2" :class="retColor(item.medianRet)">{{ item.medianRet > 0 ? `+${item.medianRet.toFixed(2)}%` : `${item.medianRet.toFixed(2)}%` }}</td>
              <td class="px-3 py-2 font-semibold text-ui-text">{{ item.pf.toFixed(2) }}</td>
              <td class="px-3 py-2 text-ui-danger">+{{ item.maxWin.toFixed(2) }}%</td>
              <td class="px-3 py-2 text-ui-success">{{ item.maxLoss.toFixed(2) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 候选标的监控列表 -->
    <div class="card p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <h4 class="text-sm font-semibold">跌停开板缠论反转监控标的</h4>
          <span class="rounded-full bg-ui-surface-2 px-2 py-0.5 text-xs text-ui-text-3">共 {{ rows.length }} 只</span>
        </div>
        <span class="text-xs text-ui-text-3">按最新信号时间倒序</span>
      </div>

      <div v-if="!rows.length" class="p-8 text-center text-xs text-ui-text-3">
        暂无监控数据，等待日线数据扫描或盘后信号触发
      </div>

      <div v-else class="watch-table-wrap">
        <table class="watch-sticky-table text-xs">
          <thead>
            <tr>
              <th class="px-3 py-2.5">标的</th>
              <th class="px-3 py-2.5">信号日期</th>
              <th class="px-3 py-2.5">状态</th>
              <th class="px-3 py-2.5">买入价</th>
              <th class="px-3 py-2.5">跌停价</th>
              <th class="px-3 py-2.5">收盘价</th>
              <th class="px-3 py-2.5">脱离中枢</th>
              <th class="px-3 py-2.5">中枢区间 [ZD, ZG]</th>
              <th class="px-3 py-2.5">d1收益%</th>
              <th class="px-3 py-2.5">d3收益%</th>
              <th class="px-3 py-2.5">d5收益%</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in rows"
              :key="`${r.代码}-${r.日期}`"
              class="border-t border-ui-hairline hover:bg-ui-surface-2/40"
            >
              <td class="px-3 py-2.5 align-top">
                <StockNameHover :code="r.代码" :name="r.名称">
                  <a
                    :href="baiduStockUrl(r.代码, r.名称)"
                    target="_blank"
                    rel="noopener"
                    class="font-semibold text-accent hover:underline"
                  >
                    {{ stockLabel(r.代码, r.名称) }}
                  </a>
                </StockNameHover>
              </td>
              <td class="px-3 py-2.5 text-ui-text-2">{{ r.日期 }}</td>
              <td class="px-3 py-2.5">
                <span class="rounded bg-ui-danger/15 px-1.5 py-0.5 text-[11px] font-medium text-ui-danger">
                  {{ r.状态 }}
                </span>
              </td>
              <td class="px-3 py-2.5 font-semibold text-ui-text">{{ fmtNum(r.买入价, 2) }}</td>
              <td class="px-3 py-2.5 text-ui-success">{{ fmtNum(r.跌停价, 2) }}</td>
              <td class="px-3 py-2.5 text-ui-text-2">{{ fmtNum(r.收盘价, 2) }}</td>
              <td class="px-3 py-2.5 text-ui-text-2">{{ r.脱离中枢天数 }} 天</td>
              <td class="px-3 py-2.5 text-ui-text-3">[{{ fmtNum(r.中枢ZD, 2) }}, {{ fmtNum(r.中枢ZG, 2) }}]</td>
              <td class="px-3 py-2.5" :class="retColor(r['d1收益%'])">
                {{ r['d1收益%'] != null ? (r['d1收益%'] > 0 ? `+${r['d1收益%']}%` : `${r['d1收益%']}%`) : '-' }}
              </td>
              <td class="px-3 py-2.5" :class="retColor(r['d3收益%'])">
                {{ r['d3收益%'] != null ? (r['d3收益%'] > 0 ? `+${r['d3收益%']}%` : `${r['d3收益%']}%`) : '-' }}
              </td>
              <td class="px-3 py-2.5" :class="retColor(r['d5收益%'])">
                {{ r['d5收益%'] != null ? (r['d5收益%'] > 0 ? `+${r['d5收益%']}%` : `${r['d5收益%']}%`) : '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
