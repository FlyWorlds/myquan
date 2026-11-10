<script setup lang="ts">
import type { ProjectTodo, TodoCategory, TodoPriority, TodoStatus } from '~/types/projectTodo'

const emit = defineEmits<{
  (e: 'update:count', pendingCount: number): void
}>()

const items = ref<ProjectTodo[]>([])
const loading = ref(true)
const error = ref('')
const busy = ref(false)

// 筛选与搜索
const filterStatus = ref<string>('active') // active = todo + in_progress, all, todo, in_progress, done, deferred
const filterCategory = ref<string>('all')
const searchQuery = ref('')

// 编辑/新建表单
const isEditing = ref(false)
const formError = ref('')
const draft = ref<ProjectTodo>({
  id: '',
  title: '',
  category: '策略优化',
  priority: 'P1',
  status: 'todo',
  content: '',
  target_date: '',
  pinned: false
})

const pendingDelete = ref<ProjectTodo | null>(null)

async function loadTodos() {
  loading.value = true
  error.value = ''
  try {
    const res = await $fetch<{ items: ProjectTodo[] }>('/api/project-todos')
    items.value = res.items || []
    const pendingCount = items.value.filter(x => x.status === 'todo' || x.status === 'in_progress').length
    emit('update:count', pendingCount)
  } catch (err: any) {
    error.value = err?.data?.error || err?.message || '获取项目改造待办失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadTodos)

// 统计数据
const todoCount = computed(() => items.value.filter(x => x.status === 'todo').length)
const inProgressCount = computed(() => items.value.filter(x => x.status === 'in_progress').length)
const doneCount = computed(() => items.value.filter(x => x.status === 'done').length)
const totalCount = computed(() => items.value.length)
const completionRate = computed(() => {
  if (totalCount.value === 0) return 0
  return Math.round((doneCount.value / totalCount.value) * 100)
})

// 过滤后的列表
const filteredTodos = computed(() => {
  return items.value.filter(item => {
    // 状态过滤
    if (filterStatus.value === 'active') {
      if (item.status !== 'todo' && item.status !== 'in_progress') return false
    } else if (filterStatus.value !== 'all' && item.status !== filterStatus.value) {
      return false
    }

    // 分类过滤
    if (filterCategory.value !== 'all' && item.category !== filterCategory.value) {
      return false
    }

    // 搜索
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      const str = `${item.title} ${item.category} ${item.content || ''} ${item.priority}`.toLowerCase()
      if (!str.includes(q)) return false
    }

    return true
  })
})

function openCreate() {
  draft.value = {
    id: '',
    title: '',
    category: '策略优化',
    priority: 'P1',
    status: 'todo',
    content: '',
    target_date: '',
    pinned: false
  }
  formError.value = ''
  isEditing.value = true
}

function openEdit(todo: ProjectTodo) {
  draft.value = { ...todo }
  formError.value = ''
  isEditing.value = true
}

async function submitForm() {
  if (busy.value) return
  if (!draft.value.title.trim()) {
    formError.value = '请填写事项标题'
    return
  }
  busy.value = true
  formError.value = ''
  try {
    await $fetch<ProjectTodo>('/api/project-todos', {
      method: 'POST',
      body: { ...draft.value }
    })
    isEditing.value = false
    await loadTodos()
  } catch (err: any) {
    formError.value = err?.data?.error || err?.message || '保存失败，请检查输入'
  } finally {
    busy.value = false
  }
}

async function togglePin(todo: ProjectTodo) {
  if (busy.value) return
  busy.value = true
  try {
    await $fetch<ProjectTodo>('/api/project-todos', {
      method: 'POST',
      body: { id: todo.id, action: 'toggle_pin', pinned: !todo.pinned }
    })
    await loadTodos()
  } catch (err: any) {
    alert(err?.data?.error || '操作失败')
  } finally {
    busy.value = false
  }
}

async function changeStatus(todo: ProjectTodo, newStatus: string) {
  if (busy.value || todo.status === newStatus) return
  busy.value = true
  try {
    await $fetch<ProjectTodo>('/api/project-todos', {
      method: 'POST',
      body: { id: todo.id, action: 'toggle_status', status: newStatus }
    })
    await loadTodos()
  } catch (err: any) {
    alert(err?.data?.error || '状态流转失败')
  } finally {
    busy.value = false
  }
}

async function confirmDelete() {
  if (!pendingDelete.value || busy.value) return
  busy.value = true
  try {
    await $fetch('/api/project-todos', {
      method: 'POST',
      body: { id: pendingDelete.value.id, action: 'delete' }
    })
    pendingDelete.value = null
    await loadTodos()
  } catch (err: any) {
    alert(err?.data?.error || '删除失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="project-todos-container text-ui-text-1">
    <!-- 统计指标看板 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      <div class="p-3.5 rounded-xl bg-ui-surface border border-ui-border flex items-center justify-between">
        <div>
          <div class="text-[11px] text-ui-text-3 font-medium">待处理 (Todo)</div>
          <div class="text-xl font-bold text-amber-400 mt-0.5">{{ todoCount }} 个</div>
        </div>
        <span class="text-2xl opacity-80">⏳</span>
      </div>

      <div class="p-3.5 rounded-xl bg-ui-surface border border-ui-border flex items-center justify-between">
        <div>
          <div class="text-[11px] text-ui-text-3 font-medium">进行中 (In Progress)</div>
          <div class="text-xl font-bold text-cyan-400 mt-0.5">{{ inProgressCount }} 个</div>
        </div>
        <span class="text-2xl opacity-80">⚡</span>
      </div>

      <div class="p-3.5 rounded-xl bg-ui-surface border border-ui-border flex items-center justify-between">
        <div>
          <div class="text-[11px] text-ui-text-3 font-medium">已完成 (Done)</div>
          <div class="text-xl font-bold text-emerald-400 mt-0.5">{{ doneCount }} 个</div>
        </div>
        <span class="text-2xl opacity-80">✅</span>
      </div>

      <div class="p-3.5 rounded-xl bg-ui-surface border border-ui-border flex flex-col justify-between">
        <div class="flex items-center justify-between text-[11px]">
          <span class="text-ui-text-3 font-medium">改造推进度</span>
          <span class="font-bold text-ui-text-1">{{ completionRate }}%</span>
        </div>
        <div class="w-full h-2 rounded-full bg-ui-bg overflow-hidden mt-2">
          <div
            class="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-500 transition-all duration-500"
            :style="{ width: `${completionRate}%` }"
          />
        </div>
      </div>
    </div>

    <!-- 顶部操作栏 -->
    <div class="flex flex-wrap items-center justify-between gap-3 pb-4 mb-4 border-b border-ui-border">
      <div class="flex items-center gap-3">
        <h2 class="text-xl font-bold flex items-center gap-2">
          <span class="text-cyan-400">🛠️</span> 项目改造跟踪
        </h2>
        <span class="text-xs text-ui-text-3">系统架构优化、策略逻辑升级、性能提速事项台账</span>
      </div>

      <button
        type="button"
        class="btn-todo-create"
        @click="openCreate"
      >
        ＋ 新增改造事项
      </button>
    </div>

    <!-- 过滤器与搜索栏 -->
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4 text-xs">
      <div class="flex flex-wrap items-center gap-2">
        <!-- 状态 Tab -->
        <div class="flex items-center gap-1 bg-ui-surface p-1 rounded-lg border border-ui-border">
          <button
            type="button"
            class="filter-tab"
            :class="{ active: filterStatus === 'active' }"
            @click="filterStatus = 'active'"
          >
            🔥 活跃中 ({{ todoCount + inProgressCount }})
          </button>
          <button
            type="button"
            class="filter-tab"
            :class="{ active: filterStatus === 'all' }"
            @click="filterStatus = 'all'"
          >
            全部 ({{ totalCount }})
          </button>
          <button
            type="button"
            class="filter-tab"
            :class="{ active: filterStatus === 'todo' }"
            @click="filterStatus = 'todo'"
          >
            待办 ({{ todoCount }})
          </button>
          <button
            type="button"
            class="filter-tab"
            :class="{ active: filterStatus === 'in_progress' }"
            @click="filterStatus = 'in_progress'"
          >
            进行中 ({{ inProgressCount }})
          </button>
          <button
            type="button"
            class="filter-tab"
            :class="{ active: filterStatus === 'done' }"
            @click="filterStatus = 'done'"
          >
            已完成 ({{ doneCount }})
          </button>
        </div>

        <!-- 分类下拉 -->
        <select
          v-model="filterCategory"
          class="px-2.5 py-1.5 rounded-lg bg-ui-surface border border-ui-border text-ui-text-2 focus:outline-none focus:border-cyan-400"
        >
          <option value="all">📁 全部模块</option>
          <option value="策略优化">策略优化</option>
          <option value="性能加速">性能加速</option>
          <option value="风控止损">风控止损</option>
          <option value="前端UI">前端UI</option>
          <option value="数据接口">数据接口</option>
          <option value="其他">其他</option>
        </select>
      </div>

      <!-- 搜索框 -->
      <div class="relative w-48 sm:w-64">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索改造事项、关键词…"
          class="w-full px-3 py-1.5 text-xs rounded-lg bg-ui-surface border border-ui-border text-ui-text-1 placeholder-ui-text-3 focus:outline-none focus:border-cyan-400"
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

    <!-- 错误提示 -->
    <div v-if="error" class="p-3 mb-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs flex justify-between items-center">
      <span>{{ error }}</span>
      <button class="underline ml-2" @click="loadTodos">重试</button>
    </div>

    <!-- 加载中 / 空列表 -->
    <div v-if="loading" class="py-12 text-center text-ui-text-3 text-sm">
      <span class="inline-block animate-spin mr-2">⚙️</span> 正在加载改造事项…
    </div>

    <div v-else-if="filteredTodos.length === 0" class="py-12 text-center rounded-xl border border-dashed border-ui-border">
      <p class="text-3xl mb-2">🎉</p>
      <p class="text-sm font-medium text-ui-text-2 mb-1">
        {{ filterStatus === 'active' ? '当前没有待处理的改造事项' : '没有符合条件的事项' }}
      </p>
      <p class="text-xs text-ui-text-3 mb-4">记录架构重构、Bug 修复与策略调优要点，持续迭代量化系统</p>
      <button type="button" class="btn-todo-create text-xs" @click="openCreate">
        创建第一条改造事项
      </button>
    </div>

    <!-- 事项列表 -->
    <div v-else class="space-y-3">
      <div
        v-for="todo in filteredTodos"
        :key="todo.id"
        class="todo-card relative rounded-xl p-4 border transition-all"
        :class="[
          todo.pinned ? 'pinned border-cyan-500/50 bg-cyan-500/5' : 'border-ui-border bg-ui-surface hover:border-ui-border-hover',
          todo.status === 'done' ? 'opacity-70 bg-emerald-500/[0.02]' : ''
        ]"
      >
        <!-- 置顶条 -->
        <div v-if="todo.pinned" class="absolute top-0 left-0 bottom-0 w-1.5 bg-gradient-to-b from-cyan-400 to-blue-600 rounded-l-xl" />

        <div class="flex flex-wrap items-start justify-between gap-3 mb-2">
          <!-- 标题与标签 -->
          <div class="flex items-center gap-2 flex-wrap flex-1 min-w-0">
            <!-- 快捷完成打勾复选框 -->
            <button
              type="button"
              class="w-5 h-5 rounded border flex items-center justify-center transition-all"
              :class="todo.status === 'done' ? 'bg-emerald-500 border-emerald-500 text-black font-bold' : 'border-ui-border hover:border-emerald-400 text-transparent'"
              :title="todo.status === 'done' ? '标记为待办' : '标记为已完成'"
              @click="changeStatus(todo, todo.status === 'done' ? 'todo' : 'done')"
            >
              ✓
            </button>

            <span
              v-if="todo.pinned"
              class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
            >
              📌 重点跟踪
            </span>

            <!-- 优先级 -->
            <span
              class="px-1.5 py-0.5 rounded text-[10px] font-bold"
              :class="{
                'bg-red-500/20 text-red-300 border border-red-500/40': todo.priority === 'P0',
                'bg-amber-500/20 text-amber-300 border border-amber-500/40': todo.priority === 'P1',
                'bg-blue-500/20 text-blue-300 border border-blue-500/40': todo.priority === 'P2'
              }"
            >
              {{ todo.priority }}
            </span>

            <!-- 分类 -->
            <span class="px-2 py-0.5 rounded text-xs bg-ui-surface-2 text-ui-text-2 border border-ui-border">
              {{ todo.category }}
            </span>

            <!-- 标题 -->
            <h3
              class="text-base font-bold text-ui-text-1 break-all"
              :class="{ 'line-through text-ui-text-3 font-normal': todo.status === 'done' }"
            >
              {{ todo.title }}
            </h3>
          </div>

          <!-- 右侧操作栏 -->
          <div class="flex items-center gap-2 text-xs">
            <!-- 状态切换 -->
            <select
              :value="todo.status"
              class="px-2 py-1 rounded bg-ui-surface-2 border border-ui-border text-xs focus:outline-none"
              :class="{
                'text-amber-300 border-amber-500/40': todo.status === 'todo',
                'text-cyan-300 border-cyan-500/40': todo.status === 'in_progress',
                'text-emerald-300 border-emerald-500/40': todo.status === 'done',
                'text-ui-text-3': todo.status === 'deferred'
              }"
              @change="e => changeStatus(todo, (e.target as HTMLSelectElement).value)"
            >
              <option value="todo">⏳ 待处理</option>
              <option value="in_progress">⚡ 进行中</option>
              <option value="done">✅ 已完成</option>
              <option value="deferred">💤 已搁置</option>
            </select>

            <!-- 置顶开关 -->
            <button
              type="button"
              class="px-2 py-1 rounded text-xs border border-ui-border transition-colors hover:bg-cyan-500/10 hover:border-cyan-500/40"
              :class="todo.pinned ? 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30' : 'text-ui-text-3'"
              title="切换置顶"
              @click="togglePin(todo)"
            >
              {{ todo.pinned ? '★ 取消置顶' : '☆ 置顶' }}
            </button>

            <!-- 编辑 -->
            <button
              type="button"
              class="px-2 py-1 rounded text-xs border border-ui-border text-ui-text-2 hover:text-ui-text-1 hover:border-ui-border-hover"
              @click="openEdit(todo)"
            >
              编辑
            </button>

            <!-- 删除 -->
            <button
              type="button"
              class="px-2 py-1 rounded text-xs text-red-400/70 hover:text-red-300 border border-transparent hover:border-red-500/30"
              @click="pendingDelete = todo"
            >
              删除
            </button>
          </div>
        </div>

        <!-- 详细内容 / 改造思路 / 涉及文件 -->
        <div v-if="todo.content" class="text-xs text-ui-text-2 leading-relaxed bg-ui-surface-2/60 p-3 rounded-lg border border-ui-border/50 my-2.5 whitespace-pre-line">
          {{ todo.content }}
        </div>

        <!-- 底部元数据 -->
        <div class="flex items-center justify-between text-[11px] text-ui-text-3 mt-2">
          <div class="flex items-center gap-3">
            <span v-if="todo.target_date">🎯 目标排期: {{ todo.target_date }}</span>
            <span>更新于: {{ todo.updated_at?.replace('T', ' ').slice(0, 19) }}</span>
          </div>
          <span
            class="px-2 py-0.5 rounded text-[10px]"
            :class="{
              'bg-amber-500/10 text-amber-300': todo.status === 'todo',
              'bg-cyan-500/10 text-cyan-300': todo.status === 'in_progress',
              'bg-emerald-500/10 text-emerald-300': todo.status === 'done',
              'bg-gray-500/10 text-gray-400': todo.status === 'deferred'
            }"
          >
            {{ todo.status === 'todo' ? '等待排期改造' : todo.status === 'in_progress' ? '正在重构实现' : todo.status === 'done' ? '已验证上线' : '已暂缓' }}
          </span>
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
            <span>{{ draft.id ? '✏️ 编辑改造事项' : '🛠️ 新增项目改造事项' }}</span>
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
          <!-- 标题 -->
          <div>
            <label class="block text-ui-text-3 mb-1">改造事项标题 <span class="text-red-400">*</span></label>
            <input
              v-model="draft.title"
              type="text"
              placeholder="例如: 策略1选股池完全覆盖与未闭环保留解耦"
              required
              class="form-input text-sm"
            >
          </div>

          <!-- 分类、优先级与状态 -->
          <div class="grid grid-cols-3 gap-3">
            <div>
              <label class="block text-ui-text-3 mb-1">所属模块</label>
              <select v-model="draft.category" class="form-input">
                <option value="策略优化">策略优化</option>
                <option value="性能加速">性能加速</option>
                <option value="风控止损">风控止损</option>
                <option value="前端UI">前端UI</option>
                <option value="数据接口">数据接口</option>
                <option value="其他">其他</option>
              </select>
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">优先级</label>
              <select v-model="draft.priority" class="form-input">
                <option value="P0">P0 (关键/阻断)</option>
                <option value="P1">P1 (常规迭代)</option>
                <option value="P2">P2 (规划储备)</option>
              </select>
            </div>
            <div>
              <label class="block text-ui-text-3 mb-1">当前进度</label>
              <select v-model="draft.status" class="form-input">
                <option value="todo">⏳ 待处理</option>
                <option value="in_progress">⚡ 进行中</option>
                <option value="done">✅ 已完成</option>
                <option value="deferred">💤 已搁置</option>
              </select>
            </div>
          </div>

          <!-- 目标日期与置顶 -->
          <div class="grid grid-cols-2 gap-3 items-center">
            <div>
              <label class="block text-ui-text-3 mb-1">目标排期 / 截止日期</label>
              <input
                v-model="draft.target_date"
                type="date"
                class="form-input"
              >
            </div>
            <div class="pt-5 flex items-center gap-2">
              <label class="flex items-center gap-2 cursor-pointer select-none">
                <input
                  v-model="draft.pinned"
                  type="checkbox"
                  class="rounded bg-ui-surface border-ui-border text-cyan-500 focus:ring-cyan-400"
                >
                <span class="font-medium text-cyan-300">📌 置顶此任务 (重点跟踪)</span>
              </label>
            </div>
          </div>

          <!-- 详细内容与验收标准 -->
          <div>
            <label class="block text-ui-text-3 mb-1">改造思路、涉及模块与验收要点</label>
            <textarea
              v-model="draft.content"
              rows="5"
              placeholder="1. 改造背景与痛点：当前问题是什么？\n2. 涉及核心文件与函数：例如 index.py、watch_config.py\n3. 验收标准与预期效果：改造完成后应达到怎样的行为表现。"
              class="form-input resize-y"
            />
          </div>

          <!-- 底部提交按钮 -->
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
              class="btn-todo-create text-xs"
              :disabled="busy"
            >
              {{ busy ? '保存中…' : '保存改造事项' }}
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
        <h4 class="text-sm font-bold text-red-400 mb-2">确认删除该改造事项？</h4>
        <p class="text-ui-text-2 mb-4">
          「{{ pendingDelete.title }}」将被移除。
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
.project-todos-container {
  width: 100%;
}

.btn-todo-create {
  background: linear-gradient(135deg, #06b6d4, #0284c7);
  color: #fff;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 8px;
  transition: all 0.2s;
  box-shadow: 0 2px 10px rgba(6, 182, 212, 0.25);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.btn-todo-create:hover {
  background: linear-gradient(135deg, #22d3ee, #0ea5e9);
  box-shadow: 0 4px 14px rgba(6, 182, 212, 0.4);
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
  background: rgba(6, 182, 212, 0.2);
  color: #22d3ee;
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
  border-color: #06b6d4;
}

.todo-card.pinned {
  box-shadow: 0 0 15px rgba(6, 182, 212, 0.12);
}
</style>
