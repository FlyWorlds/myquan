<script setup lang="ts">
import { aggregateReturns as aggregate } from '../utils/returnsCalendar'
const today = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }))
const year = ref(today.getFullYear())
const month = ref(today.getMonth() + 1)
const mode = ref('day')
const percent = ref(false)
const chart = ref(false)
const rows = ref<any[]>([])
const error = ref('')
let request = 0
async function load() {
  const id = ++request; error.value = ''
  try { const data = await $fetch<any[]>('/api/holdings/returns-calendar', { query: { year: year.value }, cache: 'no-store', timeout: 10000 }); if (id === request) rows.value = data }
  catch { if (id === request) { error.value = '收益数据库读取失败，请重试' } }
}
watch(year, load)
let refreshTimer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  void load()
  refreshTimer = setInterval(() => void load(), 5000)
})
onBeforeUnmount(() => {
  ++request
  if (refreshTimer) clearInterval(refreshTimer)
})
const daily = computed(() => new Map(rows.value.map(r => [String(r.trading_day).slice(0, 10), r])))
const cells = computed(() => {
  if (mode.value === 'month') return Array.from({ length: 12 }, (_, i) => ({ label: `${i + 1}月`, ...aggregate(rows.value.filter(r => Number(String(r.trading_day).slice(5, 7)) === i + 1)) }))
  const count = new Date(year.value, month.value, 0).getDate()
  const offset = new Date(year.value, month.value - 1, 1).getDay()
  return Array.from({ length: Math.ceil((count + offset) / 7) * 7 }, (_, i) => {
    const day = i - offset + 1
    const key = `${year.value}-${String(month.value).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    const row = daily.value.get(key)
    return { label: day > 0 && day <= count ? String(day) : '', amount: row?.day_pnl ?? null, rate: row?.day_pnl_pct ?? null, partial: false }
  })
})
const total = computed(() => aggregate(rows.value.filter(r => mode.value === 'month' || Number(String(r.trading_day).slice(5, 7)) === month.value)))
function value(cell: any) { return percent.value ? cell.rate : cell.amount }
function fmt(v: any) { return v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}${percent.value ? '%' : ''}` }
function shift(n: number) { if (mode.value === 'month') year.value += n; else { const d = new Date(year.value, month.value - 1 + n, 1); year.value = d.getFullYear(); month.value = d.getMonth() + 1 } }
</script>
<template>
  <main class="page-shell py-6 space-y-5">
    <h1 class="text-2xl font-bold">账户收益日历</h1>
    <p class="text-sm text-ui-muted">每日最后一条数据库估值快照；当天数据随估值更新。缺失日期不补零，金额为日收益之和，收益率按有效日收益率复合计算；缺少部分日收益率时标注“部分记录”，不代表完整期间收益率。</p>
    <div class="flex flex-wrap gap-3">
      <button class="btn" @click="mode = 'day'">日收益</button><button class="btn" @click="mode = 'month'">月收益</button>
      <button class="btn" @click="percent = !percent">{{ percent ? '切换收益金额' : '切换收益率' }}</button><button class="btn" @click="chart = !chart">{{ chart ? '日历图' : '柱状图' }}</button>
      <button class="btn" @click="shift(-1)">◀</button><span class="p-2 font-bold">{{ year }}年 {{ mode === 'day' ? `${month}月` : '' }}</span><button class="btn" @click="shift(1)">▶</button><button class="btn" @click="load">刷新</button>
    </div>
    <p v-if="error" class="text-ui-danger">{{ error }}</p>
    <p class="text-xl">{{ mode === 'day' ? '本月' : '年度' }}累计：{{ fmt(percent ? total.rate : total.amount) }}<span v-if="percent && total.partial" class="ml-2 text-sm text-ui-muted">（部分记录）</span></p>
    <div v-if="!chart" class="grid gap-1" :style="{ gridTemplateColumns: `repeat(${mode === 'day' ? 7 : 4}, minmax(0,1fr))` }">
      <template v-if="mode === 'day'"><div v-for="d in ['日','一','二','三','四','五','六']" :key="d" class="text-center py-2">{{ d }}</div></template>
      <div v-for="(cell, i) in cells" :key="i" class="min-h-24 p-2 text-center rounded" :style="{ background: value(cell) == null || value(cell) === 0 ? 'transparent' : value(cell) > 0 ? '#f46b60' : '#6c8cdb', color: value(cell) ? 'white' : '' }">
        <div>{{ cell.label }}</div><div v-if="cell.label" class="mt-3 text-xs sm:text-base">{{ fmt(value(cell)) }}<span v-if="percent && cell.partial" class="block text-xs">部分记录</span></div>
      </div>
    </div>
    <div v-else class="space-y-2"><div v-for="(cell, i) in cells.filter(c => c.label)" :key="i" class="flex gap-3 items-center"><span class="w-12">{{ cell.label }}</span><div class="h-5" :style="{ width: `${Math.min(75, Math.abs(Number(value(cell) || 0)) / Math.max(1, ...cells.map(c => Math.abs(Number(value(c) || 0)))) * 75)}%`, background: Number(value(cell)) > 0 ? '#f46b60' : '#6c8cdb' }"/><span>{{ fmt(value(cell)) }}{{ percent && cell.partial ? '（部分记录）' : '' }}</span></div></div>
  </main>
</template>
