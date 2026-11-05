<script setup lang="ts">
import * as echarts from 'echarts'
const props = defineProps<{ year: number; month: number; rows: any[] }>()
const el = ref<HTMLElement>()
const indexRows = ref<{ date: string; rate: number }[]>([])
const error = ref('')
let chart: echarts.ECharts | undefined
let observer: ResizeObserver | undefined
let request = 0
async function load() {
  const id = ++request
  indexRows.value = []; error.value = ''
  try {
    const data = await $fetch<{ date: string; rate: number }[]>('/api/holdings/monthly-index', {
      query: { year: props.year, month: props.month },
      cache: 'no-store',
      timeout: 20000
    })
    if (id === request) indexRows.value = data
  } catch { if (id === request) error.value = '上证指数暂时无法读取' }
}
function draw() {
  if (!chart) return
  const prefix = `${props.year}-${String(props.month).padStart(2, '0')}`
  const account = new Map(props.rows.filter(r => String(r.trading_day).startsWith(prefix)).map(r => [String(r.trading_day).slice(0, 10), r]))
  const benchmark = new Map(indexRows.value.map(r => [r.date, r.rate]))
  const dates = [...new Set([...account.keys(), ...benchmark.keys()])].sort()
  let started = false, cumulative = 1, incomplete = false
  const returns = dates.map(d => {
    const rate = account.get(d)?.day_pnl_pct
    if (rate == null || !Number.isFinite(Number(rate))) {
      if (started) incomplete = true
      return null
    }
    started = true
    if (incomplete) return null
    cumulative *= 1 + Number(rate) / 100
    return Number(((cumulative - 1) * 100).toFixed(6))
  })
  chart.setOption({
    color: ['#ef665b', '#608bea'],
    tooltip: { trigger: 'axis', valueFormatter: (v: any) => v == null ? '暂无数据' : `${Number(v).toFixed(2)}%` },
    legend: { data: ['账户当月收益', '上证指数'], textStyle: { color: '#8892a5' } },
    grid: { left: 62, right: 24, top: 48, bottom: 48 },
    xAxis: { type: 'category', data: dates, name: '交易日', nameLocation: 'middle', nameGap: 30, axisLabel: { formatter: (d: string) => d.slice(5) } },
    yAxis: { type: 'value', name: '收益率', axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { opacity: .15 } } },
    series: [
      { name: '账户当月收益', type: 'line', data: returns, connectNulls: false, symbolSize: 6 },
      { name: '上证指数', type: 'line', data: dates.map(d => benchmark.get(d) ?? null), connectNulls: false, showSymbol: false },
    ],
  }, true)
}
watch(() => [props.year, props.month], load)
watch(() => [props.rows, indexRows.value, props.year, props.month], draw, { deep: true })
onMounted(() => { chart = echarts.init(el.value!); observer = new ResizeObserver(() => chart?.resize()); observer.observe(el.value!); draw(); void load() })
onBeforeUnmount(() => { ++request; observer?.disconnect(); chart?.dispose() })
</script>
<template>
  <section class="rounded-xl border border-ui-border p-4 space-y-2">
    <h2 class="font-semibold">{{ year }}年{{ month }}月收益曲线</h2>
    <p class="text-xs text-ui-muted">账户按每日收益率复合累计；上证指数以上月末收盘为基准。缺失交易日收益不补零，账户曲线在缺失后暂停。</p>
    <p v-if="error" class="text-sm text-ui-danger">{{ error }} <button class="underline" @click="load">重试</button></p>
    <div ref="el" class="h-80 w-full" role="img" :aria-label="`${year}年${month}月收益率曲线`" />
  </section>
</template>
