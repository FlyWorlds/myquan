<script setup lang="ts">
import * as echarts from 'echarts'

function returnClass(value?: number): string {
  return value == null || value === 0 ? 'text-white' : value > 0 ? 'text-rose-400' : 'text-emerald-400'
}

function getTodayDateStr(): string {
  const d = new Date()
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const todayDateStr = getTodayDateStr()

interface BacktestSummary {
  strategy_return_pct?: number
  benchmark_return_pct?: number
  alpha_pct?: number
  annualized_return_pct?: number
  max_drawdown_pct?: number
  sharpe_ratio?: number
  calmar_ratio?: number
  win_rate_pct?: number
  profit_factor?: number
  total_trades?: number
  win_trades?: number
  loss_trades?: number
  avg_holding_days?: number
  max_holding_days?: number
  initial_capital?: number
  final_capital?: number
  universe_count?: number
  today_signal_count?: number
}

interface TradeRecord {
  symbol: string
  code: string
  name: string
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  shares: number
  pnl_amount: number
  pnl_pct: number
  holding_days: number
  peak_price: number
  max_pnl_pct: number
  exit_reason: string
}

interface ExitReasonBreakdown {
  reason: string
  count: number
  pct_of_total: number
  win_rate: number
  avg_pnl_pct: number
}

interface StockContribution {
  code: string
  name: string
  trades_count: number
  total_pnl_amount: number
  total_pnl_pct: number
  win_rate: number
  avg_pnl: number
}

interface TodaySignalItem {
  symbol: string
  code: string
  name: string
  date: string
  close: number
  buy_price?: number
  depth_pct: number
  anchor_price: number
  peak_price: number
  buy_trigger_price?: number
  support_buy_price: number
  stop_loss_price: number
  target_price: number
  logic: string
}

interface BacktestLatest {
  params: Record<string, any>
  updated_at: string
  is_single_day?: boolean
  target_day?: string
  summary: BacktestSummary
  dates: string[]
  equity_curve: number[]
  benchmark_curve: number[]
  alpha_curve: number[]
  drawdown_curve: number[]
  daily_returns: number[]
  trades: TradeRecord[]
  today_signals?: TodaySignalItem[]
  exit_reason_breakdown: ExitReasonBreakdown[]
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

// 表单参数
const form = reactive({
  universe: 'zz1000',
  start_date: '2025-01-01',
  end_date: todayDateStr,
  benchmark: '000852',
  initial_capital: 1000000,
  max_positions: 5,
  // 核心条件 1：命中信号后持股时间
  max_hold_days: 10,
  // 核心条件 2：回撤条件
  enable_trailing_drawdown: true,
  trailing_drawdown_pct: 0.04,
  trailing_profit_threshold: 0.02,
  stop_loss_pct: -0.05,
  take_profit_pct: 0.10,
})

const showAdvanced = ref(false)
const activeChartTab = ref<'equity' | 'drawdown' | 'daily'>('equity')
const activeTableTab = ref<'trades' | 'reasons' | 'stocks'>('trades')
const searchQuery = ref('')
const signalSearchQuery = ref('')
const copiedNotice = ref(false)

const chartEl = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

const loading = ref(false)
const running = ref(false)
const progress = ref<{ stage: string; percent: number; completed: number; total: number }>()
const errorMessage = ref('')
const latestData = ref<BacktestLatest | null>(null)
let pollTimer: ReturnType<typeof setInterval> | null = null

// 判断是否为单日今日信号模式
const isSingleDayMode = computed(() => {
  return Boolean(form.start_date && form.end_date && form.start_date === form.end_date)
})

// 快捷区间切换
function applyQuickToday() {
  form.start_date = todayDateStr
  form.end_date = todayDateStr
}

function applyQuickDateRange(months: number) {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - months)
  form.start_date = start.toISOString().slice(0, 10)
  form.end_date = end.toISOString().slice(0, 10)
}

function applyQuickDaysRange(days: number) {
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - days)
  form.start_date = start.toISOString().slice(0, 10)
  form.end_date = end.toISOString().slice(0, 10)
}

// 快捷预设档位
function applyPreset(preset: 'short' | 'standard' | 'medium') {
  if (preset === 'short') {
    form.max_hold_days = 5
    form.trailing_drawdown_pct = 0.03
    form.stop_loss_pct = -0.04
    form.take_profit_pct = 0.08
  } else if (preset === 'standard') {
    form.max_hold_days = 10
    form.trailing_drawdown_pct = 0.04
    form.stop_loss_pct = -0.05
    form.take_profit_pct = 0.10
  } else if (preset === 'medium') {
    form.max_hold_days = 20
    form.trailing_drawdown_pct = 0.06
    form.stop_loss_pct = -0.07
    form.take_profit_pct = 0.15
  }
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/strategy3/backtest', { signal: AbortSignal.timeout(8000) })
    if (!res.ok) throw new Error(`状态查询异常 (${res.status})`)
    const data: BacktestStatusResponse = await res.json()
    running.value = Boolean(data.running)
    loading.value = false
    progress.value = data.progress
    errorMessage.value = data.error || ''
    if (data.latest) {
      latestData.value = data.latest
      if (!data.latest.is_single_day) {
        nextTick(() => {
          updateChart()
        })
      }
    }
    if (running.value) {
      if (!pollTimer) {
        pollTimer = setInterval(fetchStatus, 1500)
      }
    } else if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  } catch (err: any) {
    errorMessage.value = err?.message || '读取回测状态失败'
  }
}

async function startBacktest() {
  if (running.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await fetch('/api/strategy3/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    const data = await res.json()
    if (!res.ok || data.error) {
      throw new Error(data.error || data.detail || '启动回测失败')
    }
    running.value = true
    if (!pollTimer) {
      pollTimer = setInterval(fetchStatus, 1500)
    }
  } catch (err: any) {
    loading.value = false
    running.value = false
    errorMessage.value = err?.message || '网络异常'
  }
}

function updateChart() {
  if (!chartEl.value || !latestData.value || latestData.value.is_single_day) return
  if (!myChart) {
    myChart = echarts.init(chartEl.value)
  }

  const d = latestData.value
  const dates = d.dates || []

  if (activeChartTab.value === 'equity') {
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          let html = `<div class="text-xs p-1 text-white"><strong>${params[0]?.axisValue}</strong><br/>`
          for (const item of params) {
            const val = item.value != null ? `${Number(item.value).toFixed(2)}%` : '—'
            html += `${item.marker} ${item.seriesName}: <strong>${val}</strong><br/>`
          }
          html += '</div>'
          return html
        },
      },
      legend: {
        data: ['策略3累计收益', '基准指数收益', '超额 Alpha'],
        textStyle: { color: '#9ca3af' },
        top: 0,
      },
      grid: { left: '3%', right: '4%', bottom: '8%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: '{value}%',
          color: '#9ca3af',
        },
        splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
      },
      series: [
        {
          name: '策略3累计收益',
          type: 'line',
          data: d.equity_curve || [],
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2.5, color: '#f43f5e' },
          itemStyle: { color: '#f43f5e' },
        },
        {
          name: '基准指数收益',
          type: 'line',
          data: d.benchmark_curve || [],
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: '#3b82f6', type: 'dashed' },
          itemStyle: { color: '#3b82f6' },
        },
        {
          name: '超额 Alpha',
          type: 'line',
          data: d.alpha_curve || [],
          smooth: true,
          showSymbol: false,
          areaStyle: { opacity: 0.15, color: '#10b981' },
          lineStyle: { width: 1.5, color: '#10b981' },
          itemStyle: { color: '#10b981' },
        },
      ],
    }, true)
  } else if (activeChartTab.value === 'drawdown') {
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          const item = params[0]
          return `<div class="text-xs p-1 text-white">${item?.axisValue}<br/>动态回撤: <strong>${Number(item?.value).toFixed(2)}%</strong></div>`
        },
      },
      grid: { left: '3%', right: '4%', bottom: '8%', top: '12%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: '{value}%', color: '#9ca3af' },
        splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
      },
      series: [
        {
          name: '动态回撤',
          type: 'line',
          data: d.drawdown_curve || [],
          smooth: true,
          showSymbol: false,
          areaStyle: { opacity: 0.35, color: '#06b6d4' },
          lineStyle: { width: 1.5, color: '#06b6d4' },
        },
      ],
    }, true)
  } else if (activeChartTab.value === 'daily') {
    myChart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '8%', top: '12%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: '{value}%', color: '#9ca3af' },
        splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
      },
      series: [
        {
          name: '单日收益率',
          type: 'bar',
          data: (d.daily_returns || []).map((val: number) => ({
            value: val,
            itemStyle: { color: val >= 0 ? '#ef4444' : '#10b981' },
          })),
        },
      ],
    }, true)
  }
}

watch(activeChartTab, () => {
  updateChart()
})

const filteredTrades = computed(() => {
  if (!latestData.value?.trades) return []
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return latestData.value.trades
  return latestData.value.trades.filter(t =>
    t.code.toLowerCase().includes(q) ||
    t.name.toLowerCase().includes(q) ||
    t.exit_reason.toLowerCase().includes(q),
  )
})

const filteredTodaySignals = computed(() => {
  if (!latestData.value?.today_signals) return []
  const q = signalSearchQuery.value.trim().toLowerCase()
  if (!q) return latestData.value.today_signals
  return latestData.value.today_signals.filter(s =>
    s.code.toLowerCase().includes(q) ||
    s.name.toLowerCase().includes(q) ||
    s.logic.toLowerCase().includes(q),
  )
})

function copyAllSignalCodes() {
  const list = latestData.value?.today_signals || []
  if (!list.length) return
  const text = list.map(s => s.code).join(',')
  navigator.clipboard.writeText(text).then(() => {
    copiedNotice.value = true
    setTimeout(() => {
      copiedNotice.value = false
    }, 2000)
  })
}

function reasonTagClass(reason: string): string {
  if (reason.includes('峰值回撤')) return 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
  if (reason.includes('持股达上限') || reason.includes('到期')) return 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
  if (reason.includes('止损')) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
  if (reason.includes('止盈')) return 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
  return 'bg-[#222733] text-gray-300 border border-white/10'
}

function handleResize() {
  myChart?.resize()
}

onMounted(() => {
  void fetchStatus()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  window.removeEventListener('resize', handleResize)
  if (myChart) {
    myChart.dispose()
    myChart = null
  }
})
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部参数配置与快速触发卡片 -->
    <div class="rounded-xl border border-white/10 bg-[#161922] p-4.5 space-y-4 shadow-xl">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-3">
        <div>
          <h3 class="text-base font-bold flex items-center gap-2 text-white">
            <span class="text-amber-400">⚡</span>
            <span>策略三·鲍鱼捞饭（破位止跌）多维回测控制台</span>
            <span class="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/30 text-amber-300 font-medium">日线缠论破位 + 量价衰竭止跌</span>
          </h3>
          <p class="text-xs text-gray-400 mt-1 flex items-center gap-1.5">
            <span>支持手选</span>
            <strong class="text-amber-300">持股时间到期平仓条件</strong>
            <span>与</span>
            <strong class="text-cyan-300">峰值移动回撤/成本止损条件</strong>
            <span class="text-gray-500">|</span>
            <span class="text-emerald-400">支持单日提取最新买入候选信号</span>
          </p>
        </div>

        <!-- 快捷策略档位 -->
        <div class="flex items-center gap-1.5 text-xs">
          <span class="text-gray-400 mr-1">快捷预设:</span>
          <button
            type="button"
            class="px-2.5 py-1 rounded-md bg-[#222733] border border-white/10 text-gray-200 hover:bg-[#2b3140] hover:text-white transition cursor-pointer"
            @click="applyPreset('short')"
          >
            短线高敏(5日/回撤3%)
          </button>
          <button
            type="button"
            class="px-2.5 py-1 rounded-md bg-[#222733] border border-white/10 text-gray-200 hover:bg-[#2b3140] hover:text-white transition cursor-pointer"
            @click="applyPreset('standard')"
          >
            经典基准(10日/回撤4%)
          </button>
          <button
            type="button"
            class="px-2.5 py-1 rounded-md bg-[#222733] border border-white/10 text-gray-200 hover:bg-[#2b3140] hover:text-white transition cursor-pointer"
            @click="applyPreset('medium')"
          >
            波段中线(20日/回撤6%)
          </button>
        </div>
      </div>

      <!-- 参数表单网格 -->
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 text-xs">
        <!-- 股票池 -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <label class="font-medium text-gray-300 flex items-center gap-1">
              <span>🎯 股票池范围 (Universe)</span>
            </label>
          </div>
          <div class="relative">
            <select
              v-model="form.universe"
              class="w-full appearance-none rounded-lg border border-white/15 bg-[#12141a] px-3 py-2 text-xs font-medium text-white transition focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400/40 cursor-pointer [color-scheme:dark]"
            >
              <option value="zz1000" class="bg-[#181c24] text-white py-1">中证1000成分股 (主板 640+ 只)</option>
              <option value="legacy30" class="bg-[#181c24] text-white py-1">经典精选30池 (固定验证池)</option>
              <option value="manual" class="bg-[#181c24] text-white py-1">当前手动监控池</option>
            </select>
            <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2.5 text-gray-400">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
            </div>
          </div>
        </div>

        <!-- 对比基准 -->
        <div class="space-y-1.5">
          <div class="flex items-center justify-between">
            <label class="font-medium text-gray-300 flex items-center gap-1">
              <span>📊 对比基准指数 (Benchmark)</span>
            </label>
          </div>
          <div class="relative">
            <select
              v-model="form.benchmark"
              class="w-full appearance-none rounded-lg border border-white/15 bg-[#12141a] px-3 py-2 text-xs font-medium text-white transition focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400/40 cursor-pointer [color-scheme:dark]"
            >
              <option value="000852" class="bg-[#181c24] text-white py-1">000852 中证1000指数 (切合风格)</option>
              <option value="000985" class="bg-[#181c24] text-white py-1">000985 中证全指 (全市场真实盈亏)</option>
              <option value="000300" class="bg-[#181c24] text-white py-1">000300 沪深300指数 (权重蓝筹)</option>
            </select>
            <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2.5 text-gray-400">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
            </div>
          </div>
        </div>

        <!-- 回测区间起止与快捷时间胶囊 -->
        <div class="space-y-1.5 sm:col-span-2">
          <div class="flex flex-wrap items-center justify-between gap-1">
            <div class="flex items-center gap-2">
              <label class="font-medium text-gray-300 flex items-center gap-1">
                <span>📅 选择区间 (起止日期)</span>
              </label>
              <span v-if="isSingleDayMode" class="px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-[10px] text-emerald-300 font-bold animate-pulse">
                ⚡ 单日今日信号模式
              </span>
            </div>
            <!-- 快捷日期胶囊 -->
            <div class="flex flex-wrap items-center gap-1 text-[11px]">
              <button
                type="button"
                class="px-2 py-0.5 rounded font-bold transition cursor-pointer"
                :class="isSingleDayMode ? 'bg-emerald-500 text-white shadow-sm' : 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'"
                @click="applyQuickToday"
              >
                ⚡ 今日信号
              </button>
              <button type="button" class="px-1.5 py-0.5 rounded bg-[#222733] text-gray-300 hover:text-white hover:bg-[#2e3444] transition" @click="applyQuickDaysRange(7)">近7天</button>
              <button type="button" class="px-1.5 py-0.5 rounded bg-[#222733] text-gray-300 hover:text-white hover:bg-[#2e3444] transition" @click="applyQuickDateRange(1)">近1月</button>
              <button type="button" class="px-1.5 py-0.5 rounded bg-[#222733] text-gray-300 hover:text-white hover:bg-[#2e3444] transition" @click="applyQuickDateRange(3)">近3月</button>
              <button type="button" class="px-1.5 py-0.5 rounded bg-[#222733] text-gray-300 hover:text-white hover:bg-[#2e3444] transition" @click="applyQuickDateRange(12)">近1年</button>
              <button type="button" class="px-1.5 py-0.5 rounded bg-[#222733] text-gray-300 hover:text-white hover:bg-[#2e3444] transition" @click="() => { form.start_date = '2025-01-01'; form.end_date = todayDateStr }">2025至今</button>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2">
            <div class="relative">
              <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-400 font-mono">从</span>
              <input
                v-model="form.start_date"
                type="date"
                :max="todayDateStr"
                class="w-full rounded-lg border border-white/15 bg-[#12141a] pl-8 pr-2.5 py-2 text-xs font-medium text-white transition focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400/40 cursor-pointer [color-scheme:dark]"
              />
            </div>
            <div class="relative">
              <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-400 font-mono">至</span>
              <input
                v-model="form.end_date"
                type="date"
                :max="todayDateStr"
                class="w-full rounded-lg border border-white/15 bg-[#12141a] pl-8 pr-2.5 py-2 text-xs font-medium text-white transition focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400/40 cursor-pointer [color-scheme:dark]"
              />
            </div>
          </div>
          <p v-if="isSingleDayMode" class="text-[11px] text-emerald-400 flex items-center gap-1">
            <span>💡 提示：开始与结束均为同一天（{{ form.start_date }}），将直接输出当日命中破位止跌的候选标的买点与风控清单。</span>
          </p>
        </div>

        <!-- 核心条件 1：命中信号后持股时间 -->
        <div class="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3.5 space-y-2 sm:col-span-2 shadow-inner">
          <div class="flex items-center justify-between">
            <span class="font-bold text-amber-300 flex items-center gap-1.5 text-xs">
              <span>⏱ 核心条件 1：命中信号后持股时间</span>
            </span>
            <div class="flex gap-1.5">
              <button
                type="button"
                class="rounded-md px-2.5 py-0.5 text-xs font-medium transition cursor-pointer"
                :class="form.max_hold_days === 3 ? 'bg-amber-500 text-black font-bold shadow' : 'bg-[#1e2330] text-gray-300 hover:text-white'"
                @click="form.max_hold_days = 3"
              >
                3天
              </button>
              <button
                type="button"
                class="rounded-md px-2.5 py-0.5 text-xs font-medium transition cursor-pointer"
                :class="form.max_hold_days === 5 ? 'bg-amber-500 text-black font-bold shadow' : 'bg-[#1e2330] text-gray-300 hover:text-white'"
                @click="form.max_hold_days = 5"
              >
                5天
              </button>
              <button
                type="button"
                class="rounded-md px-2.5 py-0.5 text-xs font-medium transition cursor-pointer"
                :class="form.max_hold_days === 10 ? 'bg-amber-500 text-black font-bold shadow' : 'bg-[#1e2330] text-gray-300 hover:text-white'"
                @click="form.max_hold_days = 10"
              >
                10天
              </button>
              <button
                type="button"
                class="rounded-md px-2.5 py-0.5 text-xs font-medium transition cursor-pointer"
                :class="form.max_hold_days === 20 ? 'bg-amber-500 text-black font-bold shadow' : 'bg-[#1e2330] text-gray-300 hover:text-white'"
                @click="form.max_hold_days = 20"
              >
                20天
              </button>
            </div>
          </div>

          <div class="flex items-center gap-3">
            <span class="text-gray-300">最长持股交易日上限:</span>
            <div class="relative w-28">
              <input
                v-model.number="form.max_hold_days"
                type="number"
                min="1"
                max="60"
                class="w-full rounded-lg border border-amber-500/30 bg-[#12141a] px-3 py-1.5 text-right font-mono text-sm font-bold text-amber-300 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400/50 [color-scheme:dark]"
              />
              <span class="pointer-events-none absolute right-7 top-1/2 -translate-y-1/2 text-xs text-gray-400">天</span>
            </div>
            <span class="text-[11px] text-gray-400">(到期无论盈亏次日开盘强制平仓)</span>
          </div>

          <p class="text-[11px] text-gray-400 leading-relaxed">
            命中破位止跌信号次日开盘买入；若在持股期间未触发止盈或峰值回撤出场，持有满 <strong class="text-amber-300">{{ form.max_hold_days }}</strong> 天后，于次日开盘卖出。
          </p>
        </div>

        <!-- 核心条件 2：回撤出场条件 -->
        <div class="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-3.5 space-y-2 sm:col-span-2 shadow-inner">
          <div class="flex items-center justify-between">
            <span class="font-bold text-cyan-300 flex items-center gap-1.5 text-xs">
              <span>📉 核心条件 2：回撤出场条件 (峰值移动 / 成本止损)</span>
            </span>
            <!-- 自定义开关 -->
            <button
              type="button"
              class="flex items-center gap-1.5 px-2 py-0.5 rounded-full border transition cursor-pointer text-xs"
              :class="form.enable_trailing_drawdown ? 'bg-cyan-500/20 border-cyan-400 text-cyan-300' : 'bg-[#1e2330] border-white/10 text-gray-400'"
              @click="form.enable_trailing_drawdown = !form.enable_trailing_drawdown"
            >
              <span class="h-2 w-2 rounded-full" :class="form.enable_trailing_drawdown ? 'bg-cyan-400' : 'bg-gray-500'" />
              <span>{{ form.enable_trailing_drawdown ? '已开启峰值回撤' : '已关闭峰值回撤' }}</span>
            </button>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <!-- 峰值回撤 -->
            <div class="space-y-1">
              <div class="flex items-center justify-between">
                <span class="text-gray-300">持仓最高点回撤阈值:</span>
                <span class="text-xs font-mono font-bold text-cyan-300">{{ (form.trailing_drawdown_pct * 100).toFixed(1) }}%</span>
              </div>
              <div class="flex items-center gap-1.5">
                <input
                  v-model.number="form.trailing_drawdown_pct"
                  type="number"
                  step="0.005"
                  min="0.01"
                  max="0.20"
                  class="w-full rounded-lg border border-cyan-500/30 bg-[#12141a] px-3 py-1.5 text-right font-mono text-xs font-bold text-cyan-300 focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400/50 [color-scheme:dark]"
                />
              </div>
              <div class="flex gap-1 text-[10px]">
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.trailing_drawdown_pct = 0.03">3%</button>
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.trailing_drawdown_pct = 0.04">4%</button>
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.trailing_drawdown_pct = 0.05">5%</button>
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.trailing_drawdown_pct = 0.08">8%</button>
              </div>
            </div>

            <!-- 成本止损 -->
            <div class="space-y-1">
              <div class="flex items-center justify-between">
                <span class="text-gray-300">成本回撤止损阈值:</span>
                <span class="text-xs font-mono font-bold text-emerald-400">{{ (form.stop_loss_pct * 100).toFixed(1) }}%</span>
              </div>
              <div class="flex items-center gap-1.5">
                <input
                  v-model.number="form.stop_loss_pct"
                  type="number"
                  step="0.005"
                  min="-0.20"
                  max="-0.01"
                  class="w-full rounded-lg border border-emerald-500/30 bg-[#12141a] px-3 py-1.5 text-right font-mono text-xs font-bold text-emerald-400 focus:border-emerald-400 focus:outline-none focus:ring-1 focus:ring-emerald-400/50 [color-scheme:dark]"
                />
              </div>
              <div class="flex gap-1 text-[10px]">
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.stop_loss_pct = -0.03">-3%</button>
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.stop_loss_pct = -0.05">-5%</button>
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.stop_loss_pct = -0.07">-7%</button>
                <button type="button" class="rounded px-1.5 py-0.5 bg-[#1e2330] text-gray-300 hover:text-white" @click="form.stop_loss_pct = -0.10">-10%</button>
              </div>
            </div>
          </div>

          <p class="text-[11px] text-gray-400 leading-relaxed">
            浮盈≥2%后从最高点回跌 <strong class="text-cyan-300">{{ (form.trailing_drawdown_pct * 100).toFixed(1) }}%</strong> 移动出场锁定利润；成本亏损达 <strong class="text-emerald-400">{{ (Math.abs(form.stop_loss_pct) * 100).toFixed(1) }}%</strong> 触发硬止损。
          </p>
        </div>
      </div>

      <!-- 高级参数折叠 -->
      <div v-if="showAdvanced" class="rounded-xl border border-white/10 bg-[#111318] p-3.5 grid gap-3 sm:grid-cols-3 text-xs">
        <div class="space-y-1">
          <label class="text-gray-400">初始资金 (元)</label>
          <div class="relative">
            <span class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 font-mono">¥</span>
            <input
              v-model.number="form.initial_capital"
              type="number"
              step="100000"
              class="w-full rounded-lg border border-white/10 bg-[#181c24] pl-7 pr-3 py-1.5 text-xs font-mono font-medium text-white focus:border-amber-400 focus:outline-none [color-scheme:dark]"
            />
          </div>
        </div>
        <div class="space-y-1">
          <label class="text-gray-400">同时最多持仓只数</label>
          <div class="relative">
            <input
              v-model.number="form.max_positions"
              type="number"
              min="1"
              max="20"
              class="w-full rounded-lg border border-white/10 bg-[#181c24] px-3 py-1.5 text-xs font-mono font-medium text-white focus:border-amber-400 focus:outline-none [color-scheme:dark]"
            />
            <span class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-xs">只</span>
          </div>
        </div>
        <div class="space-y-1">
          <label class="text-gray-400">目标止盈比例</label>
          <div class="relative">
            <input
              v-model.number="form.take_profit_pct"
              type="number"
              step="0.01"
              class="w-full rounded-lg border border-white/10 bg-[#181c24] px-3 py-1.5 text-xs font-mono font-medium text-white focus:border-amber-400 focus:outline-none [color-scheme:dark]"
            />
            <span class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-xs font-mono">({{ (form.take_profit_pct * 100).toFixed(0) }}%)</span>
          </div>
        </div>
      </div>

      <!-- 操作与触发栏 -->
      <div class="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-white/10">
        <button
          type="button"
          class="text-xs text-gray-400 hover:text-white transition flex items-center gap-1 cursor-pointer"
          @click="showAdvanced = !showAdvanced"
        >
          <span>{{ showAdvanced ? '▲ 收起高级设置' : '▼ 展开资金与止盈高级设置' }}</span>
        </button>

        <div class="flex items-center gap-3">
          <span v-if="latestData?.updated_at" class="text-xs text-gray-400 font-mono">
            上次执行: {{ latestData.updated_at }}
          </span>

          <button
            type="button"
            class="rounded-xl px-6 py-2.5 text-sm font-bold text-white shadow-lg transition disabled:opacity-50 flex items-center gap-2 cursor-pointer"
            :class="isSingleDayMode ? 'bg-gradient-to-r from-emerald-600 to-teal-500 hover:from-emerald-500 hover:to-teal-400 shadow-emerald-500/20' : 'bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 shadow-amber-500/20'"
            :disabled="running || loading"
            @click="startBacktest"
          >
            <span v-if="running || loading" class="inline-block animate-spin">⌛</span>
            <span v-else>⚡</span>
            <span>
              {{
                running
                  ? (isSingleDayMode ? '正在扫描并提取当日破位止跌信号…' : '策略3回测仿真执行中…')
                  : (isSingleDayMode ? `⚡ 提取今日买入信号 (${form.start_date})` : '立即运行策略3区间回测')
              }}
            </span>
          </button>
        </div>
      </div>

      <!-- 执行进度条与错误提示 -->
      <div v-if="running && progress" class="rounded-xl bg-amber-500/10 border border-amber-500/20 p-3 text-xs space-y-1.5">
        <div class="flex justify-between items-center text-amber-300">
          <span class="font-bold flex items-center gap-2">
            <span class="inline-block animate-pulse">●</span>
            <span>{{ progress.stage }}</span>
          </span>
          <span class="font-mono font-bold">{{ progress.percent }}%</span>
        </div>
        <div class="h-1.5 w-full bg-[#181c24] rounded-full overflow-hidden">
          <div class="h-full bg-gradient-to-r from-amber-500 to-yellow-400 transition-all duration-300" :style="{ width: `${progress.percent}%` }" />
        </div>
      </div>

      <div v-if="errorMessage" class="rounded-xl bg-rose-500/10 border border-rose-500/30 p-3 text-xs text-rose-300">
        {{ errorMessage }}
      </div>
    </div>

    <!-- 模式 A：单日模式结果视图 (提取今日破位止跌买入信号) -->
    <template v-if="latestData?.is_single_day">
      <div class="rounded-xl border border-emerald-500/30 bg-[#141d1a] p-4.5 space-y-4 shadow-xl">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-emerald-500/20 pb-3">
          <div>
            <h3 class="text-base font-bold flex items-center gap-2 text-white">
              <span class="text-emerald-400">⚡</span>
              <span>当日破位止跌推荐候选信号 ({{ latestData.target_day }})</span>
              <span class="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono font-bold">
                共命中 {{ latestData.summary?.today_signal_count ?? latestData.today_signals?.length ?? 0 }} 只
              </span>
            </h3>
            <p class="text-xs text-gray-300 mt-1">
              日线经过深度回踩，在支撑位呈现量价衰竭止跌形态。回测仿真与实盘均以<strong>扫描出信号的当天收盘价买入建仓</strong>，次日开始按持有天数与回撤止损规则跟踪出场。
            </p>
          </div>

          <div class="flex items-center gap-2">
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/50 hover:text-white text-xs font-medium transition cursor-pointer flex items-center gap-1.5"
              @click="copyAllSignalCodes"
            >
              <span>📋</span>
              <span>{{ copiedNotice ? '已复制全部代码！' : '一键复制全部代码' }}</span>
            </button>
            <input
              v-model="signalSearchQuery"
              type="text"
              placeholder="搜索代码 / 名称 / 策略说明…"
              class="rounded-lg border border-white/15 bg-[#12141a] px-3 py-1.5 text-xs text-white placeholder-gray-500 focus:border-emerald-400 focus:outline-none w-52"
            />
          </div>
        </div>

        <!-- 今日信号表格 -->
        <div class="overflow-x-auto rounded-lg border border-white/10 bg-[#101318]">
          <table class="min-w-full text-xs">
            <thead class="bg-[#181c24] text-gray-300 border-b border-white/10">
              <tr>
                <th class="p-3 text-left">标的名称/代码</th>
                <th class="p-3 text-right">当日收盘价</th>
                <th class="p-3 text-right">破位下跌深度</th>
                <th class="p-3 text-right">推荐买入价 (当日收盘)</th>
                <th class="p-3 text-right">回踩支撑位</th>
                <th class="p-3 text-right">防守止损位</th>
                <th class="p-3 text-right">前期波段目标</th>
                <th class="p-3 text-left">战术策略与执行要点</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              <tr
                v-for="s in filteredTodaySignals"
                :key="s.symbol"
                class="hover:bg-emerald-500/5 transition"
              >
                <td class="p-3 whitespace-nowrap">
                  <div class="font-bold text-white text-sm">{{ s.name }}</div>
                  <div class="font-mono text-gray-400 text-[11px]">{{ s.code }}</div>
                </td>
                <td class="p-3 text-right whitespace-nowrap">
                  <span class="font-mono font-bold text-white text-sm">¥{{ s.close.toFixed(2) }}</span>
                </td>
                <td class="p-3 text-right whitespace-nowrap">
                  <span class="inline-block px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-mono font-bold text-xs">
                    -{{ s.depth_pct }}%
                  </span>
                </td>
                <td class="p-3 text-right whitespace-nowrap">
                  <div class="font-mono font-bold text-amber-300">¥{{ (s.buy_price || s.close).toFixed(2) }}</div>
                  <div class="text-[10px] text-amber-400/80">信号日收盘买入</div>
                </td>
                <td class="p-3 text-right whitespace-nowrap">
                  <div class="font-mono font-bold text-cyan-300">¥{{ s.support_buy_price }}</div>
                  <div class="text-[10px] text-gray-400">回踩防守底线</div>
                </td>
                <td class="p-3 text-right whitespace-nowrap">
                  <div class="font-mono font-bold text-emerald-400">¥{{ s.stop_loss_price }}</div>
                  <div class="text-[10px] text-gray-400">底线硬止损</div>
                </td>
                <td class="p-3 text-right whitespace-nowrap">
                  <div class="font-mono font-bold text-purple-300">¥{{ s.target_price }}</div>
                  <div class="text-[10px] text-gray-400">前高反弹目标</div>
                </td>
                <td class="p-3 text-gray-300 text-[11px] max-w-md">
                  {{ s.logic }}
                </td>
              </tr>
              <tr v-if="filteredTodaySignals.length === 0">
                <td colspan="8" class="p-8 text-center text-gray-400 text-xs">
                  暂无匹配的信号记录（若选择今天且尚未收盘或未加载全量特征，可选择前一交易日查看）
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- 模式 B：多日区间回测结果视图 -->
    <template v-else-if="latestData?.summary">
      <!-- 核心 KPI 指标卡片 -->
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="rounded-xl border border-white/10 bg-[#161922] p-4 shadow">
          <div class="text-xs text-gray-400">策略3累计收益率</div>
          <div class="mt-1 text-2xl font-black font-mono" :class="returnClass(latestData.summary.strategy_return_pct)">
            {{ latestData.summary.strategy_return_pct != null ? `${latestData.summary.strategy_return_pct > 0 ? '+' : ''}${latestData.summary.strategy_return_pct.toFixed(2)}%` : '—' }}
          </div>
          <div class="mt-1 flex items-center justify-between text-xs text-gray-400">
            <span>基准 ({{ form.benchmark }}):</span>
            <span class="font-mono font-semibold" :class="returnClass(latestData.summary.benchmark_return_pct)">
              {{ latestData.summary.benchmark_return_pct != null ? `${latestData.summary.benchmark_return_pct > 0 ? '+' : ''}${latestData.summary.benchmark_return_pct.toFixed(2)}%` : '—' }}
            </span>
          </div>
        </div>

        <div class="rounded-xl border border-white/10 bg-[#161922] p-4 shadow">
          <div class="text-xs text-gray-400">超额 Alpha / 年化收益</div>
          <div class="mt-1 text-2xl font-black font-mono" :class="returnClass(latestData.summary.alpha_pct)">
            {{ latestData.summary.alpha_pct != null ? `${latestData.summary.alpha_pct > 0 ? '+' : ''}${latestData.summary.alpha_pct.toFixed(2)}%` : '—' }}
          </div>
          <div class="mt-1 flex items-center justify-between text-xs text-gray-400">
            <span>年化收益率:</span>
            <span class="font-mono font-semibold text-white">{{ latestData.summary.annualized_return_pct?.toFixed(2) }}%</span>
          </div>
        </div>

        <div class="rounded-xl border border-white/10 bg-[#161922] p-4 shadow">
          <div class="text-xs text-gray-400">最大动态回撤 / 卡玛比率</div>
          <div class="mt-1 text-2xl font-black font-mono text-cyan-400">
            {{ latestData.summary.max_drawdown_pct != null ? `${latestData.summary.max_drawdown_pct.toFixed(2)}%` : '—' }}
          </div>
          <div class="mt-1 flex items-center justify-between text-xs text-gray-400">
            <span>夏普比率 (Sharpe):</span>
            <span class="font-mono font-semibold text-white">{{ latestData.summary.sharpe_ratio?.toFixed(2) }}</span>
          </div>
        </div>

        <div class="rounded-xl border border-white/10 bg-[#161922] p-4 shadow">
          <div class="text-xs text-gray-400">胜率 / 平均持股天数</div>
          <div class="mt-1 text-2xl font-black font-mono text-white">
            {{ latestData.summary.win_rate_pct?.toFixed(1) }}%
            <span class="text-xs font-normal text-gray-400">({{ latestData.summary.win_trades }}赢 / {{ latestData.summary.loss_trades }}输)</span>
          </div>
          <div class="mt-1 flex items-center justify-between text-xs text-gray-400">
            <span>平均持股: <strong class="text-amber-300 font-mono">{{ latestData.summary.avg_holding_days }}天</strong></span>
            <span>盈亏比: <strong class="text-white font-mono">{{ latestData.summary.profit_factor }}</strong></span>
          </div>
        </div>
      </div>

      <!-- 出场原因分布卡片 (持股天数与回撤退出效果) -->
      <div v-if="latestData?.exit_reason_breakdown?.length" class="rounded-xl border border-white/10 bg-[#161922] p-4 space-y-3 shadow">
        <div class="flex items-center justify-between border-b border-white/10 pb-2">
          <div class="text-sm font-bold flex items-center gap-2 text-white">
            <span>出场条件触发分布与盈亏归因</span>
            <span class="text-xs text-gray-400 font-normal">（检验持股到期与峰值回撤的实际出场效率）</span>
          </div>
          <span class="text-xs text-gray-400 font-mono">总撮合成交: {{ latestData.summary.total_trades }} 笔</span>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div
            v-for="item in latestData.exit_reason_breakdown"
            :key="item.reason"
            class="rounded-lg border border-white/10 bg-[#12141a] p-3 space-y-1.5"
          >
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold" :class="reasonTagClass(item.reason)">{{ item.reason }}</span>
              <span class="text-xs font-bold font-mono text-white">{{ item.count }} 笔 ({{ item.pct_of_total }}%)</span>
            </div>
            <div class="flex justify-between text-xs text-gray-400">
              <span>胜率:</span>
              <span class="font-mono font-semibold text-white">{{ item.win_rate }}%</span>
            </div>
            <div class="flex justify-between text-xs text-gray-400">
              <span>平均每笔收益:</span>
              <span class="font-mono font-bold" :class="returnClass(item.avg_pnl_pct)">
                {{ item.avg_pnl_pct > 0 ? '+' : '' }}{{ item.avg_pnl_pct }}%
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 图表展示区域 -->
      <div class="rounded-xl border border-white/10 bg-[#161922] p-4 space-y-3 shadow">
        <div class="flex items-center justify-between border-b border-white/10 pb-2">
          <div class="flex items-center gap-2 text-xs">
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg font-bold transition cursor-pointer"
              :class="activeChartTab === 'equity' ? 'bg-rose-600 text-white shadow' : 'text-gray-400 hover:text-white'"
              @click="activeChartTab = 'equity'"
            >
              累计净值走势
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg font-bold transition cursor-pointer"
              :class="activeChartTab === 'drawdown' ? 'bg-cyan-600 text-white shadow' : 'text-gray-400 hover:text-white'"
              @click="activeChartTab = 'drawdown'"
            >
              水下动态回撤
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg font-bold transition cursor-pointer"
              :class="activeChartTab === 'daily' ? 'bg-[#222733] text-white shadow' : 'text-gray-400 hover:text-white'"
              @click="activeChartTab = 'daily'"
            >
              单日收益分布
            </button>
          </div>

          <span class="text-xs text-gray-400 font-mono">
            股票池有效标的: {{ latestData?.summary?.universe_count ?? 0 }} 只
          </span>
        </div>

        <div ref="chartEl" class="h-80 w-full" />
      </div>

      <!-- 逐笔明细与个股贡献表格 -->
      <div class="rounded-xl border border-white/10 bg-[#161922] p-4 space-y-3 shadow">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-2">
          <div class="flex items-center gap-2 text-xs">
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg font-bold transition cursor-pointer"
              :class="activeTableTab === 'trades' ? 'bg-amber-600 text-white shadow' : 'text-gray-400 hover:text-white'"
              @click="activeTableTab = 'trades'"
            >
              逐笔交易明细 ({{ filteredTrades.length }})
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg font-bold transition cursor-pointer"
              :class="activeTableTab === 'stocks' ? 'bg-amber-600 text-white shadow' : 'text-gray-400 hover:text-white'"
              @click="activeTableTab = 'stocks'"
            >
              个股盈亏贡献 Top
            </button>
          </div>

          <div v-if="activeTableTab === 'trades'" class="flex items-center gap-2">
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索代码 / 名称 / 出场原因…"
              class="rounded-lg border border-white/15 bg-[#12141a] px-3 py-1 text-xs text-white placeholder-gray-500 focus:border-amber-400 focus:outline-none w-52"
            />
          </div>
        </div>

        <!-- 逐笔交易列表 -->
        <div v-if="activeTableTab === 'trades'" class="overflow-x-auto max-h-96 rounded-lg border border-white/10 bg-[#101318]">
          <table class="min-w-full text-xs">
            <thead class="sticky top-0 bg-[#181c24] text-gray-400 border-b border-white/10">
              <tr>
                <th class="p-2.5 text-left">标的</th>
                <th class="p-2.5 text-left">买入日期/均价</th>
                <th class="p-2.5 text-left">卖出日期/均价</th>
                <th class="p-2.5 text-right">持股天数</th>
                <th class="p-2.5 text-right">期间最高浮盈</th>
                <th class="p-2.5 text-right">最终盈亏率</th>
                <th class="p-2.5 text-right">盈亏金额</th>
                <th class="p-2.5 text-left">平仓原因</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              <tr v-for="(t, idx) in filteredTrades.slice(0, 100)" :key="idx" class="hover:bg-white/5 transition">
                <td class="p-2.5 whitespace-nowrap">
                  <div class="font-bold text-white">{{ t.name }}</div>
                  <div class="text-[11px] font-mono text-gray-400">{{ t.code }}</div>
                </td>
                <td class="p-2.5 whitespace-nowrap">
                  <div class="font-mono text-gray-200">{{ t.entry_date }}</div>
                  <div class="text-gray-400 font-mono">¥{{ t.entry_price }}</div>
                </td>
                <td class="p-2.5 whitespace-nowrap">
                  <div class="font-mono text-gray-200">{{ t.exit_date }}</div>
                  <div class="text-gray-400 font-mono">¥{{ t.exit_price }}</div>
                </td>
                <td class="p-2.5 text-right font-medium font-mono text-gray-200 whitespace-nowrap">{{ t.holding_days }} 天</td>
                <td class="p-2.5 text-right font-medium font-mono text-rose-400 whitespace-nowrap">+{{ t.max_pnl_pct }}%</td>
                <td class="p-2.5 text-right font-bold font-mono whitespace-nowrap" :class="returnClass(t.pnl_pct)">
                  {{ t.pnl_pct > 0 ? '+' : '' }}{{ t.pnl_pct }}%
                </td>
                <td class="p-2.5 text-right font-mono whitespace-nowrap" :class="returnClass(t.pnl_amount)">
                  {{ t.pnl_amount > 0 ? '+' : '' }}¥{{ t.pnl_amount.toLocaleString() }}
                </td>
                <td class="p-2.5 whitespace-nowrap">
                  <span class="rounded px-2 py-0.5 text-[10px]" :class="reasonTagClass(t.exit_reason)">
                    {{ t.exit_reason }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="filteredTrades.length > 100" class="p-2 text-center text-xs text-gray-400">
            仅显示前 100 条记录（共 {{ filteredTrades.length }} 条）
          </div>
        </div>

        <!-- 个股贡献排行 -->
        <div v-else-if="activeTableTab === 'stocks'" class="overflow-x-auto max-h-96 rounded-lg border border-white/10 bg-[#101318]">
          <table class="min-w-full text-xs">
            <thead class="sticky top-0 bg-[#181c24] text-gray-400 border-b border-white/10">
              <tr>
                <th class="p-2.5 text-left">标的</th>
                <th class="p-2.5 text-right">交易次数</th>
                <th class="p-2.5 text-right">胜率</th>
                <th class="p-2.5 text-right">累计盈亏金额</th>
                <th class="p-2.5 text-right">平均盈亏率</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              <tr v-for="s in latestData?.stock_contributions || []" :key="s.code" class="hover:bg-white/5 transition">
                <td class="p-2.5 whitespace-nowrap">
                  <span class="font-bold text-white">{{ s.name }}</span>
                  <span class="ml-1 font-mono text-gray-400">({{ s.code }})</span>
                </td>
                <td class="p-2.5 text-right font-mono text-gray-200">{{ s.trades_count }} 次</td>
                <td class="p-2.5 text-right font-mono font-medium text-white">{{ s.win_rate }}%</td>
                <td class="p-2.5 text-right font-mono font-bold" :class="returnClass(s.total_pnl_amount)">
                  {{ s.total_pnl_amount > 0 ? '+' : '' }}¥{{ s.total_pnl_amount.toLocaleString() }}
                </td>
                <td class="p-2.5 text-right font-mono font-bold" :class="returnClass(s.avg_pnl)">
                  {{ s.avg_pnl > 0 ? '+' : '' }}{{ s.avg_pnl }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>