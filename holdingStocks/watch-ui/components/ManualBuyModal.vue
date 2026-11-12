<script setup lang="ts">
const props = defineProps<{
  accountTotal?: number | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success', detail: any): void
}>()

const code = ref('')
const name = ref('')
const market = ref('')
const price = ref<number | null>(null)
const prevClose = ref<number | null>(null)
const changePct = ref<number | null>(null)
const qty = ref<number>(1000)
const note = ref('手动波段建仓')

const loadingQuote = ref(false)
const submitting = ref(false)
const errorMsg = ref('')

// 自动根据输入获取股票实时行情
async function onCodeChange() {
  const cleanCode = code.value.trim().replace(/\D/g, '')
  if (cleanCode.length !== 6) {
    name.value = ''
    price.value = null
    return
  }
  loadingQuote.value = true
  errorMsg.value = ''
  try {
    const res = await $fetch<any>(`/api/manual-trade/quote?code=${cleanCode}`)
    if (res && res.code) {
      name.value = res.name || cleanCode
      market.value = res.market || ''
      if (res.price && res.price > 0) {
        price.value = res.price
      } else if (res.prev_close && res.prev_close > 0) {
        price.value = res.prev_close
      }
      prevClose.value = res.prev_close
      changePct.value = res.change_pct
      // 默认重新算一下当前仓位
      calcQtyByRatio(0.2) // 默认 20% 仓位
    }
  } catch (err: any) {
    errorMsg.value = err?.data?.error || err?.message || '获取股票行情失败'
  } finally {
    loadingQuote.value = false
  }
}

// 按总资产百分比快速计算股数（向下取整为 100 股整数倍）
function calcQtyByRatio(ratio: number) {
  const total = Number(props.accountTotal || 0)
  const px = Number(price.value || 0)
  if (total <= 0 || px <= 0) return
  const targetAmount = total * ratio
  const rawShares = Math.floor(targetAmount / px / 100) * 100
  qty.value = Math.max(100, rawShares)
}

const totalAmount = computed(() => {
  const p = Number(price.value || 0)
  const q = Number(qty.value || 0)
  return Math.round(p * q * 100) / 100
})

const positionRatio = computed(() => {
  const total = Number(props.accountTotal || 0)
  if (total <= 0 || totalAmount.value <= 0) return 0
  return Math.round((totalAmount.value / total) * 1000) / 10
})

async function submitBuy() {
  const cleanCode = code.value.trim().replace(/\D/g, '')
  if (cleanCode.length !== 6) {
    errorMsg.value = '请输入正确的 6 位股票代码'
    return
  }
  const p = Number(price.value || 0)
  if (p <= 0) {
    errorMsg.value = '请输入有效的买入价格'
    return
  }
  const q = Number(qty.value || 0)
  if (q <= 0) {
    errorMsg.value = '买入数量必须大于 0'
    return
  }

  submitting.value = true
  errorMsg.value = ''
  try {
    const res = await $fetch<any>('/api/manual-trade/buy', {
      method: 'POST',
      body: {
        code: cleanCode,
        price: p,
        qty: q,
        note: note.value.trim() || '手动买入入池',
      },
    })
    emit('success', res)
    emit('close')
  } catch (err: any) {
    errorMsg.value = err?.data?.error || err?.message || '买入录入失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in" @click.self="emit('close')">
    <div class="w-full max-w-lg rounded-2xl border border-ui-border bg-ui-surface p-6 shadow-2xl space-y-5">
      <!-- 弹窗标题 -->
      <div class="flex items-center justify-between border-b border-ui-hairline pb-3">
        <div class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-400 font-bold">➕</span>
          <h2 class="text-lg font-bold text-ui-text">手动买入建仓 · 入池盯盘</h2>
        </div>
        <button type="button" class="text-ui-text-3 hover:text-ui-text p-1 text-xl leading-none" @click="emit('close')">✕</button>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMsg" class="rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-400">
        {{ errorMsg }}
      </div>

      <!-- 表单区域 -->
      <div class="space-y-4 text-sm">
        <!-- 股票代码与自动识别 -->
        <div>
          <label class="block text-xs font-semibold text-ui-text-2 mb-1.5">股票代码 (6位数字)</label>
          <div class="flex gap-2">
            <input
              v-model="code"
              type="text"
              maxlength="6"
              placeholder="例如 600478 或 002636"
              class="flex-1 rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-ui-text focus:border-accent focus:outline-none font-mono"
              @input="onCodeChange"
            />
            <button
              type="button"
              class="btn btn-ghost px-3 text-xs"
              :disabled="loadingQuote"
              @click="onCodeChange"
            >
              {{ loadingQuote ? '查询中…' : '识别行情' }}
            </button>
          </div>
          <!-- 识别出的股票信息 -->
          <div v-if="name" class="mt-2 flex items-center justify-between rounded-lg bg-ui-fill px-3 py-2 text-xs">
            <span class="font-bold text-ui-text">{{ name }} <span class="text-ui-text-3 font-normal">({{ market }})</span></span>
            <span v-if="price" class="tabular-nums">
              现价: <b class="text-accent text-sm">¥{{ price }}</b>
              <span v-if="changePct != null" class="ml-1.5" :class="changePct >= 0 ? 'text-up' : 'text-down'">
                ({{ changePct >= 0 ? '+' : '' }}{{ changePct }}%)
              </span>
            </span>
          </div>
        </div>

        <!-- 买入价格与数量 -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-xs font-semibold text-ui-text-2 mb-1.5">买入成交价格 (元)</label>
            <input
              v-model.number="price"
              type="number"
              step="0.01"
              placeholder="0.00"
              class="w-full rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-ui-text focus:border-accent focus:outline-none tabular-nums font-semibold"
            />
          </div>
          <div>
            <label class="block text-xs font-semibold text-ui-text-2 mb-1.5">买入数量 (股)</label>
            <input
              v-model.number="qty"
              type="number"
              step="100"
              placeholder="1000"
              class="w-full rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-ui-text focus:border-accent focus:outline-none tabular-nums font-semibold"
            />
          </div>
        </div>

        <!-- 快速仓位按钮（基于总资产计算） -->
        <div v-if="accountTotal && accountTotal > 0">
          <div class="flex items-center justify-between text-xs text-ui-text-3 mb-1.5">
            <span>按账户总资产快速折算股数:</span>
            <span>总资产 ¥{{ Math.round(accountTotal).toLocaleString() }}</span>
          </div>
          <div class="grid grid-cols-4 gap-2">
            <button
              v-for="item in [{ label: '10% 仓位', val: 0.1 }, { label: '20% 仓位', val: 0.2 }, { label: '30% 仓位', val: 0.3 }, { label: '半仓 (50%)', val: 0.5 }]"
              :key="item.val"
              type="button"
              class="rounded border border-ui-border bg-ui-fill hover:bg-ui-fill-hover py-1 text-xs text-ui-text-2 transition"
              @click="calcQtyByRatio(item.val)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>

        <!-- 成交金额与仓位预计 -->
        <div class="rounded-xl border border-ui-hairline bg-ui-fill/60 p-3 text-xs flex items-center justify-between">
          <span class="text-ui-text-3">预计成交金额:</span>
          <div class="text-right">
            <b class="text-sm font-bold text-ui-text tabular-nums">¥{{ totalAmount.toLocaleString() }}</b>
            <span v-if="positionRatio > 0" class="ml-2 text-ui-text-2">
              (约占资产 <b>{{ positionRatio }}%</b>)
            </span>
          </div>
        </div>

        <!-- 买入理由/备注 -->
        <div>
          <label class="block text-xs font-semibold text-ui-text-2 mb-1.5">买入理由 / 策略备注</label>
          <input
            v-model="note"
            type="text"
            placeholder="例如：地量倍量起爆尾盘建仓、缠论底分型确认等"
            class="w-full rounded-lg border border-ui-border bg-ui-fill px-3 py-2 text-xs text-ui-text focus:border-accent focus:outline-none"
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
          class="rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold px-5 py-2 text-xs transition shadow-lg shadow-emerald-900/30 disabled:opacity-50"
          :disabled="submitting || !code || !price || !qty"
          @click="submitBuy"
        >
          {{ submitting ? '提交录入中…' : '确认买入并入池' }}
        </button>
      </div>
    </div>
  </div>
</template>
