<script setup lang="ts">
import * as echarts from 'echarts'

export interface DailyPoint {
  date: string
  total: number
  pnl: number
  pnlPct: number
  dayPnl: number
  drawdown: number // 0 ~ 1
  drawdownVal: number
}

const props = defineProps<{
  dailyPoints: DailyPoint[]
  base: number
  peakEquity: number
  peakDate: string
  maxDrawdown: number
  maxDrawdownVal: number
}>()

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | undefined
let resizeObserver: ResizeObserver | undefined
let themeObserver: MutationObserver | undefined

function isDark(): boolean {
  if (typeof document === 'undefined') return true
  return document.documentElement.getAttribute('data-ui-scheme') !== 'light'
}

function initChart() {
  if (!chartRef.value) return
  if (chart) chart.dispose()

  chart = echarts.init(chartRef.value)
  updateChart()
}

function updateChart() {
  if (!chart || !props.dailyPoints.length) return

  const dark = isDark()
  const dates = props.dailyPoints.map((p) => p.date)
  const totals = props.dailyPoints.map((p) => p.total)
  const drawdowns = props.dailyPoints.map((p) => -(p.drawdown * 100))

  const textColor = dark ? '#9ca3af' : '#6b7280'
  const lineColor = dark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.06)'
  const tooltipBg = dark ? '#1e222b' : '#ffffff'
  const tooltipBorder = dark ? '#374151' : '#e5e7eb'
  const tooltipText = dark ? '#f3f4f6' : '#111827'

  const option: echarts.EChartsOption = {
    animationDuration: 800,
    tooltip: {
      trigger: 'axis',
      backgroundColor: tooltipBg,
      borderColor: tooltipBorder,
      textStyle: { color: tooltipText, fontSize: 12 },
      formatter: (params: any) => {
        if (!Array.isArray(params) || !params.length) return ''
        const idx = params[0].dataIndex
        const pt = props.dailyPoints[idx]
        if (!pt) return ''

        const pnlSign = pt.pnl >= 0 ? '+' : ''
        const dayPnlSign = pt.dayPnl >= 0 ? '+' : ''
        const pnlColor = pt.pnl >= 0 ? '#ff4d4f' : '#22c55e'
        const dayPnlColor = pt.dayPnl >= 0 ? '#ff4d4f' : '#22c55e'

        return `
          <div style="font-weight:600;margin-bottom:6px;border-bottom:1px solid ${lineColor};padding-bottom:4px;">
            ${pt.date}
          </div>
          <div style="display:grid;grid-template-columns:auto auto;gap:4px 16px;font-size:12px;">
            <span>总资产:</span>
            <span style="font-weight:700;text-align:right;">¥${pt.total.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            <span>较30万基准:</span>
            <span style="font-weight:600;color:${pnlColor};text-align:right;">${pnlSign}¥${pt.pnl.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${pnlSign}${pt.pnlPct.toFixed(2)}%)</span>
            <span>当日盈亏:</span>
            <span style="font-weight:600;color:${dayPnlColor};text-align:right;">${dayPnlSign}¥${pt.dayPnl.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            <span>相对峰值回撤:</span>
            <span style="font-weight:600;color:#60a5fa;text-align:right;">-${(pt.drawdown * 100).toFixed(2)}% (-¥${pt.drawdownVal.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })})</span>
          </div>
        `
      },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      lineStyle: { color: dark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.2)', type: 'dashed' },
    },
    grid: [
      { left: 65, right: 30, top: 40, height: '52%' },
      { left: 65, right: 30, top: '70%', height: '20%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLine: { lineStyle: { color: lineColor } },
        axisTick: { show: false },
        axisLabel: {
          color: textColor,
          fontSize: 11,
          formatter: (v: string) => v.slice(5),
        },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLine: { lineStyle: { color: lineColor } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
    ],
    yAxis: [
      {
        gridIndex: 0,
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: lineColor } },
        axisLabel: {
          color: textColor,
          fontSize: 11,
          formatter: (v: number) => `¥${(v / 10000).toFixed(1)}万`,
        },
      },
      {
        gridIndex: 1,
        type: 'value',
        max: 0,
        splitLine: { lineStyle: { color: lineColor } },
        axisLabel: {
          color: textColor,
          fontSize: 10,
          formatter: (v: number) => `${v.toFixed(0)}%`,
        },
      },
    ],
    series: [
      {
        name: '账户总资产',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: totals,
        smooth: 0.15,
        symbol: 'circle',
        symbolSize: 6,
        itemStyle: { color: '#5eead4' },
        lineStyle: { width: 2.5, color: '#5eead4' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(94, 234, 212, 0.28)' },
            { offset: 1, color: 'rgba(94, 234, 212, 0.01)' },
          ]),
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              yAxis: props.base,
              lineStyle: { color: dark ? 'rgba(255, 255, 255, 0.35)' : 'rgba(0, 0, 0, 0.35)', type: 'dashed', width: 1 },
              label: {
                formatter: '30万起步本金',
                position: 'insideStartTop',
                color: textColor,
                fontSize: 10,
              },
            },
          ],
        },
        markPoint: {
          symbol: 'pin',
          symbolSize: 45,
          itemStyle: { color: '#ff4d4f' },
          label: { fontSize: 10, color: '#fff' },
          data: [
            {
              type: 'max',
              name: '历史最高点',
              label: { formatter: '峰值' },
            },
          ],
        },
      },
      {
        name: '回撤幅度',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: drawdowns,
        smooth: 0.1,
        symbol: 'none',
        lineStyle: { width: 1.5, color: '#60a5fa' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(96, 165, 250, 0.05)' },
            { offset: 1, color: 'rgba(96, 165, 250, 0.35)' },
          ]),
        },
      },
    ],
  }

  chart.setOption(option, true)
}

watch(
  () => [props.dailyPoints, props.base, props.peakEquity, props.maxDrawdown],
  () => {
    updateChart()
  },
  { deep: true },
)

onMounted(() => {
  initChart()

  if (chartRef.value) {
    resizeObserver = new ResizeObserver(() => {
      chart?.resize()
    })
    resizeObserver.observe(chartRef.value)
  }

  if (typeof document !== 'undefined') {
    themeObserver = new MutationObserver(() => {
      updateChart()
    })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-ui-scheme'] })
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div class="w-full">
    <div ref="chartRef" class="h-80 w-full" />
    <div class="mt-1 flex items-center justify-between px-3 text-[11px] text-ui-text-3">
      <div class="flex items-center gap-4">
        <span class="inline-flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-[#5eead4]" />
          <span>总资产净值趋势</span>
        </span>
        <span class="inline-flex items-center gap-1.5">
          <span class="h-0.5 w-3 border-b border-dashed border-ui-text-3" />
          <span>30万起步本金基准</span>
        </span>
        <span class="inline-flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-[#60a5fa]" />
          <span>相对峰值回撤幅度 (%)</span>
        </span>
      </div>
      <div v-if="peakDate" class="tabular-nums">
        峰值 {{ peakDate }} (¥{{ peakEquity.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}) · 最大回撤 -{{ (maxDrawdown * 100).toFixed(2) }}%
      </div>
    </div>
  </div>
</template>
