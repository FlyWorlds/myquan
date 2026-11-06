<script setup lang="ts">
import * as echarts from 'echarts'
import type { Strategy36Payload, StrategyTab } from '~/types/snapshot'

const props = defineProps<{
  tab?: StrategyTab | null
  payload?: Strategy36Payload | null
  phase?: string
}>()

const localPayload = ref<Strategy36Payload | null>(null)
const loading = ref(false)
const activeChartTab = ref<'breadth' | 'index'>('breadth')

const chartEl = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

const effectivePayload = computed(() => {
  return props.payload?.current ? props.payload : localPayload.value
})

async function fetchTimingState() {
  loading.value = true
  try {
    const res = await fetch('/api/strategy36/timing-state')
    if (res.ok) {
      localPayload.value = await res.json()
      updateChart()
    }
  } catch (err) {
    console.error('Failed to load strategy36 timing state:', err)
  } finally {
    loading.value = false
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
  const p = effectivePayload.value
  if (!chartEl.value || !p || !p.history || !p.history.length) return
  initChart()
  if (!myChart) return

  const dates = p.history.map((h) => h.date)
  const breadthValues = p.history.map((h) => h.tech_breadth)
  const cybCloseValues = p.history.map((h) => h.cyb_close)
  const cybMa20Values = p.history.map((h) => h.cyb_ma20)
  const cybMa60Values = p.history.map((h) => h.cyb_ma60)

  // 构造空仓阴影区间 markArea 数据
  const markAreaData = (p.cash_intervals || []).map((interval) => [
    {
      xAxis: interval.start,
      itemStyle: {
        color: 'rgba(239, 68, 68, 0.12)',
      },
      label: {
        show: true,
        position: 'top',
        formatter: '科技空仓',
        color: '#f87171',
        fontSize: 10,
      },
    },
    {
      xAxis: interval.end,
    },
  ])

  if (activeChartTab.value === 'breadth') {
    // 构造有效坐标序列供 lines 流动光点使用
    const breadthCoords = dates
      .map((d, i) => [d, breadthValues[i]])
      .filter((pt) => pt[1] != null && !Number.isNaN(Number(pt[1])))

    const firstDate = dates[0]
    const lastDate = dates[dates.length - 1]
    const exitBreadth = p.thresholds?.exit_breadth ?? 38
    const panicBreadth = p.thresholds?.breadth_panic ?? 30
    const extremeBreadth = p.thresholds?.extreme_panic ?? 15

    // 图表 1: 科技池广度与空仓界限水位图
    myChart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          let s = `<div class="font-bold border-b border-gray-600/50 pb-1 mb-1">${params[0]?.name || ''}</div>`
          for (const item of params) {
            if (item.seriesType === 'lines') continue
            const v = item.value != null ? `${Number(item.value).toFixed(2)}%` : '—'
            s += `<div class="flex items-center justify-between gap-4 py-0.5 text-xs">
              <span class="inline-flex items-center gap-1.5">${item.marker} ${item.seriesName}</span>
              <span class="font-mono font-bold">${v}</span>
            </div>`
          }
          return s
        },
      },
      legend: {
        data: ['科技池个股站上20日线比例', '科技溃败线(30%)', '科技极端熔断线(15%)', '科技企稳解除线(38%)'],
        textStyle: { color: '#9ca3af', fontSize: 11 },
        top: 6,
        right: 12,
      },
      grid: { left: 16, right: 32, bottom: 20, top: 48, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        name: '科技池广度 (%)',
        min: 0,
        max: 100,
        axisLabel: { formatter: '{value}%', color: '#9ca3af' },
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.25)', type: 'dashed' } },
      },
      series: [
        {
          name: '科技池个股站上20日线比例',
          type: 'line',
          data: breadthValues,
          smooth: true,
          showSymbol: false,
          animation: false,
          lineStyle: { width: 2.2, color: '#38bdf8' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(56, 189, 248, 0.25)' },
              { offset: 1, color: 'rgba(56, 189, 248, 0.00)' },
            ]),
          },
          markLine: {
            animation: false,
            symbol: ['none', 'none'],
            data: [
              {
                yAxis: exitBreadth,
                lineStyle: { color: '#10b981', width: 1.5, type: 'dashed' },
                label: {
                  position: 'insideEndTop',
                  formatter: `企稳解除线 (${exitBreadth}%)`,
                  color: '#10b981',
                  fontSize: 11,
                  backgroundColor: 'rgba(15, 23, 42, 0.85)',
                  padding: [2, 6],
                  borderRadius: 4,
                  borderWidth: 1,
                  borderColor: 'rgba(16, 185, 129, 0.35)',
                },
              },
              {
                yAxis: panicBreadth,
                lineStyle: { color: '#ef4444', width: 1.5, type: 'dashed' },
                label: {
                  // 放置在左侧起始端，彻底与右侧企稳线错开，杜绝上下重叠
                  position: 'insideStartTop',
                  distance: 8,
                  formatter: `科技溃败线 (${panicBreadth}%)`,
                  color: '#ef4444',
                  fontSize: 11,
                  backgroundColor: 'rgba(15, 23, 42, 0.85)',
                  padding: [2, 6],
                  borderRadius: 4,
                  borderWidth: 1,
                  borderColor: 'rgba(239, 68, 68, 0.35)',
                },
              },
              {
                yAxis: extremeBreadth,
                lineStyle: { color: '#b91c1c', width: 2, type: 'dashed' },
                label: {
                  // 放置在右侧末端，距离 38% 企稳线有 23% 的宽裕垂直间距，绝不重叠
                  position: 'insideEndTop',
                  formatter: `科技极端熔断线 (${extremeBreadth}%)`,
                  color: '#f87171',
                  fontSize: 11,
                  backgroundColor: 'rgba(15, 23, 42, 0.85)',
                  padding: [2, 6],
                  borderRadius: 4,
                  borderWidth: 1,
                  borderColor: 'rgba(248, 113, 113, 0.35)',
                },
              },
            ],
          },
          markArea: {
            data: markAreaData,
          },
        },
        {
          name: '科技光点流转',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          polyline: true,
          silent: true,
          zlevel: 3,
          lineStyle: {
            width: 0,
            opacity: 0,
          },
          effect: {
            show: true,
            period: 4,
            trailLength: 0.18,
            symbol: 'circle',
            symbolSize: 6,
            color: '#ffffff',
            shadowBlur: 10,
            shadowColor: '#38bdf8',
          },
          data: [
            {
              coords: breadthCoords,
            },
          ],
        },
        {
          name: '科技企稳线光点',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          polyline: false,
          silent: true,
          zlevel: 3,
          lineStyle: { width: 0, opacity: 0 },
          effect: {
            show: true,
            period: 4,
            trailLength: 0.22,
            symbol: 'circle',
            symbolSize: 5,
            color: '#34d399',
            shadowBlur: 8,
            shadowColor: '#10b981',
          },
          data: [{ coords: [[firstDate, exitBreadth], [lastDate, exitBreadth]] }],
        },
        {
          name: '科技溃败线光点',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          polyline: false,
          silent: true,
          zlevel: 3,
          lineStyle: { width: 0, opacity: 0 },
          effect: {
            show: true,
            period: 4,
            trailLength: 0.22,
            symbol: 'circle',
            symbolSize: 5,
            color: '#f87171',
            shadowBlur: 8,
            shadowColor: '#ef4444',
          },
          data: [{ coords: [[firstDate, panicBreadth], [lastDate, panicBreadth]] }],
        },
        {
          name: '科技极端熔断线光点',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          polyline: false,
          silent: true,
          zlevel: 3,
          lineStyle: { width: 0, opacity: 0 },
          effect: {
            show: true,
            period: 4,
            trailLength: 0.22,
            symbol: 'circle',
            symbolSize: 5,
            color: '#fb7185',
            shadowBlur: 8,
            shadowColor: '#e11d48',
          },
          data: [{ coords: [[firstDate, extremeBreadth], [lastDate, extremeBreadth]] }],
        },
      ],
    }, true)
  } else {
    // 构造创业板坐标序列供 lines 流动光点使用
    const cybCoords = dates
      .map((d, i) => [d, cybCloseValues[i]])
      .filter((pt) => pt[1] != null && !Number.isNaN(Number(pt[1])))

    // 图表 2: 创业板/深成指/科创50生命线
    myChart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: {
        data: ['创业板指收盘价', '创业板MA20', '创业板MA60生命线'],
        textStyle: { color: '#9ca3af', fontSize: 11 },
        top: 6,
        right: 12,
      },
      grid: { left: 16, right: 32, bottom: 20, top: 48, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        name: '指数点位',
        scale: true,
        axisLabel: { color: '#9ca3af' },
        splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.25)', type: 'dashed' } },
      },
      series: [
        {
          name: '创业板指收盘价',
          type: 'line',
          data: cybCloseValues,
          smooth: true,
          showSymbol: false,
          animation: false,
          lineStyle: { width: 2, color: '#f59e0b' },
          markArea: {
            data: markAreaData,
          },
        },
        {
          name: '创业板MA20',
          type: 'line',
          data: cybMa20Values,
          smooth: true,
          showSymbol: false,
          animation: false,
          lineStyle: { width: 1.5, color: '#10b981', type: 'dashed' },
        },
        {
          name: '创业板MA60生命线',
          type: 'line',
          data: cybMa60Values,
          smooth: true,
          showSymbol: false,
          animation: false,
          lineStyle: { width: 2, color: '#ec4899' },
        },
        {
          name: '创业板光点流转',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          polyline: true,
          silent: true,
          zlevel: 3,
          lineStyle: {
            width: 0,
            opacity: 0,
          },
          effect: {
            show: true,
            period: 4,
            trailLength: 0.18,
            symbol: 'circle',
            symbolSize: 6,
            color: '#ffffff',
            shadowBlur: 10,
            shadowColor: '#f59e0b',
          },
          data: [
            {
              coords: cybCoords,
            },
          ],
        },
      ],
    }, true)
  }
}

watch(activeChartTab, () => {
  nextTick(updateChart)
})

watch(
  () => props.payload,
  () => {
    nextTick(updateChart)
  },
  { deep: true },
)

function onResize() {
  if (myChart) myChart.resize()
}

onMounted(() => {
  if (!effectivePayload.value?.current) {
    fetchTimingState()
  } else {
    nextTick(updateChart)
  }
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (myChart) {
    myChart.dispose()
    myChart = null
  }
})
</script>

<template>
  <div class="space-y-4">
    <!-- 1. 当前科技空仓状态看板与诊断 -->
    <div
      class="card rounded-2xl p-4 sm:p-5 border transition-all"
      :class="effectivePayload?.current?.is_cash
        ? 'border-red-500/40 bg-gradient-to-r from-red-950/25 via-ui-surface to-ui-surface'
        : 'border-cyan-500/40 bg-gradient-to-r from-cyan-950/25 via-ui-surface to-ui-surface'"
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <div
            class="flex h-12 w-12 items-center justify-center rounded-xl text-2xl font-black shadow-inner"
            :class="effectivePayload?.current?.is_cash ? 'bg-red-500/20 text-red-400' : 'bg-cyan-500/20 text-cyan-400'"
          >
            <span v-if="effectivePayload?.current?.is_cash">🛑</span>
            <span v-else>🚀</span>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-semibold uppercase tracking-wider text-ui-text-3">科技成长 · 风格择时</span>
              <span class="rounded-full px-2 py-0.5 text-[11px] font-medium text-ui-text-3 border border-ui-hairline">
                创业板/科创板/深成指 · {{ effectivePayload?.current?.date || '最新交易日' }}
              </span>
            </div>
            <h2
              class="mt-0.5 text-xl font-bold sm:text-2xl"
              :class="effectivePayload?.current?.is_cash ? 'text-red-400' : 'text-cyan-400'"
            >
              {{ effectivePayload?.current?.status_label || '计算中...' }}
            </h2>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-lg border border-ui-hairline/80 bg-ui-surface/80 px-3 py-1.5 text-xs font-medium text-ui-text hover:bg-ui-surface hover:text-accent transition"
            :disabled="loading"
            @click="fetchTimingState"
          >
            <span :class="loading ? 'animate-spin' : ''">↻</span>
            <span>刷新诊断</span>
          </button>
        </div>
      </div>

      <!-- 诊断理由说明条 -->
      <div
        class="mt-4 rounded-xl border p-3 text-xs leading-relaxed"
        :class="effectivePayload?.current?.tier === 1 ? 'border-red-500/30 bg-red-950/20 text-red-200' : (effectivePayload?.current?.tier === 2 ? 'border-orange-500/30 bg-orange-950/20 text-orange-200' : (effectivePayload?.current?.tier === 3 ? 'border-amber-500/30 bg-amber-950/20 text-amber-200' : 'border-cyan-500/30 bg-cyan-950/20 text-cyan-200'))"
      >
        <span class="font-bold">【科技成长风控结论】</span>
        {{ effectivePayload?.current?.reason || '加载科技成长择时指标中...' }}
      </div>

      <!-- 四级科技阶梯形动态仓位罗盘尺 -->
      <div class="mt-4 rounded-xl border border-ui-hairline/80 bg-ui-surface/70 p-3.5">
        <div class="flex items-center justify-between text-xs">
          <div class="flex items-center gap-2">
            <span class="font-bold text-ui-text">科技成长四级阶梯仓位罗盘</span>
            <span class="rounded bg-ui-fill-hover px-1.5 py-0.5 text-[10px] text-ui-text-3 font-mono">Tech Tiered Gate</span>
          </div>
          <div class="text-xs font-mono">
            当前科技建议仓位：<b class="text-accent text-sm">{{ effectivePayload?.current ? Math.round((effectivePayload.current.position_ratio ?? 0.3) * 100) + '%' : '—' }}</b>
          </div>
        </div>

        <div class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div
            v-for="step in [
              { t: 1, p: '0%', l: '阶梯1·极端熔断', c: 'border-red-500/50 bg-red-500/10 text-red-400', desc: '科技广度<15% 硬熔断' },
              { t: 2, p: '30%', l: '阶梯2·破位防守', c: 'border-orange-500/50 bg-orange-500/10 text-orange-400', desc: '创指破MA60 且 科技广度<30%' },
              { t: 3, p: '60%', l: '阶梯3·减速控仓', c: 'border-amber-500/50 bg-amber-500/10 text-amber-400', desc: '创指收复MA20 或 广度38%~50%' },
              { t: 4, p: '100%', l: '阶梯4·全面进攻', c: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400', desc: '创指>MA60 且 科技广度>50%' }
            ]"
            :key="step.t"
            class="relative rounded-xl border p-2.5 transition-all"
            :class="(effectivePayload?.current?.tier ?? 2) === step.t
              ? step.c + ' ring-2 ring-accent/60 shadow-md scale-[1.02] font-semibold'
              : 'border-ui-hairline/60 bg-ui-surface/40 text-ui-text-3 opacity-60'"
          >
            <div class="flex items-center justify-between">
              <span class="text-xs">{{ step.l }}</span>
              <span class="text-sm font-bold font-mono">{{ step.p }}</span>
            </div>
            <p class="mt-1 text-[11px] leading-tight text-ui-text-3">{{ step.desc }}</p>
            <div
              v-if="(effectivePayload?.current?.tier ?? 2) === step.t"
              class="absolute -top-1.5 -right-1.5 rounded-full bg-accent px-1.5 py-0.2 text-[9px] font-bold text-slate-900 uppercase tracking-tighter"
            >
              当前档位
            </div>
          </div>
        </div>
      </div>

      <!-- 5 维核心指标比对网格卡片 -->
      <div v-if="effectivePayload?.current?.breakdown" class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <!-- 维度 1: 创业板生命线 -->
        <div class="rounded-xl border border-ui-hairline/70 bg-ui-surface/60 p-3">
          <div class="flex items-center justify-between text-xs text-ui-text-3">
            <span>创业板指 (MA60)</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-bold"
              :class="effectivePayload.current.breakdown.cyb_trend.ok ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'"
            >
              {{ effectivePayload.current.breakdown.cyb_trend.status }}
            </span>
          </div>
          <div class="mt-1 flex items-baseline gap-2">
            <span class="text-base font-bold font-mono">{{ effectivePayload.current.breakdown.cyb_trend.current_value }}</span>
            <span class="text-xs text-ui-text-3 font-mono">线: {{ effectivePayload.current.breakdown.cyb_trend.threshold }}</span>
          </div>
          <div class="mt-1 text-[11px] text-ui-text-3">
            偏离度:
            <span :class="effectivePayload.current.breakdown.cyb_trend.diff_pct < 0 ? 'text-red-400 font-bold' : 'text-emerald-400'">
              {{ effectivePayload.current.breakdown.cyb_trend.diff_pct }}%
            </span>
          </div>
        </div>

        <!-- 维度 2: 深成指 & 科创50 协同 -->
        <div class="rounded-xl border border-ui-hairline/70 bg-ui-surface/60 p-3">
          <div class="flex items-center justify-between text-xs text-ui-text-3">
            <span>深成指 & 科创50</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-bold"
              :class="effectivePayload.current.breakdown.peer_indices.ok ? 'bg-cyan-500/20 text-cyan-400' : 'bg-red-500/20 text-red-400'"
            >
              {{ effectivePayload.current.breakdown.peer_indices.status }}
            </span>
          </div>
          <div class="mt-1 text-xs font-mono text-ui-text-2">
            深成: {{ effectivePayload.current.breakdown.peer_indices.sz_close }} (MA: {{ effectivePayload.current.breakdown.peer_indices.sz_ma60 }})
          </div>
          <div class="mt-1 text-xs font-mono text-ui-text-2">
            科创: {{ effectivePayload.current.breakdown.peer_indices.kc_close }} (MA: {{ effectivePayload.current.breakdown.peer_indices.kc_ma60 }})
          </div>
        </div>

        <!-- 维度 3: 科技池微观广度 -->
        <div class="rounded-xl border border-ui-hairline/70 bg-ui-surface/60 p-3">
          <div class="flex items-center justify-between text-xs text-ui-text-3">
            <span>科技微观广度</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-bold"
              :class="effectivePayload.current.breakdown.tech_breadth.ok ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'"
            >
              {{ effectivePayload.current.breakdown.tech_breadth.status }}
            </span>
          </div>
          <div class="mt-1 flex items-baseline gap-2">
            <span class="text-base font-bold font-mono">{{ effectivePayload.current.breakdown.tech_breadth.current_value }}%</span>
            <span class="text-xs text-ui-text-3 font-mono">警戒: 30%</span>
          </div>
          <div class="mt-2 h-1.5 w-full rounded-full bg-ui-hairline overflow-hidden">
            <div
              class="h-full rounded-full transition-all"
              :class="effectivePayload.current.breakdown.tech_breadth.current_value < 30 ? 'bg-red-500' : 'bg-cyan-500'"
              :style="{ width: `${Math.min(100, (effectivePayload.current.breakdown.tech_breadth.current_value / 50) * 100)}%` }"
            ></div>
          </div>
        </div>

        <!-- 维度 4: 科技极端熔断防线 -->
        <div class="rounded-xl border border-ui-hairline/70 bg-ui-surface/60 p-3">
          <div class="flex items-center justify-between text-xs text-ui-text-3">
            <span>科技流动性熔断</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-bold"
              :class="effectivePayload.current.breakdown.extreme_panic.ok ? 'bg-ui-surface text-ui-text-2 border border-ui-hairline' : 'bg-red-600 text-white'"
            >
              {{ effectivePayload.current.breakdown.extreme_panic.status }}
            </span>
          </div>
          <div class="mt-1 flex items-baseline gap-2">
            <span class="text-base font-bold font-mono">{{ effectivePayload.current.breakdown.extreme_panic.current_value }}%</span>
            <span class="text-xs text-ui-text-3 font-mono">熔断线: 15%</span>
          </div>
          <div class="mt-1 text-[11px] text-ui-text-3">
            {{ effectivePayload.current.breakdown.extreme_panic.desc }}
          </div>
        </div>

        <!-- 维度 5: 右侧解除进度 -->
        <div class="rounded-xl border border-ui-hairline/70 bg-ui-surface/60 p-3">
          <div class="flex items-center justify-between text-xs text-ui-text-3">
            <span>右侧企稳解除</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-bold"
              :class="effectivePayload.current.breakdown.exit_progress.ok ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'"
            >
              {{ effectivePayload.current.breakdown.exit_progress.status }}
            </span>
          </div>

          <!-- 当前指标与目标清晰对齐展示 -->
          <div class="mt-1.5 space-y-1 text-xs">
            <!-- 创业板指数 vs 20日线 -->
            <div class="flex items-center justify-between">
              <span class="text-ui-text-3">创业板指:</span>
              <span class="font-mono">
                <b class="text-ui-text">{{ effectivePayload.current.breakdown.exit_progress.current_index ?? effectivePayload.current.cyb_close }}</b>
                <span class="text-ui-text-3"> / {{ effectivePayload.current.breakdown.exit_progress.index_target }}</span>
                <span
                  class="ml-1 text-[11px] font-bold"
                  :class="(effectivePayload.current.breakdown.exit_progress.current_index ?? effectivePayload.current.cyb_close) >= effectivePayload.current.breakdown.exit_progress.index_target ? 'text-emerald-400' : 'text-red-400'"
                >
                  {{ (effectivePayload.current.breakdown.exit_progress.current_index ?? effectivePayload.current.cyb_close) >= effectivePayload.current.breakdown.exit_progress.index_target ? '✓已收复' : `${(((effectivePayload.current.breakdown.exit_progress.current_index ?? effectivePayload.current.cyb_close) - effectivePayload.current.breakdown.exit_progress.index_target) / effectivePayload.current.breakdown.exit_progress.index_target * 100).toFixed(1)}%` }}
                </span>
              </span>
            </div>

            <!-- 科技广度 vs 企稳门槛 38% -->
            <div class="flex items-center justify-between">
              <span class="text-ui-text-3">科技广度:</span>
              <span class="font-mono">
                <b class="text-ui-text">{{ effectivePayload.current.breakdown.exit_progress.current_breadth ?? effectivePayload.current.tech_breadth }}%</b>
                <span class="text-ui-text-3"> / {{ effectivePayload.current.breakdown.exit_progress.breadth_target ?? 38 }}%</span>
                <span
                  class="ml-1 text-[11px] font-bold"
                  :class="(effectivePayload.current.breakdown.exit_progress.current_breadth ?? effectivePayload.current.tech_breadth) >= (effectivePayload.current.breakdown.exit_progress.breadth_target ?? 38) ? 'text-emerald-400' : 'text-amber-400'"
                >
                  {{ (effectivePayload.current.breakdown.exit_progress.current_breadth ?? effectivePayload.current.tech_breadth) >= (effectivePayload.current.breakdown.exit_progress.breadth_target ?? 38) ? '✓达标' : `还差${((effectivePayload.current.breakdown.exit_progress.breadth_target ?? 38) - (effectivePayload.current.breakdown.exit_progress.current_breadth ?? effectivePayload.current.tech_breadth)).toFixed(1)}%` }}
                </span>
              </span>
            </div>
          </div>

          <div class="mt-1.5 line-clamp-1 text-[10px] text-ui-text-3 border-t border-ui-hairline/40 pt-1.5">
            {{ effectivePayload.current.breakdown.exit_progress.desc }}
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 可视化图表区：科技广度水位线 vs 创业板/科创50生命线 -->
    <div class="card rounded-2xl p-4 sm:p-5">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline/60 pb-3">
        <div>
          <h3 class="text-base font-semibold">科技成长择时与空仓界限时序分析</h3>
          <p class="mt-0.5 text-xs text-ui-text-3">红色阴影为历史触发科技空仓防守区间；线条文字绝对固定，流光微粒自左向右动态滑行。</p>
        </div>

        <div class="inline-flex rounded-lg bg-ui-surface/80 p-0.5 text-xs border border-ui-hairline">
          <button
            type="button"
            class="rounded-md px-3 py-1.5 font-medium transition"
            :class="activeChartTab === 'breadth' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'breadth'"
          >
            科技池微观广度与空仓界限 (推荐)
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1.5 font-medium transition"
            :class="activeChartTab === 'index' ? 'bg-accent/20 text-accent font-bold' : 'text-ui-text-3 hover:text-ui-text'"
            @click="activeChartTab = 'index'"
          >
            创业板指与 MA20/MA60 生命线
          </button>
        </div>
      </div>

      <!-- ECharts 宿主容器 -->
      <div ref="chartEl" class="mt-4 h-72 w-full sm:h-80" style="width: 100%; min-width: 100%;"></div>

      <!-- 图例与界限说明 -->
      <div class="mt-3 flex flex-wrap items-center justify-around gap-2 rounded-xl bg-ui-surface/40 p-2.5 text-xs border border-ui-hairline/40">
        <div class="flex items-center gap-1.5">
          <span class="inline-block h-2 w-4 rounded-sm bg-red-500/20 border border-red-500/40"></span>
          <span class="text-ui-text-2">红色阴影：科技空仓防守区间</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="inline-block h-0.5 w-4 bg-red-500 border-b border-dashed border-red-500"></span>
          <span class="text-ui-text-2">30% 科技溃败警戒线 (触发防守)</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="inline-block h-1 w-4 bg-red-700"></span>
          <span class="text-ui-text-2">15% 科技流动性熔断线 (一票否决)</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="inline-block h-0.5 w-4 bg-emerald-500 border-b border-dashed border-emerald-500"></span>
          <span class="text-ui-text-2">38% 科技企稳解除线 (右侧安全确认)</span>
        </div>
      </div>
    </div>

    <!-- 3. 策略机制与重大科技避险战纪 -->
    <div class="grid gap-4 lg:grid-cols-2">
      <!-- 策略机制详细说明 -->
      <div class="card rounded-2xl p-4 sm:p-5 space-y-3">
        <h3 class="text-sm font-bold text-ui-text flex items-center gap-2">
          <span>📋</span> 策略三十六 · 运作机制说明
        </h3>
        <ul class="space-y-2 text-xs leading-relaxed text-ui-text-2">
          <li
            v-for="(rule, idx) in effectivePayload?.rules || []"
            :key="idx"
            class="rounded-lg bg-ui-surface/60 p-2 border border-ui-hairline/50"
          >
            {{ rule }}
          </li>
        </ul>
      </div>

      <!-- 历史重大科技避险战纪 -->
      <div class="card rounded-2xl p-4 sm:p-5 space-y-3">
        <h3 class="text-sm font-bold text-ui-text flex items-center gap-2">
          <span>⚔️</span> 科技高 Beta 资产避险实录
        </h3>

        <!-- 回测摘要数据条 -->
        <div class="grid grid-cols-2 gap-2 text-center text-xs">
          <div class="rounded-xl border border-ui-hairline/60 bg-ui-surface/60 p-2.5">
            <div class="text-ui-text-3">全周期科技最大回撤压降</div>
            <div class="mt-1 text-base font-bold text-cyan-400">
              -52.4% → -35.2% (缩减17.2%)
            </div>
          </div>
          <div class="rounded-xl border border-ui-hairline/60 bg-ui-surface/60 p-2.5">
            <div class="text-ui-text-3">2025-2026 样本外盲测回撤</div>
            <div class="mt-1 text-base font-bold text-cyan-400">
              -38.6% → -19.4% (腰斩减损)
            </div>
          </div>
        </div>

        <!-- 历史危机战报明细 -->
        <div class="space-y-2">
          <div
            v-for="b in effectivePayload?.battles || []"
            :key="b.name"
            class="rounded-xl border border-ui-hairline/60 bg-ui-surface/40 p-2.5 text-xs"
          >
            <div class="flex items-center justify-between font-semibold">
              <span class="text-ui-text">{{ b.name }}</span>
              <span class="font-mono text-cyan-400 font-bold">避险超额 {{ b.alpha }}</span>
            </div>
            <div class="mt-1 flex items-center justify-between text-[11px] text-ui-text-3">
              <span>区间: {{ b.period }}</span>
              <span>创业板 {{ b.cyb_ret }} vs 空仓因子 {{ b.cash_ret }}</span>
            </div>
            <p class="mt-1 text-[11px] text-ui-text-2 leading-relaxed">
              {{ b.desc }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
