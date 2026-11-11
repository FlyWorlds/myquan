<script setup lang="ts">
import * as echarts from 'echarts'

function returnClass(value?: number): string {
  return value == null || value === 0 ? 'text-ui-text' : value > 0 ? 'text-rose-400' : 'text-emerald-400'
}

interface BacktestSummary {
  strategy_return_pct?: number
  benchmark_return_pct?: number
  alpha_pct?: number
  annualized_return_pct?: number
  max_drawdown_pct?: number
  sharpe_ratio?: number
  win_rate_pct?: number
  profit_factor?: number
  total_trades?: number
  win_trades?: number
  loss_trades?: number
  avg_holding_days?: number
  cash_gate_days?: number
  cash_gate_pct?: number
  initial_capital?: number
  final_capital?: number
}

interface TradeRecord {
  code: string
  name: string
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  pnl_pct: number
  holding_days: number
  exit_reason: string
  volume_multiple?: number
}

interface StockContribution {
  code: string
  name: string
  total_pnl_pct: number
  trades_count: number
  win_rate: number
  avg_pnl: number
}

interface BacktestLatest {
  params: Record<string, any>
  updated_at: string
  summary: BacktestSummary
  dates: string[]
  equity_curve: number[]
  benchmark_curve: number[]
  alpha_curve: number[]
  drawdown_curve: number[]
  daily_returns: number[]
  trades: TradeRecord[]
  stock_contributions: StockContribution[]
}

interface BacktestStatusResponse {
  running: boolean
  started_at?: string
  progress?: {
    stage: string
    percent: number
    completed: number
    total: number
  }
  error?: string
  params?: Record<string, any>
  latest?: BacktestLatest
}

// 可选参数状态表单
const form = reactive({
  universe: 'hs300',
  start_date: '2024-01-01',
  end_date: new Date().toISOString().slice(0, 10),
  benchmark: '000985',
  initial_capital: 1000000,
  max_positions: 5,
  single_position_max_pct: 0.20,
  // Step 1
  enable_cash_gate: true,
  cash_gate_ma: 'ma60',
  // Step 2
  ban_st: true,
  mainboard_only: true,
  min_price: 3.0,
  max_price: 120.0,
  min_amount: 30000000,
  // Step 3
  lookback: 60,
  max_age: 10,
  volume_multiple: 2.0,
  body_min: 0.05,
  recent_hit_days: 3,
  // Step 4
  buy_mode: 'breakout',
  take_profit_pct: 0.08,
  stop_loss_pct: -0.04,
  max_hold_days: 5,
})

// 折叠高级参数面板
const showAdvanced = ref(false)

// 视图切换
const activeChartTab = ref<'equity' | 'drawdown' | 'daily'>('equity')
const activeTableTab = ref<'trades' | 'stocks'>('trades')

const chartEl = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

const loading = ref(false)
const running = ref(false)
const progress = ref<{ stage: string; percent: number; completed: number; total: number }>()
const errorMessage = ref('')
const latestData = ref<BacktestLatest | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

function applyQuickDateRange(months: number) {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - months)
  form.start_date = start.toISOString().slice(0, 10)
  form.end_date = end.toISOString().slice(0, 10)
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/strategy38/backtest', { signal: AbortSignal.timeout(8000) })
    if (!res.ok) throw new Error(`状态查询异常 (${res.status})`)
    const data: BacktestStatusResponse = await res.json()
    running.value = Boolean(data.running)
    loading.value = false
    progress.value = data.progress
    errorMessage.value = data.error || ''
    if (data.latest) {
      latestData.value = data.latest
      updateChart()
    }
    if (running.value) {
      if (!pollTimer) {
        pollTimer = setInterval(fetchStatus, 1000)
      }
    } else if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch (err) {
    console.error('Fetch strategy38 status error:', err)
  }
}

async function triggerBacktest() {
  if (loading.value || running.value) return
  loading.value = true
  running.value = true
  errorMessage.value = ''
  try {
    const res = await fetch('/api/strategy38/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
      signal: AbortSignal.timeout(10000),
    })
    if (res.ok) {
      await fetchStatus()
      if (!pollTimer) {
        pollTimer = setInterval(fetchStatus, 1000)
      }
    } else {
      errorMessage.value = `启动回测失败 (${res.status})`
      loading.value = false
      running.value = false
    }
  } catch (err) {
    errorMessage.value = '启动请求未确认，正在查询后台状态...'
    if (!pollTimer) pollTimer = setInterval(fetchStatus, 1500)
    loading.value = false
    running.value = false
  }
}

function initChart() {
  if (!chartEl.value) return
  if (!myChart) {
    myChart = echarts.init(chartEl.value)
  }
  myChart.resize()
}

function updateChart() {
  if (!chartEl.value || !latestData.value) return
  initChart()
  if (!myChart) return

  const d = latestData.value
  const dates = d.dates || []

  if (activeChartTab.value === 'equity') {
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any[]) => {
          let html = `<div class="font-bold border-b border-gray-600/50 pb-1 mb-1">${params[0]?.name || ''}</div>`
          for (const item of params) {
            const v = item.value != null ? `${Number(item.value).toFixed(2)}%` : '—'
            html += `<div class="flex items-center justify-between gap-4 py-0.5 text-xs">
              <span style="color:${item.color}">${item.seriesName}:</span>
              <span class="font-bold">${v}</span>
            </div>`
          }
          return html
        },
      },
      legend: {
        data: ['策略38 累计净值收益', '基准指数 累计收益', '超额 Alpha (策略 - 基准)'],
        textStyle: { color: '#9ca3af' },
        top: 0,
      },
      grid: { left: '3%', right: '4%', bottom: '8%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af' },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#374151' } },
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.2)' } },
        axisLabel: { formatter: '{value}%', color: '#9ca3af' },
      },
      series: [
        {
          name: '策略38 累计净值收益',
          type: 'line',
          data: d.equity_curve,
          smooth: true,
          itemStyle: { color: '#ff4d4f' },
          lineStyle: { width: 2.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(255, 77, 79, 0.25)' },
              { offset: 1, color: 'rgba(255, 77, 79, 0.0)' },
            ]),
          },
        },
        {
          name: '基准指数 累计收益',
          type: 'line',
          data: d.benchmark_curve,
          smooth: true,
          itemStyle: { color: '#eab308' },
          lineStyle: { width: 1.8, type: 'dashed' },
        },
        {
          name: '超额 Alpha (策略 - 基准)',
          type: 'line',
          data: d.alpha_curve,
          smooth: true,
          itemStyle: { color: '#06b6d4' },
          lineStyle: { width: 1.8 },
        },
      ],
    }, true)
  } else if (activeChartTab.value === 'drawdown') {
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any[]) => {
          const item = params[0]
          return `<div class="font-bold">${item?.name}</div>
            <div class="text-xs text-emerald-400 mt-1">动态回撤深度: <b>${item?.value}%</b></div>`
        },
      },
      legend: {
        data: ['水下动态回撤 (Drawdown Depth)'],
        textStyle: { color: '#9ca3af' },
        top: 0,
      },
      grid: { left: '3%', right: '4%', bottom: '8%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af' },
      },
      yAxis: {
        type: 'value',
        max: 0,
        axisLine: { lineStyle: { color: '#374151' } },
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.2)' } },
        axisLabel: { formatter: '{value}%', color: '#9ca3af' },
      },
      series: [
        {
          name: '水下动态回撤 (Drawdown Depth)',
          type: 'line',
          data: d.drawdown_curve,
          smooth: true,
          itemStyle: { color: '#10b981' },
          lineStyle: { width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(16, 185, 129, 0.05)' },
              { offset: 1, color: 'rgba(16, 185, 129, 0.35)' },
            ]),
          },
        },
      ],
    }, true)
  } else if (activeChartTab.value === 'daily') {
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params: any[]) => {
          const item = params[0]
          const val = Number(item?.value || 0)
          return `<div class="font-bold">${item?.name}</div>
            <div class="text-xs mt-1" style="color:${val >= 0 ? '#ff4d4f' : '#22c55e'}">
              单日组合盈亏: <b>${val >= 0 ? '+' : ''}${val.toFixed(2)}%</b>
            </div>`
        },
      },
      legend: {
        data: ['每日组合盈亏率'],
        textStyle: { color: '#9ca3af' },
        top: 0,
      },
      grid: { left: '3%', right: '4%', bottom: '8%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af' },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#374151' } },
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.2)' } },
        axisLabel: { formatter: '{value}%', color: '#9ca3af' },
      },
      series: [
        {
          name: '每日组合盈亏率',
          type: 'bar',
          data: d.daily_returns.map((val) => ({
            value: val,
            itemStyle: { color: val >= 0 ? '#ff4d4f' : '#22c55e' },
          })),
        },
      ],
    }, true)
  }

  nextTick(() => myChart?.resize())
}

watch(activeChartTab, () => {
  nextTick(() => updateChart())
})

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  nextTick(() => {
    initChart()
    fetchStatus()
  })

  if (typeof ResizeObserver !== 'undefined' && chartEl.value) {
    resizeObserver = new ResizeObserver(() => {
      myChart?.resize()
    })
    resizeObserver.observe(chartEl.value)
  }

  const handleResize = () => myChart?.resize()
  window.addEventListener('resize', handleResize)

  onBeforeUnmount(() => {
    window.removeEventListener('resize', handleResize)
    resizeObserver?.disconnect()
    if (pollTimer) clearInterval(pollTimer)
    myChart?.dispose()
  })
})
</script>

<template>
  <div class="space-y-4">
    <!-- 回测多维手选参数控制台卡片 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-accent/20 px-2 py-0.5 text-xs font-bold text-accent">参数调优</span>
          <h3 class="text-sm font-bold text-ui-text">策略38 多维回测控制台</h3>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="text-xs text-accent hover:underline"
            @click="showAdvanced = !showAdvanced"
          >
            {{ showAdvanced ? '收起高级变量 ▲' : '展开漏斗详细变量 ▼' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-accent/40 bg-accent/20 px-3.5 py-1.5 text-xs font-bold text-accent transition hover:bg-accent/30 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="loading || running"
            @click="triggerBacktest"
          >
            <svg
              v-if="loading || running"
              class="h-3.5 w-3.5 animate-spin text-accent"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity=".25" />
              <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
            </svg>
            <span v-if="loading || running">
              回测中 {{ progress?.percent || 0 }}%
            </span>
            <span v-else>⚡ 运行多维参数回测</span>
          </button>
        </div>
      </div>

      <!-- 快捷参数区 -->
      <div class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
        <!-- 股票池 -->
        <div>
          <label class="block text-ui-text-3 font-medium">1. 选股股票池 (Universe)</label>
          <select
            v-model="form.universe"
            class="mt-1 w-full rounded-md border border-ui-hairline bg-ui-surface px-2.5 py-1.5 text-ui-text focus:border-accent focus:outline-none"
          >
            <option value="hs300">沪深300（大盘蓝筹）</option>
            <option value="zz500">中证500（中盘成长）</option>
            <option value="zz800">中证800（综合主力）</option>
            <option value="zz1000">中证1000（小盘弹性）</option>
            <option value="mainboard">全市场主板 (60/00)</option>
          </select>
        </div>

        <!-- 对比基准 -->
        <div>
          <label class="block text-ui-text-3 font-medium">2. 对比基准指数 (Benchmark)</label>
          <select
            v-model="form.benchmark"
            class="mt-1 w-full rounded-md border border-ui-hairline bg-ui-surface px-2.5 py-1.5 text-ui-text focus:border-accent focus:outline-none"
          >
            <option value="000985">中证全指（000985 · 全市场基准）</option>
            <option value="000300">沪深300（000300 · 大盘指数）</option>
            <option value="000905">中证500（000905 · 中盘指数）</option>
          </select>
        </div>

        <!-- 回测起止日期范围 -->
        <div class="sm:col-span-2">
          <label class="block text-ui-text-3 font-medium mb-1">3. 回测时间区间 (Date Range)</label>
          <AppDatePicker
            mode="range"
            v-model:start="form.start_date"
            v-model:end="form.end_date"
            placeholder="点击选择回测起止日期范围"
          />
        </div>
      </div>

      <!-- 快捷时间预设按钮 -->
      <div class="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-ui-text-3">
        <span>快速区间：</span>
        <button
          type="button"
          class="rounded bg-ui-surface-2 px-2 py-0.5 hover:text-accent"
          @click="applyQuickDateRange(1)"
        >
          近1个月
        </button>
        <button
          type="button"
          class="rounded bg-ui-surface-2 px-2 py-0.5 hover:text-accent"
          @click="applyQuickDateRange(3)"
        >
          近3个月
        </button>
        <button
          type="button"
          class="rounded bg-ui-surface-2 px-2 py-0.5 hover:text-accent"
          @click="applyQuickDateRange(6)"
        >
          近半年
        </button>
        <button
          type="button"
          class="rounded bg-ui-surface-2 px-2 py-0.5 hover:text-accent"
          @click="applyQuickDateRange(12)"
        >
          近1年
        </button>
        <button
          type="button"
          class="rounded bg-ui-surface-2 px-2 py-0.5 hover:text-accent"
          @click="applyQuickDateRange(36)"
        >
          近3年
        </button>
      </div>

      <!-- 展开高级漏斗手选参数 -->
      <div v-if="showAdvanced" class="mt-4 border-t border-ui-hairline/80 pt-3 text-xs">
        <h4 class="font-bold text-accent mb-2">漏斗各层核心变量手选设置：</h4>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <!-- Step 1 因子35 -->
          <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface-2/30 p-2.5">
            <div class="font-semibold text-ui-text mb-1.5">Step 1: 绝对风控 (因子35)</div>
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input v-model="form.enable_cash_gate" type="checkbox" class="rounded text-accent" />
              <span>开启大盘一票否决空仓</span>
            </label>
            <div class="mt-2">
              <span class="text-ui-text-3">大盘生命线周期:</span>
              <select v-model="form.cash_gate_ma" class="mt-1 w-full rounded border border-ui-hairline bg-ui-surface px-1.5 py-1">
                <option value="ma20">MA20（短线敏感）</option>
                <option value="ma60">MA60（中线标准）</option>
                <option value="ma120">MA120（半年线大防守）</option>
              </select>
            </div>
          </div>

          <!-- Step 2 因子13A -->
          <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface-2/30 p-2.5">
            <div class="font-semibold text-ui-text mb-1.5">Step 2: 质地清洗 (因子13A)</div>
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input v-model="form.ban_st" type="checkbox" class="rounded text-accent" />
              <span>严格剔除 ST 与退市预警</span>
            </label>
            <label class="mt-1 flex items-center gap-1.5 cursor-pointer">
              <input v-model="form.mainboard_only" type="checkbox" class="rounded text-accent" />
              <span>仅限沪深主板 (排除双创/北交)</span>
            </label>
          </div>

          <!-- Step 3 因子34 -->
          <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface-2/30 p-2.5">
            <div class="font-semibold text-ui-text mb-1.5">Step 3: 地量起爆 (因子34)</div>
            <div class="flex items-center justify-between">
              <span class="text-ui-text-3">放量起爆倍数:</span>
              <span class="font-bold text-accent">{{ form.volume_multiple }}x</span>
            </div>
            <input
              v-model.number="form.volume_multiple"
              type="range"
              min="1.5"
              max="3.5"
              step="0.1"
              class="mt-1 w-full accent-accent"
            />
            <div class="mt-1.5 flex items-center justify-between">
              <span class="text-ui-text-3">长周期缩量窗口:</span>
              <span class="font-bold text-accent">{{ form.lookback }}日</span>
            </div>
            <input
              v-model.number="form.lookback"
              type="range"
              min="5"
              max="90"
              step="1"
              class="mt-1 w-full accent-accent"
            />
            <div class="mt-1 flex items-center justify-between text-[10px] text-ui-text-3">
              <button type="button" class="hover:text-accent" @click="form.lookback = 5">极短5日</button>
              <button type="button" class="hover:text-accent" @click="form.lookback = 20">月度20日</button>
              <button type="button" class="hover:text-accent" @click="form.lookback = 60">季度60日</button>
              <button type="button" class="hover:text-accent" @click="form.lookback = 90">半年90日</button>
            </div>
          </div>

          <!-- Step 4 执行与风控 -->
          <div class="rounded-lg border border-ui-hairline/60 bg-ui-surface-2/30 p-2.5">
            <div class="font-semibold text-ui-text mb-1.5">Step 4: 挂单与止盈止损</div>
            <div class="flex items-center justify-between">
              <span class="text-ui-text-3">目标止盈率:</span>
              <span class="font-bold text-ui-danger">+{{ (form.take_profit_pct * 100).toFixed(1) }}%</span>
            </div>
            <input
              v-model.number="form.take_profit_pct"
              type="range"
              min="0.04"
              max="0.15"
              step="0.01"
              class="mt-1 w-full accent-ui-danger"
            />
            <div class="mt-1.5 flex items-center justify-between">
              <span class="text-ui-text-3">严格止损率:</span>
              <span class="font-bold text-ui-success">{{ (form.stop_loss_pct * 100).toFixed(1) }}%</span>
            </div>
            <input
              v-model.number="form.stop_loss_pct"
              type="range"
              min="-0.08"
              max="-0.02"
              step="0.005"
              class="mt-1 w-full accent-ui-success"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 运行动态进度条 -->
    <div
      v-if="running && progress"
      class="rounded-xl border border-accent/40 bg-accent/10 p-3 text-xs text-ui-text shadow-sm"
      role="status"
    >
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <span class="rounded bg-accent/20 px-2 py-0.5 font-bold text-accent">执行仿真中</span>
          <span class="font-medium">{{ progress.stage }}</span>
        </div>
        <span class="font-mono text-sm font-extrabold text-accent">{{ progress.percent }}%</span>
      </div>
      <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-ui-surface-3/80">
        <div
          class="h-full rounded-full bg-gradient-to-r from-teal-400 via-emerald-400 to-accent transition-all duration-300"
          :style="{ width: `${Math.max(4, progress.percent)}%` }"
        ></div>
      </div>
    </div>

    <!-- 异常警示 -->
    <div
      v-if="errorMessage"
      class="rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-xs text-rose-400"
      role="alert"
    >
      ⚠️ {{ errorMessage }}
    </div>

    <!-- 核心 KPI 看板 (8大指标) -->
    <div v-if="latestData?.summary" class="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8 text-xs text-center">
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">策略累计收益</div>
        <div class="mt-1 text-base font-bold" :class="returnClass(latestData.summary.strategy_return_pct)">
          {{ (latestData.summary.strategy_return_pct ?? 0) > 0 ? '+' : '' }}{{ latestData.summary.strategy_return_pct }}%
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">基准收益率</div>
        <div class="mt-1 text-base font-bold" :class="returnClass(latestData.summary.benchmark_return_pct)">
          {{ (latestData.summary.benchmark_return_pct ?? 0) > 0 ? '+' : '' }}{{ latestData.summary.benchmark_return_pct }}%
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">超额 Alpha</div>
        <div class="mt-1 text-base font-bold text-cyan-400">
          {{ (latestData.summary.alpha_pct ?? 0) > 0 ? '+' : '' }}{{ latestData.summary.alpha_pct }}%
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">年化收益 (CAGR)</div>
        <div class="mt-1 text-base font-bold" :class="returnClass(latestData.summary.annualized_return_pct)">
          {{ (latestData.summary.annualized_return_pct ?? 0) > 0 ? '+' : '' }}{{ latestData.summary.annualized_return_pct }}%
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">夏普比率 (Sharpe)</div>
        <div class="mt-1 text-base font-bold text-accent">
          {{ latestData.summary.sharpe_ratio }}
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">最大回撤 (MaxDD)</div>
        <div class="mt-1 text-base font-bold text-emerald-400">
          {{ latestData.summary.max_drawdown_pct }}%
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">胜率 / 盈亏比</div>
        <div class="mt-1 text-base font-bold text-ui-text">
          {{ latestData.summary.win_rate_pct }}% / {{ latestData.summary.profit_factor }}
        </div>
      </div>
      <div class="card p-2.5">
        <div class="text-[11px] text-ui-text-3">交易笔数 / 空仓天</div>
        <div class="mt-1 text-base font-bold text-ui-text">
          {{ latestData.summary.total_trades }}笔 / {{ latestData.summary.cash_gate_days }}天
        </div>
      </div>
    </div>

    <!-- 图表容器与视图切换 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline/60 pb-2">
        <div class="inline-flex rounded-lg bg-ui-surface p-0.5 text-xs">
          <button
            type="button"
            class="rounded-md px-3 py-1 font-medium transition"
            :class="activeChartTab === 'equity' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'equity'"
          >
            累计资产对比 (策略 vs 基准 vs Alpha)
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1 font-medium transition"
            :class="activeChartTab === 'drawdown' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'drawdown'"
          >
            水下动态回撤曲线
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1 font-medium transition"
            :class="activeChartTab === 'daily' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'daily'"
          >
            每日收益柱状图
          </button>
        </div>
        <span v-if="latestData?.updated_at" class="text-xs text-ui-text-3">
          数据生成时间: {{ latestData.updated_at }}
        </span>
      </div>

      <!-- ECharts 宿主容器 -->
      <div ref="chartEl" class="mt-3 h-72 w-full sm:h-80"></div>
    </div>

    <!-- 回测明细表格：交易日志 与 单股收益贡献 -->
    <div class="card p-4">
      <div class="flex items-center justify-between border-b border-ui-hairline/60 pb-2">
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="text-xs font-bold transition"
            :class="activeTableTab === 'trades' ? 'text-accent border-b-2 border-accent pb-1' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeTableTab = 'trades'"
          >
            交易记录明细表 (共 {{ latestData?.trades?.length || 0 }} 笔)
          </button>
          <button
            type="button"
            class="text-xs font-bold transition ml-4"
            :class="activeTableTab === 'stocks' ? 'text-accent border-b-2 border-accent pb-1' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeTableTab = 'stocks'"
          >
            单股累计收益贡献排行榜 (共 {{ latestData?.stock_contributions?.length || 0 }} 只)
          </button>
        </div>
      </div>

      <!-- 交易记录明细 -->
      <div v-if="activeTableTab === 'trades'" class="watch-table-wrap mt-3 max-h-80 overflow-auto">
        <table class="watch-sticky-table text-xs">
          <thead>
            <tr>
              <th class="px-3 py-2">代码 / 标的</th>
              <th class="px-3 py-2">买入日期</th>
              <th class="px-3 py-2">买入均价</th>
              <th class="px-3 py-2">卖出日期</th>
              <th class="px-3 py-2">卖出均价</th>
              <th class="px-3 py-2">单笔收益率</th>
              <th class="px-3 py-2">持有天数</th>
              <th class="px-3 py-2">放量倍数</th>
              <th class="px-3 py-2">离场原因</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(t, idx) in latestData?.trades || []"
              :key="`${t.code}-${t.entry_date}-${idx}`"
              class="border-t border-ui-hairline hover:bg-ui-surface-2/40"
            >
              <td class="px-3 py-2 font-semibold text-accent">{{ t.code }} · {{ t.name }}</td>
              <td class="px-3 py-2 text-ui-text-2">{{ t.entry_date }}</td>
              <td class="px-3 py-2">{{ t.entry_price.toFixed(2) }}</td>
              <td class="px-3 py-2 text-ui-text-2">{{ t.exit_date }}</td>
              <td class="px-3 py-2">{{ t.exit_price.toFixed(2) }}</td>
              <td class="px-3 py-2 font-bold" :class="returnClass(t.pnl_pct)">
                {{ t.pnl_pct > 0 ? '+' : '' }}{{ t.pnl_pct.toFixed(2) }}%
              </td>
              <td class="px-3 py-2 text-ui-text-2">{{ t.holding_days }} 天</td>
              <td class="px-3 py-2 text-accent font-medium">{{ t.volume_multiple || 2.4 }}x</td>
              <td class="px-3 py-2 text-ui-text-3">{{ t.exit_reason }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 单股收益贡献明细 -->
      <div v-else class="watch-table-wrap mt-3 max-h-80 overflow-auto">
        <table class="watch-sticky-table text-xs">
          <thead>
            <tr>
              <th class="px-3 py-2">股票标的</th>
              <th class="px-3 py-2">累计贡献收益率</th>
              <th class="px-3 py-2">交易笔数</th>
              <th class="px-3 py-2">胜率</th>
              <th class="px-3 py-2">平均单笔收益</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in latestData?.stock_contributions || []"
              :key="s.code"
              class="border-t border-ui-hairline hover:bg-ui-surface-2/40"
            >
              <td class="px-3 py-2 font-semibold text-ui-text">{{ s.code }} · {{ s.name }}</td>
              <td class="px-3 py-2 font-bold" :class="returnClass(s.total_pnl_pct)">
                {{ s.total_pnl_pct > 0 ? '+' : '' }}{{ s.total_pnl_pct.toFixed(2) }}%
              </td>
              <td class="px-3 py-2 text-ui-text-2">{{ s.trades_count }} 次</td>
              <td class="px-3 py-2 text-ui-text-2">{{ s.win_rate }}%</td>
              <td class="px-3 py-2 font-medium" :class="returnClass(s.avg_pnl)">
                {{ s.avg_pnl > 0 ? '+' : '' }}{{ s.avg_pnl.toFixed(2) }}%
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
