<script setup lang="ts">
import * as echarts from 'echarts'

interface BacktestMetrics {
  strategy_final_return?: number
  sh_final_return_x2?: number
  sh_final_return_raw?: number
  alpha?: number
  max_drawdown?: number
  n_buys?: number
  n_sells?: number
  n_closed?: number
  avg_closed_pnl?: number
}

interface BacktestPayload {
  date: string
  updated_at: string
  dates: string[]
  strategy_cum_pct: number[]
  strategy_daily_pct: number[]
  strategy_ma7_pct: number[]
  sh_cum_pct: number[]
  sh_cum_x2_pct: number[]
  sh_daily_pct: number[]
  sh_daily_x2_pct: number[]
  alpha_cum_pct: number[]
  sh_kline: [number, number, number, number][]
  metrics: BacktestMetrics
}

interface BacktestApiResponse {
  running: boolean
  started_at?: string
  error?: string
  latest?: BacktestPayload
  history_dates?: string[]
}

const chartEl = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

const activeChartTab = ref<'line' | 'kline' | 'daily'>('line')
const loading = ref(false)
const running = ref(false)
const latestData = ref<BacktestPayload | null>(null)
const lastUpdatedAt = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchStatus() {
  try {
    const res = await fetch('/api/strategy1/backtest')
    if (!res.ok) return
    const data: BacktestApiResponse = await res.json()
    running.value = Boolean(data.running)
    if (data.latest) {
      latestData.value = data.latest
      lastUpdatedAt.value = data.latest.updated_at || data.latest.date || ''
      updateChart()
    }
    if (running.value && !pollTimer) {
      pollTimer = setInterval(fetchStatus, 3000)
    } else if (!running.value && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
      loading.value = false
    }
  } catch (err) {
    console.error('Failed to load strategy1 backtest:', err)
  }
}

async function triggerBacktest() {
  if (loading.value || running.value) return
  loading.value = true
  running.value = true
  try {
    const res = await fetch('/api/strategy1/backtest', { method: 'POST' })
    if (res.ok) {
      if (!pollTimer) {
        pollTimer = setInterval(fetchStatus, 3000)
      }
    } else {
      loading.value = false
      running.value = false
    }
  } catch (err) {
    console.error('Trigger backtest error:', err)
    loading.value = false
    running.value = false
  }
}

function initChart() {
  if (!chartEl.value) return
  if (!myChart) {
    myChart = echarts.init(chartEl.value)
  }
  const w = chartEl.value.clientWidth
  if (w > 50) {
    myChart.resize()
  }
}

function updateChart() {
  if (!chartEl.value || !latestData.value) return
  initChart()
  if (!myChart) return
  const d = latestData.value
  const dates = d.dates || []

  if (activeChartTab.value === 'line') {
    // 1. 折线趋势对比图：策略1 累计 vs 7MA 均线 vs 上证*2
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          let s = `<div class="font-bold border-b border-gray-600/50 pb-1 mb-1">${params[0]?.name || ''}</div>`
          for (const p of params) {
            const v = p.value != null ? `${Number(p.value).toFixed(2)}%` : '—'
            s += `<div class="flex items-center justify-between gap-4 py-0.5 text-xs">
              <span class="inline-flex items-center gap-1.5">${p.marker} ${p.seriesName}</span>
              <span class="font-mono font-bold">${v}</span>
            </div>`
          }
          return s
        },
      },
      legend: {
        type: 'scroll',
        orient: 'horizontal',
        data: ['策略1 累计收益', '策略1 7日均线(7MA)', '上证指数×2 累计收益', '超额 Alpha'],
        textStyle: { color: '#9ca3af', fontSize: 11 },
        top: 4,
        right: 8,
        itemGap: 14,
      },
      grid: { left: 12, right: 16, bottom: 12, top: 40, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.25)', type: 'dashed' } },
        axisLabel: {
          color: '#9ca3af',
          formatter: '{value}%',
          fontSize: 11,
        },
      },
      series: [
        {
          name: '策略1 累计收益',
          type: 'line',
          data: d.strategy_cum_pct,
          smooth: true,
          showSymbol: true,
          symbolSize: 6,
          lineStyle: { width: 3, color: '#10b981' },
          itemStyle: { color: '#10b981' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(16, 185, 129, 0.28)' },
              { offset: 1, color: 'rgba(16, 185, 129, 0.02)' },
            ]),
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ yAxis: 0, lineStyle: { color: 'rgba(156, 163, 175, 0.5)', type: 'dashed' } }],
          },
        },
        {
          name: '策略1 7日均线(7MA)',
          type: 'line',
          data: d.strategy_ma7_pct,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: '#06b6d4', type: 'dashed' },
          itemStyle: { color: '#06b6d4' },
        },
        {
          name: '上证指数×2 累计收益',
          type: 'line',
          data: d.sh_cum_x2_pct,
          smooth: true,
          showSymbol: true,
          symbolSize: 5,
          lineStyle: { width: 2.2, color: '#f59e0b' },
          itemStyle: { color: '#f59e0b' },
        },
        {
          name: '超额 Alpha',
          type: 'line',
          data: d.alpha_cum_pct,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#ec4899', type: 'dotted' },
          itemStyle: { color: '#ec4899' },
        },
      ],
    }, true)
  } else if (activeChartTab.value === 'kline') {
    // 2. K线图：上证指数蜡烛线 + 超额收益柱状图
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: {
        type: 'scroll',
        orient: 'horizontal',
        data: ['上证指数 K线', '超额 Alpha(%)'],
        textStyle: { color: '#9ca3af', fontSize: 11 },
        top: 4,
        right: 8,
        itemGap: 14,
      },
      grid: [
        { left: 12, right: 16, top: 40, height: '52%', containLabel: true },
        { left: 12, right: 16, top: '74%', height: '20%', containLabel: true },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#4b5563' } },
          axisLabel: { show: false },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          axisLine: { lineStyle: { color: '#4b5563' } },
          axisLabel: { color: '#9ca3af', fontSize: 10 },
        },
      ],
      yAxis: [
        {
          scale: true,
          splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.25)', type: 'dashed' } },
          axisLabel: { color: '#9ca3af', fontSize: 11 },
        },
        {
          scale: true,
          gridIndex: 1,
          splitLine: { show: false },
          axisLabel: { color: '#9ca3af', fontSize: 10, formatter: '{value}%' },
        },
      ],
      series: [
        {
          name: '上证指数 K线',
          type: 'candlestick',
          data: d.sh_kline,
          itemStyle: {
            color: '#ef4444',
            color0: '#10b981',
            borderColor: '#ef4444',
            borderColor0: '#10b981',
          },
        },
        {
          name: '超额 Alpha(%)',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: d.alpha_cum_pct.map((val) => ({
            value: val,
            itemStyle: { color: val >= 0 ? '#10b981' : '#ef4444' },
          })),
        },
      ],
    }, true)
  } else {
    // 3. 每日对比柱状图：策略1 单日收益 vs 上证指数*2 单日
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: any) => {
          let s = `<div class="font-bold pb-1 mb-1 border-b border-gray-600/50">${params[0]?.name || ''}</div>`
          for (const p of params) {
            s += `<div class="flex justify-between gap-4 py-0.5 text-xs">
              <span>${p.marker} ${p.seriesName}</span>
              <span class="font-mono font-bold">${p.value != null ? Number(p.value).toFixed(2) : '—'}%</span>
            </div>`
          }
          return s
        },
      },
      legend: {
        type: 'scroll',
        orient: 'horizontal',
        data: ['策略1 单日收益', '上证指数×2 单日'],
        textStyle: { color: '#9ca3af', fontSize: 11 },
        top: 4,
        right: 8,
        itemGap: 14,
      },
      grid: { left: 12, right: 16, bottom: 12, top: 40, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.25)', type: 'dashed' } },
        axisLabel: { color: '#9ca3af', formatter: '{value}%', fontSize: 11 },
      },
      series: [
        {
          name: '策略1 单日收益',
          type: 'bar',
          data: d.strategy_daily_pct,
          itemStyle: {
            color: '#10b981',
            borderRadius: [3, 3, 0, 0],
          },
        },
        {
          name: '上证指数×2 单日',
          type: 'bar',
          data: d.sh_daily_x2_pct,
          itemStyle: {
            color: '#f59e0b',
            borderRadius: [3, 3, 0, 0],
          },
        },
      ],
    }, true)
  }

  nextTick(() => {
    myChart?.resize()
  })
}

watch(activeChartTab, () => {
  nextTick(() => {
    updateChart()
  })
})

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  nextTick(() => {
    initChart()
    fetchStatus()
  })

  if (typeof ResizeObserver !== 'undefined' && chartEl.value) {
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 50) {
          if (!myChart && chartEl.value) {
            initChart()
            if (latestData.value) updateChart()
          } else {
            myChart?.resize()
          }
        }
      }
    })
    resizeObserver.observe(chartEl.value)
  }

  const onResize = () => {
    if (chartEl.value && chartEl.value.clientWidth > 50) {
      myChart?.resize()
    }
  }
  window.addEventListener('resize', onResize)

  onBeforeUnmount(() => {
    window.removeEventListener('resize', onResize)
    resizeObserver?.disconnect()
    if (pollTimer) clearInterval(pollTimer)
    myChart?.dispose()
  })
})
</script>

<template>
  <div class="mt-3 rounded-xl border border-ui-hairline/80 bg-ui-surface-2/30 p-3 sm:p-4 text-ui-text">
    <!-- 头部指标卡片与触发按钮 -->
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline/60 pb-3">
      <div class="flex items-center gap-2">
        <span class="inline-flex items-center justify-center rounded-lg bg-emerald-500/15 px-2 py-1 text-xs font-bold text-emerald-400">
          7日高频仿真
        </span>
        <h3 class="text-sm font-bold text-ui-text">策略1 vs 上证指数×2 表现对比</h3>
        <span v-if="lastUpdatedAt" class="text-xs text-ui-text-3">
          (更新: {{ lastUpdatedAt }})
        </span>
      </div>

      <div class="flex items-center gap-2">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/15 px-3 py-1.5 text-xs font-bold text-accent transition hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="loading || running"
          @click="triggerBacktest"
        >
          <svg
            v-if="loading || running"
            class="h-3.5 w-3.5 animate-spin"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity=".25" />
            <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
          </svg>
          <span v-if="loading || running">回测计算中 (覆盖当天)...</span>
          <span v-else>⚡ 运行最近7天回测</span>
        </button>
      </div>
    </div>

    <!-- 关键数据指标小牌 -->
    <div v-if="latestData?.metrics" class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface/60 p-2 text-center">
        <div class="text-[11px] text-ui-text-3">策略1 7日累计收益</div>
        <div class="mt-0.5 text-base font-bold" :class="(latestData.metrics.strategy_final_return ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'">
          {{ (latestData.metrics.strategy_final_return ?? 0) > 0 ? '+' : '' }}{{ latestData.metrics.strategy_final_return }}%
        </div>
      </div>
      <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface/60 p-2 text-center">
        <div class="text-[11px] text-ui-text-3">上证指数×2 7日收益</div>
        <div class="mt-0.5 text-base font-bold" :class="(latestData.metrics.sh_final_return_x2 ?? 0) >= 0 ? 'text-amber-400' : 'text-rose-400'">
          {{ (latestData.metrics.sh_final_return_x2 ?? 0) > 0 ? '+' : '' }}{{ latestData.metrics.sh_final_return_x2 }}%
        </div>
      </div>
      <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface/60 p-2 text-center">
        <div class="text-[11px] text-ui-text-3">超额 Alpha (策略 - 指数×2)</div>
        <div class="mt-0.5 text-base font-bold text-emerald-400">
          {{ (latestData.metrics.alpha ?? 0) > 0 ? '+' : '' }}{{ latestData.metrics.alpha }}%
        </div>
      </div>
      <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface/60 p-2 text-center">
        <div class="text-[11px] text-ui-text-3">7日最大回撤 / 回合数</div>
        <div class="mt-0.5 text-base font-bold text-ui-text">
          {{ latestData.metrics.max_drawdown }}% / {{ latestData.metrics.n_closed }}次
        </div>
      </div>
    </div>

    <!-- 视图切换与图表容器 -->
    <div class="mt-3">
      <div class="flex items-center justify-between gap-2 border-b border-ui-hairline/40 pb-1.5">
        <div class="inline-flex rounded-lg bg-ui-surface/80 p-0.5 text-xs">
          <button
            type="button"
            class="rounded-md px-2.5 py-1 font-medium transition"
            :class="activeChartTab === 'line' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'line'"
          >
            趋势对比折线图 (7MA)
          </button>
          <button
            type="button"
            class="rounded-md px-2.5 py-1 font-medium transition"
            :class="activeChartTab === 'kline' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'kline'"
          >
            上证K线 & 超额Alpha
          </button>
          <button
            type="button"
            class="rounded-md px-2.5 py-1 font-medium transition"
            :class="activeChartTab === 'daily' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'daily'"
          >
            每日收益柱状图
          </button>
        </div>

        <span class="text-[11px] text-ui-text-3">
          支持多次运行覆盖当天数据
        </span>
      </div>

      <!-- ECharts 宿主 -->
      <div ref="chartEl" class="mt-2 h-64 w-full min-w-full sm:h-72" style="width: 100%; min-width: 100%;"></div>
    </div>
  </div>
</template>
