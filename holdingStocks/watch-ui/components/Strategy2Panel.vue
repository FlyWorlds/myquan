<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { baiduStockUrl, baiduIndexUrl } from '~/utils/stockLink'

const props = defineProps<{
  tab?: any
  payload?: any
}>()

// 选股池范围
const scope = ref<'sectors' | 'zz500' | 'zz1000' | 'hs300' | 'sector_members'>('sectors')
const targetConcept = ref<string>('半导体')

// 结果区子 Tab：'sectors' | 'stocks'
const resultTab = ref<'sectors' | 'stocks'>('sectors')

// 形态过滤：all | buy2 | buy1
const patternFilter = ref<'all' | 'buy2' | 'buy1'>('all')

// 扫描状态
const isScanning = ref(false)
const scanProgress = ref<{ percent: number; stage: string; completed: number; total: number }>({
  percent: 0,
  stage: '',
  completed: 0,
  total: 0,
})
let pollTimer: any = null

// 本地数据缓存
const localPayload = ref<any>(props.payload || null)

watch(() => props.payload, (val) => {
  if (val && Object.keys(val).length > 0) {
    localPayload.value = val
    // 若当前快照主要是股票，且板块为空，自动智能切换到个股 Tab
    if ((val.stocks_buy2?.length || val.stocks_buy1?.length) && !(val.sectors_buy2?.length || val.sectors_buy1?.length)) {
      resultTab.value = 'stocks'
    }
  }
}, { immediate: true, deep: true })

// 列表数据源
const allBuy2 = computed(() => localPayload.value?.all_buy2 || [])
const allBuy1 = computed(() => localPayload.value?.all_buy1 || [])

// 板块列表数据（受形态过滤控制）
const sectorList = computed(() => {
  const s2 = (localPayload.value?.sectors_buy2 && localPayload.value.sectors_buy2.length > 0)
    ? localPayload.value.sectors_buy2
    : allBuy2.value.filter((it: any) => it.is_sector)
  const s1 = (localPayload.value?.sectors_buy1 && localPayload.value.sectors_buy1.length > 0)
    ? localPayload.value.sectors_buy1
    : allBuy1.value.filter((it: any) => it.is_sector)
  if (patternFilter.value === 'all') return [...s2, ...s1]
  if (patternFilter.value === 'buy2') return [...s2]
  return [...s1]
})

// 股票列表数据（受形态过滤控制）
const stockList = computed(() => {
  const st2 = (localPayload.value?.stocks_buy2 && localPayload.value.stocks_buy2.length > 0)
    ? localPayload.value.stocks_buy2
    : allBuy2.value.filter((it: any) => !it.is_sector)
  const st1 = (localPayload.value?.stocks_buy1 && localPayload.value.stocks_buy1.length > 0)
    ? localPayload.value.stocks_buy1
    : allBuy1.value.filter((it: any) => !it.is_sector)
  if (patternFilter.value === 'all') return [...st2, ...st1]
  if (patternFilter.value === 'buy2') return [...st2]
  return [...st1]
})

// 当前激活 Tab 下的标的列表
const currentTabItems = computed(() => {
  return resultTab.value === 'sectors' ? sectorList.value : stockList.value
})

const displayItems = computed(() => currentTabItems.value)

// 统计
const totalScanned = computed(() => localPayload.value?.summary?.total_scanned || 0)
const buy2Count = computed(() => allBuy2.value.length)
const buy1Count = computed(() => allBuy1.value.length)
const avgDivRatio = computed(() => {
  const list = allBuy2.value
  if (!list.length) return '—'
  const sum = list.reduce((acc: number, cur: any) => acc + (cur.divergence_ratio || 0), 0)
  return (sum / list.length).toFixed(2)
})

// 触发扫描
async function startScan(targetScope = scope.value, concept = targetConcept.value) {
  if (isScanning.value) return
  isScanning.value = true
  scanProgress.value = { percent: 5, stage: '正在启动扫描引擎...', completed: 0, total: 0 }

  try {
    await fetch('/api/strategy2/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scope: targetScope,
        target_concept: concept,
      }),
    })

    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(pollScanStatus, 1000)
  } catch (e: any) {
    isScanning.value = false
    scanProgress.value = { percent: 0, stage: `启动失败: ${e.message}`, completed: 0, total: 0 }
  }
}

async function pollScanStatus() {
  try {
    const res = await fetch('/api/strategy2/scan')
    const data = await res.json()
    if (data.progress) {
      scanProgress.value = data.progress
    }
    if (!data.running && data.progress?.percent >= 100) {
      if (pollTimer) clearInterval(pollTimer)
      isScanning.value = false
      // 重新拉取快照
      await fetchPayload()
    }
  } catch {
    // 忽略瞬时轮询失败
  }
}

async function fetchPayload() {
  try {
    const res = await fetch('/api/strategy2/payload')
    const data = await res.json()
    if (data && !data.error) {
      localPayload.value = data
      if ((data.stocks_buy2?.length || data.stocks_buy1?.length) && !(data.sectors_buy2?.length || data.sectors_buy1?.length)) {
        resultTab.value = 'stocks'
      }
    }
  } catch {
    // 保持之前快照
  }
}

function handleSelectScope(newScope: typeof scope.value) {
  scope.value = newScope
  if (newScope === 'sectors') {
    resultTab.value = 'sectors'
  } else {
    resultTab.value = 'stocks'
  }
  startScan(newScope)
}

function drillIntoConcept(conceptName: string) {
  scope.value = 'sector_members'
  targetConcept.value = conceptName
  resultTab.value = 'stocks'
  startScan('sector_members', conceptName)
}

// ================= K线 & 缠论划线弹窗 =================
const showChartModal = ref(false)
const chartLoading = ref(false)
const chartCode = ref('')
const chartName = ref('')
const chartIsSector = ref(false)
const chartDom = ref<HTMLElement | null>(null)
const currentChartData = ref<any>(null)
let myChart: echarts.ECharts | null = null

async function openChart(item: any) {
  chartCode.value = item.code
  chartName.value = item.name
  chartIsSector.value = !!item.is_sector
  showChartModal.value = true
  chartLoading.value = true
  currentChartData.value = null

  await nextTick()
  initChart()

  try {
    const res = await fetch(`/api/strategy2/chart?code=${item.code}&name=${encodeURIComponent(item.name)}&is_sector=${chartIsSector.value}`)
    const data = await res.json()
    currentChartData.value = data
    renderChart(data)
  } catch (e) {
    console.error('获取K线数据失败', e)
  } finally {
    chartLoading.value = false
  }
}

function closeChart() {
  showChartModal.value = false
  if (myChart) {
    myChart.dispose()
    myChart = null
  }
}

function initChart() {
  if (!chartDom.value) return
  if (myChart) myChart.dispose()
  myChart = echarts.init(chartDom.value)
}

function renderChart(data: any) {
  if (!myChart || !data || data.error) return

  const dates = data.dates || []
  const kline = data.kline || [] // [open, close, low, high, vol]
  const ohlc = kline.map((k: any) => [k[0], k[1], k[2], k[3]])
  const volumes = kline.map((k: any, i: number) => [i, k[4], k[1] >= k[0] ? 1 : -1])

  const dif = data.macd?.dif || []
  const dea = data.macd?.dea || []
  const bar = data.macd?.bar || []

  // 构造笔折线 markLine 或 lines
  const biLines = data.bi_lines || []
  const biMarkLines: any[] = []
  biLines.forEach((bi: any) => {
    biMarkLines.push([
      {
        coord: [bi.start_date, bi.start_val],
        lineStyle: {
          color: bi.direction === 'up' ? '#ef4444' : '#06b6d4',
          width: 2.5,
          type: 'solid',
        },
        label: {
          show: true,
          formatter: `${bi.start_val}`,
          color: bi.direction === 'up' ? '#ef4444' : '#06b6d4',
          fontSize: 10,
        },
      },
      { coord: [bi.end_date, bi.end_val] },
    ])
  })

  // 构造中枢矩形 markArea
  const zsBoxes = data.zs_boxes || []
  const zsMarkAreas: any[] = []
  zsBoxes.forEach((zs: any) => {
    zsMarkAreas.push([
      {
        name: `中枢 [${zs.zd} - ${zs.zg}]`,
        coord: [zs.start_date, zs.zg],
        itemStyle: {
          color: 'rgba(234, 179, 8, 0.12)',
          borderColor: 'rgba(234, 179, 8, 0.7)',
          borderWidth: 1.5,
          borderType: 'dashed',
        },
        label: {
          show: true,
          position: 'insideTopLeft',
          color: '#eab308',
          fontSize: 11,
          formatter: `中枢\nZG:${zs.zg}\nZD:${zs.zd}`,
        },
      },
      { coord: [zs.end_date, zs.zd] },
    ])
  })

  // 构造 1买 与 类2买 关键点 markPoint
  const markPoints: any[] = []
  if (data.pattern_info) {
    const pi = data.pattern_info
    if (pi.buy1_date && pi.buy1_price) {
      markPoints.push({
        name: '1买底背驰',
        coord: [pi.buy1_date, pi.buy1_price],
        value: '🌱 1买',
        symbol: 'pin',
        symbolSize: 42,
        itemStyle: { color: '#06b6d4' },
        label: { show: true, color: '#fff', fontSize: 10, fontWeight: 'bold', offset: [0, -3] },
      })
    }
    if (pi.pullback_date && pi.pullback_low && pi.pattern === 'buy2_prime') {
      markPoints.push({
        name: '类2买点',
        coord: [pi.pullback_date, pi.pullback_low],
        value: '🔥 类2买',
        symbol: 'pin',
        symbolSize: 42,
        itemStyle: { color: '#a855f7' },
        label: { show: true, color: '#fff', fontSize: 10, fontWeight: 'bold', offset: [0, -3] },
      })
    }
  }

  const option: echarts.EChartsOption = {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      borderWidth: 1,
      borderColor: '#374151',
      backgroundColor: 'rgba(17, 24, 39, 0.95)',
      textStyle: { color: '#f3f4f6', fontSize: 12 },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: '4%', right: '3%', top: '7%', height: '55%' },
      { left: '4%', right: '3%', top: '65%', height: '14%' },
      { left: '4%', right: '3%', top: '81%', height: '15%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        scale: true,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#4b5563' } },
        splitLine: { show: false },
        min: 'dataMin',
        max: 'dataMax',
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#4b5563' } },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 2,
        data: dates,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#4b5563' } },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitArea: { show: false },
        axisLine: { lineStyle: { color: '#4b5563' } },
        splitLine: { lineStyle: { color: '#374151', type: 'dashed' } },
      },
      {
        gridIndex: 1,
        scale: true,
        splitNumber: 2,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#4b5563' } },
        splitLine: { show: false },
      },
      {
        gridIndex: 2,
        scale: true,
        splitNumber: 2,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#4b5563' } },
        splitLine: { lineStyle: { color: '#374151', type: 'dashed' } },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], start: 30, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1, 2], top: '96%', height: 16, start: 30, end: 100 },
    ],
    series: [
      {
        name: '日K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ef4444',
          color0: '#10b981',
          borderColor: '#ef4444',
          borderColor0: '#10b981',
        },
        markLine: {
          symbol: ['none', 'none'],
          data: biMarkLines,
          animation: false,
        },
        markArea: {
          data: zsMarkAreas,
          animation: false,
        },
        markPoint: {
          data: markPoints,
          animation: false,
        },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes.map((v: any) => v[1]),
        itemStyle: {
          color: (param: any) => {
            return volumes[param.dataIndex][2] > 0 ? '#ef4444' : '#10b981'
          },
        },
      },
      {
        name: 'MACD DIF',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: dif,
        lineStyle: { color: '#f59e0b', width: 1.5 },
        showSymbol: false,
      },
      {
        name: 'MACD DEA',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: dea,
        lineStyle: { color: '#38bdf8', width: 1.5 },
        showSymbol: false,
      },
      {
        name: 'MACD BAR',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: bar,
        itemStyle: {
          color: (param: any) => (param.value >= 0 ? '#ef4444' : '#10b981'),
        },
      },
    ],
  }

  myChart.setOption(option)
}

// ================= 缠论回测控制台 =================
const showBacktestDrawer = ref(false)
const btLoading = ref(false)
const btUniverse = ref<'sectors' | 'sector_members' | 'zz1000' | 'zz500' | 'hs300'>('sectors')
const btConceptName = ref('半导体')
const btTakeProfit = ref(0.15)
const btStopLoss = ref(0.05)
const btMaxHoldDays = ref(25)
const btResult = ref<any>(null)

// 回测时间范围与持股周期
const btTimeRangePreset = ref<'3m' | '6m' | '1y' | '2y' | 'custom'>('1y')
const nowTs = new Date()
const todayStr = nowTs.toISOString().slice(0, 10)
const oneYearAgoStr = new Date(nowTs.getTime() - 365 * 86400000).toISOString().slice(0, 10)
const btStartDate = ref(oneYearAgoStr)
const btEndDate = ref(todayStr)

function handleTimePresetChange(preset: typeof btTimeRangePreset.value) {
  btTimeRangePreset.value = preset
  const now = new Date()
  btEndDate.value = now.toISOString().slice(0, 10)
  if (preset === '3m') {
    btStartDate.value = new Date(now.getTime() - 90 * 86400000).toISOString().slice(0, 10)
  } else if (preset === '6m') {
    btStartDate.value = new Date(now.getTime() - 180 * 86400000).toISOString().slice(0, 10)
  } else if (preset === '1y') {
    btStartDate.value = new Date(now.getTime() - 365 * 86400000).toISOString().slice(0, 10)
  } else if (preset === '2y') {
    btStartDate.value = new Date(now.getTime() - 730 * 86400000).toISOString().slice(0, 10)
  }
}

async function runBacktest() {
  if (btLoading.value) return
  btLoading.value = true
  btResult.value = null

  try {
    const res = await fetch('/api/strategy2/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        universe: btUniverse.value,
        concept_name: btConceptName.value,
        start_date: btStartDate.value,
        end_date: btEndDate.value,
        take_profit_pct: btTakeProfit.value,
        stop_loss_pct: btStopLoss.value,
        max_hold_days: btMaxHoldDays.value,
      }),
    })
    const data = await res.json()
    btResult.value = data
  } catch (e: any) {
    console.error('回测失败', e)
  } finally {
    btLoading.value = false
  }
}

onMounted(() => {
  // 初始拉取一次最新缓存
  fetchPayload()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (myChart) myChart.dispose()
})
</script>

<template>
  <div class="space-y-4">
    <!-- 头部策略卡片与控制栏 -->
    <div class="rounded-xl border border-ui-hairline bg-ui-surface p-4 sm:p-5 shadow-sm">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center rounded-md bg-purple-500/10 px-2.5 py-1 text-xs font-semibold text-purple-400 border border-purple-500/20">
              策略二 · 缠论形态
            </span>
            <span class="text-xs text-ui-text-3">CZSC 1买底背驰 / 类2买主升拐点扫描</span>
          </div>
          <p class="mt-2 text-xs sm:text-sm text-ui-text-2 leading-relaxed">
            核心形态：下跌笔出中枢创出新低，MACD绿柱面积明显缩小形成动能底背驰（1买）；随后走出放量反弹浪，回踩不破1买低点（低点抬高），底分型拐点确立类2买主升。
          </p>
        </div>

        <!-- 顶部操作按钮 -->
        <div class="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-ui-hairline bg-ui-card px-3 py-2 text-xs font-medium text-ui-text-2 hover:bg-ui-surface-hover hover:text-ui-text transition-colors"
            @click="showBacktestDrawer = !showBacktestDrawer"
          >
            <svg class="h-4 w-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            {{ showBacktestDrawer ? '收起回测' : '缠论历史回测' }}
          </button>

          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg bg-purple-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50 transition-colors disabled:opacity-50"
            :disabled="isScanning"
            @click="startScan()"
          >
            <svg v-if="isScanning" class="h-4 w-4 animate-spin text-white" viewBox="0 0 24 24" fill="none">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
            </svg>
            <svg v-else class="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {{ isScanning ? '扫描中...' : '一键形态全景扫描' }}
          </button>
        </div>
      </div>

      <!-- 扫描进度条 -->
      <div v-if="isScanning || scanProgress.stage" class="mt-4 pt-3 border-t border-ui-hairline">
        <div class="flex items-center justify-between text-xs mb-1.5">
          <span class="text-ui-text-2 font-medium">{{ scanProgress.stage || '准备就绪' }}</span>
          <span class="text-purple-400 font-semibold tabular-nums">{{ scanProgress.percent }}%</span>
        </div>
        <div class="h-1.5 w-full overflow-hidden rounded-full bg-ui-hairline">
          <div
            class="h-full bg-gradient-to-r from-purple-500 to-indigo-500 transition-all duration-300 rounded-full"
            :style="{ width: `${scanProgress.percent}%` }"
          ></div>
        </div>
      </div>
    </div>

    <!-- 范围选择器与形态过滤栏 -->
    <div class="flex flex-col gap-3 rounded-xl border border-ui-hairline bg-ui-surface p-4 sm:flex-row sm:items-center sm:justify-between">
      <!-- 标的池切换 -->
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-xs text-ui-text-3 font-medium mr-1">标的范围:</span>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
          :class="scope === 'sectors' ? 'bg-purple-600 text-white' : 'bg-ui-card text-ui-text-2 hover:bg-ui-surface-hover'"
          @click="handleSelectScope('sectors')"
        >
          📊 行业核心板块 (图形选板块)
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
          :class="scope === 'zz1000' ? 'bg-purple-600 text-white' : 'bg-ui-card text-ui-text-2 hover:bg-ui-surface-hover'"
          @click="handleSelectScope('zz1000')"
        >
          🚀 中证1000 选股
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
          :class="scope === 'zz500' ? 'bg-purple-600 text-white' : 'bg-ui-card text-ui-text-2 hover:bg-ui-surface-hover'"
          @click="handleSelectScope('zz500')"
        >
          🔬 中证500 选股
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
          :class="scope === 'hs300' ? 'bg-purple-600 text-white' : 'bg-ui-card text-ui-text-2 hover:bg-ui-surface-hover'"
          @click="handleSelectScope('hs300')"
        >
          🏛️ 沪深300 选股
        </button>
        <div v-if="scope === 'sector_members'" class="flex items-center gap-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 px-2.5 py-1 text-xs text-purple-300">
          <span>🧬 {{ targetConcept }} 成分股穿透</span>
          <button type="button" class="text-purple-400 hover:text-white" @click="handleSelectScope('sectors')">✕</button>
        </div>
      </div>

      <!-- 形态过滤单选 -->
      <div class="flex items-center gap-1.5 bg-ui-card p-1 rounded-lg border border-ui-hairline self-start sm:self-auto">
        <button
          type="button"
          class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
          :class="patternFilter === 'all' ? 'bg-ui-surface text-ui-text shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
          @click="patternFilter = 'all'"
        >
          全部 ({{ (allBuy2.length + allBuy1.length) }})
        </button>
        <button
          type="button"
          class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
          :class="patternFilter === 'buy2' ? 'bg-purple-600 text-white shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
          @click="patternFilter = 'buy2'"
        >
          🔥 类2买确认 ({{ allBuy2.length }})
        </button>
        <button
          type="button"
          class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
          :class="patternFilter === 'buy1' ? 'bg-cyan-600 text-white shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
          @click="patternFilter = 'buy1'"
        >
          🌱 1买初成 ({{ allBuy1.length }})
        </button>
      </div>
    </div>

    <!-- 统计指标小卡片 -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div class="rounded-xl border border-ui-hairline bg-ui-surface p-3.5">
        <div class="text-[11px] text-ui-text-3">已扫描标的池</div>
        <div class="mt-1 text-xl font-bold tabular-nums text-ui-text">{{ totalScanned }}</div>
      </div>
      <div class="rounded-xl border border-purple-500/20 bg-purple-500/5 p-3.5">
        <div class="text-[11px] text-purple-400">🔥 类2买确认 (即时介入)</div>
        <div class="mt-1 text-xl font-bold tabular-nums text-purple-400">{{ buy2Count }}</div>
      </div>
      <div class="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3.5">
        <div class="text-[11px] text-cyan-400">🌱 1买初成 (底背驰观察)</div>
        <div class="mt-1 text-xl font-bold tabular-nums text-cyan-400">{{ buy1Count }}</div>
      </div>
      <div class="rounded-xl border border-ui-hairline bg-ui-surface p-3.5">
        <div class="text-[11px] text-ui-text-3">平均背驰绿柱面积比</div>
        <div class="mt-1 text-xl font-bold tabular-nums text-ui-text">{{ avgDivRatio }}</div>
      </div>
    </div>

    <!-- 缠论历史回测抽屉 / 控制台 -->
    <div v-if="showBacktestDrawer" class="rounded-xl border border-purple-500/30 bg-ui-surface p-4 sm:p-5 shadow-md">
      <div class="flex items-center justify-between pb-3 border-b border-ui-hairline">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold text-ui-text">缠论类2买策略历史回测控制台</span>
          <span class="text-xs text-ui-text-3">按历史出中枢1买底背驰 -> 突破放量 -> 回调不破前低买入验证</span>
        </div>
        <button type="button" class="text-xs text-ui-text-3 hover:text-ui-text" @click="showBacktestDrawer = false">✕ 关闭</button>
      </div>

      <!-- 回测配置控制行 1：标的池与时间区间 -->
      <div class="grid grid-cols-1 sm:grid-cols-4 gap-3 mt-4">
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">回测标的池</label>
          <select v-model="btUniverse" class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm">
            <option value="sectors" class="bg-[#1e2430] text-white">行业核心板块 (32个核心行业)</option>
            <option value="sector_members" class="bg-[#1e2430] text-white">半导体成分股 (穿透)</option>
            <option value="zz1000" class="bg-[#1e2430] text-white">中证1000 样本股</option>
            <option value="zz500" class="bg-[#1e2430] text-white">中证500 样本股</option>
            <option value="hs300" class="bg-[#1e2430] text-white">沪深300 权重股</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">时间跨度快捷预设</label>
          <select :value="btTimeRangePreset" @change="handleTimePresetChange(($event.target as HTMLSelectElement).value as any)" class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm">
            <option value="3m" class="bg-[#1e2430] text-white">近 3 个月 (90天短周期)</option>
            <option value="6m" class="bg-[#1e2430] text-white">近 6 个月 (半年行情)</option>
            <option value="1y" class="bg-[#1e2430] text-white">近 1 年 (完整年度走势)</option>
            <option value="2y" class="bg-[#1e2430] text-white">近 2 年 (牛熊波段大周期)</option>
            <option value="custom" class="bg-[#1e2430] text-white">自定义时间区间 ✎</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">回测开始日期</label>
          <input
            type="date"
            v-model="btStartDate"
            class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm"
            @change="btTimeRangePreset = 'custom'"
          />
        </div>
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">回测结束日期</label>
          <input
            type="date"
            v-model="btEndDate"
            class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-1.5 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm"
            @change="btTimeRangePreset = 'custom'"
          />
        </div>
      </div>

      <!-- 回测配置控制行 2：交易风控、持股周期与执行按钮 -->
      <div class="grid grid-cols-1 sm:grid-cols-4 gap-3 mt-3">
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">目标持股周期 (最长持仓)</label>
          <select v-model="btMaxHoldDays" class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm">
            <option :value="5" class="bg-[#1e2430] text-white">5 个交易日 (超短线快进快出)</option>
            <option :value="10" class="bg-[#1e2430] text-white">10 个交易日 (两周快速波段)</option>
            <option :value="15" class="bg-[#1e2430] text-white">15 个交易日 (单笔反弹标准周期)</option>
            <option :value="25" class="bg-[#1e2430] text-white">25 个交易日 (类2买主升标准持仓)</option>
            <option :value="40" class="bg-[#1e2430] text-white">40 个交易日 (次级别波段中线)</option>
            <option :value="60" class="bg-[#1e2430] text-white">60 个交易日 (大级别趋势中长线)</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">止盈目标位</label>
          <select v-model="btTakeProfit" class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm">
            <option :value="0.08" class="bg-[#1e2430] text-white">+8% 极速落袋防守</option>
            <option :value="0.10" class="bg-[#1e2430] text-white">+10% 快速落袋</option>
            <option :value="0.15" class="bg-[#1e2430] text-white">+15% 标准类2买主升</option>
            <option :value="0.20" class="bg-[#1e2430] text-white">+20% 趋势波段</option>
            <option :value="0.30" class="bg-[#1e2430] text-white">+30% 大级别主升浪</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-ui-text-3 mb-1 font-medium">最大止损位</label>
          <select v-model="btStopLoss" class="w-full rounded-lg border border-gray-700 bg-[#1e2430] px-3 py-2 text-xs text-white focus:outline-none focus:border-purple-500 shadow-sm">
            <option :value="0.03" class="bg-[#1e2430] text-white">-3% 极紧止损</option>
            <option :value="0.05" class="bg-[#1e2430] text-white">-5% 破前低/支撑止损</option>
            <option :value="0.08" class="bg-[#1e2430] text-white">-8% 宽幅容错</option>
            <option :value="0.10" class="bg-[#1e2430] text-white">-10% 宽幅中线容忍</option>
          </select>
        </div>
        <div class="flex items-end">
          <button
            type="button"
            class="w-full rounded-lg bg-purple-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-purple-500 transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5 h-[34px]"
            :disabled="btLoading"
            @click="runBacktest"
          >
            <svg v-if="btLoading" class="h-4 w-4 animate-spin text-white" viewBox="0 0 24 24" fill="none">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
            </svg>
            <svg v-else class="h-4 w-4 text-purple-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {{ btLoading ? '正在回测历史走势...' : '启动缠论历史回测' }}
          </button>
        </div>
      </div>

      <!-- 回测结果展示 -->
      <div v-if="btResult && btResult.summary" class="mt-5 space-y-4 pt-4 border-t border-ui-hairline">
        <div class="flex flex-wrap items-center justify-between text-xs text-ui-text-3 px-1">
          <span class="flex items-center gap-2">
            <span>📅 回测有效区间: <b class="text-ui-text font-mono">{{ btResult.summary.date_range }}</b></span>
            <span>·</span>
            <span>⏱️ 持股周期上限: <b class="text-amber-400 font-mono">{{ btResult.summary.max_hold_days }} 天</b></span>
          </span>
          <span class="text-[11px] text-ui-text-3">信号确认次日 09:30 开盘入场 · 真实撮合风控</span>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-6 gap-3">
          <div class="rounded-lg bg-ui-card p-3">
            <div class="text-[10px] text-ui-text-3">回测交易总笔数</div>
            <div class="text-lg font-bold text-ui-text tabular-nums">{{ btResult.summary.total_trades }} 笔</div>
          </div>
          <div class="rounded-lg bg-ui-card p-3">
            <div class="text-[10px] text-ui-text-3">策略胜率</div>
            <div class="text-lg font-bold text-emerald-400 tabular-nums">{{ btResult.summary.win_rate }}%</div>
          </div>
          <div class="rounded-lg bg-ui-card p-3">
            <div class="text-[10px] text-ui-text-3">平均每笔收益率</div>
            <div class="text-lg font-bold text-purple-400 tabular-nums">{{ btResult.summary.avg_pnl >= 0 ? '+' : '' }}{{ btResult.summary.avg_pnl }}%</div>
          </div>
          <div class="rounded-lg bg-ui-card p-3">
            <div class="text-[10px] text-ui-text-3">累计总收益</div>
            <div class="text-lg font-bold tabular-nums" :class="btResult.summary.total_return >= 0 ? 'text-emerald-400' : 'text-rose-400'">{{ btResult.summary.total_return >= 0 ? '+' : '' }}{{ btResult.summary.total_return }}%</div>
          </div>
          <div class="rounded-lg bg-ui-card p-3">
            <div class="text-[10px] text-ui-text-3">盈亏比 / 最大回撤</div>
            <div class="text-lg font-bold text-ui-text tabular-nums">{{ btResult.summary.profit_factor }} / {{ btResult.summary.max_drawdown }}%</div>
          </div>
          <div class="rounded-lg bg-ui-card p-3">
            <div class="text-[10px] text-ui-text-3">平均持仓天数</div>
            <div class="text-lg font-bold text-amber-400 tabular-nums">{{ btResult.summary.avg_hold_days ?? '—' }} 天</div>
          </div>
        </div>

        <!-- 历史交易列表 -->
        <div class="max-h-64 overflow-y-auto rounded-lg border border-ui-hairline">
          <table class="w-full text-left text-xs">
            <thead class="bg-ui-card text-ui-text-3 sticky top-0">
              <tr>
                <th class="p-2.5">标的</th>
                <th class="p-2.5">买入日期/买价</th>
                <th class="p-2.5">出场日期/出价</th>
                <th class="p-2.5">持仓天数</th>
                <th class="p-2.5">收益率</th>
                <th class="p-2.5">退出原因</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ui-hairline text-ui-text">
              <tr v-for="(tr, idx) in btResult.trades.slice(0, 50)" :key="idx" class="hover:bg-ui-surface-hover">
                <td class="p-2.5 font-medium">
                  <a
                    :href="baiduStockUrl(tr.code, tr.name)"
                    target="_blank"
                    rel="noopener"
                    class="hover:text-purple-400 hover:underline inline-flex items-center gap-1 text-ui-text"
                    :title="`在外部行情中查看 ${tr.name}`"
                  >
                    <span>{{ tr.name }}</span>
                    <span class="text-[10px] text-ui-text-3 font-mono">({{ tr.code }})</span>
                    <svg class="h-3 w-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                </td>
                <td class="p-2.5 tabular-nums">{{ tr.buy_date }} · ¥{{ tr.buy_price }}</td>
                <td class="p-2.5 tabular-nums">{{ tr.exit_date }} · ¥{{ tr.exit_price }}</td>
                <td class="p-2.5 tabular-nums">{{ tr.hold_days }} 天</td>
                <td class="p-2.5 font-bold tabular-nums" :class="tr.pnl_pct >= 0 ? 'text-red-400' : 'text-emerald-400'">
                  {{ tr.pnl_pct >= 0 ? '+' : '' }}{{ tr.pnl_pct }}%
                </td>
                <td class="p-2.5 text-ui-text-2">{{ tr.exit_reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 标的列表展示区（板块与股票子 TAB 切换，带高度控制） -->
    <div class="space-y-3">
      <!-- 列表子 TAB 导航条 -->
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-ui-hairline pb-2.5">
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
            :class="resultTab === 'sectors' ? 'bg-purple-600 text-white shadow-sm' : 'bg-ui-card text-ui-text-2 hover:bg-ui-surface-hover hover:text-ui-text'"
            @click="resultTab = 'sectors'"
          >
            <span>📊 行业核心板块</span>
            <span class="rounded-full px-1.5 py-0.5 text-[10px] leading-none" :class="resultTab === 'sectors' ? 'bg-white/20 text-white' : 'bg-ui-hairline text-ui-text-3'">
              {{ sectorList.length }}
            </span>
          </button>

          <button
            type="button"
            class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
            :class="resultTab === 'stocks' ? 'bg-purple-600 text-white shadow-sm' : 'bg-ui-card text-ui-text-2 hover:bg-ui-surface-hover hover:text-ui-text'"
            @click="resultTab = 'stocks'"
          >
            <span>🧬 潜力个股列表</span>
            <span class="rounded-full px-1.5 py-0.5 text-[10px] leading-none" :class="resultTab === 'stocks' ? 'bg-white/20 text-white' : 'bg-ui-hairline text-ui-text-3'">
              {{ stockList.length }}
            </span>
          </button>
        </div>

        <div class="text-xs text-ui-text-3 flex items-center gap-2">
          <span>当前显示 {{ currentTabItems.length }} 个标的</span>
          <span>·</span>
          <span>点击标的名称可直接跳转行情 ↗</span>
        </div>
      </div>

      <!-- 标的卡片列表容器 (自适应可滚动高度，防止页面无限堆叠) -->
      <div v-if="currentTabItems.length > 0" class="max-h-[640px] overflow-y-auto pr-1 space-y-3">
        <div
          v-for="item in currentTabItems"
          :key="item.code"
          class="rounded-xl border bg-ui-surface p-4 transition-all hover:border-purple-500/40 hover:shadow-sm"
          :class="item.pattern === 'buy2_prime' ? 'border-purple-500/30' : 'border-ui-hairline'"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <!-- 标的名称与状态 -->
            <div class="flex items-center gap-3">
              <div>
                <div class="flex items-center gap-2">
                  <a
                    :href="item.is_sector ? baiduIndexUrl(item.code, item.name) : baiduStockUrl(item.code, item.name)"
                    target="_blank"
                    rel="noopener"
                    class="text-base font-bold text-ui-text hover:text-purple-400 hover:underline transition-colors inline-flex items-center gap-1"
                    :title="`在外部行情中查看 ${item.name} (${item.code})`"
                  >
                    <span>{{ item.name }}</span>
                    <svg class="h-3.5 w-3.5 opacity-50 hover:opacity-100" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                    </svg>
                  </a>
                  <a
                    :href="item.is_sector ? baiduIndexUrl(item.code, item.name) : baiduStockUrl(item.code, item.name)"
                    target="_blank"
                    rel="noopener"
                    class="text-xs text-ui-text-3 font-mono hover:text-purple-400"
                  >
                    ({{ item.code }})
                  </a>
                  <span
                    class="rounded px-2 py-0.5 text-[11px] font-semibold"
                    :class="item.pattern === 'buy2_prime' ? 'bg-purple-500/15 text-purple-400 border border-purple-500/30' : 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'"
                  >
                    {{ item.pattern_label }}
                  </span>
                  <span v-if="item.is_sector" class="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">板块</span>
                </div>
                <div class="mt-1 text-xs text-ui-text-3">
                  {{ item.details }}
                </div>
              </div>
            </div>

            <!-- 价格与操作 -->
            <div class="flex items-center gap-4 self-end sm:self-auto">
              <div class="text-right">
                <div class="text-sm font-bold tabular-nums text-ui-text">¥{{ item.last_price }}</div>
                <div class="text-xs font-semibold tabular-nums" :class="item.change_pct >= 0 ? 'text-red-400' : 'text-emerald-400'">
                  {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct }}%
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="flex items-center gap-2">
                <button
                  v-if="item.is_sector"
                  type="button"
                  class="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20 transition-colors"
                  @click="drillIntoConcept(item.name)"
                  title="穿透扫描该板块全部成分股中的类2买标的"
                >
                  🧬 选板块成分股
                </button>

                <button
                  type="button"
                  class="rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs font-medium text-purple-300 hover:bg-purple-500/20 transition-colors"
                  @click="openChart(item)"
                >
                  📈 查看缠论K线
                </button>
              </div>
            </div>
          </div>

          <!-- 关键缠论形态点位拆解 -->
          <div class="mt-3.5 grid grid-cols-2 sm:grid-cols-5 gap-2 rounded-lg bg-ui-card/60 p-2.5 text-xs border border-ui-hairline/60">
            <div>
              <span class="text-ui-text-3 text-[10px] block">1买筑底位 (日期)</span>
              <span class="font-semibold text-ui-text tabular-nums">
                ¥{{ item.buy1_price ?? '—' }}
                <span class="text-[10px] text-ui-text-3 font-normal" v-if="item.buy1_date">({{ item.buy1_date.slice(5) }})</span>
              </span>
            </div>
            <div>
              <span class="text-ui-text-3 text-[10px] block">1买后反弹高点</span>
              <span class="font-semibold text-ui-text tabular-nums">¥{{ item.rebound_high ?? '—' }}</span>
            </div>
            <div>
              <span class="text-ui-text-3 text-[10px] block">回踩支撑低点 (不破前低)</span>
              <span class="font-semibold text-emerald-400 tabular-nums">¥{{ item.pullback_low ?? '—' }}</span>
            </div>
            <div>
              <span class="text-ui-text-3 text-[10px] block">建议防守止损位</span>
              <span class="font-semibold text-rose-400 tabular-nums">¥{{ item.stop_loss ?? '—' }}</span>
            </div>
            <div>
              <span class="text-ui-text-3 text-[10px] block">MACD绿柱背驰比 (Sb / Sa)</span>
              <span class="font-semibold text-purple-400 tabular-nums">
                {{ item.divergence_ratio ?? '—' }}
                <span class="text-[10px] text-purple-300 font-normal" v-if="item.divergence_ratio">
                  (减弱 {{ Math.round((1 - item.divergence_ratio) * 100) }}%)
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 空数据提示 -->
      <div v-else class="rounded-xl border border-ui-hairline bg-ui-surface p-12 text-center">
        <div class="text-3xl">🔍</div>
        <div class="mt-3 text-sm font-medium text-ui-text">
          当前【{{ resultTab === 'sectors' ? '行业核心板块' : '潜力个股' }}】分类下暂无符合该形态条件的标的
        </div>
        <p class="mt-1 text-xs text-ui-text-3">点击上方「一键形态全景扫描」刷新或切换至【{{ resultTab === 'sectors' ? '潜力个股列表' : '行业核心板块' }}】查看。</p>
        <div class="mt-4 flex items-center justify-center gap-3">
          <button
            type="button"
            class="rounded-lg bg-purple-600 px-4 py-2 text-xs font-semibold text-white hover:bg-purple-500"
            @click="startScan()"
          >
            立即开始全景扫描
          </button>
          <button
            type="button"
            class="rounded-lg border border-ui-hairline bg-ui-card px-4 py-2 text-xs font-medium text-ui-text-2 hover:bg-ui-surface-hover hover:text-ui-text"
            @click="resultTab = resultTab === 'sectors' ? 'stocks' : 'sectors'"
          >
            切换到{{ resultTab === 'sectors' ? '潜力个股' : '板块列表' }}
          </button>
        </div>
      </div>
    </div>

    <!-- K线与缠论笔 / 中枢 / MACD 弹窗 -->
    <div
      v-if="showChartModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-3 sm:p-6 backdrop-blur-sm"
      @click.self="closeChart"
    >
      <div class="relative flex h-[90vh] w-full max-w-5xl flex-col rounded-2xl border border-ui-hairline bg-ui-surface p-4 sm:p-6 shadow-2xl">
        <!-- 弹窗头部 -->
        <div class="flex items-center justify-between pb-3 border-b border-ui-hairline">
          <div class="flex items-center gap-3">
            <span class="text-lg font-bold text-ui-text">{{ chartName }}</span>
            <span class="text-xs text-ui-text-3 font-mono">({{ chartCode }})</span>
            <span class="rounded bg-purple-500/10 px-2 py-0.5 text-xs text-purple-400">
              缠论日K线分析 · 笔折线 / 中枢 / MACD 面积
            </span>
          </div>
          <button
            type="button"
            class="rounded-lg p-1.5 text-ui-text-3 hover:bg-ui-card hover:text-ui-text transition-colors"
            @click="closeChart"
          >
            ✕
          </button>
        </div>

        <!-- 形态关键点详情横条 -->
        <div v-if="currentChartData?.pattern_info" class="my-2.5 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-purple-500/10 border border-purple-500/20 px-3 py-2 text-xs text-purple-300">
          <div class="flex items-center gap-2">
            <span class="font-bold text-purple-400">{{ currentChartData.pattern_info.pattern_label }}</span>
            <span class="text-ui-text-2">{{ currentChartData.pattern_info.details }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-3 tabular-nums font-mono text-[11px]">
            <span>1买低点: <b class="text-cyan-400">¥{{ currentChartData.pattern_info.buy1_price }}</b></span>
            <span>回踩支撑: <b class="text-emerald-400">¥{{ currentChartData.pattern_info.pullback_low }}</b></span>
            <span>防守止损: <b class="text-rose-400">¥{{ currentChartData.pattern_info.stop_loss }}</b></span>
            <span>背驰比: <b class="text-purple-300">{{ currentChartData.pattern_info.divergence_ratio }}</b></span>
          </div>
        </div>

        <!-- 图例说明 -->
        <div class="flex items-center gap-4 py-2 text-[11px] text-ui-text-3">
          <span class="flex items-center gap-1.5">
            <span class="h-2 w-3 bg-red-500 inline-block rounded-xs"></span> 向上笔
          </span>
          <span class="flex items-center gap-1.5">
            <span class="h-2 w-3 bg-cyan-500 inline-block rounded-xs"></span> 向下笔
          </span>
          <span class="flex items-center gap-1.5">
            <span class="h-2.5 w-4 border border-dashed border-amber-500 bg-amber-500/20 inline-block"></span> 缠论中枢
          </span>
          <span class="flex items-center gap-1.5">
            <span class="h-2 w-2 rounded-full bg-purple-500 inline-block"></span> 绿柱缩小面积背驰
          </span>
        </div>

        <!-- ECharts 容器 -->
        <div class="relative flex-1 min-h-0 w-full">
          <div v-if="chartLoading" class="absolute inset-0 z-10 flex items-center justify-center bg-ui-surface/60 backdrop-blur-xs">
            <div class="flex items-center gap-2 text-xs text-purple-400">
              <svg class="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
              </svg>
              <span>正在加载并计算缠论笔与中枢...</span>
            </div>
          </div>
          <div ref="chartDom" class="h-full w-full"></div>
        </div>
      </div>
    </div>
  </div>
</template>
