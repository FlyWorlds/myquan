<script setup lang="ts">
import type { HoldingRow } from '~/types/snapshot'
import { fmtNum, fmtSignedMoney, fmtSignedPct } from '~/utils/format'

const props = defineProps<{
  row: HoldingRow
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success', detail: any): void
}>()

const code = computed(() => String(props.row.代码 || ''))
const name = computed(() => String(props.row.名称 || code.value))
const cost = computed(() => Number(props.row.成本 || 0))
const currentPx = computed(() => Number(props.row.现价 || cost.value || 0))
const totalHoldingQty = computed(() => Number(props.row.持仓 || 0))

const sellPrice = ref<number>(currentPx.value || cost.value)
const sellQty = ref<number>(totalHoldingQty.value)
const note = ref('手动平仓')

const submitting = ref(false)
const errorMsg = ref('')

// 当现价变化或打开时同步
watch(() => props.row.现价, (px) => {
  if (px && Number(px) > 0 && (!sellPrice.value || sellPrice.value === cost.value)) {
    sellPrice.value = Number(px)
  }
}, { immediate: true })

watch(totalHoldingQty, (q) => {
  if (q > 0 && !sellQty.value) {
    sellQty.value = q
  }
}, { immediate: true })

function setAllQty() {
  sellQty.value = totalHoldingQty.value
}

function setHalfQty() {
  const half = Math.floor(totalHoldingQty.value / 200) * 100
  sellQty.value = Math.max(100, half)
}

// 实时预估本次卖出实现的盈亏金额与收益率
const estimatedPnl = computed(() => {
  const p = Number(sellPrice.value || 0)
  const c = cost.value
  const q = Number(sellQty.value || 0)
  if (p <= 0 || c <= 0 || q <= 0) return 0
  return Math.round((p - c) * q * 100) / 100
})

const estimatedPnlPct = computed(() => {
  const p = Number(sellPrice.value || 0)
  const c = cost.value
  if (p <= 0 || c <= 0) return 0
  return Math.round(((p - c) / c) * 10000) / 100
})

const totalSellAmount = computed(() => {
  const p = Number(sellPrice.value || 0)
  const q = Number(sellQty.value || 0)
  return Math.round(p * q * 100) / 100
})

async function submitSell() {
  const p = Number(sellPrice.value || 0)
  if (p <= 0) {
    errorMsg.value = '请输入有效的卖出价格'
    return
  }
  const q = Number(sellQty.value || 0)
  if (q <= 0 || q > totalHoldingQty.value) {
    errorMsg.value = `卖出数量必须在 1 ~ ${totalHoldingQty.value} 股之间`
    return
  }

  submitting.value = true
  errorMsg.value = ''
  try {
    const res = await $fetch<any>('/api/manual-trade/sell', {
      method: 'POST',
      body: {
        code: code.value,
        price: p,
        qty: q,
        note: note.value.trim() || '手动卖出平仓',
      },
    })
    emit('success', res)
    emit('close')
  } catch (err: any) {
    errorMsg.value = err?.data?.error || err?.message || '卖出平仓失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in" @click.self="emit('close')">
    <div class="w-full max-w-md rounded-2xl border border-ui-border bg-ui-surface p-6 shadow-2xl space-y-5">
      <!-- 弹窗标题 -->
      <div class="flex items-center justify-between border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-red-500/20 text-red-400 font-bold">🔴</span>
          <div>
            <h2 class="text-lg font-bold text-ui-text">手动卖出平仓 · 锁定收益</h2>
            <p class="text-xs text-ui-text-3">{{ name }} ({{ code }})</p>
          </div>
        </div>
        <button type="button" class="text-ui-text-3 hover:text-ui-text p-1 text-xl leading-none" @click="emit('close')">✕</button>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMsg" class="rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-400">
        {{ errorMsg }}
      </div>

      <!-- 当前持仓基准展示 -->
      <div class="grid grid-cols-3 gap-2 rounded-xl bg-ui-fill p-3 text-xs text-center">
        <div>
          <div class="text-ui-text-3">买入成本</div>
          <div class="font-bold text-ui-text mt-0.5 tabular-nums">¥{{ fmtNum(cost, 2) }}</div>
        </div>
        <div>
          <div class="text-ui-text-3">市场现价</div>
          <div class="font-bold text-accent mt-0.5 tabular-nums">¥{{ fmtNum(currentPx, 2) }}</div>
        </div>
        <div>
          <div class="text-ui-text-3">当前持仓</div>
          <div class="font-bold text-ui-text mt-0.5 tabular-nums">{{ totalHoldingQty }} 股</div>
        </div>
      </div>

      <!-- 卖出价格与数量输入 -->
      <div class="space-y-4 text-sm">
        <div>
          <label class="block text-xs font-semibold text-ui-text-2 mb-1.5">卖出成交价格 (元)</label>
          <input
            v-model.number="sellPrice"
            type="number"
            step="0.01"
            placeholder="0.00"
            class="w-full rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-ui-text focus:border-down focus:outline-none tabular-nums font-semibold"
          />
        </div>

        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="text-xs font-semibold text-ui-text-2">卖出数量 (股)</label>
            <div class="flex gap-2">
              <button
                type="button"
                class="rounded bg-ui-fill px-2 py-0.5 text-xs text-accent hover:bg-ui-fill-hover border border-ui-hairline"
                @click="setHalfQty"
              >
                减半 (50%)
              </button>
              <button
                type="button"
                class="rounded bg-ui-fill px-2 py-0.5 text-xs text-red-400 hover:bg-ui-fill-hover border border-ui-hairline"
                @click="setAllQty"
              >
                全仓平仓 (100%)
              </button>
            </div>
          </div>
          <input
            v-model.number="sellQty"
            type="number"
            step="100"
            :max="totalHoldingQty"
            placeholder="1000"
            class="w-full rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-ui-text focus:border-down focus:outline-none tabular-nums font-semibold"
          />
        </div>

        <!-- 收益预计看板（核心收益计算展示） -->
        <div class="rounded-xl border border-ui-hairline bg-ui-fill/60 p-3.5 space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="text-ui-text-3">预计回收资金:</span>
            <b class="text-ui-text tabular-nums font-bold">¥{{ totalSellAmount.toLocaleString() }}</b>
          </div>
          <div class="flex items-center justify-between border-t border-ui-hairline pt-2 text-xs">
            <span class="text-ui-text-3 font-semibold">本次实现盈亏:</span>
            <div class="text-right">
              <span class="text-base font-bold tabular-nums" :class="estimatedPnl >= 0 ? 'text-up' : 'text-down'">
                {{ fmtSignedMoney(estimatedPnl) }}
              </span>
              <span class="ml-1.5 text-xs font-semibold" :class="estimatedPnlPct >= 0 ? 'text-up' : 'text-down'">
                ({{ fmtSignedPct(estimatedPnlPct) }})
              </span>
            </div>
          </div>
        </div>

        <!-- 备注 -->
        <div>
          <label class="block text-xs font-semibold text-ui-text-2 mb-1.5">平仓备注说明</label>
          <input
            v-model="note"
            type="text"
            placeholder="例如：波段达标止盈、触碰20日线平仓、尾盘离场等"
            class="w-full rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-xs text-ui-text focus:border-down focus:outline-none"
          />
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="flex items-center justify-end gap-3 pt-3 border-t border-ui-hairline">
        <button
          type="button"
          class="btn btn-ghost px-4 py-2 text-xs"
          @click="emit('close')"
        >
          取消
        </button>
        <button
          type="button"
          class="rounded-lg bg-red-600 hover:bg-red-500 text-white font-bold px-5 py-2 text-xs transition shadow-lg shadow-red-900/30 disabled:opacity-50"
          :disabled="submitting || !sellPrice || !sellQty || sellQty <= 0"
          @click="submitSell"
        >
          {{ submitting ? '执行平仓中…' : '确认卖出平仓' }}
        </button>
      </div>
    </div>
  </div>
</template>
