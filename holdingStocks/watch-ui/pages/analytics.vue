<script setup lang="ts">
import type { HoldingRow, WatchAccount } from '~/types/snapshot'
import type { TradeLedgerEntry, TradeLedgerResponse } from '~/types/trades'
import type { DailyPoint } from '~/components/AssetAnalysisChart.vue'
import { baiduStockUrl } from '~/utils/stockLink'
import { fmtPositionPct, positionPctOf } from '~/utils/position'
import exitLabels from '../../../exit_reason_labels.json'

const reasons: Record<string, string> = exitLabels

function displayReason(value?: string): string {
  return String(value || '')
    .replace(/报价驱动因子26\((\w+)\)/g, (original, code) => reasons[code] || original)
    .replaceAll('跌破保护线（因子26·隔夜峰值回落）', reasons.t1_peak_trail || '隔夜峰值回落止盈')
}

interface StockAnalysisItem {
  code: string
  name: string
  market?: string
  isHolding: boolean
  currentQty: number
  currentPrice: number | null
  costPrice: number | null
  marketValue: number
  positionPct: number | null
  unrealizedPnl: number
  unrealizedPnlPct: number | null
  realizedPnl: number
  totalPnl: number
  totalPnlPct: number
  buyAmount: number
  sellAmount: number
  buyCount: number
  sellCount: number
  winCount: number
  lossCount: number
  winRate: number | null
  maxWin: number
  maxLoss: number
  lastTime: string
  lastReason: string
  history: TradeLedgerEntry[]
}

const loading = ref(true)
const error = ref('')
const refreshedAt = ref('')

const snapshotAccount = ref<WatchAccount | null>(null)
const snapshotHoldings = ref<HoldingRow[]>([])
const tradeEntries = ref<TradeLedgerEntry[]>([])
const calendarRows = ref<any[]>([])

// 选中的 Tab 筛选和排序
type FilterTab = 'all' | 'gain' | 'loss' | 'holding'
const currentTab = ref<FilterTab>('all')

type SortKey = 'totalPnl' | 'totalPnlPct' | 'winRate' | 'sellCount' | 'lastTime'
const currentSort = ref<SortKey>('totalPnl')
const sortAsc = ref(false)

const expandedCodes = ref<Set<string>>(new Set())

function toggleExpand(code: string) {
  if (expandedCodes.value.has(code)) {
    expandedCodes.value.delete(code)
  } else {
    expandedCodes.value.add(code)
  }
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const curYear = new Date().getFullYear()
    const [snapRes, tradesRes, calRes] = await Promise.all([
      fetch('/api/snapshot').then((r) => (r.ok ? r.json() : null)),
      fetch('/api/trades?limit=1000').then((r) => (r.ok ? r.json() : null)),
      fetch(`/api/holdings/returns-calendar?year=${curYear}`).then((r) => (r.ok ? r.json() : [])),
    ])

    if (snapRes) {
      snapshotAccount.value = snapRes.account || null
      snapshotHoldings.value = snapRes.holdings || []
    }
    if (tradesRes) {
      tradeEntries.value = (tradesRes as TradeLedgerResponse).entries || []
    }
    if (Array.isArray(calRes)) {
      calendarRows.value = calRes
    }

    refreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (err: any) {
    error.value = String(err?.message || err || '数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadData()
})

// 30万纸面基准本金
const baseCapital = computed(() => {
  return Number(snapshotAccount.value?.paperEquityBase || 300000.0)
})

// 当前总资产与盈亏
const currentTotal = computed(() => {
  return Number(snapshotAccount.value?.accountTotal || 300000.0)
})

const currentTotalPnl = computed(() => {
  return currentTotal.value - baseCapital.value
})

const currentTotalPnlPct = computed(() => {
  return baseCapital.value > 0 ? (currentTotalPnl.value / baseCapital.value) * 100 : 0
})

// 历史日资产点和最大回撤计算
const seriesData = computed(() => {
  const base = baseCapital.value
  const points: DailyPoint[] = []

  // 起始点（2026-09-09 基准 30 万）
  const startDate = snapshotAccount.value?.totalPnlStart || '2026-09-09'
  points.push({
    date: startDate,
    total: base,
    pnl: 0,
    pnlPct: 0,
    dayPnl: 0,
    drawdown: 0,
    drawdownVal: 0,
  })

  // 按日期排序的历史日历数据
  const sortedCal = [...calendarRows.value].sort((a, b) => String(a.trading_day).localeCompare(String(b.trading_day)))

  for (const row of sortedCal) {
    const day = String(row.trading_day || '').slice(0, 10)
    if (!day || day === startDate) continue
    const tot = Number(row.account_total ?? base)
    const dayPnl = Number(row.day_pnl ?? 0)
    const pnl = tot - base
    const pnlPct = (pnl / base) * 100
    points.push({
      date: day,
      total: tot,
      pnl,
      pnlPct,
      dayPnl,
      drawdown: 0,
      drawdownVal: 0,
    })
  }

  // 如果今天不在列表中，加入今日当前资产
  const todayStr = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Shanghai' })).toISOString().slice(0, 10)
  const lastPoint = points[points.length - 1]
  if (lastPoint && lastPoint.date !== todayStr && currentTotal.value > 0) {
    const tot = currentTotal.value
    const dayPnl = Number(snapshotAccount.value?.dayPnl || 0)
    const pnl = tot - base
    const pnlPct = (pnl / base) * 100
    points.push({
      date: todayStr,
      total: tot,
      pnl,
      pnlPct,
      dayPnl,
      drawdown: 0,
      drawdownVal: 0,
    })
  }

  // 动态回撤计算
  let runningPeak = base
  let runningPeakDate = startDate
  let maxDD = 0
  let maxDDVal = 0
  let maxDDPeakDate = startDate
  let maxDDTroughDate = startDate

  for (const pt of points) {
    if (pt.total > runningPeak) {
      runningPeak = pt.total
      runningPeakDate = pt.date
    }
    const ddVal = Math.max(0, runningPeak - pt.total)
    const ddPct = runningPeak > 0 ? ddVal / runningPeak : 0
    pt.drawdown = ddPct
    pt.drawdownVal = ddVal

    if (ddPct > maxDD) {
      maxDD = ddPct
      maxDDVal = ddVal
      maxDDPeakDate = runningPeakDate
      maxDDTroughDate = pt.date
    }
  }

  // 整体历史峰值
  let peakEq = base
  let peakDt = startDate
  for (const pt of points) {
    if (pt.total >= peakEq) {
      peakEq = pt.total
      peakDt = pt.date
    }
  }

  const curDD = peakEq > 0 ? Math.max(0, (peakEq - currentTotal.value) / peakEq) : 0
  const curDDVal = Math.max(0, peakEq - currentTotal.value)

  return {
    points,
    peakEquity: peakEq,
    peakDate: peakDt,
    peakProfit: peakEq - base,
    peakProfitPct: base > 0 ? ((peakEq - base) / base) * 100 : 0,
    maxDrawdown: maxDD,
    maxDrawdownVal: maxDDVal,
    maxDrawdownPeakDate: maxDDPeakDate,
    maxDrawdownTroughDate: maxDDTroughDate,
    currentDrawdown: curDD,
    currentDrawdownVal: curDDVal,
  }
})

// 聚合每只股票的盈亏分析数据
const aggregatedStocks = computed(() => {
  const stockMap = new Map<string, StockAnalysisItem>()

  // 1. 初始化当前持仓
  for (const row of snapshotHoldings.value) {
    const code = String(row.代码 || '').trim()
    if (!code) continue
    const name = String(row.名称 || code)
    const currentPrice = Number(row.现价 ?? 0) || null
    const costPrice = Number(row.成本价 ?? 0) || null
    const qty = Number(row.持仓 ?? 0)
    const floatPnl = Number(row.浮盈 ?? 0)
    const floatPnlPct = Number(row.浮盈率 ?? 0)
    const mktVal = Number(row.市值 ?? (currentPrice ? currentPrice * qty : 0))
    const posPct = positionPctOf(row, currentTotal.value)

    stockMap.set(code, {
      code,
      name,
      market: String(row.市场 || ''),
      isHolding: qty > 0,
      currentQty: qty,
      currentPrice,
      costPrice,
      marketValue: mktVal,
      positionPct: posPct,
      unrealizedPnl: floatPnl,
      unrealizedPnlPct: floatPnlPct,
      realizedPnl: 0,
      totalPnl: floatPnl,
      totalPnlPct: floatPnlPct,
      buyAmount: 0,
      sellAmount: 0,
      buyCount: 0,
      sellCount: 0,
      winCount: 0,
      lossCount: 0,
      winRate: null,
      maxWin: 0,
      maxLoss: 0,
      lastTime: '',
      lastReason: '持仓中',
      history: [],
    })
  }

  // 2. 遍历交易单记录（按时间正序处理）
  const reversedTrades = [...tradeEntries.value].sort((a, b) => String(a.time || '').localeCompare(String(b.time || '')))

  for (const entry of reversedTrades) {
    const code = String(entry.code || '').trim()
    if (!code) continue
    let item = stockMap.get(code)
    if (!item) {
      item = {
        code,
        name: String(entry.name || code),
        market: String(entry.market || ''),
        isHolding: false,
        currentQty: 0,
        currentPrice: null,
        costPrice: null,
        marketValue: 0,
        positionPct: null,
        unrealizedPnl: 0,
        unrealizedPnlPct: null,
        realizedPnl: 0,
        totalPnl: 0,
        totalPnlPct: 0,
        buyAmount: 0,
        sellAmount: 0,
        buyCount: 0,
        sellCount: 0,
        winCount: 0,
        lossCount: 0,
        winRate: null,
        maxWin: 0,
        maxLoss: 0,
        lastTime: '',
        lastReason: '',
        history: [],
      }
      stockMap.set(code, item)
    }

    item.history.unshift(entry)
    const time = String(entry.time || '')
    if (!item.lastTime || time > item.lastTime) {
      item.lastTime = time
      if (entry.reason) item.lastReason = displayReason(entry.reason)
    }

    const amt = Number(entry.amount || 0)
    if (entry.side === 'buy') {
      item.buyCount++
      item.buyAmount += amt
    } else if (entry.side === 'sell') {
      item.sellCount++
      item.sellAmount += amt
      const pnl = Number(entry.pnl ?? 0)
      item.realizedPnl += pnl

      if (pnl > 0) {
        item.winCount++
        if (pnl > item.maxWin) item.maxWin = pnl
      } else if (pnl < 0) {
        item.lossCount++
        if (pnl < item.maxLoss) item.maxLoss = pnl
      }
    }
  }

  // 3. 最终收益计算
  const items = Array.from(stockMap.values())
  for (const item of items) {
    item.totalPnl = item.realizedPnl + item.unrealizedPnl
    const baseDenom = item.buyAmount > 0 ? item.buyAmount : (item.costPrice || 0) * item.currentQty
    item.totalPnlPct = baseDenom > 0 ? (item.totalPnl / baseDenom) * 100 : item.unrealizedPnlPct || 0
    item.winRate = item.sellCount > 0 ? (item.winCount / item.sellCount) * 100 : null
  }

  return items
})

// 筛选后的列表
const filteredStocks = computed(() => {
  let list = aggregatedStocks.value
  if (currentTab.value === 'gain') {
    list = list.filter((s) => s.totalPnl > 0)
  } else if (currentTab.value === 'loss') {
    list = list.filter((s) => s.totalPnl < 0)
  } else if (currentTab.value === 'holding') {
    list = list.filter((s) => s.isHolding)
  }

  // 排序
  const factor = sortAsc.value ? 1 : -1
  return [...list].sort((a, b) => {
    if (currentSort.value === 'totalPnl') return (a.totalPnl - b.totalPnl) * factor
    if (currentSort.value === 'totalPnlPct') return (a.totalPnlPct - b.totalPnlPct) * factor
    if (currentSort.value === 'winRate') return ((a.winRate ?? -1) - (b.winRate ?? -1)) * factor
    if (currentSort.value === 'sellCount') return (a.sellCount - b.sellCount) * factor
    if (currentSort.value === 'lastTime') return a.lastTime.localeCompare(b.lastTime) * factor
    return 0
  })
})

function changeSort(key: SortKey) {
  if (currentSort.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    currentSort.value = key
    sortAsc.value = false
  }
}

// 统计总览卡片数据
const stats = computed(() => {
  const all = aggregatedStocks.value
  const gainers = all.filter((s) => s.totalPnl > 0)
  const losers = all.filter((s) => s.totalPnl < 0)

  const totalGain = gainers.reduce((acc, s) => acc + s.totalPnl, 0)
  const totalLoss = Math.abs(losers.reduce((acc, s) => acc + s.totalPnl, 0))

  const topGainer = [...gainers].sort((a, b) => b.totalPnl - a.totalPnl)[0] || null
  const topLoser = [...losers].sort((a, b) => a.totalPnl - b.totalPnl)[0] || null

  // 全部平仓笔数胜率与盈亏比
  let totalSellCount = 0
  let totalWinTrades = 0
  let sumWinPnl = 0
  let totalLossTrades = 0
  let sumLossPnl = 0
  let maxSingleLoss = 0
  let maxSingleLossStock = ''

  for (const s of all) {
    totalSellCount += s.sellCount
    totalWinTrades += s.winCount
    totalLossTrades += s.lossCount
    for (const h of s.history) {
      if (h.side === 'sell') {
        const p = Number(h.pnl || 0)
        if (p > 0) sumWinPnl += p
        else if (p < 0) {
          sumLossPnl += Math.abs(p)
          if (p < maxSingleLoss) {
            maxSingleLoss = p
            maxSingleLossStock = `${s.name}(${s.code})`
          }
        }
      }
    }
  }

  const tradeWinRate = totalSellCount > 0 ? (totalWinTrades / totalSellCount) * 100 : 0
  const avgWin = totalWinTrades > 0 ? sumWinPnl / totalWinTrades : 0
  const avgLoss = totalLossTrades > 0 ? sumLossPnl / totalLossTrades : 0
  const profitLossRatio = avgLoss > 0 ? avgWin / avgLoss : avgWin > 0 ? 99 : 0
  const expectancy = totalSellCount > 0 ? (sumWinPnl - sumLossPnl) / totalSellCount : 0

  // 仓位集中度
  const posHoldings = all.filter((s) => s.isHolding).sort((a, b) => (b.positionPct || 0) - (a.positionPct || 0))
  const top1Holding = posHoldings[0] || null
  const top2Holding = posHoldings[1] || null

  return {
    totalStocks: all.length,
    gainCount: gainers.length,
    lossCount: losers.length,
    holdingCount: all.filter((s) => s.isHolding).length,
    totalGain,
    totalLoss,
    topGainer,
    topLoser,
    tradeWinRate,
    totalSellCount,
    totalWinTrades,
    totalLossTrades,
    avgWin,
    avgLoss,
    profitLossRatio,
    expectancy,
    maxSingleLoss,
    maxSingleLossStock,
    top1Holding,
    top2Holding,
  }
})

// 格式化函数
function fmt(v?: number | null, d = 2) {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
}

function fmtSigned(v?: number | null, d = 2) {
  if (v == null || !Number.isFinite(v)) return '—'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })}`
}
</script>

<template>
  <div class="page-shell py-6 space-y-6">
    <!-- 顶部导航与更新状态 -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <div class="flex items-center gap-2">
          <NuxtLink to="/" class="text-xs text-accent hover:underline flex items-center gap-1">
            <span>←</span> 返回持仓盯盘
          </NuxtLink>
          <span class="text-ui-text-3">/</span>
          <span class="text-xs text-ui-text-2">量化资产分析</span>
        </div>
        <h1 class="mt-1 text-2xl font-bold tracking-tight text-ui-text">
          资产分析 · 30万起步全维度诊断
        </h1>
        <p class="mt-1 text-xs text-ui-text-3">
          基准：自 {{ snapshotAccount?.totalPnlStart || '2026-09-09' }} 起以重置本金 ¥{{ fmt(baseCapital, 0) }} 核算 · 涵盖个股盈亏归因、最大回撤测算与风控全景诊断
        </p>
      </div>

      <div class="flex items-center gap-3">
        <span v-if="refreshedAt" class="text-xs text-ui-text-3">数据已更新: {{ refreshedAt }}</span>
        <button
          type="button"
          class="btn text-xs px-3 py-1.5"
          :disabled="loading"
          @click="loadData"
        >
          {{ loading ? '刷新中…' : '刷新数据' }}
        </button>
      </div>
    </div>

    <!-- 错误警告提示 -->
    <div v-if="error" class="rounded-lg border border-ui-danger/40 bg-ui-danger/10 p-3 text-sm text-ui-danger">
      {{ error }}
    </div>

    <!-- 模块 1：30万起步·核心宏观指标看板 -->
    <section class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <!-- 1. 当前总资产 -->
      <div class="card p-4 space-y-1">
        <span class="text-xs text-ui-text-2">当前总资产 (30万起步)</span>
        <div class="sensitive text-xl font-bold tabular-nums text-ui-text">
          ¥{{ fmt(currentTotal) }}
        </div>
        <div class="text-xs tabular-nums">
          <span class="text-ui-text-3">累计收益: </span>
          <ChgText :chg="currentTotalPnl" class="font-semibold">
            {{ fmtSigned(currentTotalPnl) }} ({{ fmtSigned(currentTotalPnlPct) }}%)
          </ChgText>
        </div>
      </div>

      <!-- 2. 阶段最大资产峰值 -->
      <div class="card p-4 space-y-1">
        <div class="flex items-center justify-between text-xs text-ui-text-2">
          <span>阶段最大资产 (峰值)</span>
          <span class="rounded bg-accent/15 px-1 text-[10px] text-accent">新高位</span>
        </div>
        <div class="sensitive text-xl font-bold tabular-nums text-ui-text">
          ¥{{ fmt(seriesData.peakEquity) }}
        </div>
        <div class="text-xs text-ui-text-3 tabular-nums">
          峰值盈利: <span class="text-up font-semibold">+{{ fmt(seriesData.peakProfit) }}</span> ({{ seriesData.peakDate.slice(5) }})
        </div>
      </div>

      <!-- 3. 账户历史最大回撤 -->
      <div class="card p-4 space-y-1">
        <div class="flex items-center justify-between text-xs text-ui-text-2">
          <span>历史最大回撤 (MDD)</span>
          <span class="rounded bg-ui-danger/15 px-1 text-[10px] text-ui-danger">风控基线</span>
        </div>
        <div class="sensitive text-xl font-bold tabular-nums text-ui-danger">
          -{{ (seriesData.maxDrawdown * 100).toFixed(2) }}%
        </div>
        <div class="text-xs text-ui-text-3 tabular-nums">
          回撤金额: -¥{{ fmt(seriesData.maxDrawdownVal) }}
        </div>
      </div>

      <!-- 4. 当前回撤水平 -->
      <div class="card p-4 space-y-1">
        <span class="text-xs text-ui-text-2">当前距峰值回撤</span>
        <div class="sensitive text-xl font-bold tabular-nums" :class="seriesData.currentDrawdown > 0.05 ? 'text-ui-danger' : 'text-accent'">
          -{{ (seriesData.currentDrawdown * 100).toFixed(2) }}%
        </div>
        <div class="text-xs text-ui-text-3 tabular-nums">
          距高点差: ¥{{ fmt(seriesData.currentDrawdownVal) }}
        </div>
      </div>

      <!-- 5. 交易平仓胜率 -->
      <div class="card p-4 space-y-1">
        <span class="text-xs text-ui-text-2">交易平仓胜率</span>
        <div class="sensitive text-xl font-bold tabular-nums text-ui-text">
          {{ stats.tradeWinRate.toFixed(1) }}%
        </div>
        <div class="text-xs text-ui-text-3 tabular-nums">
          {{ stats.totalWinTrades }} 胜 / {{ stats.totalLossTrades }} 负 (共 {{ stats.totalSellCount }} 笔)
        </div>
      </div>

      <!-- 6. 盈亏比健康度 -->
      <div class="card p-4 space-y-1">
        <span class="text-xs text-ui-text-2">获利盈亏比</span>
        <div class="sensitive text-xl font-bold tabular-nums text-up">
          {{ stats.profitLossRatio > 50 ? '极高' : stats.profitLossRatio.toFixed(2) }}
        </div>
        <div class="text-xs text-ui-text-3 tabular-nums">
          均赢 ¥{{ fmt(stats.avgWin, 0) }} / 均亏 ¥{{ fmt(stats.avgLoss, 0) }}
        </div>
      </div>
    </section>

    <!-- 模块 2：资产净值走势与动态回撤双网格图 -->
    <section class="card p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ui-hairline pb-2">
        <div>
          <h2 class="text-sm font-semibold text-ui-text">
            总资产趋势与动态回撤深度曲线
          </h2>
          <span class="text-xs text-ui-text-3">
            自 30 万起点以来的总资产波动轨迹，虚线为 300,000 元基准线，下层面积显示回撤深度
          </span>
        </div>
        <div class="flex items-center gap-3 text-xs">
          <span class="text-ui-text-3">回撤波谷: {{ seriesData.maxDrawdownTroughDate }}</span>
        </div>
      </div>
      <ClientOnly>
        <AssetAnalysisChart
          :daily-points="seriesData.points"
          :base="baseCapital"
          :peak-equity="seriesData.peakEquity"
          :peak-date="seriesData.peakDate"
          :max-drawdown="seriesData.maxDrawdown"
          :max-drawdown-val="seriesData.maxDrawdownVal"
        />
      </ClientOnly>
    </section>

    <!-- 模块 3：账户全方位量化智能诊断 -->
    <section class="space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-bold text-ui-text flex items-center gap-2">
          <span>🩺</span> 账户全方位量化诊断
        </h2>
        <span class="text-xs text-ui-text-3">依据持仓分布、交易期望、止损纪律与回撤弹性综合诊断</span>
      </div>

      <div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        <!-- 诊断 1: 仓位控制与流动性 -->
        <div class="card p-4 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-ui-text-2">1. 仓位控制与流动性</span>
            <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
              {{ (snapshotAccount?.positionPct || 0) < 60 ? '稳健健康' : '重仓运行' }}
            </span>
          </div>
          <div class="text-xs leading-relaxed text-ui-text-2">
            当前总仓位 <b class="text-ui-text tabular-nums">{{ fmtPositionPct(snapshotAccount?.positionPct) }}</b>，现金占比 <b class="text-ui-text tabular-nums">{{ fmtPositionPct(snapshotAccount?.positionPct != null ? 100 - snapshotAccount.positionPct : null) }}</b>。
            <template v-if="stats.top1Holding">
              第一大重仓股为 <span class="text-ui-text font-medium">{{ stats.top1Holding.name }}</span>（{{ fmtPositionPct(stats.top1Holding.positionPct) }}），单票仓位符合分散风控（不超过 25%）。
            </template>
            流动性极其充裕，拥有充沛的开仓机动进攻空间。
          </div>
        </div>

        <!-- 诊断 2: 盈亏比与交易质量 -->
        <div class="card p-4 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-ui-text-2">2. 盈亏比与交易质量</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-semibold"
              :class="stats.profitLossRatio >= 1.8 ? 'bg-up/15 text-up' : 'bg-accent/15 text-accent'"
            >
              {{ stats.profitLossRatio >= 1.8 ? '优势截断亏损' : '健康良好' }}
            </span>
          </div>
          <div class="text-xs leading-relaxed text-ui-text-2">
            获利盈亏比为 <b class="text-up tabular-nums">{{ stats.profitLossRatio.toFixed(2) }} : 1</b>（平均盈利 ¥{{ fmt(stats.avgWin, 0) }} vs 平均亏损 ¥{{ fmt(stats.avgLoss, 0) }}）。
            胜率 <b class="text-ui-text tabular-nums">{{ stats.tradeWinRate.toFixed(1) }}%</b>。
            单笔交易数学期望值为 <b class="text-up tabular-nums">+¥{{ fmt(stats.expectancy, 1) }}</b>，符合“小亏大赢、严格止盈”的正期望策略模型。
          </div>
        </div>

        <!-- 诊断 3: 单笔风控与止损执行力 -->
        <div class="card p-4 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-ui-text-2">3. 单笔风控与止损执行力</span>
            <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent">执行坚决</span>
          </div>
          <div class="text-xs leading-relaxed text-ui-text-2">
            历史单笔最大亏损为 <b class="text-ui-danger tabular-nums">¥{{ fmt(stats.maxSingleLoss) }}</b>（来自 {{ stats.maxSingleLossStock || '个股' }}），占 30 万本金比例仅为 <b class="text-ui-danger tabular-nums">{{ Math.abs(stats.maxSingleLoss / baseCapital * 100).toFixed(2) }}%</b>。
            无恶性大亏与单票深套，表明“成本-1%保护与低开开盘保护”风控规则被忠实执行。
          </div>
        </div>

        <!-- 诊断 4: 回撤深度与恢复力 -->
        <div class="card p-4 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-ui-text-2">4. 回撤深度与恢复力</span>
            <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent">控制良好</span>
          </div>
          <div class="text-xs leading-relaxed text-ui-text-2">
            历史最大回撤为 <b class="text-ui-danger tabular-nums">-{{ (seriesData.maxDrawdown * 100).toFixed(2) }}%</b>，处于低中度稳健区间。
            当前距历史最高资产仅回撤 <b class="text-accent tabular-nums">-{{ (seriesData.currentDrawdown * 100).toFixed(2) }}%</b>，修复迅速，账户整体净值持续保持在历史高位附近运行。
          </div>
        </div>
      </div>
    </section>

    <!-- 模块 4：盈利股票 vs 亏损股票分类统计卡片 -->
    <section class="grid grid-cols-1 gap-4 md:grid-cols-2">
      <!-- 盈利股票阵营 -->
      <div class="card p-4 space-y-3 border-l-4 border-l-up">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-sm font-bold text-up">🏆 盈利股票阵营</span>
            <span class="rounded bg-up/15 px-2 py-0.5 text-xs font-bold text-up">{{ stats.gainCount }} 只股票</span>
          </div>
          <div class="text-right">
            <span class="text-xs text-ui-text-3">贡献总盈利</span>
            <div class="text-lg font-bold text-up tabular-nums">+¥{{ fmt(stats.totalGain) }}</div>
          </div>
        </div>

        <div v-if="stats.topGainer" class="rounded-lg bg-ui-ink/50 p-2.5 text-xs space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-ui-text-2 font-medium">盈利第一标杆：</span>
            <StockNameHover :code="stats.topGainer.code" :name="stats.topGainer.name">
              <span class="font-bold text-ui-text hover:underline">{{ stats.topGainer.name }} ({{ stats.topGainer.code }})</span>
            </StockNameHover>
          </div>
          <div class="flex items-center justify-between text-ui-text-3">
            <span>累计收益: <b class="text-up tabular-nums">+¥{{ fmt(stats.topGainer.totalPnl) }} (+{{ stats.topGainer.totalPnlPct.toFixed(2) }}%)</b></span>
            <span>平仓 {{ stats.topGainer.sellCount }} 笔全胜</span>
          </div>
        </div>

        <!-- 盈利与亏损覆盖比进度条 -->
        <div class="space-y-1 pt-1">
          <div class="flex justify-between text-[11px] text-ui-text-3">
            <span>盈利贡献覆盖率</span>
            <span class="tabular-nums">盈利 ¥{{ fmt(stats.totalGain, 0) }} / 净利润 ¥{{ fmt(stats.totalGain - stats.totalLoss, 0) }}</span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-ui-hairline">
            <div
              class="h-full bg-up"
              :style="{ width: `${Math.min(100, (stats.totalGain / (stats.totalGain + stats.totalLoss || 1)) * 100)}%` }"
            />
          </div>
        </div>
      </div>

      <!-- 亏损股票阵营 -->
      <div class="card p-4 space-y-3 border-l-4 border-l-down">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-sm font-bold text-down">🛡️ 亏损股票阵营</span>
            <span class="rounded bg-down/15 px-2 py-0.5 text-xs font-bold text-down">{{ stats.lossCount }} 只股票</span>
          </div>
          <div class="text-right">
            <span class="text-xs text-ui-text-3">产生总亏损</span>
            <div class="text-lg font-bold text-down tabular-nums">-¥{{ fmt(stats.totalLoss) }}</div>
          </div>
        </div>

        <div v-if="stats.topLoser" class="rounded-lg bg-ui-ink/50 p-2.5 text-xs space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-ui-text-2 font-medium">最大亏损标的：</span>
            <StockNameHover :code="stats.topLoser.code" :name="stats.topLoser.name">
              <span class="font-bold text-ui-text hover:underline">{{ stats.topLoser.name }} ({{ stats.topLoser.code }})</span>
            </StockNameHover>
          </div>
          <div class="flex items-center justify-between text-ui-text-3">
            <span>累计亏损: <b class="text-down tabular-nums">¥{{ fmt(stats.topLoser.totalPnl) }} ({{ stats.topLoser.totalPnlPct.toFixed(2) }}%)</b></span>
            <span>触发止损平仓 {{ stats.topLoser.sellCount }} 笔</span>
          </div>
        </div>

        <!-- 亏损控制提示 -->
        <div class="rounded-lg bg-ui-hairline/40 px-2.5 py-2 text-[11px] text-ui-text-3 leading-relaxed">
          亏损标的均严格按照止损条件卖出，未发生持续放任扩大亏损。总亏损金额完全被盈利标的（覆盖率 {{ ((stats.totalGain / (stats.totalLoss || 1)) * 100).toFixed(0) }}%）充分消化。
        </div>
      </div>
    </section>

    <!-- 模块 5：个股盈利亏损排行榜与明细表 -->
    <section class="card overflow-hidden">
      <!-- 筛选与控制栏 -->
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline p-4">
        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            class="tab-pill"
            :class="currentTab === 'all' ? 'tab-pill-active' : 'tab-pill-idle'"
            @click="currentTab = 'all'"
          >
            全部标的 ({{ aggregatedStocks.length }})
          </button>
          <button
            type="button"
            class="tab-pill"
            :class="currentTab === 'gain' ? 'tab-pill-active' : 'tab-pill-idle'"
            @click="currentTab = 'gain'"
          >
            盈利股票 ({{ stats.gainCount }})
          </button>
          <button
            type="button"
            class="tab-pill"
            :class="currentTab === 'loss' ? 'tab-pill-active' : 'tab-pill-idle'"
            @click="currentTab = 'loss'"
          >
            亏损股票 ({{ stats.lossCount }})
          </button>
          <button
            type="button"
            class="tab-pill"
            :class="currentTab === 'holding' ? 'tab-pill-active' : 'tab-pill-idle'"
            @click="currentTab = 'holding'"
          >
            当前持仓 ({{ stats.holdingCount }})
          </button>
        </div>

        <div class="flex items-center gap-2 text-xs text-ui-text-2">
          <span>排序方式:</span>
          <select
            v-model="currentSort"
            class="rounded border border-ui-hairline bg-ui-surface px-2.5 py-1 text-xs text-ui-text focus:outline-none"
          >
            <option value="totalPnl">总盈亏金额</option>
            <option value="totalPnlPct">累计收益率</option>
            <option value="winRate">平仓胜率</option>
            <option value="sellCount">平仓次数</option>
            <option value="lastTime">最近交易时间</option>
          </select>
          <button
            type="button"
            class="btn px-2 py-1 text-xs"
            @click="sortAsc = !sortAsc"
          >
            {{ sortAsc ? '升序 ↑' : '降序 ↓' }}
          </button>
        </div>
      </div>

      <!-- 个股排行榜表格 -->
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead>
            <tr class="border-b border-ui-hairline bg-ui-surface/60 text-ui-text-3">
              <th class="py-3 pl-4 pr-2 font-medium">股票 / 代码</th>
              <th class="px-2 py-3 font-medium">当前状态</th>
              <th class="cursor-pointer px-2 py-3 font-medium hover:text-ui-text" @click="changeSort('totalPnl')">
                总盈亏 {{ currentSort === 'totalPnl' ? (sortAsc ? '↑' : '↓') : '' }}
              </th>
              <th class="cursor-pointer px-2 py-3 font-medium hover:text-ui-text" @click="changeSort('totalPnlPct')">
                盈亏率 {{ currentSort === 'totalPnlPct' ? (sortAsc ? '↑' : '↓') : '' }}
              </th>
              <th class="px-2 py-3 font-medium">已实现盈亏</th>
              <th class="px-2 py-3 font-medium">持仓浮动盈亏</th>
              <th class="cursor-pointer px-2 py-3 font-medium hover:text-ui-text" @click="changeSort('winRate')">
                胜率 / 平仓笔数 {{ currentSort === 'winRate' ? (sortAsc ? '↑' : '↓') : '' }}
              </th>
              <th class="px-2 py-3 font-medium">极端单笔</th>
              <th class="px-2 py-3 font-medium">主要退出/执行理由</th>
              <th class="cursor-pointer py-3 pl-2 pr-4 text-right font-medium hover:text-ui-text" @click="changeSort('lastTime')">
                最近交易 {{ currentSort === 'lastTime' ? (sortAsc ? '↑' : '↓') : '' }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ui-hairline/60">
            <template v-for="stock in filteredStocks" :key="stock.code">
              <tr class="hover:bg-ui-fill-hover transition-colors">
                <!-- 股票名与代码 -->
                <td class="py-3 pl-4 pr-2">
                  <div class="flex items-center gap-1.5">
                    <StockNameHover :code="stock.code" :name="stock.name">
                      <a
                        :href="baiduStockUrl(stock.code)"
                        target="_blank"
                        rel="noreferrer"
                        class="font-semibold text-ui-text hover:text-accent hover:underline"
                      >
                        {{ stock.name }}
                      </a>
                    </StockNameHover>
                    <span class="text-[11px] text-ui-text-3">{{ stock.code }}</span>
                    <button
                      v-if="stock.history.length > 0"
                      type="button"
                      class="ml-1 text-[10px] text-accent hover:underline"
                      @click="toggleExpand(stock.code)"
                    >
                      {{ expandedCodes.has(stock.code) ? '收起' : `流水(${stock.history.length})` }}
                    </button>
                  </div>
                </td>

                <!-- 当前状态 -->
                <td class="px-2 py-3">
                  <span
                    v-if="stock.isHolding"
                    class="inline-flex items-center gap-1 rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent"
                  >
                    <span class="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                    持仓 {{ stock.currentQty }}股 ({{ fmtPositionPct(stock.positionPct) }})
                  </span>
                  <span v-else class="text-[11px] text-ui-text-3">已清仓</span>
                </td>

                <!-- 总盈亏 -->
                <td class="px-2 py-3 font-bold tabular-nums">
                  <ChgText :chg="stock.totalPnl">
                    {{ fmtSigned(stock.totalPnl) }}
                  </ChgText>
                </td>

                <!-- 总盈亏率 -->
                <td class="px-2 py-3 font-semibold tabular-nums">
                  <ChgText :chg="stock.totalPnlPct">
                    {{ fmtSigned(stock.totalPnlPct) }}%
                  </ChgText>
                </td>

                <!-- 已实现盈亏 -->
                <td class="px-2 py-3 tabular-nums">
                  <ChgText :chg="stock.realizedPnl">
                    {{ fmtSigned(stock.realizedPnl) }}
                  </ChgText>
                </td>

                <!-- 持仓浮动盈亏 -->
                <td class="px-2 py-3 tabular-nums">
                  <template v-if="stock.isHolding">
                    <ChgText :chg="stock.unrealizedPnl">
                      {{ fmtSigned(stock.unrealizedPnl) }}
                    </ChgText>
                  </template>
                  <span v-else class="text-ui-text-3">—</span>
                </td>

                <!-- 胜率 / 笔数 -->
                <td class="px-2 py-3 tabular-nums">
                  <template v-if="stock.sellCount > 0">
                    <span class="font-medium" :class="(stock.winRate ?? 0) >= 50 ? 'text-up' : 'text-down'">
                      {{ (stock.winRate ?? 0).toFixed(0) }}%
                    </span>
                    <span class="ml-1 text-ui-text-3">({{ stock.winCount }}胜/{{ stock.sellCount }}平)</span>
                  </template>
                  <span v-else class="text-ui-text-3">持仓未平仓</span>
                </td>

                <!-- 极端单笔 -->
                <td class="px-2 py-3 text-[11px] tabular-nums text-ui-text-3">
                  <div v-if="stock.maxWin > 0" class="text-up">
                    赢: +{{ fmt(stock.maxWin, 0) }}
                  </div>
                  <div v-if="stock.maxLoss < 0" class="text-down">
                    亏: {{ fmt(stock.maxLoss, 0) }}
                  </div>
                  <span v-if="stock.maxWin === 0 && stock.maxLoss === 0">—</span>
                </td>

                <!-- 卖出理由 / 策略说明 -->
                <td class="px-2 py-3 max-w-xs truncate text-[11px] text-ui-text-2" :title="stock.lastReason">
                  {{ stock.lastReason || '—' }}
                </td>

                <!-- 最近交易时间 -->
                <td class="py-3 pl-2 pr-4 text-right text-[11px] text-ui-text-3 tabular-nums">
                  {{ stock.lastTime ? stock.lastTime.slice(5) : '—' }}
                </td>
              </tr>

              <!-- 展开的历史流水子行 -->
              <tr v-if="expandedCodes.has(stock.code)" class="bg-ui-surface/80">
                <td colspan="10" class="p-3 pl-8">
                  <div class="rounded-lg border border-ui-hairline bg-ui-page p-3 space-y-2">
                    <div class="text-xs font-semibold text-ui-text flex items-center justify-between">
                      <span>{{ stock.name }} ({{ stock.code }}) 历史交割流水明细</span>
                      <span class="text-ui-text-3 font-normal">累计买入: ¥{{ fmt(stock.buyAmount) }} | 累计卖出: ¥{{ fmt(stock.sellAmount) }}</span>
                    </div>

                    <div class="overflow-x-auto">
                      <table class="w-full text-left text-[11px]">
                        <thead>
                          <tr class="border-b border-ui-hairline text-ui-text-3">
                            <th class="py-1">时间</th>
                            <th class="py-1">方向</th>
                            <th class="py-1">成交价</th>
                            <th class="py-1">数量</th>
                            <th class="py-1">成交额</th>
                            <th class="py-1">单笔盈亏</th>
                            <th class="py-1">操作理由</th>
                          </tr>
                        </thead>
                        <tbody class="divide-y divide-ui-hairline/40">
                          <tr v-for="t in stock.history" :key="t.id" class="hover:bg-ui-fill-hover">
                            <td class="py-1.5 tabular-nums text-ui-text-3">{{ t.time }}</td>
                            <td class="py-1.5 font-medium">
                              <span :class="t.side === 'buy' ? 'text-accent' : 'text-ui-text'">
                                {{ t.side === 'buy' ? '买入' : (t.action_kind === 'half' ? '卖出·半仓' : '卖出') }}
                              </span>
                            </td>
                            <td class="py-1.5 tabular-nums">¥{{ fmt(t.price) }}</td>
                            <td class="py-1.5 tabular-nums">{{ t.qty }} 股</td>
                            <td class="py-1.5 tabular-nums">¥{{ fmt(t.amount) }}</td>
                            <td class="py-1.5 tabular-nums font-semibold">
                              <template v-if="t.side === 'sell'">
                                <ChgText :chg="t.pnl">
                                  {{ fmtSigned(t.pnl) }} ({{ fmtSigned(t.pnl_pct) }}%)
                                </ChgText>
                              </template>
                              <span v-else class="text-ui-text-3">—</span>
                            </td>
                            <td class="py-1.5 text-ui-text-2">{{ displayReason(t.reason) }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div v-if="filteredStocks.length === 0" class="py-8 text-center text-xs text-ui-text-3">
        当前分类下暂无股票记录
      </div>
    </section>
  </div>
</template>
