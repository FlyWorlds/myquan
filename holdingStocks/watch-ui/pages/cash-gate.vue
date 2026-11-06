<script setup lang="ts">
import type { Strategy35Payload, Strategy36Payload } from '~/types/snapshot'

useHead({ title: '多维空仓 · 持仓盯盘' })

type CashGateTab = 'market' | 'tech'

const activeTab = ref<CashGateTab>('market')
const loading = ref(false)

const marketPayload = ref<Strategy35Payload | null>(null)
const techPayload = ref<Strategy36Payload | null>(null)

async function refreshAll() {
  loading.value = true
  try {
    const [res35, res36] = await Promise.all([
      fetch('/api/strategy35/timing-state').then((r) => (r.ok ? r.json() : null)),
      fetch('/api/strategy36/timing-state').then((r) => (r.ok ? r.json() : null)),
    ])
    if (res35) marketPayload.value = res35
    if (res36) techPayload.value = res36
  } catch (err) {
    console.error('Failed to refresh cash gate timing states:', err)
  } finally {
    loading.value = false
    nextTick(() => {
      window.dispatchEvent(new Event('resize'))
    })
  }
}

function switchTab(tab: CashGateTab) {
  activeTab.value = tab
  nextTick(() => {
    window.dispatchEvent(new Event('resize'))
  })
}

onMounted(() => {
  refreshAll()
})
</script>

<template>
  <main class="page-shell py-6">
    <!-- 头部说明与操作区 -->
    <header class="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="mb-1 text-xs font-semibold tracking-widest text-accent">RISK CONTROL & CASH DEFENSE</p>
        <h1 class="text-2xl font-bold">多维空仓择时</h1>
        <p class="mt-2 text-sm text-ui-text-2">
          全市场宽基与科技成长专属空仓防御中心。基于全市场及成长池 20 日均线广度、核心指数生命线与极端熔断机制，动态规避系统性下行风险。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <NuxtLink to="/strategies" class="btn text-xs text-ui-text-2 hover:text-accent">
          策略文档 ↗
        </NuxtLink>
        <button
          class="btn text-xs font-semibold text-accent"
          :disabled="loading"
          @click="refreshAll"
        >
          {{ loading ? '更新中…' : '刷新择时状态' }}
        </button>
      </div>
    </header>

    <!-- 顶部综合状态罗盘卡片 -->
    <div class="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
      <!-- 全市场多维空仓概览 -->
      <div
        class="card cursor-pointer p-4 transition-all duration-200 border-2"
        :class="activeTab === 'market' ? 'border-accent shadow-md bg-ui-fill-hover/20' : 'border-transparent hover:border-ui-hairline'"
        @click="switchTab('market')"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span
              class="inline-block h-2.5 w-2.5 rounded-full"
              :class="marketPayload?.current?.tier === 1 ? 'bg-red-500 animate-pulse' : (marketPayload?.current?.tier === 2 ? 'bg-orange-500 animate-pulse' : (marketPayload?.current?.tier === 3 ? 'bg-amber-400' : 'bg-emerald-500'))"
            ></span>
            <span class="font-semibold text-sm">全市场阶梯空仓</span>
            <span class="text-xs font-mono text-ui-text-3">宽基·中证1000</span>
          </div>
          <span
            class="rounded px-2 py-0.5 text-xs font-bold font-mono"
            :class="marketPayload?.current?.tier === 1 ? 'bg-red-500/20 text-red-400 border border-red-500/40' : (marketPayload?.current?.tier === 2 ? 'bg-orange-500/20 text-orange-400 border border-orange-500/40' : (marketPayload?.current?.tier === 3 ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'))"
          >
            {{ marketPayload?.current?.tier === 1 ? '阶梯1·极端熔断' : (marketPayload?.current?.tier === 2 ? '阶梯2·轻仓防守' : (marketPayload?.current?.tier === 3 ? '阶梯3·减速控仓' : '阶梯4·全面进攻')) }}
          </span>
        </div>

        <div class="mt-3 flex items-baseline justify-between text-xs text-ui-text-2">
          <div>
            全市场广度：
            <span class="font-mono text-base font-bold text-ui-text">
              {{ marketPayload?.current?.breadth != null ? marketPayload.current.breadth.toFixed(1) + '%' : '—' }}
            </span>
          </div>
          <div class="text-right">
            建议阶梯仓位：
            <span
              class="font-mono font-bold text-base"
              :class="marketPayload?.current?.tier === 1 ? 'text-red-400' : (marketPayload?.current?.tier === 2 ? 'text-orange-400' : (marketPayload?.current?.tier === 3 ? 'text-amber-400' : 'text-emerald-400'))"
            >
              {{ marketPayload?.current ? Math.round((marketPayload.current.position_ratio ?? 0.3) * 100) + '%' : '—' }}
            </span>
          </div>
        </div>

        <!-- 四级阶梯台阶尺 -->
        <div class="mt-3 grid grid-cols-4 gap-1.5 pt-1">
          <div
            v-for="step in [
              { t: 1, p: '0%', l: '熔断' },
              { t: 2, p: '30%', l: '防守' },
              { t: 3, p: '60%', l: '控仓' },
              { t: 4, p: '100%', l: '进攻' }
            ]"
            :key="step.t"
            class="flex flex-col items-center rounded-lg border py-1.5 px-1 transition-all"
            :class="(marketPayload?.current?.tier ?? 2) === step.t
              ? 'border-accent bg-accent/20 text-accent font-bold shadow-sm'
              : 'border-ui-hairline/40 bg-ui-surface/40 text-ui-text-3'"
          >
            <div class="text-[10px] scale-90">{{ step.l }}</div>
            <div class="text-xs font-mono font-bold">{{ step.p }}</div>
          </div>
        </div>

        <p class="mt-2.5 line-clamp-1 text-xs text-ui-text-3">
          {{ marketPayload?.current?.reason || '全市场广度阶梯跟踪正常' }}
        </p>
      </div>

      <!-- 科技成长多维空仓概览 -->
      <div
        class="card cursor-pointer p-4 transition-all duration-200 border-2"
        :class="activeTab === 'tech' ? 'border-accent shadow-md bg-ui-fill-hover/20' : 'border-transparent hover:border-ui-hairline'"
        @click="switchTab('tech')"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span
              class="inline-block h-2.5 w-2.5 rounded-full"
              :class="techPayload?.current?.tier === 1 ? 'bg-red-500 animate-pulse' : (techPayload?.current?.tier === 2 ? 'bg-orange-500 animate-pulse' : (techPayload?.current?.tier === 3 ? 'bg-amber-400' : 'bg-emerald-500'))"
            ></span>
            <span class="font-semibold text-sm">科技成长阶梯空仓</span>
            <span class="text-xs font-mono text-ui-text-3">创·科·深成指</span>
          </div>
          <span
            class="rounded px-2 py-0.5 text-xs font-bold font-mono"
            :class="techPayload?.current?.tier === 1 ? 'bg-red-500/20 text-red-400 border border-red-500/40' : (techPayload?.current?.tier === 2 ? 'bg-orange-500/20 text-orange-400 border border-orange-500/40' : (techPayload?.current?.tier === 3 ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'))"
          >
            {{ techPayload?.current?.tier === 1 ? '阶梯1·极端熔断' : (techPayload?.current?.tier === 2 ? '阶梯2·轻仓防守' : (techPayload?.current?.tier === 3 ? '阶梯3·减速控仓' : '阶梯4·全面进攻')) }}
          </span>
        </div>

        <div class="mt-3 flex items-baseline justify-between text-xs text-ui-text-2">
          <div>
            科技池广度：
            <span class="font-mono text-base font-bold text-ui-text">
              {{ techPayload?.current?.tech_breadth != null ? techPayload.current.tech_breadth.toFixed(1) + '%' : '—' }}
            </span>
          </div>
          <div class="text-right">
            科技建议阶梯仓位：
            <span
              class="font-mono font-bold text-base"
              :class="techPayload?.current?.tier === 1 ? 'text-red-400' : (techPayload?.current?.tier === 2 ? 'text-orange-400' : (techPayload?.current?.tier === 3 ? 'text-amber-400' : 'text-emerald-400'))"
            >
              {{ techPayload?.current ? Math.round((techPayload.current.position_ratio ?? 0.3) * 100) + '%' : '—' }}
            </span>
          </div>
        </div>

        <!-- 四级阶梯台阶尺 -->
        <div class="mt-3 grid grid-cols-4 gap-1.5 pt-1">
          <div
            v-for="step in [
              { t: 1, p: '0%', l: '熔断' },
              { t: 2, p: '30%', l: '防守' },
              { t: 3, p: '60%', l: '控仓' },
              { t: 4, p: '100%', l: '进攻' }
            ]"
            :key="step.t"
            class="flex flex-col items-center rounded-lg border py-1.5 px-1 transition-all"
            :class="(techPayload?.current?.tier ?? 2) === step.t
              ? 'border-accent bg-accent/20 text-accent font-bold shadow-sm'
              : 'border-ui-hairline/40 bg-ui-surface/40 text-ui-text-3'"
          >
            <div class="text-[10px] scale-90">{{ step.l }}</div>
            <div class="text-xs font-mono font-bold">{{ step.p }}</div>
          </div>
        </div>

        <p class="mt-2.5 line-clamp-1 text-xs text-ui-text-3">
          {{ techPayload?.current?.reason || '科技池广度阶梯跟踪正常' }}
        </p>
      </div>
    </div>

    <!-- 聚合 Tab 控制器 -->
    <div class="mb-5 flex border-b border-ui-hairline">
      <button
        class="relative px-5 py-2.5 text-sm font-semibold transition-colors flex items-center gap-2"
        :class="activeTab === 'market' ? 'text-accent border-b-2 border-accent font-bold' : 'text-ui-text-2 hover:text-ui-text'"
        @click="switchTab('market')"
      >
        <span>全市场多维空仓</span>
        <span class="text-xs px-1.5 py-0.2 rounded bg-ui-fill-hover text-ui-text-3 font-mono">策略35</span>
      </button>
      <button
        class="relative px-5 py-2.5 text-sm font-semibold transition-colors flex items-center gap-2"
        :class="activeTab === 'tech' ? 'text-accent border-b-2 border-accent font-bold' : 'text-ui-text-2 hover:text-ui-text'"
        @click="switchTab('tech')"
      >
        <span>科技成长多维空仓</span>
        <span class="text-xs px-1.5 py-0.2 rounded bg-ui-fill-hover text-ui-text-3 font-mono">策略36</span>
      </button>
    </div>

    <!-- Tab 1: 全市场多维空仓面板 -->
    <section v-show="activeTab === 'market'">
      <Strategy35Panel :payload="marketPayload" />
    </section>

    <!-- Tab 2: 科技成长多维空仓面板 -->
    <section v-show="activeTab === 'tech'">
      <Strategy36Panel :payload="techPayload" />
    </section>
  </main>
</template>
