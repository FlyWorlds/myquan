<script setup lang="ts">
import * as echarts from 'echarts'
import { baiduStockUrl } from '~/utils/stockLink'
import { fmtNum } from '~/utils/format'
import type { RadarStock, SentimentHistoryItem } from '~/types/marketRadar'

useHead({ title: '短线情绪 · 持仓盯盘' })

const { data, loading, error, refresh } = useMarketRadar()
const query = ref('')
const pool = ref<'sealed' | 'broken'>('sealed')
const board = ref('全部')
const theme = ref('')
const sort = ref('height')

const summary = computed(() => data.value?.summary)
const sentiment = computed(() => data.value?.sentiment)
const historyData = computed(() => data.value?.history || [])

// 连板梯队
const ladder = computed(() => {
  if (sentiment.value?.ladder?.length) {
    return sentiment.value.ladder
  }
  const groups = new Map<number, RadarStock[]>()
  for (const s of data.value?.stocks || []) {
    const h = s.limit_days ?? 1
    if (!groups.has(h)) groups.set(h, [])
    groups.get(h)!.push(s)
  }
  return [...groups.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([h, stks]) => ({
      height: h,
      label: h === 1 ? '首板' : `${h}连板`,
      count: stks.length,
      stocks: stks,
    }))
})

// 梯队与题材共振
const themeResonance = computed(() => {
  return sentiment.value?.theme_resonance || []
})

// 强势股与空间龙【X天X板】
const strongDragons = computed(() => {
  if (sentiment.value?.strong_dragons?.length) {
    return sentiment.value.strong_dragons
  }
  return (data.value?.stocks || []).filter((s) => (s.limit_days ?? 0) >= 2)
})

// 情绪周期、晋级天梯与日内大面
const emotionCycle = computed(() => sentiment.value?.emotion_cycle)
const promotionLadder = computed(() => sentiment.value?.promotion_ladder || [])
const badDrawdownStats = computed(() => sentiment.value?.bad_drawdown_stats)
const showBadApples = ref(false)

// 数据源表格
const sourceRows = computed(() => (pool.value === 'sealed' ? data.value?.stocks || [] : data.value?.broken || []))
const rows = computed(() => {
  return sourceRows.value
    .filter((s) => {
      const height = s.limit_days ?? 1
      const matchBoard =
        board.value === '全部' ||
        (board.value === '首板' && height === 1) ||
        (board.value === '连板' && height >= 2) ||
        (board.value.endsWith('板') && Number.parseInt(board.value) === height)

      const matchTheme = !theme.value || s.themes?.includes(theme.value)
      const keyword = query.value.trim().toLowerCase()
      const matchQuery =
        !keyword ||
        `${s.code} ${s.name} ${s.industry || ''} ${s.reason || ''} ${s.reason_detail || ''} ${s.zt_stat || ''}`
          .toLowerCase()
          .includes(keyword)

      return matchBoard && matchTheme && matchQuery
    })
    .slice()
    .sort((a, b) => {
      if (sort.value === 'change') return (b.pct ?? -Infinity) - (a.pct ?? -Infinity)
      if (sort.value === 'time') return (b.first_seal || b.quote_at || '').localeCompare(a.first_seal || a.quote_at || '')
      return (b.limit_days ?? 0) - (a.limit_days ?? 0) || (b.pct ?? 0) - (a.pct ?? 0)
    })
})

const leadingThemes = computed(() => (data.value?.themes || []).slice(0, 10))
const hasMicrostructure = computed(() => rows.value.some((s) => s.seal_fund_yi != null || s.first_seal != null || s.break_times != null))

function switchPool(value: 'sealed' | 'broken') {
  pool.value = value
  board.value = '全部'
  theme.value = ''
}

function selectTheme(tName: string) {
  theme.value = theme.value === tName ? '' : tName
  pool.value = 'sealed'
}

// 情绪走势图 ECharts 渲染
const chartEl = ref<HTMLElement | null>(null)
let myChart: echarts.ECharts | null = null

function initOrUpdateChart() {
  if (!chartEl.value) return
  if (!myChart) {
    myChart = echarts.init(chartEl.value)
  }
  const hist = historyData.value
  if (!hist || !hist.length) return

  const dates = hist.map((h: SentimentHistoryItem) => h.date.slice(5))
  const sealedList = hist.map((h: SentimentHistoryItem) => h.sealed)
  const downList = hist.map((h: SentimentHistoryItem) => h.down)
  const ratioList = hist.map((h: SentimentHistoryItem) => h.ratio)
  const heightList = hist.map((h: SentimentHistoryItem) => h.max_height)

  myChart.setOption(
    {
      backgroundColor: 'transparent',
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: any) => {
          let s = `<div class="font-bold border-b border-gray-600/50 pb-1 mb-1">${params[0]?.name || ''} 短线情绪快照</div>`
          for (const item of params) {
            const val = item.value != null ? item.value : '—'
            s += `<div class="flex items-center justify-between gap-4 py-0.5 text-xs">
              <span class="inline-flex items-center gap-1.5">${item.marker} ${item.seriesName}</span>
              <span class="font-mono font-bold">${val}</span>
            </div>`
          }
          return s
        },
      },
      legend: {
        data: ['涨停家数', '跌停家数', '涨跌停比', '最高连板'],
        textStyle: { color: '#9ca3af', fontSize: 11 },
        top: 4,
        right: 12,
      },
      grid: { left: 16, right: 36, bottom: 20, top: 40, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#4b5563' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 },
      },
      yAxis: [
        {
          type: 'value',
          name: '涨/跌停家数',
          axisLabel: { color: '#9ca3af', fontSize: 10 },
          splitLine: { lineStyle: { color: 'rgba(75, 85, 99, 0.2)', type: 'dashed' } },
        },
        {
          type: 'value',
          name: '涨跌停比 / 板数',
          position: 'right',
          axisLabel: { color: '#eab308', fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '涨停家数',
          type: 'bar',
          data: sealedList,
          barMaxWidth: 16,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#f87171' },
              { offset: 1, color: '#dc2626' },
            ]),
            borderRadius: [3, 3, 0, 0],
          },
        },
        {
          name: '跌停家数',
          type: 'bar',
          data: downList,
          barMaxWidth: 16,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#34d399' },
              { offset: 1, color: '#059669' },
            ]),
            borderRadius: [3, 3, 0, 0],
          },
        },
        {
          name: '涨跌停比',
          type: 'line',
          yAxisIndex: 1,
          data: ratioList,
          smooth: true,
          lineStyle: { width: 2.2, color: '#eab308' },
          itemStyle: { color: '#eab308' },
          markLine: {
            symbol: ['none', 'none'],
            data: [
              {
                yAxis: 1.0,
                lineStyle: { color: '#ef4444', width: 1.5, type: 'dashed' },
                label: {
                  position: 'insideEndTop',
                  formatter: '1:1 倒挂红线(跌停>涨停)',
                  color: '#f87171',
                  fontSize: 10,
                  backgroundColor: 'rgba(15, 23, 42, 0.85)',
                  padding: [2, 4],
                  borderRadius: 3,
                },
              },
            ],
          },
        },
        {
          name: '最高连板',
          type: 'line',
          yAxisIndex: 1,
          data: heightList,
          smooth: true,
          lineStyle: { width: 1.8, color: '#a855f7', type: 'dotted' },
          itemStyle: { color: '#a855f7' },
        },
      ],
    },
    true,
  )
}

watch(
  () => [historyData.value, data.value?.trade_date],
  () => {
    nextTick(initOrUpdateChart)
  },
  { deep: true },
)

function onResize() {
  myChart?.resize()
}

onMounted(() => {
  nextTick(initOrUpdateChart)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  myChart?.dispose()
  myChart = null
})
</script>

<template>
  <main class="page-shell py-6 space-y-6">
    <!-- 头部说明与操作区 -->
    <header class="flex flex-wrap items-end justify-between gap-4 border-b border-ui-hairline pb-4">
      <div>
        <div class="flex flex-wrap items-center gap-2">
          <p class="text-xs font-semibold tracking-widest text-accent">SHORT-TERM SENTIMENT & DRAGON RADAR</p>
          <span
            v-if="data?.trade_date"
            class="rounded-full bg-ui-surface-2 px-2.5 py-0.5 font-mono text-[11px] text-ui-text-2 border border-ui-hairline font-semibold"
          >
            交易日 {{ data.trade_date }}
          </span>
          <span
            v-if="data?.session_context"
            class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium border"
            :class="{
              'bg-emerald-500/15 border-emerald-500/30 text-emerald-300': data.session_context.phase === 'intraday_live',
              'bg-amber-500/15 border-amber-500/30 text-amber-300': data.session_context.phase === 'pre_market_replay' || data.session_context.phase === 'auction_transition',
              'bg-slate-500/15 border-slate-500/30 text-slate-300': data.session_context.phase === 'post_market_closed',
              'bg-purple-500/15 border-purple-500/30 text-purple-300': data.session_context.phase === 'holiday_closed',
            }"
          >
            <span
              v-if="data.session_context.phase === 'intraday_live'"
              class="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse"
            />
            {{ data.session_context.phase_label }}
          </span>
          <span v-if="data?.fetched_at" class="text-[11px] text-ui-text-3 font-mono">
            更新于 {{ data.fetched_at.slice(11) }}
          </span>
        </div>
        <h1 class="mt-1.5 text-2xl font-bold flex items-center gap-2">
          <span>短线情绪看板</span>
        </h1>
        <p class="mt-1 text-sm text-ui-text-2">
          全景监测连板梯队高度、题材共振主线与情绪周期。严格执行跌停倒挂风控熔断，指引短线开仓纪律。
        </p>
      </div>

      <div class="flex items-center gap-2.5">
        <NuxtLink to="/theme-heat" class="btn text-xs text-ui-text-2 hover:text-accent">
          题材热度 ↗
        </NuxtLink>
        <button
          class="btn inline-flex items-center gap-1.5 text-xs font-semibold text-accent"
          :disabled="loading || data?.refreshing"
          @click="refresh(true)"
        >
          <svg
            v-if="loading || data?.refreshing"
            class="h-3.5 w-3.5 animate-spin text-accent"
            viewBox="0 0 24 24"
            fill="none"
          >
            <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity=".25" />
            <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
          </svg>
          <svg
            v-else
            class="h-3.5 w-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
          </svg>
          <span>{{ loading || data?.refreshing ? '更新中…' : '刷新情绪数据' }}</span>
        </button>
      </div>
    </header>

    <!-- 时间节点把控提示条 -->
    <div
      v-if="data?.session_context?.tip"
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-ui-surface-2/70 border border-ui-hairline px-3.5 py-2 text-xs text-ui-text-2"
    >
      <div class="flex items-center gap-2">
        <span class="font-semibold text-accent">时间节点机制：</span>
        <span>{{ data.session_context.tip }}</span>
      </div>
      <span class="text-[11px] text-ui-text-3 font-mono">
        规则：9:25后实时分笔更新 | 0:00~9:20盘前锁定上一日 | 节假日自动定位上一日
      </span>
    </div>

    <MarketRadarStatus :data="data" :error="error" />

    <!-- 1. 核心风控一票否决警报卡（用户核心诉求：跌停数 > 涨停数，次日禁止开仓） -->
    <div
      class="rounded-xl border p-4 shadow-sm transition-all"
      :class="
        sentiment?.is_down_gt_up
          ? 'border-red-500/50 bg-red-950/25 text-red-100'
          : (sentiment?.risk_level === 'warning'
              ? 'border-amber-500/40 bg-amber-950/20 text-amber-100'
              : 'border-emerald-500/40 bg-emerald-950/20 text-emerald-100')
      "
    >
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-start gap-3">
          <div class="mt-0.5 rounded-lg p-2" :class="sentiment?.is_down_gt_up ? 'bg-red-500/20 text-red-400' : 'bg-emerald-500/20 text-emerald-400'">
            <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path v-if="sentiment?.is_down_gt_up" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              <path v-else d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span
                class="rounded px-2 py-0.5 text-xs font-bold"
                :class="sentiment?.is_down_gt_up ? 'bg-red-500 text-white animate-pulse' : 'bg-emerald-500/30 text-emerald-300'"
              >
                {{ sentiment?.is_down_gt_up ? '核心风控触发 · 一票否决' : '风控放行' }}
              </span>
              <h2 class="text-base font-bold sm:text-lg">
                {{ sentiment?.risk_verdict || (summary?.down && summary?.sealed && summary.down > summary.sealed ? `⚠️ 跌停数(${summary.down}) > 涨停数(${summary.sealed}) · 次日禁止开仓！` : '✓ 短线情绪平稳') }}
              </h2>
            </div>
            <p class="mt-1 text-xs opacity-90 leading-relaxed">
              {{
                sentiment?.is_down_gt_up
                  ? `【硬风控规则】：跌停家数 (${summary?.down ?? 0}家) 已经超越涨停家数 (${summary?.sealed ?? 0}家)，涨跌停比严重倒挂 (${sentiment?.ratio ?? 0}:1)。微观流动性发生挤兑踩踏，短线接力容错极低，次日全天严禁打板或新开仓，全面空仓防守！`
                  : `【赚钱效应健康】：涨停家数 (${summary?.sealed ?? 0}家) 保持对跌停家数 (${summary?.down ?? 0}家) 的压制，涨跌停比维持在 ${sentiment?.ratio ?? '—'}:1，允许围绕主线梯队龙头执行正常操作。`
              }}
            </p>
          </div>
        </div>
        <div class="text-right">
          <div class="text-[11px] text-ui-text-3">当前涨跌停比</div>
          <div
            class="text-2xl font-bold font-mono"
            :class="sentiment?.is_down_gt_up ? 'text-red-400' : 'text-emerald-400'"
          >
            {{ sentiment?.ratio_label || `${summary?.sealed ?? 0}:${summary?.down ?? 0}` }}
          </div>
        </div>
      </div>
    </div>

    <!-- 2. 短线情绪周期定位仪与实战操盘指南 (Market Emotion Cycle Radar) -->
    <section v-if="emotionCycle" class="card rounded-2xl p-4 sm:p-5 relative overflow-hidden border transition-all"
      :class="{
        'border-emerald-500/50 bg-emerald-950/20 shadow-[0_0_20px_rgba(16,185,129,0.12)]': emotionCycle.key === 'freeze',
        'border-amber-500/50 bg-amber-950/20 shadow-[0_0_20px_rgba(245,158,11,0.12)]': emotionCycle.key === 'chaos',
        'border-rose-500/50 bg-rose-950/20 shadow-[0_0_20px_rgba(244,63,94,0.12)]': emotionCycle.key === 'rise',
        'border-purple-500/50 bg-purple-950/20 shadow-[0_0_20px_rgba(168,85,247,0.12)]': emotionCycle.key === 'climax',
      }"
    >
      <div class="flex flex-wrap items-center justify-between gap-4 border-b border-ui-hairline pb-4">
        <div class="flex items-center gap-3">
          <span class="text-3xl select-none">{{ emotionCycle.icon }}</span>
          <div>
            <div class="flex items-center gap-2">
              <span
                class="text-xs font-bold px-2 py-0.5 rounded uppercase tracking-wider"
                :class="{
                  'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40': emotionCycle.key === 'freeze',
                  'bg-amber-500/25 text-amber-300 border border-amber-500/40': emotionCycle.key === 'chaos',
                  'bg-rose-500/25 text-rose-300 border border-rose-500/40': emotionCycle.key === 'rise',
                  'bg-purple-500/25 text-purple-300 border border-purple-500/40': emotionCycle.key === 'climax',
                }"
              >
                情绪周期定位
              </span>
              <h2 class="text-base font-black sm:text-lg text-ui-text">
                {{ emotionCycle.name }}
              </h2>
            </div>
            <p class="mt-0.5 text-xs text-ui-text-3 font-mono">
              量化情绪温度：<span class="font-bold text-accent text-sm">{{ emotionCycle.temperature }}℃</span>
              <span class="text-[11px] text-ui-text-3/80 ml-2">（0℃极寒冰点 · 35℃混沌分歧 · 65℃主升共振 · 100℃亢奋高潮）</span>
            </p>
          </div>
        </div>

        <!-- 操盘建议胶囊 -->
        <div class="flex flex-wrap items-center gap-3">
          <div class="rounded-xl border border-ui-hairline bg-ui-surface-2/70 px-3.5 py-2 text-right">
            <div class="text-[10px] text-ui-text-3 uppercase tracking-wider">建议总仓位上限</div>
            <div
              class="text-sm font-black font-mono"
              :class="emotionCycle.key === 'freeze' ? 'text-emerald-400' : 'text-accent'"
            >
              {{ emotionCycle.suggested_position }}
            </div>
          </div>
          <div class="rounded-xl border border-accent/40 bg-accent/15 px-4 py-2">
            <div class="text-[10px] text-accent font-medium">实战战术指令</div>
            <div class="text-sm font-black text-accent">
              {{ emotionCycle.action_guide }}
            </div>
          </div>
        </div>
      </div>

      <!-- 情绪温度进度条与详细操盘指引 -->
      <div class="mt-4 space-y-3">
        <div>
          <div class="flex items-center justify-between text-[11px] text-ui-text-3 font-mono mb-1.5">
            <span class="text-emerald-400 font-medium">❄️ 极寒冰点 (0℃)</span>
            <span class="text-amber-400 font-medium">🌫️ 混沌分歧 (35℃)</span>
            <span class="text-rose-400 font-medium">🚀 主升共振 (65℃)</span>
            <span class="text-purple-400 font-medium">🌋 极度亢奋 (100℃)</span>
          </div>
          <div class="relative h-2.5 w-full rounded-full bg-ui-surface-2 overflow-hidden border border-ui-hairline">
            <div
              class="h-full rounded-full transition-all duration-700"
              :style="{ width: `${emotionCycle.temperature}%` }"
              :class="{
                'bg-gradient-to-r from-emerald-500 to-teal-400': emotionCycle.key === 'freeze',
                'bg-gradient-to-r from-teal-400 to-amber-400': emotionCycle.key === 'chaos',
                'bg-gradient-to-r from-amber-400 to-rose-500': emotionCycle.key === 'rise',
                'bg-gradient-to-r from-rose-500 to-purple-500': emotionCycle.key === 'climax',
              }"
            />
          </div>
        </div>

        <div class="rounded-xl bg-ui-surface-2/60 border border-ui-hairline p-3 text-xs leading-relaxed text-ui-text-2">
          <span class="font-bold text-accent">【操盘纪律指南】：</span>
          {{ emotionCycle.detail_guide }}
        </div>
      </div>
    </section>

    <!-- 3. 核心情绪六宫格指标卡片 -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <div class="card p-3.5">
        <div class="flex items-center justify-between text-xs text-ui-text-3">
          <span>涨跌停比</span>
          <span class="font-mono text-[10px]">Ratio</span>
        </div>
        <div
          class="mt-2 text-2xl font-bold font-mono"
          :class="(sentiment?.ratio ?? 1) >= 1 ? 'text-up' : 'text-emerald-400'"
        >
          {{ sentiment?.ratio ?? '—' }}
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">
          {{ sentiment?.ratio_label || '—' }}
        </div>
      </div>

      <div class="card p-3.5">
        <div class="flex items-center justify-between text-xs text-ui-text-3">
          <span>封板家数</span>
          <span class="font-mono text-[10px]">Limit Up</span>
        </div>
        <div class="mt-2 text-2xl font-bold font-mono text-up">
          {{ summary?.sealed ?? '—' }} <span class="text-xs font-normal">只</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">
          赚钱效应核心标尺
        </div>
      </div>

      <!-- 跌停家数卡片：数值固定使用醒目翠绿色，倒挂时增加红框预警 -->
      <div
        class="card p-3.5 transition-all"
        :class="sentiment?.is_down_gt_up ? 'border-red-500/60 bg-red-950/20 shadow-[0_0_15px_rgba(239,68,68,0.15)]' : ''"
      >
        <div class="flex items-center justify-between text-xs text-ui-text-3">
          <span class="font-medium">跌停家数</span>
          <span
            v-if="sentiment?.is_down_gt_up"
            class="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-bold text-red-400 border border-red-500/30 animate-pulse"
          >
            倒挂熔断
          </span>
          <span v-else class="font-mono text-[10px]">Limit Down</span>
        </div>
        <div
          class="mt-2 text-2xl font-black font-mono tracking-tight text-emerald-400 drop-shadow-[0_0_10px_rgba(52,211,153,0.35)]"
        >
          {{ summary?.down ?? '—' }} <span class="text-xs font-normal">只</span>
        </div>
        <div
          class="mt-1 text-[11px]"
          :class="sentiment?.is_down_gt_up ? 'text-red-400 font-bold' : 'text-emerald-400/80'"
        >
          {{ sentiment?.is_down_gt_up ? '倒挂超限 · 次日禁开仓' : '跌停风险可控' }}
        </div>
      </div>

      <div class="card p-3.5">
        <div class="flex items-center justify-between text-xs text-ui-text-3">
          <span>炸板率</span>
          <span class="font-mono text-[10px]">Broken Rate</span>
        </div>
        <div class="mt-2 text-2xl font-bold font-mono" :class="(summary?.break_rate ?? 0) > 30 ? 'text-amber-400' : 'text-ui-text'">
          {{ summary?.break_rate == null ? '—' : summary.break_rate + '%' }}
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">
          炸板 {{ summary?.broken ?? '—' }} 只
        </div>
      </div>

      <div class="card p-3.5">
        <div class="flex items-center justify-between text-xs text-ui-text-3">
          <span>最高连板空间</span>
          <span class="font-mono text-[10px]">Max Height</span>
        </div>
        <div class="mt-2 text-2xl font-bold font-mono text-purple-400">
          {{ summary?.max_height == null ? '—' : summary.max_height + '板' }}
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">
          情绪空间压制高度
        </div>
      </div>

      <div class="card p-3.5">
        <div class="flex items-center justify-between text-xs text-ui-text-3">
          <span>连板标的总数</span>
          <span class="font-mono text-[10px]">Lianban</span>
        </div>
        <div class="mt-2 text-2xl font-bold font-mono text-accent">
          {{ strongDragons.length }} <span class="text-xs font-normal">只</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">
          梯队纵深接力池
        </div>
      </div>
    </div>

    <!-- 4. 连板梯队晋级天梯 & 日内大面亏钱效应监控 -->
    <div class="grid gap-4 lg:grid-cols-2">
      <!-- 连板梯队晋级天梯 -->
      <section v-if="promotionLadder.length" class="card p-4 space-y-3">
        <div class="flex items-center justify-between border-b border-ui-hairline pb-3">
          <div class="flex items-center gap-2">
            <span class="rounded bg-accent/20 px-2 py-0.5 text-xs font-bold text-accent">晋级天梯</span>
            <h3 class="text-sm font-semibold text-ui-text">连板晋级率与接力胜率</h3>
          </div>
          <span class="text-xs text-ui-text-3 font-mono">反映短线资金接力意愿</span>
        </div>

        <div class="space-y-2.5">
          <div
            v-for="item in promotionLadder"
            :key="item.stage"
            class="rounded-xl border border-ui-hairline bg-ui-surface-2/40 p-3 space-y-1.5"
          >
            <div class="flex items-center justify-between text-xs">
              <span class="font-bold text-ui-text">{{ item.stage }}</span>
              <div class="flex items-center gap-2">
                <span class="font-mono text-ui-text-3">{{ item.count }} 只晋级</span>
                <span
                  class="rounded px-2 py-0.5 font-mono text-xs font-bold"
                  :class="item.rate_pct >= 25 ? 'bg-rose-500/20 text-rose-300' : 'bg-ui-surface text-ui-text-2 border border-ui-hairline'"
                >
                  晋级率 {{ item.rate_pct }}%
                </span>
              </div>
            </div>
            <div class="flex flex-wrap gap-1.5 pt-1">
              <span
                v-for="stk in item.stocks"
                :key="stk"
                class="rounded bg-ui-page px-2 py-0.5 text-[11px] font-mono text-ui-text-2 border border-ui-hairline"
              >
                {{ stk }}
              </span>
              <span v-if="!item.stocks.length" class="text-[11px] text-ui-text-3 italic">暂无在榜晋级标的</span>
            </div>
            <div class="text-[11px] text-ui-text-3">{{ item.desc }}</div>
          </div>
        </div>
      </section>

      <!-- 日内大面与亏钱效应监控 -->
      <section v-if="badDrawdownStats" class="card p-4 space-y-3">
        <div class="flex items-center justify-between border-b border-ui-hairline pb-3">
          <div class="flex items-center gap-2">
            <span class="rounded bg-emerald-500/20 px-2 py-0.5 text-xs font-bold text-emerald-300">亏钱效应</span>
            <h3 class="text-sm font-semibold text-ui-text">日内大面与炸板踩踏监控</h3>
          </div>
          <button
            class="text-xs text-accent hover:underline inline-flex items-center gap-1"
            @click="showBadApples = !showBadApples"
          >
            {{ showBadApples ? '收起大面榜 ▲' : '查看大面恶性榜 ▼' }}
          </button>
        </div>

        <div class="grid grid-cols-3 gap-2 text-center">
          <div class="rounded-xl border border-ui-hairline bg-ui-surface-2/40 p-2.5">
            <div class="text-[10px] text-ui-text-3">冲高回落>7%大面</div>
            <div class="mt-1 font-mono text-lg font-bold text-emerald-400">
              {{ badDrawdownStats.big_drawdown_count }} <span class="text-xs font-normal">只</span>
            </div>
          </div>
          <div class="rounded-xl border border-ui-hairline bg-ui-surface-2/40 p-2.5">
            <div class="text-[10px] text-ui-text-3">炸板大面率</div>
            <div class="mt-1 font-mono text-lg font-bold" :class="badDrawdownStats.big_drawdown_rate >= 30 ? 'text-emerald-400' : 'text-ui-text'">
              {{ badDrawdownStats.big_drawdown_rate }}%
            </div>
          </div>
          <div class="rounded-xl border border-ui-hairline bg-ui-surface-2/40 p-2.5">
            <div class="text-[10px] text-ui-text-3">恶性核按钮(>13%)</div>
            <div class="mt-1 font-mono text-lg font-bold" :class="badDrawdownStats.severe_drawdown_count > 0 ? 'text-emerald-400 animate-pulse' : 'text-ui-text-3'">
              {{ badDrawdownStats.severe_drawdown_count }} <span class="text-xs font-normal">只</span>
            </div>
          </div>
        </div>

        <!-- 恶性大面个股列表折叠区 -->
        <div v-if="showBadApples && badDrawdownStats.top_bad_apples.length" class="space-y-1.5 pt-1">
          <div class="text-[11px] font-semibold text-ui-text-3">日内最大回落恶性砸盘榜：</div>
          <div class="max-h-60 overflow-y-auto space-y-1.5 pr-1">
            <div
              v-for="stk in badDrawdownStats.top_bad_apples"
              :key="stk.code"
              class="flex items-center justify-between rounded-lg border border-ui-hairline bg-ui-page px-3 py-1.5 text-xs"
            >
              <div class="flex items-center gap-2">
                <a :href="baiduStockUrl(stk.code, stk.name)" target="_blank" class="font-bold hover:text-accent">{{ stk.name }}</a>
                <span class="font-mono text-[10px] text-ui-text-3">{{ stk.code }}</span>
                <span v-if="stk.is_severe" class="rounded bg-emerald-500/20 px-1 text-[9px] font-bold text-emerald-300">重度面</span>
              </div>
              <div class="flex items-center gap-3 font-mono">
                <span class="text-ui-text-3">炸板{{ stk.break_times || 1 }}次</span>
                <span class="text-ui-text-3">换手{{ stk.turnover ? `${fmtNum(stk.turnover, 1)}%` : '—' }}</span>
                <span class="text-emerald-400 font-bold">回落 -{{ stk.drawdown }}%</span>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="text-[11px] text-ui-text-3 leading-relaxed">
          ※ 市场短线退潮往往以“炸板大面”为第一信号。当冲高回落大面股激增时，次日极易在竞价发生核按钮踩踏。
        </div>
      </section>
    </div>

    <!-- 3. 涨停家数 & 跌停家数 K 线/走势图表 -->
    <section class="card rounded-2xl p-4 sm:p-5">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-accent/20 px-2 py-0.5 text-xs font-bold text-accent">情绪时序</span>
          <h2 class="text-sm font-bold text-ui-text">涨停 / 跌停家数双轴走势与情绪周期</h2>
        </div>
        <div class="flex items-center gap-3 text-xs text-ui-text-3">
          <span class="inline-flex items-center gap-1.5">
            <span class="h-2 w-2 rounded-full bg-red-500"></span> 涨停家数(红柱)
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="h-2 w-2 rounded-full bg-emerald-500"></span> 跌停家数(绿柱)
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="h-1.5 w-3 bg-yellow-500 rounded"></span> 涨跌停比(折线)
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="h-1.5 w-3 bg-purple-500 rounded"></span> 最高板(虚线)
          </span>
        </div>
      </div>

      <div class="mt-4 h-64 sm:h-72 w-full">
        <div ref="chartEl" class="h-full w-full" />
      </div>
      <p class="mt-2 text-[11px] text-ui-text-3 border-t border-ui-hairline/60 pt-2">
        ※ 红色虚线为 1:1 倒挂分水岭。当金色涨跌停比折线跌落至 1.0 下方时（跌停数 > 涨停数），确立短线极度冰点溃退，触发次日严禁开仓风控。
      </p>
    </section>

    <!-- 4. 连板梯度 (梯队晋级与分布) -->
    <section class="card p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-purple-500/20 px-2 py-0.5 text-xs font-bold text-purple-300">连板梯度</span>
          <h2 class="text-sm font-semibold">梯队晋级全景结构</h2>
        </div>
        <span class="text-xs text-ui-text-3">点击对应高度可快速高亮下方明细</span>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div
          v-for="item in ladder"
          :key="item.height"
          class="rounded-xl border p-3 cursor-pointer transition hover:border-accent hover:bg-ui-fill-hover"
          :class="board === (item.height === 1 ? '首板' : `${item.height}板`) ? 'border-accent bg-accent/15' : 'border-ui-hairline bg-ui-surface-2/40'"
          @click="board = board === (item.height === 1 ? '首板' : `${item.height}板`) ? '全部' : (item.height === 1 ? '首板' : `${item.height}板`); pool = 'sealed'"
        >
          <div class="flex items-center justify-between">
            <span class="font-bold text-sm" :class="item.height >= 3 ? 'text-rose-400' : (item.height === 2 ? 'text-amber-300' : 'text-ui-text')">
              {{ item.label }}
            </span>
            <span class="rounded bg-ui-surface px-2 py-0.5 font-mono text-xs font-bold text-accent border border-ui-hairline">
              {{ item.count }} 只
            </span>
          </div>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <span
              v-for="stk in (item.stocks || []).slice(0, 4)"
              :key="stk.code"
              class="rounded bg-ui-page px-1.5 py-0.5 text-[11px] font-mono text-ui-text-2 border border-ui-hairline"
            >
              {{ stk.name }}
            </span>
            <span v-if="(item.stocks?.length || 0) > 4" class="text-[10px] text-ui-text-3 self-center">
              +{{ (item.stocks?.length || 0) - 4 }}只
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- 5. 梯度题材关系与共振矩阵 -->
    <section class="card p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-amber-500/20 px-2 py-0.5 text-xs font-bold text-amber-300">题材共振</span>
          <h2 class="text-sm font-semibold">梯度题材关系与共振评级</h2>
        </div>
        <NuxtLink to="/theme-heat" class="text-xs text-accent hover:underline">
          查看全部题材热度 ↗
        </NuxtLink>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="t in themeResonance"
          :key="t.name"
          class="rounded-xl border border-ui-hairline bg-ui-surface-2/40 p-3.5 space-y-2 hover:border-accent transition cursor-pointer"
          :class="theme === t.name ? 'border-accent bg-accent/15' : ''"
          @click="selectTheme(t.name)"
        >
          <div class="flex items-center justify-between">
            <span class="font-bold text-sm text-ui-text hover:text-accent">{{ t.name }}</span>
            <span
              class="rounded px-2 py-0.5 text-[10px] font-bold"
              :class="t.resonance_tag === 'high' ? 'bg-red-500/25 text-red-300 border border-red-500/40' : (t.resonance_tag === 'medium' ? 'bg-amber-500/25 text-amber-300 border border-amber-500/40' : 'bg-ui-surface text-ui-text-3 border border-ui-hairline')"
            >
              {{ t.resonance_level }}
            </span>
          </div>

          <div class="flex items-center justify-between text-xs text-ui-text-3 font-mono">
            <span>涨停总数: <b class="text-accent">{{ t.count }}</b> 只</span>
            <span>最高板: <b class="text-rose-400">{{ t.max_height }}</b> 板</span>
          </div>

          <p class="text-[11px] text-ui-text-3 leading-relaxed">
            {{ t.resonance_desc }}
          </p>

          <div class="flex flex-wrap gap-1 pt-1 border-t border-ui-hairline/60">
            <span
              v-for="s in (t.stocks || []).slice(0, 3)"
              :key="s.code"
              class="rounded bg-ui-page px-1.5 py-0.5 text-[10px] text-ui-text-2 border border-ui-hairline"
            >
              {{ s.name }} ({{ s.limit_days || 1 }}板)
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- 6. 强势股【X天X板】与空间龙追踪专区 -->
    <section v-if="strongDragons.length" class="card p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-rose-500/20 px-2 py-0.5 text-xs font-bold text-rose-300">空间龙头</span>
          <h2 class="text-sm font-semibold">强势股【X天X板】龙虎追踪</h2>
        </div>
        <span class="text-xs text-ui-text-3">共 {{ strongDragons.length }} 只连板 / 高度标的</span>
      </div>

      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <div
          v-for="s in strongDragons"
          :key="s.code"
          class="rounded-xl border border-ui-hairline bg-ui-surface-2/40 p-3 space-y-2 hover:border-rose-500/60 transition"
        >
          <div class="flex items-start justify-between">
            <div>
              <a
                :href="baiduStockUrl(s.code, s.name)"
                target="_blank"
                rel="noopener"
                class="font-bold text-base hover:text-accent"
              >
                {{ s.name }}
              </a>
              <div class="text-xs font-mono text-ui-text-3">{{ s.code }}</div>
            </div>
            <!-- X天X板徽章 -->
            <span
              class="rounded-lg bg-rose-500/20 border border-rose-500/50 px-2 py-0.5 text-xs font-bold font-mono text-rose-400"
            >
              {{ s.zt_stat || (s.limit_days ? `${s.limit_days}连板` : '首板') }}
            </span>
          </div>

          <div class="flex items-baseline justify-between text-xs">
            <span class="font-mono text-base font-bold tabular-nums">{{ fmtNum(s.price, 2) }}</span>
            <span class="text-up font-bold font-mono">{{ s.pct == null ? '—' : `+${fmtNum(s.pct, 2)}%` }}</span>
          </div>

          <div class="grid grid-cols-2 gap-1 text-[11px] text-ui-text-3 border-t border-ui-hairline/60 pt-2 font-mono">
            <div>封单: <b class="text-ui-text">{{ s.seal_fund_yi != null ? `${fmtNum(s.seal_fund_yi, 2)}亿` : '—' }}</b></div>
            <div>首封: <b class="text-ui-text">{{ s.first_seal || '—' }}</b></div>
          </div>

          <div v-if="s.reason" class="text-[11px] text-ui-text-2 line-clamp-1">
            <span class="text-accent font-medium">题材：</span>{{ s.reason }}
          </div>
        </div>
      </div>
    </section>

    <!-- 7. 全量涨停池与炸板跟踪明细 -->
    <section class="card overflow-hidden">
      <div class="space-y-3 border-b border-ui-hairline p-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex gap-2">
            <button
              class="btn"
              :class="pool === 'sealed' ? 'btn-primary text-accent font-bold' : ''"
              @click="switchPool('sealed')"
            >
              已封板 {{ summary?.sealed ?? '—' }}
            </button>
            <button
              class="btn"
              :class="pool === 'broken' ? 'btn-primary text-amber-300 font-bold' : ''"
              @click="switchPool('broken')"
            >
              炸板跟踪 {{ summary?.broken ?? '—' }}
            </button>
          </div>
          <span class="text-xs text-ui-text-3">显示 {{ rows.length }} / {{ sourceRows.length }} 只标的</span>
        </div>

        <div class="flex flex-wrap gap-2">
          <input
            v-model="query"
            class="min-w-60 flex-1 rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm"
            placeholder="搜索股票代码、名称、题材标签或涨停原因"
            aria-label="搜索股票"
          />
          <select v-model="board" class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm" aria-label="连板筛选">
            <option>全部</option>
            <option>首板</option>
            <option>连板</option>
            <option v-for="item in ladder.filter((l) => l.height > 1)" :key="item.height">
              {{ item.height }}板
            </option>
          </select>
          <select v-model="sort" class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm" aria-label="排序方式">
            <option value="height">连板高度优先</option>
            <option value="change">涨幅优先</option>
            <option value="time">首次封板时间优先</option>
          </select>
          <button
            v-if="query || theme || board !== '全部'"
            class="btn text-ui-text-2 hover:text-accent"
            @click="query = ''; theme = ''; board = '全部'"
          >
            清除筛选{{ theme ? ' · ' + theme : '' }}
          </button>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-ui-hairline text-xs text-ui-text-2">
            <tr>
              <th class="whitespace-nowrap p-4">标的 / X天X板</th>
              <th class="whitespace-nowrap p-3">现价 / 涨跌幅</th>
              <th class="min-w-80 p-3">涨停题材与详细归因</th>
              <th class="whitespace-nowrap p-3">首封 / 记录时间</th>
              <th v-if="hasMicrostructure" class="whitespace-nowrap p-3">封单 / 炸板</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ui-hairline">
            <tr v-for="s in rows" :key="s.code" class="align-top hover:bg-ui-fill-hover">
              <td class="whitespace-nowrap p-4">
                <a
                  :href="baiduStockUrl(s.code, s.name)"
                  target="_blank"
                  rel="noopener"
                  class="font-semibold text-base hover:text-accent"
                >
                  {{ s.name }}
                </a>
                <div class="mt-1 flex items-center gap-2">
                  <span class="font-mono text-xs text-ui-text-3">{{ s.code }}</span>
                  <!-- X天X板 / 连板高度 -->
                  <span
                    v-if="s.zt_stat || s.limit_days"
                    class="rounded px-1.5 py-0.5 text-xs font-bold font-mono"
                    :class="(s.limit_days ?? 1) >= 2 ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40' : 'bg-accent/15 text-accent'"
                  >
                    {{ s.zt_stat || (s.limit_days === 1 ? '首板' : `${s.limit_days}连板`) }}
                  </span>
                </div>
              </td>
              <td class="whitespace-nowrap p-3">
                <div class="font-semibold font-mono tabular-nums text-base">{{ fmtNum(s.price, 2) }}</div>
                <div class="mt-1 text-xs">
                  <ChgText :chg="s.pct">
                    {{ s.pct == null ? '—' : (s.pct > 0 ? '+' : '') + fmtNum(s.pct, 2) + '%' }}
                  </ChgText>
                </div>
              </td>
              <td class="p-3">
                <div v-if="s.themes?.length" class="mb-2 flex flex-wrap gap-1.5">
                  <button
                    v-for="tag in s.themes"
                    :key="tag"
                    class="rounded border border-ui-hairline px-2 py-0.5 text-xs text-accent transition hover:bg-accent/15"
                    @click="theme = theme === tag ? '' : tag"
                  >
                    {{ tag }}
                  </button>
                </div>
                <p v-else class="text-xs text-ui-text-3">数据源暂无题材标签</p>
                <details v-if="s.reason_detail" class="mt-1 text-xs leading-6 text-ui-text-2">
                  <summary class="cursor-pointer">
                    <span class="ml-1">{{ s.reason_detail.slice(0, 80) }}{{ s.reason_detail.length > 80 ? '…' : '' }}</span>
                    <span class="ml-2 text-accent">展开详细归因</span>
                  </summary>
                  <p class="mt-2 whitespace-pre-line rounded-lg bg-ui-page p-3 border border-ui-hairline">
                    {{ s.reason_detail }}
                  </p>
                </details>
                <p v-else-if="s.reason" class="mt-1 text-xs text-ui-text-3">{{ s.reason }}</p>
                <p v-if="s.industry" class="mt-1 text-[11px] text-ui-text-3">行业 · {{ s.industry }}</p>
              </td>
              <td class="whitespace-nowrap p-3 font-mono text-xs text-ui-text-2">
                <div>首封: <b class="text-ui-text">{{ s.first_seal || '—' }}</b></div>
                <div class="text-[10px] text-ui-text-3 mt-1">{{ s.quote_at?.slice(11) || '—' }}</div>
              </td>
              <td v-if="hasMicrostructure" class="whitespace-nowrap p-3 text-xs leading-6 text-ui-text-2">
                <p>封单 <b class="text-ui-text font-mono">{{ fmtNum(s.seal_fund_yi, 3) }}</b> 亿</p>
                <p>炸板 <b class="text-amber-400 font-mono">{{ s.break_times ?? 0 }}</b> 次</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="!rows.length" class="px-4 py-12 text-center text-sm text-ui-text-2">
        {{ !data?.trade_date ? '实时数据暂不可用，正在尝试更新' : '当前筛选下暂无股票，可清除筛选查看完整列表' }}
      </p>
      <p class="border-t border-ui-hairline p-4 text-xs leading-relaxed text-ui-text-3">
        ※ 短线情绪看板整合了连板梯队、题材共振主线与涨跌停比。当全市场跌停数超过涨停数时，触发一票否决硬纪律，次日禁止开仓。
      </p>
    </section>
  </main>
</template>
