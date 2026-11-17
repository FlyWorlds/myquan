<script setup lang="ts">
import type { WatchAccount } from '~/types/snapshot'
import { fmtNum } from '~/utils/format'

const props = defineProps<{
  account?: WatchAccount | null
}>()

interface TimingCurrent {
  date: string
  is_cash: boolean
  is_cash_mode: boolean
  tier: number
  tier_name: string
  position_ratio: number
  status_label: string
  status_tag: 'success' | 'warning' | 'danger' | string
  reason: string
  close?: number
  ma20?: number
  ma60?: number
  breadth?: number
  breakdown?: {
    macro_trend?: {
      name: string
      current_value?: number
      threshold?: number
      diff_pct?: number
      status: string
      ok: boolean
      desc: string
    }
    market_breadth?: {
      name: string
      current_value?: number
      threshold?: number
      status: string
      ok: boolean
      desc: string
    }
    exit_progress?: {
      name: string
      desc: string
      index_diff_pct?: number
      breadth_diff?: number
    }
  }
}

const current = ref<TimingCurrent | null>(null)
const loading = ref(false)
const collapsed = ref(false)
const lastFetched = ref<string>('')

// 建议仓位百分比 (0~100)
const suggestedPct = computed(() => {
  if (!current.value) return 100
  return Math.round((current.value.position_ratio ?? 1.0) * 100)
})

// 实际仓位百分比
const actualPct = computed(() => {
  if (!props.account) return null
  if (props.account.positionPct != null) {
    return Number(props.account.positionPct)
  }
  const total = Number(props.account.accountTotal || 0)
  const mv = Number(props.account.marketValue || 0)
  if (total > 0) {
    return (mv / total) * 100
  }
  return 0
})

// 是否发生仓位超限 (当前持仓 > 多维空仓建议上限 + 2%)
const isOverweight = computed(() => {
  if (actualPct.value == null || !current.value) return false
  return actualPct.value > suggestedPct.value + 2.0
})

// 仓位超配差值
const overweightDiff = computed(() => {
  if (actualPct.value == null) return 0
  return Math.max(0, actualPct.value - suggestedPct.value)
})

async function fetchTimingState() {
  if (loading.value) return
  loading.value = true
  try {
    const res = await $fetch<{ current?: TimingCurrent }>('/api/strategy35/timing-state')
    if (res?.current) {
      current.value = res.current
      lastFetched.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    }
  } catch (err) {
    console.warn('获取多维空仓择时状态失败:', err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchTimingState()
  // 每 60 秒轻量静默轮询一次
  const timer = setInterval(fetchTimingState, 60000)
  onBeforeUnmount(() => clearInterval(timer))
})
</script>

<template>
  <div
    v-if="current"
    class="mb-4 overflow-hidden rounded-xl border transition-all duration-300 shadow-sm"
    :class="{
      'border-red-500/50 bg-gradient-to-r from-red-950/30 via-ui-surface to-ui-surface text-red-100': current.tier === 1 || isOverweight,
      'border-amber-500/50 bg-gradient-to-r from-amber-950/25 via-ui-surface to-ui-surface text-amber-100': current.tier === 2 && !isOverweight,
      'border-yellow-500/40 bg-ui-surface text-yellow-100': current.tier === 3 && !isOverweight,
      'border-emerald-500/30 bg-ui-surface text-ui-text-2': current.tier === 4 && !isOverweight,
    }"
  >
    <!-- 主展示条 -->
    <div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div class="flex items-center gap-3 min-w-0">
        <!-- 盾牌风控动态图标 -->
        <div
          class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
          :class="{
            'bg-red-500/20 text-red-400': current.tier === 1 || isOverweight,
            'bg-amber-500/20 text-amber-400': current.tier === 2 && !isOverweight,
            'bg-yellow-500/20 text-yellow-400': current.tier === 3 && !isOverweight,
            'bg-emerald-500/20 text-emerald-400': current.tier === 4 && !isOverweight,
          }"
        >
          <!-- 警示盾牌 SVG -->
          <svg
            v-if="current.tier <= 2 || isOverweight"
            class="h-5 w-5 animate-pulse"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <path d="M12 8v4" />
            <path d="M12 16h.01" />
          </svg>
          <!-- 放行盾牌 SVG -->
          <svg
            v-else
            class="h-5 w-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <path d="m9 12 2 2 4-4" />
          </svg>
        </div>

        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="rounded px-2 py-0.5 text-xs font-bold"
              :class="{
                'bg-red-500 text-white animate-pulse': current.tier === 1,
                'bg-amber-500/25 text-amber-300 border border-amber-500/40': current.tier === 2,
                'bg-yellow-500/25 text-yellow-300 border border-yellow-500/40': current.tier === 3,
                'bg-emerald-500/25 text-emerald-300 border border-emerald-500/40': current.tier === 4,
              }"
            >
              多维空仓 · {{ current.tier_name }}
            </span>

            <span class="text-sm font-bold tracking-tight text-ui-text">
              建议总仓位上限 ≤ <span class="font-mono text-base font-black text-accent">{{ suggestedPct }}%</span>
            </span>

            <!-- 仓位超限警告徽章 -->
            <span
              v-if="isOverweight"
              class="rounded-full bg-red-500/25 border border-red-500/60 px-2.5 py-0.5 text-xs font-bold text-red-300 animate-pulse flex items-center gap-1"
            >
              <span>⚠️ 实际仓位超限</span>
              <span class="font-mono">({{ fmtNum(actualPct, 1) }}% > {{ suggestedPct }}%)</span>
            </span>
            <span
              v-else-if="actualPct != null"
              class="text-xs text-ui-text-3 font-mono"
            >
              当前持仓: {{ fmtNum(actualPct, 1) }}% (在风控线内)
            </span>
          </div>

          <p class="mt-1 text-xs leading-relaxed text-ui-text-2 truncate max-w-2xl">
            <span class="font-medium text-ui-text">{{ current.status_label }}</span>
            <span class="text-ui-text-3 ml-2">({{ current.reason }})</span>
          </p>
        </div>
      </div>

      <!-- 右侧行动与快捷折叠 -->
      <div class="flex items-center gap-2 shrink-0">
        <NuxtLink
          to="/cash-gate"
          class="btn inline-flex items-center gap-1.5 text-xs font-bold border border-ui-hairline hover:border-accent hover:text-accent bg-ui-surface-2 px-3 py-1.5 rounded-lg transition"
        >
          <span>多维空仓诊断</span>
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <path d="M7 17L17 7M17 7H7M17 7V17" />
          </svg>
        </NuxtLink>

        <button
          type="button"
          class="btn btn-ghost px-2 py-1.5 text-xs text-ui-text-3 hover:text-ui-text"
          :title="collapsed ? '展开风控指标详情' : '折叠详情'"
          @click="collapsed = !collapsed"
        >
          <svg
            class="h-4 w-4 transition-transform duration-200"
            :class="collapsed ? '-rotate-90' : 'rotate-0'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 展开的风控归因指标明细栏 -->
    <div
      v-if="!collapsed"
      class="border-t border-ui-hairline/60 bg-ui-surface/60 px-4 py-2.5 text-xs text-ui-text-2"
    >
      <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <!-- 宏观指数生命线 (MA60) -->
        <div class="rounded-lg bg-ui-page/70 border border-ui-hairline p-2.5">
          <div class="flex items-center justify-between text-ui-text-3 text-[11px]">
            <span>宏观指数生命线 (MA60)</span>
            <span
              class="font-bold"
              :class="current.breakdown?.macro_trend?.ok ? 'text-emerald-400' : 'text-red-400'"
            >
              {{ current.breakdown?.macro_trend?.status || '破位空头' }}
            </span>
          </div>
          <div class="mt-1 font-mono font-bold text-sm text-ui-text">
            中证1000: {{ current.close }}
            <span
              class="text-xs font-normal ml-1"
              :class="(current.breakdown?.macro_trend?.diff_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'"
            >
              {{ (current.breakdown?.macro_trend?.diff_pct ?? 0) >= 0 ? '+' : '' }}{{ fmtNum(current.breakdown?.macro_trend?.diff_pct, 1) }}%
            </span>
          </div>
          <p class="mt-1 text-[11px] text-ui-text-3 line-clamp-1">
            {{ current.breakdown?.macro_trend?.desc }}
          </p>
        </div>

        <!-- 全市场广度 (站上20日线比例) -->
        <div class="rounded-lg bg-ui-page/70 border border-ui-hairline p-2.5">
          <div class="flex items-center justify-between text-ui-text-3 text-[11px]">
            <span>全市场微观广度 (>MA20)</span>
            <span
              class="font-bold"
              :class="current.breakdown?.market_breadth?.ok ? 'text-emerald-400' : 'text-amber-400'"
            >
              {{ current.breakdown?.market_breadth?.status || '广度不足' }}
            </span>
          </div>
          <div class="mt-1 font-mono font-bold text-sm text-ui-text">
            当前广度: {{ fmtNum(current.breadth, 1) }}%
            <span class="text-xs font-normal text-ui-text-3 ml-1">(警戒线 28.0%)</span>
          </div>
          <p class="mt-1 text-[11px] text-ui-text-3 line-clamp-1">
            {{ current.breakdown?.market_breadth?.desc }}
          </p>
        </div>

        <!-- 操盘建议与仓位指令 -->
        <div class="rounded-lg bg-ui-page/70 border border-ui-hairline p-2.5">
          <div class="flex items-center justify-between text-ui-text-3 text-[11px]">
            <span>风控操盘纪律</span>
            <span v-if="lastFetched" class="text-[10px] text-ui-text-3 font-mono">更新于 {{ lastFetched }}</span>
          </div>
          <div class="mt-1 font-bold text-sm" :class="isOverweight ? 'text-red-400' : 'text-accent'">
            {{ isOverweight ? `需减仓 ${fmtNum(overweightDiff, 1)}% 降至 ${suggestedPct}% 以下` : `持仓合规 (上限 ${suggestedPct}%)` }}
          </div>
          <p class="mt-1 text-[11px] text-ui-text-3 line-clamp-1">
            {{ current.breakdown?.exit_progress?.desc || '需指数站稳MA20且广度回升至35%以上方可解除防守' }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
