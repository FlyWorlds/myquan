<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    mode?: 'single' | 'range'
    modelValue?: string | { start: string; end: string }
    start?: string
    end?: string
    placeholder?: string
    min?: string
    max?: string
    disabled?: boolean
    quickRanges?: boolean
    size?: 'sm' | 'md'
  }>(),
  {
    mode: 'single',
    modelValue: '',
    start: '',
    end: '',
    placeholder: '选择日期',
    disabled: false,
    quickRanges: true,
    size: 'md',
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', val: string | { start: string; end: string }): void
  (e: 'update:start', val: string): void
  (e: 'update:end', val: string): void
  (e: 'change', val: any): void
}>()

const isOpen = ref(false)
const containerRef = ref<HTMLElement | null>(null)

// 内部当前查看的年与月
const today = new Date()
const viewYear = ref(today.getFullYear())
const viewMonth = ref(today.getMonth()) // 0 - 11

// 当前选中的起止日期（字符串 YYYY-MM-DD）
const selectedSingle = computed(() => (typeof props.modelValue === 'string' ? props.modelValue : ''))

const selectedStart = computed(() => {
  if (props.start) return props.start
  if (props.modelValue && typeof props.modelValue === 'object') return props.modelValue.start || ''
  return ''
})

const selectedEnd = computed(() => {
  if (props.end) return props.end
  if (props.modelValue && typeof props.modelValue === 'object') return props.modelValue.end || ''
  return ''
})

// 鼠标悬停时的临时终点（用于范围预览）
const hoverDate = ref<string>('')
// 范围选择阶段：'idle' | 'picking_end'
const pickingState = ref<'idle' | 'picking_end'>('idle')

// 当打开面板时，默认定位到选中的年月或今天
watch(isOpen, (open) => {
  if (open) {
    const target = props.mode === 'single' ? selectedSingle.value : selectedStart.value || selectedEnd.value
    if (target && target.length >= 7) {
      const parts = target.split('-').map(Number)
      if (parts[0] && parts[1]) {
        viewYear.value = parts[0]
        viewMonth.value = parts[1] - 1
      }
    } else {
      viewYear.value = today.getFullYear()
      viewMonth.value = today.getMonth()
    }
    pickingState.value = 'idle'
  }
})

function prevMonth() {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value -= 1
  } else {
    viewMonth.value -= 1
  }
}

function nextMonth() {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value += 1
  } else {
    viewMonth.value += 1
  }
}

function prevYear() {
  viewYear.value -= 1
}

function nextYear() {
  viewYear.value += 1
}

// 格式化日期对象为 YYYY-MM-DD
function formatDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const todayStr = formatDate(today)

interface CalendarDay {
  dateStr: string
  dayNum: number
  isCurrentMonth: boolean
  isToday: boolean
  isSelected: boolean
  isRangeStart: boolean
  isRangeEnd: boolean
  isInRange: boolean
  isDisabled: boolean
}

const calendarDays = computed<CalendarDay[]>(() => {
  const y = viewYear.value
  const m = viewMonth.value

  const firstDayOfMonth = new Date(y, m, 1)
  const lastDayOfMonth = new Date(y, m + 1, 0)

  // 星期几（0:周日, 1:周一 ... 6:周六）。按周一为一周起始
  let startDayOfWeek = firstDayOfMonth.getDay() - 1
  if (startDayOfWeek === -1) startDayOfWeek = 6

  const days: CalendarDay[] = []

  // 上月补足天数
  const prevMonthLastDate = new Date(y, m, 0).getDate()
  for (let i = startDayOfWeek - 1; i >= 0; i--) {
    const d = new Date(y, m - 1, prevMonthLastDate - i)
    const str = formatDate(d)
    days.push(createDayItem(str, d.getDate(), false))
  }

  // 当月天数
  for (let i = 1; i <= lastDayOfMonth.getDate(); i++) {
    const d = new Date(y, m, i)
    const str = formatDate(d)
    days.push(createDayItem(str, i, true))
  }

  // 下月补齐到 42 格 (6周)
  const total = days.length
  const remaining = (42 - total) % 7 || (total <= 35 ? 7 : 0)
  for (let i = 1; i <= remaining; i++) {
    const d = new Date(y, m + 1, i)
    const str = formatDate(d)
    days.push(createDayItem(str, i, false))
  }

  return days
})

function createDayItem(dateStr: string, dayNum: number, isCurrentMonth: boolean): CalendarDay {
  const isToday = dateStr === todayStr
  let isSelected = false
  let isRangeStart = false
  let isRangeEnd = false
  let isInRange = false

  if (props.mode === 'single') {
    isSelected = dateStr === selectedSingle.value
  } else {
    const s = selectedStart.value
    const e = selectedEnd.value
    isRangeStart = dateStr === s
    isRangeEnd = dateStr === e
    isSelected = isRangeStart || isRangeEnd

    // 计算区间判定（考虑 hoverDate）
    let effectiveEnd = e
    if (pickingState.value === 'picking_end' && hoverDate.value) {
      effectiveEnd = hoverDate.value
    }

    if (s && effectiveEnd) {
      const minDate = s < effectiveEnd ? s : effectiveEnd
      const maxDate = s > effectiveEnd ? s : effectiveEnd
      isInRange = dateStr >= minDate && dateStr <= maxDate
    }
  }

  let isDisabled = false
  if (props.min && dateStr < props.min) isDisabled = true
  if (props.max && dateStr > props.max) isDisabled = true

  return {
    dateStr,
    dayNum,
    isCurrentMonth,
    isToday,
    isSelected,
    isRangeStart,
    isRangeEnd,
    isInRange,
    isDisabled,
  }
}

function selectDay(day: CalendarDay) {
  if (day.isDisabled) return

  if (props.mode === 'single') {
    emit('update:modelValue', day.dateStr)
    emit('change', day.dateStr)
    isOpen.value = false
    return
  }

  // 范围选择逻辑
  if (pickingState.value === 'idle') {
    // 第一次点击：选定开始日期
    emit('update:start', day.dateStr)
    emit('update:end', '')
    emit('update:modelValue', { start: day.dateStr, end: '' })
    pickingState.value = 'picking_end'
  } else {
    // 第二次点击：选定结束日期
    let s = selectedStart.value
    let e = day.dateStr
    if (s > e) {
      // 倒选则自动调换顺序
      const temp = s
      s = e
      e = temp
    }
    emit('update:start', s)
    emit('update:end', e)
    emit('update:modelValue', { start: s, end: e })
    emit('change', { start: s, end: e })
    pickingState.value = 'idle'
    isOpen.value = false
  }
}

function handleDayHover(day: CalendarDay) {
  if (props.mode === 'range' && pickingState.value === 'picking_end') {
    hoverDate.value = day.dateStr
  }
}

// 快速预设区间选择
function applyPreset(daysCount?: number, presetType?: 'ytd' | 'today') {
  const end = new Date()
  let start = new Date()

  if (presetType === 'today') {
    start = new Date()
  } else if (presetType === 'ytd') {
    start = new Date(end.getFullYear(), 0, 1)
  } else if (daysCount != null) {
    start.setDate(start.getDate() - daysCount)
  }

  const sStr = formatDate(start)
  const eStr = formatDate(end)

  emit('update:start', sStr)
  emit('update:end', eStr)
  emit('update:modelValue', { start: sStr, end: eStr })
  emit('change', { start: sStr, end: eStr })
  pickingState.value = 'idle'
  isOpen.value = false
}

function selectToday() {
  if (props.mode === 'single') {
    emit('update:modelValue', todayStr)
    emit('change', todayStr)
    isOpen.value = false
  } else {
    applyPreset(undefined, 'today')
  }
}

function clearSelection() {
  if (props.mode === 'single') {
    emit('update:modelValue', '')
    emit('change', '')
  } else {
    emit('update:start', '')
    emit('update:end', '')
    emit('update:modelValue', { start: '', end: '' })
    emit('change', { start: '', end: '' })
  }
  pickingState.value = 'idle'
  isOpen.value = false
}

// 点击外部关闭
function handleClickOutside(event: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(event.target as Node)) {
    isOpen.value = false
    pickingState.value = 'idle'
  }
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})
</script>

<template>
  <div ref="containerRef" class="relative inline-block w-full text-ui-text">
    <!-- 外部输入框展示区 -->
    <div
      class="group flex w-full items-center justify-between rounded-lg border border-ui-hairline bg-ui-surface px-3 py-1.5 text-xs transition hover:border-accent focus-within:border-accent focus-within:ring-1 focus-within:ring-accent cursor-pointer"
      :class="[
        disabled ? 'cursor-not-allowed opacity-50' : '',
        isOpen ? 'border-accent ring-1 ring-accent' : '',
        size === 'sm' ? 'py-1 text-[11px]' : 'py-1.5 text-xs',
      ]"
      @click="!disabled && (isOpen = !isOpen)"
    >
      <div class="flex items-center gap-2 truncate">
        <!-- 日历小图标 -->
        <svg
          class="h-3.5 w-3.5 shrink-0 text-ui-text-3 group-hover:text-accent transition-colors"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
          <line x1="16" y1="2" x2="16" y2="6"></line>
          <line x1="8" y1="2" x2="8" y2="6"></line>
          <line x1="3" y1="10" x2="21" y2="10"></line>
        </svg>

        <!-- 单日展示 -->
        <template v-if="mode === 'single'">
          <span v-if="selectedSingle" class="font-medium text-ui-text font-mono">
            {{ selectedSingle }}
          </span>
          <span v-else class="text-ui-text-3">
            {{ placeholder }}
          </span>
        </template>

        <!-- 范围展示 -->
        <template v-else>
          <span v-if="selectedStart || selectedEnd" class="font-medium text-ui-text font-mono flex items-center gap-1.5">
            <span>{{ selectedStart || '开始日期' }}</span>
            <span class="text-ui-text-3 font-normal">至</span>
            <span>{{ selectedEnd || '结束日期' }}</span>
          </span>
          <span v-else class="text-ui-text-3">
            {{ placeholder || '选择日期范围' }}
          </span>
        </template>
      </div>

      <!-- 右侧清除/下拉小箭头 -->
      <div class="flex items-center gap-1 shrink-0 ml-1">
        <button
          v-if="(mode === 'single' ? selectedSingle : selectedStart || selectedEnd) && !disabled"
          type="button"
          class="p-0.5 text-ui-text-3 hover:text-ui-danger rounded transition"
          title="清除日期"
          @click.stop="clearSelection"
        >
          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
        <span class="text-ui-text-3 text-[10px] transition-transform duration-200" :class="{ 'rotate-180': isOpen }">
          ▼
        </span>
      </div>
    </div>

    <!-- 弹出的精致日历面板 -->
    <div
      v-if="isOpen"
      class="absolute left-0 top-full z-50 mt-1.5 rounded-xl border border-ui-hairline/80 bg-ui-surface p-3.5 shadow-2xl backdrop-blur-md select-none animate-in fade-in zoom-in-95 duration-150"
      :class="[mode === 'range' && quickRanges ? 'min-w-[440px] flex gap-3' : 'min-w-[280px]']"
    >
      <!-- 范围模式：左侧快捷时间预设 -->
      <div
        v-if="mode === 'range' && quickRanges"
        class="border-r border-ui-hairline/60 pr-3 flex flex-col gap-1 w-28 shrink-0 text-xs"
      >
        <div class="text-[11px] font-semibold text-ui-text-3 pb-1 border-b border-ui-hairline/40">
          快捷区间
        </div>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(0, 'today')"
        >
          今日
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(7)"
        >
          近 7 天
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(30)"
        >
          近 1 个月
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(90)"
        >
          近 3 个月
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(180)"
        >
          近半年
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(undefined, 'ytd')"
        >
          今年以来 (YTD)
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(365)"
        >
          近 1 年
        </button>
        <button
          type="button"
          class="text-left px-2 py-1.5 rounded hover:bg-ui-surface-2 hover:text-accent transition text-ui-text-2 text-xs"
          @click="applyPreset(1095)"
        >
          近 3 年
        </button>
      </div>

      <!-- 右侧日历主体 -->
      <div class="flex-1">
        <!-- 头部年月切换 -->
        <div class="flex items-center justify-between border-b border-ui-hairline/60 pb-2 mb-2 text-xs">
          <div class="flex items-center gap-1">
            <button
              type="button"
              class="h-6 w-6 rounded hover:bg-ui-surface-2 flex items-center justify-center text-ui-text-3 hover:text-ui-text font-bold"
              title="上一年"
              @click="prevYear"
            >
              «
            </button>
            <button
              type="button"
              class="h-6 w-6 rounded hover:bg-ui-surface-2 flex items-center justify-center text-ui-text-3 hover:text-ui-text font-bold"
              title="上一月"
              @click="prevMonth"
            >
              ‹
            </button>
          </div>

          <div class="font-bold text-ui-text tracking-wide">
            {{ viewYear }}年 {{ String(viewMonth + 1).padStart(2, '0') }}月
          </div>

          <div class="flex items-center gap-1">
            <button
              type="button"
              class="h-6 w-6 rounded hover:bg-ui-surface-2 flex items-center justify-center text-ui-text-3 hover:text-ui-text font-bold"
              title="下一月"
              @click="nextMonth"
            >
              ›
            </button>
            <button
              type="button"
              class="h-6 w-6 rounded hover:bg-ui-surface-2 flex items-center justify-center text-ui-text-3 hover:text-ui-text font-bold"
              title="下一年"
              @click="nextYear"
            >
              »
            </button>
          </div>
        </div>

        <!-- 星期表头 -->
        <div class="grid grid-cols-7 gap-1 text-center text-[11px] font-semibold text-ui-text-3 mb-1">
          <span>一</span>
          <span>二</span>
          <span>三</span>
          <span>四</span>
          <span>五</span>
          <span class="text-rose-400/80">六</span>
          <span class="text-rose-400/80">日</span>
        </div>

        <!-- 日历天数网格 -->
        <div class="grid grid-cols-7 gap-1 text-xs">
          <button
            v-for="d in calendarDays"
            :key="d.dateStr"
            type="button"
            class="relative h-7 w-7 rounded-md flex items-center justify-center font-mono text-[11px] transition"
            :class="[
              !d.isCurrentMonth ? 'text-ui-text-3/40' : 'text-ui-text',
              d.isDisabled ? 'opacity-30 cursor-not-allowed' : 'hover:bg-ui-surface-2',
              d.isInRange && !d.isSelected ? 'bg-accent/20 text-accent font-semibold rounded-none' : '',
              d.isSelected ? 'bg-accent text-white font-bold shadow-md' : '',
              d.isToday && !d.isSelected ? 'border border-accent text-accent font-bold' : '',
              d.isRangeStart ? 'rounded-r-none' : '',
              d.isRangeEnd ? 'rounded-l-none' : '',
            ]"
            :disabled="d.isDisabled"
            @click="selectDay(d)"
            @mouseenter="handleDayHover(d)"
          >
            {{ d.dayNum }}
          </button>
        </div>

        <!-- 底部快捷辅助操作 -->
        <div class="mt-2.5 flex items-center justify-between border-t border-ui-hairline/60 pt-2 text-[11px]">
          <span v-if="mode === 'range'" class="text-ui-text-3">
            {{ pickingState === 'picking_end' ? '请选择结束日期...' : '点击选择日期范围' }}
          </span>
          <button
            type="button"
            class="text-accent hover:underline font-medium"
            @click="selectToday"
          >
            选择今天
          </button>
          <button
            type="button"
            class="text-ui-text-3 hover:text-ui-text"
            @click="clearSelection"
          >
            清空
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
