<script setup lang="ts">
import { fmtNum, fmtSignedPct } from '~/utils/format'

type Item = { code: string; name: string }
type Quote = { code: string; name: string; market: string; price: number; prevClose?: number; changePct?: number; quoteTime: string; source: string }
const items = ref<Item[]>([])
const code = ref('')
const busy = ref(false)
const error = ref('')
const message = ref('')
const expanded = ref(false)
const preview = ref<{ quote: Quote; token: string; alreadyAdded: boolean } | null>(null)

async function request(path = '', body?: object) {
  const response = await fetch(`/api/self-watchlist${path}`, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  } : { cache: 'no-store' })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error || '自选池请求失败，请稍后重试')
  return data
}
async function load() {
  try { items.value = (await request()).items || [] } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
}
watch(code, () => { preview.value = null; error.value = '' })
async function lookup() {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''; preview.value = null
  try { preview.value = await request('/preview', { code: code.value.trim() }) }
  catch (e) { error.value = String(e instanceof Error ? e.message : e) }
  finally { busy.value = false }
}
async function confirmAdd() {
  if (!preview.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const data = await request('/confirm', { token: preview.value.token })
    items.value = data.items; preview.value = null; code.value = ''
    message.value = `${data.quote.name}已加入自选，行情和信号将自动更新`
  } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
  finally { busy.value = false }
}
async function remove(item: Item) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    const data = await request('/remove', { code: item.code })
    items.value = data.items; preview.value = null
    message.value = `${item.name}已移出自选，当天信号、持仓和成交记录保留`
  } catch (e) { error.value = String(e instanceof Error ? e.message : e) }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="card overflow-hidden">
    <button class="flex w-full items-center justify-between px-4 py-3 text-left" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="text-sm font-semibold">自选池 <span class="ml-1 font-normal text-ui-text-3">{{ items.length }}</span></span>
      <span class="text-xs text-accent">{{ expanded ? '收起' : '添加 / 删除' }}</span>
    </button>
    <div v-if="expanded" class="space-y-3 border-t border-ui-hairline p-4">
      <p class="text-xs text-ui-text-2">公共自选，全策略共用。确认加入后会参与现有策略监控和信号判断；删除不清除当天信号，也不卖出持仓；仍属于其他策略池的股票会继续展示。</p>
      <form class="flex flex-wrap items-end gap-2" @submit.prevent="lookup">
        <label class="flex flex-col gap-1 text-xs text-ui-text-2">股票代码（沪深A股）
          <input v-model="code" :disabled="busy" maxlength="8" autocomplete="off" placeholder="例如 600552" class="rounded-lg border border-ui-hairline bg-ui-surface px-3 py-2 text-sm text-ui-text" />
        </label>
        <button class="btn btn-ghost" type="submit" :disabled="busy || !code.trim()">{{ busy ? '处理中…' : '查询行情并核对' }}</button>
      </form>
      <div v-if="preview" class="rounded-lg border border-accent/40 bg-accent/10 p-3">
        <h3 class="text-sm font-semibold">核对股票与行情：{{ preview.quote.name }} {{ preview.quote.code }} · {{ preview.quote.market }}</h3>
        <p class="mt-2 text-sm tabular-nums">现价 {{ fmtNum(preview.quote.price) }} · 今日涨跌幅 {{ fmtSignedPct(preview.quote.changePct) }} · 昨收 {{ fmtNum(preview.quote.prevClose) }}</p>
        <p class="mt-1 text-xs text-ui-text-2">行情时间 {{ preview.quote.quoteTime }} · {{ preview.quote.source === 'sina_batch' ? '新浪行情' : '腾讯行情' }}</p>
        <p v-if="preview.alreadyAdded" class="mt-2 text-xs text-ui-text-2">该股票已在自选池，无需重复添加。</p>
        <div v-else class="mt-3 flex gap-2">
          <button type="button" class="btn btn-ghost" :disabled="busy" @click="confirmAdd">确认加入自选</button>
          <button type="button" class="btn btn-ghost" :disabled="busy" @click="preview = null">取消</button>
        </div>
      </div>
      <p v-if="error" role="alert" class="text-xs text-down">{{ error }}</p>
      <p v-if="message" role="status" class="text-xs text-accent">{{ message }}</p>
      <div class="flex flex-wrap gap-2">
        <div v-for="item in items" :key="item.code" class="flex items-center gap-3 rounded-lg border border-ui-hairline px-3 py-2 text-xs">
          <span>{{ item.name }} <span class="font-mono text-ui-text-3">{{ item.code }}</span></span>
          <button type="button" class="text-ui-text-3 hover:text-down" :aria-label="`删除自选${item.name}`" :disabled="busy" @click="remove(item)">删除</button>
        </div>
      </div>
      <p v-if="!items.length && !error" class="text-xs text-ui-text-3">暂无自选，输入股票代码开始添加。</p>
    </div>
  </div>
</template>
