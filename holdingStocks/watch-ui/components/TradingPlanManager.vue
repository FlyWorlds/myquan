<script setup lang="ts">
import type { TradingPlan } from '~/types/tradingPlan'

const props = defineProps<{
  // 紧凑模式（用于盯盘首页弹窗内），或全屏模式（用于复盘笔记页）
  compact?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'update:count', pendingCount: number): void
}>()

const items = ref<TradingPlan[]>([])
const loading = ref(true)
const error = ref('')
const busy = ref(false)
const filterStatus = ref<'all' | 'pending' | 'executed' | 'cancelled'>('pending')
const searchQuery = ref('')

// 编辑/新建表单
const isEditing = ref(false)
const formError = ref('')
const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' })
const draft = ref<TradingPlan>({
  id: '',
  title: '',
  code: '',
  name: '',
  date: today(),
  direction: '买入',
  target_price: null,
  stop_loss: null,
  target_profit: null,
  planned_position: '',
  strategy_tag: '策略1·援军战法',
  content: '',
  status: 'pending',
  pinned: false
})

const pendingDelete = ref<TradingPlan | null>(null)

async function loadPlans() {
  loading.value = true
  error.value = ''
  try {
    const res = await $fetch<{ items: TradingPlan[] }>('/api/trading-plans')
    items.value = res.items || []
    const pendingCount = items.value.filter(x => x.status === 'pending').length
    emit('update:count', pendingCount)
  } catch (err: any) {
    error.value = err?.data?.error || err?.message || '获取交易计划失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadPlans)

// 过滤后的列表（置顶优先，已由后端排序）
const filteredPlans = computed(() => {
  return items.value.filter(p => {
    if (filterStatus.value !== 'all' && p.status !== filterStatus.value) {
      return false
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      const str = `${p.title} ${p.code || ''} ${p.name || ''} ${p.content || ''} ${p.strategy_tag || ''}`.toLowerCase()
      if (!str.includes(q)) return false
    }
    return true
  })
})

const pendingCount = computed(() => items.value.filter(x => x.status === 'pending').length)
const executedCount = computed(() => items.value.filter(x => x.status === 'executed').length)

function openCreate() {
  draft.value = {
    id: '',
    title: '',
    code: '',
    name: '',
    date: today(),
    direction: '买入',
    target_price: null,
    stop_loss: null,
    target_profit: null,
    planned_position: '2成仓',
    strategy_tag: '策略1·援军战法',
    content: '',
    status: 'pending',
    pinned: false
  }
  formError.value = ''
  isEditing.value = true
}

function openEdit(plan: TradingPlan) {
  draft.value = { ...plan }
  formError.value = ''
  isEditing.value = true
}

async function submitForm() {
  if (busy.value) return
  busy.value = true
  formError.value = ''
  try {
    const payload = { ...draft.value }
    if (!payload.title.trim()) {
      if (payload.code || payload.name) {
        payload.title = `${payload.name || ''} ${payload.code ? `(${payload.code})` : ''}`.trim()
      } else {
        payload.title = '未命名交易计划'
      }
    }
    await $fetch<TradingPlan>('/api/trading-plans', {
      method: 'POST',
      body: payload
    })
    isEditing.value = false
    await loadPlans()
  } catch (err: any) {
    formError.value = err?.data?.error || err?.message || '保存失败，请检查输入'
  } finally {
    busy.value = false
  }
}

async function togglePin(plan: TradingPlan) {
  if (busy.value) return
  busy.value = true
  try {
    await $fetch<TradingPlan>('/api/trading-plans', {
      method: 'POST',
      body: { id: plan.id, action: 'toggle_pin', pinned: !plan.pinned }
    })
    await loadPlans()
  } catch (err: any) {
    alert(err?.data?.error || '操作失败')
  } finally {
    busy.value = false
  }
}

async function changeStatus(plan: TradingPlan, newStatus: string) {
  if (busy.value || plan.status === newStatus) return
  busy.value = true
  try {
    await $fetch<TradingPlan>('/api/trading-plans', {
      method: 'POST',
      body: { id: plan.id, action: 'toggle_status', status: newStatus }
    })
    await loadPlans()
  } catch (err: any) {
    alert(err?.data?.error || '状态切换失败')
  } finally {
    busy.value = false
  }
}

async function confirmDelete() {
  if (!pendingDelete.value || busy.value) return
  busy.value = true
  try {
    await $fetch('/api/trading-plans', {
      method: 'POST',
      body: { id: pendingDelete.value.id, action: 'delete' }
    })
    pendingDelete.value = null
    await loadPlans()
  } catch (err: any) {
    alert(err?.data?.error || '删除失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="trading-plan-container text-ui-text-1">
    <!-- 头部工具栏 -->
    <div class="flex flex-wrap items-center justify-between gap-3 pb-4 mb-4 border-b border-ui-border">
      <div class="flex items-center gap-3">
        <h2 class="text-xl font-bold flex items-center gap-2">
          <span class="text-amber-400">📋</span> 开盘交易计划
        </h2>
        <div class="flex items-center gap-1 text-xs">
          <span class="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-semibold border border-amber-500/30">
            待执行: {{ pendingCount }}
          </span>
          <span class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300">
            已执行: {{ executedCount }}
          </span>
          <span class="px-2 py-0.5 rounded-full bg-ui-surface text-ui-text-3">
            总计: {{ items.length }}
          </span>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <button
          type="button"
          class="btn-plan-create"
          @click="openCreate"
        >
          ＋ 新建交易计划
        </button>
        <button
          v-if="compact"
          type="button"
          class="btn btn-ghost text-xs"
          @click="emit('close')"
        >
          ✕ 关闭
        </button>
      </div>
    </div>

    <!-- 过滤器与搜索 -->
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4 text-xs">
      <div class="flex items-center gap-1 bg-ui-surface p-1 rounded-lg border border-ui-border">
        <button
          type="button"
          class="filter-tab"
          :class="{ active: filterStatus === 'pending' }"
          @click="filterStatus = 'pending'"
        >
          待执行 ({{ pendingCount }})
        </button>
        <button
          type="button"
          class="filter-tab"
          :class="{ active: filterStatus === 'all' }"
          @click="filterStatus = 'all'"
        >
          全部 ({{ items.length }})
        </button>
        <button
          type="button"
          class="filter-tab"
          :class="{ active: filterStatus === 'executed' }"
          @click="filterStatus = 'executed'"
        >
          已执行 ({{ executedCount }})
        </button>
        <button
          type="button"
          class="filter-tab"
          :class="{ active: filterStatus === 'cancelled' }"
          @click="filterStatus = 'cancelled'"
        >
          已取消
        </button>
      </div>

      <div class="relative w-48 sm:w-64">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索标的、代码、策略…"
          class="w-full px-3 py-1.5 text-xs rounded-lg bg-ui-surface border border-ui-border text-ui-text-1 placeholder-ui-text-3 focus:outline-none focus:border-amber-400"
        >
        <button
          v-if="searchQuery"
          type="button"
          class="absolute right-2 top-1.5 text-ui-text-3 hover:text-ui-text-1"
          @click="searchQuery = ''"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- 错误提醒 -->
    <div v-if="error" class="p-3 mb-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex justify-between items-center">
      <span>{{ error }}</span>
      <button class="underline ml-2" @click="loadPlans">重试</button>
    </div>

    <!-- 加载中 / 空列表 -->
    <div v-if="loading" class="py-12 text-center text-ui-text-3 text-sm">
      <span class="inline-block animate-spin mr-2">⏳</span> 正在加载交易计划…
    </div>

    <div v-else-if="filteredPlans.length === 0" class="py-12 text-center rounded-xl border border-dashed border-ui-border">
      <p class="text-3xl mb-2">📝</p>
      <p class="text-sm font-medium text-ui-text-2 mb-1">
        {{ filterStatus === 'pending' ? '当前没有待执行的交易计划' : '没有符合条件的交易计划' }}
      </p>
      <p class="text-xs text-ui-text-3 mb-4">开盘前过一遍计划，知行合一，从容交易</p>
      <button type="button" class="btn-plan-create text-xs" @click="openCreate">
        立即制定第一笔计划
      </button>
    </div>

    <!-- 计划卡片列表 -->
    <div v-else class="space-y-3">
      <div
        v-for="plan in filteredPlans"
        :key="plan.id"
        class="plan-card relative rounded-xl p-4 border transition-all"
        :class="[
          plan.pinned ? 'pinned border-amber-500/50 bg-amber-500/5' : 'border-ui-border bg-ui-surface hover:border-ui-border-hover',
          plan.status === 'executed' ? 'opacity-75' : ''
        ]"
      >
        <!-- 置顶标记条 -->
        <div v-if="plan.pinned" class="absolute top-0 left-0 bottom-0 w-1.5 bg-gradient-to-b from-amber-400 to-amber-600 rounded-l-xl" />

        <div class="flex flex-wrap items-start justify-between gap-3 mb-2">
          <!-- 标题与核心信息 -->
          <div class="flex items-center gap-2 flex-wrap">
            <span
              v-if="plan.pinned"
              class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40"
            >
              📌 置顶
            </span>
            <span
              class="px-2 py-0.5 rounded text-xs font-bold"
              :class="{
                'bg-red-500/20 text-red-300 border border-red-500/30': plan.direction === '买入' || plan.direction === '加仓',
                'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30': plan.direction === '卖出' || plan.direction === '减仓',
                'bg-blue-500/20 text-blue-300 border border-blue-500/30': plan.direction === '观察'
              }"
            >
              {{ plan.direction }}
            </span>
            <h3 class="text-base font-bold text-ui-text-1">
              {{ plan.title }}
            </h3>
            <span v-if="plan.code" class="text-xs font-mono text-ui-text-3">
              {{ plan.code }}
            </span>
            <span v-if="plan.strategy_tag" class="text-xs px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
              {{ plan.strategy_tag }}
            </span>
          </div>

          <!-- 右上角操作按钮栏 -->
          <div class="flex items-center gap-2 text-xs">
            <!-- 状态快速切换 -->
            <select
              :value="plan.status"
              class="px-2 py-1 rounded bg-ui-surface-2 border border-ui-border text-xs focus:outline-none"
              :class="{
                'text-amber-300 border-amber-500/40': plan.status === 'pending',
                'text-emerald-300 border-emerald-500/40': plan.status === 'executed',
                'text-ui-text-3': plan.status === 'cancelled'
              }"
              @change="e => changeStatus(plan, (e.target as HTMLSelectElement).value)"
            >
              <option value="pending">🟡 待执行</option>
              <option value="executed">🟢 已执行</option>
              <option value="cancelled">⚪ 已取消</option>
            </select>

            <!-- 置顶开关 -->
            <button
              type="button"
              class="px-2 py-1 rounded text-xs border border-ui-border transition-colors hover:bg-amber-500/10 hover:border-amber-500/40"
              :class="plan.pinned ? 'text-amber-400 bg-amber-500/10 border-amber-500/30' : 'text-ui-text-3'"
              title="切换置顶"
              @click="togglePin(plan)"
            >
              {{ plan.pinned ? '★ 取消置顶' : '☆ 置顶' }}
            </button>

            <!-- 编辑 -->
            <button
              type="button"
              class="px-2 py-1 rounded text-xs border border-ui-border text-ui-text-2 hover:text-ui-text-1 hover:border-ui-border-hover"
              @click="openEdit(plan)"
            >
              编辑
            </button>

            <!-- 删除 -->
            <button
              type="button"
              class="px-2 py-1 rounded text-xs text-red-400/70 hover:text-red-300 border border-transparent hover:border-red-500/30"
              @click="pendingDelete = plan"
            >
              删除
            </button>
          </div>
        </div>

        <!-- 点位与仓位参数一览 -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 my-2.5 p-2 rounded-lg bg-ui-bg/60 border border-ui-border/60 text-xs">
          <div>
            <span class="text-ui-text-3">计划买点/触发价:</span>
            <span class="ml-1 font-mono font-semibold" :class="plan.target_price ? 'text-amber-300' : 'text-ui-text-3'">
              {{ plan.target_price != null ? `¥${plan.target_price.toFixed(2)}` : '盘中现价/自定' }}
            </span>
          </div>
          <div>
            <span class="text-ui-text-3">防守止损位:</span>
            <span class="ml-1 font-mono font-semibold" :class="plan.stop_loss ? 'text-red-400' : 'text-ui-text-3'">
              {{ plan.stop_loss != null ? `¥${plan.stop_loss.toFixed(2)}` : '严格-1%/保护线' }}
            </span>
          </div>
          <div>
            <span class="text-ui-text-3">预期止盈位:</span>
            <span class="ml-1 font-mono font-semibold" :class="plan.target_profit ? 'text-emerald-400' : 'text-ui-text-3'">
              {{ plan.target_profit != null ? `¥${plan.target_profit.toFixed(2)}` : '多层止盈' }}
            </span>
          </div>
          <div>
            <span class="text-ui-text-3">预设仓位:</span>
            <span class="ml-1 font-semibold text-ui-text-1">
              {{ plan.planned_position || '标准1槽(20%)' }}
            </span>
          </div>
        </div>

        <!-- 计划逻辑与前置条件 -->
        <div v-if="plan.content" class="text-xs text-ui-text-2 leading-relaxed bg-ui-surface/50 p-2.5 rounded border border-ui-border/40 whitespace-pre-line">
          {{ plan.content }}
        </div>

        <div class="flex items-center justify-between text-[11px] text-ui-text-3 mt-2.5">
          <span>📅 计划日期: {{ plan.date }}</span>
          <span v-if="plan.updated_at">更新于: {{ plan.updated_at.replace('T', ' ').slice(0, 19) }}</span>
        </div>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <div
      v-if="isEditing"
      class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto"
      @keydown.esc="isEditing = false"
    >
      <div class="bg-ui-surface-2 border border-ui-border rounded-2xl w-full max-w-xl p-6 shadow-2xl relative my-8">
        <div class="flex items-center justify-between pb-3 mb-4 border-b border-ui-border">
          <h3 class="text-lg font-bold flex items-center gap-2">
            <span>{{ draft.id ? '✏️ 编辑交易计划' : '📝 新建交易计划' }}</span>
          </h3>
          <button
            type="button"
            class="text-ui-text-3 hover:text-ui-text-1 text-lg"
            @click="isEditing = false"
          >
            ✕
          </button>
        </div>

        <div v-if="formError" class="p-2.5 mb-4 rounded bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
          {{ formError }}
        </div>

        <form class="space-y-3.5 text-xs" @submit.prevent="submitForm">
          <!-- 标题与日期 -->
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div class="sm:col-span-2">
              <label class="block text-ui-text-3 mb-1">计划标题 / 标的名称 <span class="text-red-400">*</span></label>
              <input
                v-model="draft.title"
                type="text"
                placeholder="例如: 视源股份回踩低吸 / 早盘冲高止盈"
                required
                class="form-input"
              >
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">计划所属交易日</label>
              <input
                v-model="draft.date"
                type="date"
                required
                class="form-input"
              >
            </div>
          </div>

          <!-- 代码与方向 -->
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-ui-text-3 mb-1">股票代码 (选填)</label>
              <input
                v-model="draft.code"
                type="text"
                placeholder="如 002841"
                class="form-input font-mono"
              >
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">操作方向</label>
              <select v-model="draft.direction" class="form-input">
                <option value="买入">买入</option>
                <option value="加仓">加仓</option>
                <option value="卖出">卖出</option>
                <option value="减仓">减仓</option>
                <option value="观察">观察</option>
              </select>
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">关联策略</label>
              <input
                v-model="draft.strategy_tag"
                type="text"
                placeholder="如 策略1·援军战法"
                class="form-input"
              >
            </div>
          </div>

          <!-- 点位参数 -->
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-ui-text-3 mb-1">目标买点 / 挂单价</label>
              <input
                v-model.number="draft.target_price"
                type="number"
                step="0.01"
                placeholder="例如 42.10"
                class="form-input font-mono"
              >
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">防守止损价</label>
              <input
                v-model.number="draft.stop_loss"
                type="number"
                step="0.01"
                placeholder="例如 41.49"
                class="form-input font-mono"
              >
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">预期止盈目标</label>
              <input
                v-model.number="draft.target_profit"
                type="number"
                step="0.01"
                placeholder="例如 44.50"
                class="form-input font-mono"
              >
            </div>
          </div>

          <!-- 计划仓位与置顶 -->
          <div class="grid grid-cols-2 gap-3 items-center">
            <div>
              <label class="block text-ui-text-3 mb-1">预设仓位</label>
              <input
                v-model="draft.planned_position"
                type="text"
                placeholder="如 1成仓 / 20% / 1000股"
                class="form-input"
              >
            </div>
            <div class="pt-5 flex items-center gap-2">
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input
                  v-model="draft.pinned"
                  type="checkbox"
                  class="rounded bg-ui-surface border-ui-border text-amber-500 focus:ring-amber-400"
                >
                <span class="font-medium text-amber-300">📌 置顶此交易计划 (开盘重点看)</span>
              </label>
            </div>
          </div>

          <!-- 交易逻辑与前置条件 -->
          <div>
            <label class="block text-ui-text-3 mb-1">前置条件、交易逻辑与复核要点</label>
            <textarea
              v-model="draft.content"
              rows="4"
              placeholder="1. 集合竞价情况：开盘涨幅在什么范围？\n2. 盘中走势：分时黄线上方回踩企稳方可介入。\n3. 破位应对：10点前跌破-1%无条件出局，坚决执行纪律。"
              class="form-input resize-y"
            />
          </div>

          <!-- 底部按钮 -->
          <div class="flex items-center justify-end gap-3 pt-4 border-t border-ui-border">
            <button
              type="button"
              class="btn btn-ghost text-xs"
              @click="isEditing = false"
            >
              取消
            </button>
            <button
              type="submit"
              class="btn-plan-create text-xs"
              :disabled="busy"
            >
              {{ busy ? '保存中…' : '保存交易计划' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <div
      v-if="pendingDelete"
      class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
    >
      <div class="bg-ui-surface-2 border border-ui-border rounded-xl w-full max-w-sm p-5 shadow-2xl text-xs">
        <h4 class="text-sm font-bold text-red-400 mb-2">确认删除该交易计划？</h4>
        <p class="text-ui-text-2 mb-4">
          「{{ pendingDelete.title }}」将被永久移除。
        </p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="btn btn-ghost"
            @click="pendingDelete = null"
          >
            取消
          </button>
          <button
            type="button"
            class="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white font-medium"
            :disabled="busy"
            @click="confirmDelete"
          >
            {{ busy ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trading-plan-container {
  width: 100%;
}

.btn-plan-create {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #fff;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 8px;
  transition: all 0.2s;
  box-shadow: 0 2px 10px rgba(245, 158, 11, 0.25);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.btn-plan-create:hover {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.4);
  transform: translateY(-1px);
}

.filter-tab {
  padding: 4px 10px;
  border-radius: 6px;
  color: var(--ui-text-3, #9ca3af);
  transition: all 0.2s;
}
.filter-tab:hover {
  color: var(--ui-text-1, #f3f4f6);
}
.filter-tab.active {
  background: rgba(245, 158, 11, 0.2);
  color: #fbbf24;
  font-weight: 600;
}

.form-input {
  width: 100%;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--ui-border, rgba(255, 255, 255, 0.12));
  color: inherit;
  transition: border-color 0.2s;
}
.form-input:focus {
  outline: none;
  border-color: #f59e0b;
}

.plan-card.pinned {
  box-shadow: 0 0 15px rgba(245, 158, 11, 0.12);
}
</style>
