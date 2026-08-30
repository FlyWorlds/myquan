<script setup lang="ts">
import * as echarts from 'echarts'
import type { ConceptDetailPayload } from '~/types/sectors'

const props = defineProps<{
  detail: ConceptDetailPayload
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

function fmtDateShort(d: string) {
  const parts = d.split('-')
  if (parts.length >= 3) return `${parts[0]}.${parts[1]}.${parts[2]}`
  return d
}

function fmtRange(start: string, end: string) {
  const s = fmtDateShort(start)
  const eParts = end.split('-')
  const eShort = eParts.length >= 3 ? `${eParts[1]}.${eParts[2]}` : end
  return `${s} - ${eShort}`
}

function buildOption() {
  const kline = props.detail.kline || []
  const dates = kline.map((b) => b.date)
  const ohlc = kline.map((b) => [b.open, b.close, b.low, b.high])
  const vols = kline.map((b) => b.amount || 0)

  const graphics = (props.detail.segments || []).map((seg, idx) => {
    const x = seg.end_idx
    const y = kline[seg.end_idx]?.high || kline[seg.end_idx]?.close || 0
    const lines = [
      fmtRange(seg.start_date, seg.end_date),
      `${seg.days}日`,
      ...seg.leaders.map((l) => `${l.rank} ${l.name} ${l.return_pct.toFixed(2)}%`),
    ]
    return {
      type: 'group',
      right: 12 + (idx % 2) * 8,
      top: 48 + idx * 92,
      children: [
        {
          type: 'rect',
          shape: { width: 168, height: 12 + lines.length * 16 },
          style: {
            fill: 'rgba(255, 140, 58, 0.92)',
            stroke: 'rgba(255,255,255,0.2)',
            lineWidth: 1,
            shadowBlur: 8,
            shadowColor: 'rgba(0,0,0,0.25)',
          },
        },
        ...lines.map((text, li) => ({
          type: 'text',
          left: 8,
          top: 6 + li * 16,
          style: {
            text,
            fill: li === 0 ? '#fff' : '#fff',
            font: li === 0 ? 'bold 11px sans-serif' : '11px sans-serif',
          },
        })),
      ],
      z: 100,
      // anchor near segment end on chart - use convertToPixel in mounted
      _anchor: { x, y, idx },
    }
  })

  return {
    animation: false,
    grid: [
      { left: 48, right: 16, top: 24, height: '58%' },
      { left: 48, right: 16, top: '72%', height: '18%' },
    ],
    axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false }, gridIndex: 0 },
      { type: 'category', data: dates, boundaryGap: true, gridIndex: 1, axisLabel: { show: false } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { opacity: 0.15 } } },
      { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 40, end: 100 }],
    series: [
      {
        name: props.detail.concept,
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: '#f87171',
          color0: '#34d399',
          borderColor: '#f87171',
          borderColor0: '#34d399',
        },
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(255, 140, 58, 0.08)' },
          data: (props.detail.segments || []).map((seg) => [
            { xAxis: seg.start_date },
            { xAxis: seg.end_date },
          ]),
        },
      },
      {
        name: '成交额',
        type: 'bar',
        data: vols,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: { color: 'rgba(94, 234, 212, 0.45)' },
      },
    ],
    graphic: graphics,
  }
}

function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const option = buildOption()
  chart.setOption(option, true)

  // Position leader boxes near segment peaks
  const opt = chart.getOption() as { graphic?: unknown[] }
  const graphics = (opt.graphic || []) as Array<{ _anchor?: { x: number; y: number; idx: number } }>
  const positioned = graphics.map((g) => {
    const anchor = g._anchor
    if (!anchor || !chart) return g
    const pt = chart.convertToPixel({ seriesIndex: 0 }, [anchor.x, anchor.y])
    if (!Array.isArray(pt)) return g
    const { _anchor, ...rest } = g
    return {
      ...rest,
      position: [Math.min(pt[0] + 8, chartEl.value!.clientWidth - 180), Math.max(24, pt[1] - 40 - anchor.idx * 12)],
    }
  })
  chart.setOption({ graphic: positioned })
}

onMounted(() => {
  render()
  window.addEventListener('resize', render)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', render)
  chart?.dispose()
  chart = null
})

watch(() => props.detail, () => nextTick(render), { deep: true })
</script>

<template>
  <div ref="chartEl" class="concept-kline-chart h-[480px] w-full rounded-xl border border-ui-hairline bg-ui-surface" />
</template>
