<script setup lang="ts">
import type { Strategy38Payload, Strategy38Row, StrategyTab } from '~/types/snapshot'
import { baiduStockUrl } from '~/utils/stockLink'
import { fmtNum, stockLabel } from '~/utils/format'

const props = defineProps<{
  tab?: StrategyTab
  payload?: Strategy38Payload | null
  phase?: string
}>()

const localPayload = ref<Strategy38Payload | null>(null)
const currentPayload = computed(() => localPayload.value || props.payload)

const step1 = computed(() => currentPayload.value?.step1)
const step2 = computed(() => currentPayload.value?.step2)
const kpi = computed(() => currentPayload.value?.kpi)
const rows = computed<Strategy38Row[]>(() => {
  const p = currentPayload.value
  if (!p) return []
  const list = (p.rows && p.rows.length) ? p.rows : ((p as any).orders || (p as any).candidates || [])
  return list.map((r: any) => ({
    代码: String(r.代码 || r.code || ''),
    名称: String(r.名称 || r.name || ''),
    最新价: r.最新价 ?? r.last_close ?? 0,
    突破买入价: r.突破买入价 ?? r.buy_trigger_price ?? 0,
    回踩买入价: r.回踩买入价 ?? r.support_buy_price ?? 0,
    止损保护价: r.止损保护价 ?? r.stop_loss_price ?? 0,
    放量倍数: r.放量倍数 != null ? String(r.放量倍数) : (r.volume_ratio ? `${r.volume_ratio}x` : '—'),
    起爆日期: r.起爆日期 || r.breakout_date || '—',
    起爆涨幅: r.起爆涨幅 != null ? String(r.起爆涨幅) : (r.body_return ? `${(r.body_return * 100).toFixed(2)}%` : '—'),
    状态: r.状态 || r.status || 'READY_TO_BUY',
    买点确认逻辑: r.买点确认逻辑 || r.confirm_logic || '',
    symbol: r.symbol || r.code || '',
  }))
})

const isVetoCash = computed(() => Boolean(step1.value?.veto_cash))
const activeTab = ref<'live' | 'backtest'>('live')

const scanning = ref(false)
const syncSelf = ref(false)
const scanProgress = ref<{ stage: string; percent: number; completed?: number; total?: number } | null>(null)
const scanError = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

async function checkScanStatus() {
  try {
    const res = await fetch('/api/strategy38/scan')
    if (!res.ok) return
    const data = await res.json()
    scanning.value = Boolean(data.running)
    if (data.progress) scanProgress.value = data.progress
    if (data.error) scanError.value = data.error
    if (!data.running && scanning.value) {
      scanning.value = false
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
      await refreshPayload()
    }
  } catch {}
}

async function refreshPayload() {
  try {
    const res = await fetch('/api/strategy38/payload')
    if (res.ok) {
      localPayload.value = await res.json()
    }
  } catch {}
}

async function triggerScan() {
  if (scanning.value) return
  scanning.value = true
  scanError.value = ''
  try {
    const res = await fetch('/api/strategy38/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ top_n: 15, recent_hit_days: 5, sync_self: syncSelf.value }),
    })
    const data = await res.json()
    if (!res.ok || data.error) throw new Error(data.error || '扫描触发失败')
    if (!pollTimer) {
      pollTimer = setInterval(async () => {
        try {
          const r = await fetch('/api/strategy38/scan')
          if (r.ok) {
            const s = await r.json()
            scanning.value = Boolean(s.running)
            if (s.progress) scanProgress.value = s.progress
            if (!s.running) {
              if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
              await refreshPayload()
            }
          }
        } catch {}
      }, 1500)
    }
  } catch (err: any) {
    scanning.value = false
    scanError.value = err?.message || '网络异常'
  }
}

onMounted(() => {
  void checkScanStatus()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部视图切换：实时盯盘 vs 多维回测 -->
    <div class="flex items-center justify-between border-b border-ui-hairline pb-2">
      <div class="inline-flex rounded-lg bg-ui-surface-2/60 p-1 text-xs">
        <button
          type="button"
          class="rounded-md px-4 py-1.5 font-bold transition"
          :class="activeTab === 'live' ? 'bg-accent/20 text-accent font-bold shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
          @click="activeTab = 'live'"
        >
          实时盯盘信号与四步漏斗
        </button>
        <button
          type="button"
          class="rounded-md px-4 py-1.5 font-bold transition ml-1"
          :class="activeTab === 'backtest' ? 'bg-accent/20 text-accent font-bold shadow-sm' : 'text-ui-text-3 hover:text-ui-text'"
          @click="activeTab = 'backtest'"
        >
          ⚡ 策略多维参数回测平台
        </button>
      </div>
      <span class="text-xs text-ui-text-3">
        {{ activeTab === 'live' ? '每日盘前/盘中选股与买点执行' : '自定义股票池 · 因子手选 · 绩效对比' }}
      </span>
    </div>

    <!-- 多维回测控制台视图 -->
    <div v-if="activeTab === 'backtest'">
      <Strategy38BacktestConsole />
    </div>

    <!-- 实时盯盘视图 -->
    <div v-else class="space-y-4">
    <!-- 顶部四步流转指标 KPI -->
    <div class="card grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <!-- Step 1 状态 -->
      <div class="border-b border-ui-hairline pb-2 sm:border-b-0 sm:pb-0">
        <div class="text-xs text-ui-text-3">Step 1: 大盘绝对风控</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span
            class="text-lg font-bold"
            :class="isVetoCash ? 'text-ui-danger' : 'text-ui-success'"
          >
            {{ isVetoCash ? '【一票否决】空仓避险' : '【安全放行】允许开仓' }}
          </span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">
          {{ step1?.tier_name || '多头进攻态' }} · 广度 {{ ((step1?.breadth || 0.55) * 100).toFixed(1) }}%
        </div>
      </div>

      <!-- Step 2 状态 -->
      <div class="border-b border-ui-hairline pb-2 sm:border-b-0 sm:pb-0">
        <div class="text-xs text-ui-text-3">Step 2: 因子13A底池清洗</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-accent">{{ step2?.count ?? 0 }} 只</span>
          <span class="text-xs text-ui-text-2">质地达标</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">全A剔ST/剔退市/主板纯净底池</div>
      </div>

      <!-- Step 3 状态 -->
      <div class="border-b border-ui-hairline pb-2 sm:border-b-0 sm:pb-0">
        <div class="text-xs text-ui-text-3">Step 3: 因子34地量起爆</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-ui-danger">{{ kpi?.step3_candidate_count ?? 0 }} 只</span>
          <span class="text-xs text-ui-text-2">均放量 {{ kpi?.avg_volume_multiple ?? 2.5 }}x</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">60日地量沉淀 + 倍量大阳起爆</div>
      </div>

      <!-- Step 4 状态 -->
      <div>
        <div class="text-xs text-ui-text-3">Step 4: 缠论执行买单</div>
        <div class="mt-1 flex items-baseline gap-2">
          <span class="text-xl font-bold text-accent">{{ kpi?.step4_order_count ?? 0 }} 笔</span>
          <span class="text-xs text-ui-text-2">次日就绪</span>
        </div>
        <div class="mt-1 text-[11px] text-ui-text-3">日线底分型向上笔 + 突破/回踩买点</div>
      </div>
    </div>

    <!-- 策略四步流转架构说明横幅 -->
    <div class="card p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="rounded bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">执行流水线</span>
          <h3 class="text-sm font-semibold">日线四步闭环漏斗架构</h3>
          <span v-if="currentPayload?.as_of" class="text-xs text-ui-text-3 font-normal">
            (快照时间: {{ currentPayload.as_of }})
          </span>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <label class="inline-flex items-center gap-1.5 text-xs text-ui-text-2 cursor-pointer">
            <input v-model="syncSelf" type="checkbox" class="accent-accent rounded" />
            <span>入选标的自动同步自选池</span>
          </label>
          <button
            type="button"
            class="rounded-lg bg-accent px-3 py-1.5 text-xs font-bold text-white shadow hover:opacity-90 transition disabled:opacity-50 flex items-center gap-1.5"
            :disabled="scanning"
            @click="triggerScan"
          >
            <span v-if="scanning" class="inline-block animate-spin">⌛</span>
            <span v-else>🔍</span>
            <span>{{ scanning ? '全市场扫描中…' : '重新扫描全市场起爆标的' }}</span>
          </button>
        </div>
      </div>

      <!-- 扫描进度条与错误反馈 -->
      <div v-if="scanning && scanProgress" class="rounded-lg bg-accent/10 border border-accent/20 p-2.5 text-xs space-y-1">
        <div class="flex justify-between items-center text-accent">
          <span class="font-bold">{{ scanProgress.stage }}</span>
          <span>{{ scanProgress.percent }}%</span>
        </div>
        <div class="h-1.5 w-full bg-ui-hairline rounded-full overflow-hidden">
          <div class="h-full bg-accent transition-all duration-300" :style="{ width: `${scanProgress.percent}%` }" />
        </div>
      </div>

      <div v-if="scanError" class="rounded-lg bg-red-500/10 border border-red-500/30 p-2 text-xs text-red-400">
        {{ scanError }}
      </div>

      <div class="mt-3 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <!-- 漏斗卡片 1 -->
        <div
          class="rounded-lg border p-3"
          :class="isVetoCash ? 'border-ui-danger bg-ui-danger/5' : 'border-ui-hairline bg-ui-surface-2/40'"
        >
          <div class="flex items-center justify-between">
            <span class="font-semibold text-accent">Step 1: 绝对风控</span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] font-medium"
              :class="isVetoCash ? 'bg-ui-danger text-white' : 'bg-ui-success/15 text-ui-success'"
            >
              {{ isVetoCash ? '一票否决' : '门控通过' }}
            </span>
          </div>
          <div class="mt-2 text-ui-text-2">
            接入【因子35-多维复合空仓因子】。跌破 60日生命线 或全市场广度溃散时，直接空仓防守，次日禁止开仓。
          </div>
          <div class="mt-2 text-[11px] text-ui-text-3">
            诊断：{{ step1?.reason || '大盘运行稳健' }}
          </div>
        </div>

        <!-- 漏斗卡片 2 -->
        <div class="rounded-lg border border-ui-hairline bg-ui-surface-2/40 p-3">
          <div class="flex items-center justify-between">
            <span class="font-semibold text-accent">Step 2: 底池清洗</span>
            <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">基本面质地</span>
          </div>
          <div class="mt-2 text-ui-text-2">
            接入【因子13A-契合选股】。剔除全市场 ST/退市标的，排除创业板/科创板/北交所，锁定流动性健康的主板优良正股。
          </div>
          <div class="mt-2 text-[11px] text-ui-text-3">
            过滤规则：主板正股 · 股价 3~120元 · 流动性充足
          </div>
        </div>

        <!-- 漏斗卡片 3 -->
        <div class="rounded-lg border border-ui-hairline bg-ui-surface-2/40 p-3">
          <div class="flex items-center justify-between">
            <span class="font-semibold text-accent">Step 3: 核心进攻</span>
            <span class="rounded bg-ui-danger/15 px-1.5 py-0.5 text-[10px] font-medium text-ui-danger">地量起爆</span>
          </div>
          <div class="mt-2 text-ui-text-2">
            在底池中执行【因子34-地量转放量动量】。寻找前期缩量（最低支持 5 日至 90 日，默认 60 日）地量充分沉淀，近期 1~10日底部放量 ≥ 2.0倍 且 K线实体 ≥ 5% 的起爆标的。
          </div>
          <div class="mt-2 text-[11px] text-ui-text-3">
            形态：长周期筹码洗尽 · 底部巨量突破大阳
          </div>
        </div>

        <!-- 漏斗卡片 4 -->
        <div class="rounded-lg border border-ui-hairline bg-ui-surface-2/40 p-3">
          <div class="flex items-center justify-between">
            <span class="font-semibold text-accent">Step 4: 买点生成</span>
            <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">执行层挂单</span>
          </div>
          <div class="mt-2 text-ui-text-2">
            接入【因子8-缠论结构】确立日线底分型向上一笔，配合【因子33-回落后攻击波】精确计算次日挂单价格。
          </div>
          <div class="mt-2 text-[11px] text-ui-text-3">
            执行：顺势突破买点 + 回踩二分位买点 + 保护止损
          </div>
        </div>
      </div>
    </div>

    <!-- 警示条：若大盘触发一票否决 -->
    <div
      v-if="isVetoCash"
      class="rounded-lg border border-ui-danger/50 bg-ui-danger/10 p-4 text-xs text-ui-danger"
    >
      <div class="font-bold">⚠️ Step 1 绝对风控触发一票否决：</div>
      <div class="mt-1">
        当前大盘指数跌破 MA60 生命线或微观广度出现恐慌溃散，多维复合空仓因子已下达硬风控指令。本策略今天不生成任何买入指令，次日全天停止开仓操作。
      </div>
    </div>

    <!-- 候选买点与挂单执行表格 -->
    <div class="card p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <h4 class="text-sm font-semibold">地量起爆候选标的与次日挂单买点</h4>
          <span class="rounded-full bg-ui-surface-2 px-2 py-0.5 text-xs text-ui-text-3">
            共 {{ rows.length }} 只标的
          </span>
        </div>
        <span class="text-xs text-ui-text-3">按放量倍数与实体涨幅优选排序</span>
      </div>

      <div v-if="!rows.length" class="p-8 text-center text-xs text-ui-text-3">
        {{ isVetoCash ? '因大盘触发一票否决空仓避险，策略返回空名单' : '暂无触发地量倍量起爆的候选标的' }}
      </div>

      <div v-else class="watch-table-wrap-scroll mt-1 max-h-[40rem]">
        <table class="watch-sticky-table text-xs">
          <thead>
            <tr>
              <th class="px-3 py-2.5">标的</th>
              <th class="px-3 py-2.5">起爆日期</th>
              <th class="px-3 py-2.5">最新价</th>
              <th class="px-3 py-2.5 text-accent">突破买入价</th>
              <th class="px-3 py-2.5 text-ui-success">回踩支撑价</th>
              <th class="px-3 py-2.5 text-ui-danger">止损保护价</th>
              <th class="px-3 py-2.5">放量倍数</th>
              <th class="px-3 py-2.5">起爆涨幅</th>
              <th class="px-3 py-2.5">状态</th>
              <th class="px-3 py-2.5 min-w-[240px]">买点确认逻辑</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in rows"
              :key="`${r.代码}-${r.起爆日期}`"
              class="border-t border-ui-hairline hover:bg-ui-surface-2/40"
            >
              <td class="px-3 py-2.5 align-top">
                <StockNameHover :code="r.代码" :name="r.名称">
                  <a
                    :href="baiduStockUrl(r.代码, r.名称)"
                    target="_blank"
                    rel="noopener"
                    class="font-semibold text-accent hover:underline inline-flex items-center gap-1"
                  >
                    <span>{{ stockLabel(r.代码, r.名称) }}</span>
                    <span class="text-[10px] text-accent/70 hover:text-accent">↗</span>
                  </a>
                </StockNameHover>
              </td>
              <td class="px-3 py-2.5 text-ui-text-2">{{ r.起爆日期 }}</td>
              <td class="px-3 py-2.5 font-semibold text-ui-text">{{ fmtNum(r.最新价, 2) }}</td>
              <td class="px-3 py-2.5 font-bold text-accent">{{ fmtNum(r.突破买入价, 2) }}</td>
              <td class="px-3 py-2.5 font-bold text-ui-success">{{ fmtNum(r.回踩买入价, 2) }}</td>
              <td class="px-3 py-2.5 font-semibold text-ui-danger">{{ fmtNum(r.止损保护价, 2) }}</td>
              <td class="px-3 py-2.5 font-medium text-ui-danger">{{ r.放量倍数 }}</td>
              <td class="px-3 py-2.5 font-medium text-ui-danger">{{ r.起爆涨幅 }}</td>
              <td class="px-3 py-2.5">
                <span class="rounded bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent">
                  {{ r.状态 }}
                </span>
              </td>
              <td class="px-3 py-2.5 text-ui-text-2 leading-relaxed">
                {{ r.买点确认逻辑 }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
  </div>
</template>
