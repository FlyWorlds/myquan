<script setup lang="ts">
import { toRaw } from 'vue'
const props = defineProps<{
  selection: any
  disabled?: boolean
  paramsDirty?: boolean
  prepareSelection?: () => Promise<any>
}>()
const emit = defineEmits<{ load: [selection: any]; busy: [pending: boolean] }>()
const groups = ref<any[]>([])
const selected = ref('')
const defaultId = ref('')
const loadedId = ref('')
const name = ref('')
const error = ref('')
const notice = ref('')
const pending = ref('initial')
const busy = computed(() => !!pending.value || !!props.disabled)
watch(pending, value => emit('busy', !!value), { immediate: true })
const job = ref<any>(null)
const selectedGroup = computed(() => groups.value.find(g => g.id === selected.value))
const loadedGroup = computed(() => groups.value.find(g => g.id === loadedId.value))
const defaultGroup = computed(() => groups.value.find(g => g.id === defaultId.value))
const duplicateGroup = computed(() => selectedGroup.value?.fingerprint
  ? groups.value.find(g => g.id !== selected.value && g.fingerprint === selectedGroup.value.fingerprint)
  : null)
function groupLabel(group: any) {
  const count = group.stock_count == null ? '' : ` · ${group.stock_count}只`
  const preview = group.preview ? ` (${group.preview}等)` : ''
  const created = String(group.created_at || '').replace('T', ' ').slice(0, 16)
  return `${group.id === defaultId.value ? '★ ' : ''}${group.name}${count}${preview}${created ? ` · ${created}` : ''}`
}
let loadedSelection: any = null
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
watch(() => props.selection, value => {
  if (toRaw(value) !== toRaw(loadedSelection)) loadedId.value = ''
})
async function refresh() {
  const [list, preference] = await Promise.all([
    $fetch<any[]>('/api/strategy16b/groups'),
    $fetch<any>('/api/strategy16b/groups/default'),
  ])
  groups.value = list
  defaultId.value = preference.groupId || ''
}
async function activate(id: string) {
  const selection = await $fetch<any>('/api/strategy16b/activate', { method: 'POST', body: { groupId: id } })
  if (disposed) return
  loadedSelection = selection
  loadedId.value = id
  selected.value = id
  name.value = groups.value.find(g => g.id === id)?.name || ''
  emit('load', selection)
}
onMounted(async () => {
  try {
    await refresh()
    if (defaultId.value && !disposed) {
      await activate(defaultId.value)
      notice.value = '已自动载入默认分组'
    }
  } catch (e: any) { error.value = e.data?.error || '默认分组读取失败，请点击刷新分组重试' }
  finally { pending.value = '' }
})
onBeforeUnmount(() => { disposed = true; clearTimeout(timer); emit('busy', false) })
async function action(kind: string) {
  if (busy.value) return
  pending.value = kind; error.value = ''; notice.value = ''
  try {
    if (kind === 'save') {
      let targetSelection = props.selection
      if ((!targetSelection?.picks?.items?.length || props.paramsDirty) && props.prepareSelection) {
        const fresh = await props.prepareSelection()
        if (!fresh?.picks?.items?.length) {
          throw new Error('当前条件筛选未完成，暂无法保存分组')
        }
        targetSelection = fresh
      }
      const saved = await $fetch<any>('/api/strategy16b/groups', { method: 'POST', body: { name: name.value.trim(), selection: targetSelection } })
      await refresh(); selected.value = saved.id
      loadedId.value = saved.id; loadedSelection = targetSelection
      notice.value = '分组已保存，可设为默认供下次自动载入'
    } else if (kind === 'refresh') {
      await refresh(); notice.value = '已更新保存分组'
    } else if (kind === 'load') {
      await activate(selected.value); notice.value = `已载入分组「${selectedGroup.value?.name || ''}」，股票列表已更新`
    } else if (kind === 'default') {
      const id = selected.value
      await $fetch('/api/strategy16b/groups/default', { method: 'POST', body: { groupId: id } })
      defaultId.value = id
      await activate(id)
      notice.value = '已设为默认，下次进入自动载入此分组'
    } else {
      job.value = null
      const started = await $fetch<any>('/api/strategy16b/replay', { method: 'POST', body: { groupId: selected.value } })
      await poll(started.id)
      return
    }
  } catch (e: any) { error.value = e.data?.error || e.message }
  pending.value = ''
}
async function poll(id: string) {
  if (disposed) return
  try {
    job.value = await $fetch<any>(`/api/strategy16b/replay/${id}`)
    if (job.value.status === 'running') { timer = setTimeout(() => poll(id), 2000); return }
    if (job.value.status === 'failed') error.value = job.value.error
  } catch { error.value = '回测状态读取失败，请重试' }
  pending.value = ''
}
</script>
<template>
  <section class="selection-library" aria-label="数据库选股分组" :aria-busy="busy">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div><p class="library-eyebrow">股票池管理</p><h3 class="mt-1 text-base font-semibold">数据库选股分组</h3></div>
      <span class="library-badge">{{ defaultGroup ? `默认 · ${defaultGroup.name}` : '尚未设置默认分组' }}</span>
    </header>
    <div class="library-grid">
      <div class="library-block">
        <h4 class="font-medium text-sm">保存本次筛选</h4>
        <p class="library-help">为当前股票池命名，下次直接载入（若已修改上方筛选条件，保存时会自动按新条件重筛）。</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <input v-model="name" aria-label="分组名称" maxlength="80" placeholder="例如：低价核心龙头" class="library-input flex-1 min-w-0" :disabled="busy" @keyup.enter="name.trim() && (selection?.picks?.items?.length || prepareSelection) && action('save')">
          <button class="library-button" :disabled="busy || !name.trim() || (!selection?.picks?.items?.length && !prepareSelection)" @click="action('save')">
            <svg v-if="pending === 'save'" class="mr-1.5 inline-block h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity=".25" /><path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" stroke-width="3" stroke-linecap="round" /></svg>
            {{ pending === 'save' ? '筛选并保存中…' : '保存分组' }}
          </button>
        </div>
      </div>
      <div class="library-block">
        <div class="flex items-center justify-between gap-2"><h4 class="font-medium text-sm">使用已保存分组</h4><button class="library-link" :disabled="busy" @click="action('refresh')">刷新分组</button></div>
        <p class="library-help">默认分组将在下次进入时自动载入。</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <select v-model="selected" aria-label="已保存分组" :disabled="busy" class="library-input flex-1 min-w-0"><option value="">{{ groups.length ? '选择一个分组' : '暂无保存分组' }}</option><option v-for="g in groups" :key="g.id" :value="g.id">{{ groupLabel(g) }}</option></select>
          <button class="library-button library-primary" :disabled="busy || !selected" @click="action('load')">
            <svg v-if="pending === 'load'" class="mr-1.5 inline-block h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity=".25" /><path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" stroke-width="3" stroke-linecap="round" /></svg>
            {{ pending === 'load' ? '载入中…' : '载入分组 ↗' }}
          </button>
          <button class="library-button" :disabled="busy || !selected || selected === defaultId" @click="action('default')">{{ pending === 'default' ? '设置中…' : selected && selected === defaultId ? '★ 默认分组' : '设为默认' }}</button>
        </div>
      </div>
    </div>
    <p v-if="duplicateGroup" class="library-help text-ui-danger">提示：当前所选分组与「{{ duplicateGroup.name }}」保存的股票代码完全相同（可能是此前未重新筛选即直接保存所致）。请调整上方条件点击「从全A筛选」后再保存新分组。</p>
    <div class="library-footer flex flex-wrap items-center justify-between gap-3">
      <div><p class="text-sm">当前载入：<strong>{{ loadedGroup?.name || (selection ? '本次筛选结果' : '未载入保存分组') }}</strong></p><p class="library-help">{{ selectedGroup ? `回测对象：${selectedGroup.name}` : '选择保存分组后可回测' }} · 点击回测后才拉取1分钟行情</p></div>
      <button class="library-button" :disabled="busy || !selected" @click="action('replay')">{{ pending === 'replay' ? '回测中…' : '回测近7天 →' }}</button>
    </div>
    <p v-if="pending === 'initial'" role="status" class="text-sm text-ui-text-3">正在读取默认分组…</p>
    <p v-if="notice" role="status" class="library-notice">✓ {{ notice }}</p>
    <p v-if="error" role="alert" class="text-sm text-ui-danger">{{ error }}</p>
    <p v-if="job?.status === 'running'" role="status" class="text-sm">正在拉取并回测 · 已处理 {{ job.completed }} 只</p>
    <div v-if="job?.status === 'done'" class="library-block space-y-2">
      <p>{{ job.start }} 至 {{ job.end }} · 收益 {{ job.result.summary?.return_pct }}% · 最大回撤 {{ job.result.summary?.max_dd_pct }}%</p>
      <p class="library-help">{{ job.note }}</p>
      <p v-if="job.coverage.some((c: any) => c.missingDays?.length)" class="text-ui-danger">部分股票缺少窗口内交易日行情，收益仅对应实际覆盖范围，请查看明细。</p>
      <details><summary class="cursor-pointer text-sm">行情覆盖与完整回测结果</summary><pre class="overflow-auto max-h-96 text-xs">{{ JSON.stringify({ coverage: job.coverage, ...job.result }, null, 2) }}</pre></details>
    </div>
  </section>
</template>
<style scoped>
.selection-library{border-top:1px solid var(--ui-hairline);padding-top:1.25rem;display:grid;gap:1rem}
.library-eyebrow{font-size:.65rem;letter-spacing:.15em;color:var(--ui-text-3)}
.library-badge{border:1px solid var(--ui-hairline);border-radius:99px;padding:.35rem .7rem;font-size:.7rem;color:var(--ui-text-2)}
.library-grid{display:grid;grid-template-columns:1fr 1.35fr;gap:1rem}
.library-block{border:1px solid var(--ui-hairline);border-radius:16px;padding:1rem;background:var(--ui-surface)}
.library-help{font-size:.75rem;color:var(--ui-text-3);margin-top:.35rem;line-height:1.6}
.library-input{border:1px solid var(--ui-hairline);border-radius:10px;background:var(--ui-surface);color:inherit;padding:.65rem .75rem;font-size:.8rem;min-width:130px}
.library-button{border:1px solid var(--ui-hairline);border-radius:99px;padding:.6rem 1rem;font-size:.75rem;white-space:nowrap;transition:transform .15s,opacity .15s,background .15s}
.library-button:hover:not(:disabled){background:var(--ui-fill-hover);transform:translateY(-1px)}
.library-primary{background:var(--ui-text);color:var(--ui-surface);border-color:transparent;font-weight:600}
.library-primary:hover:not(:disabled){background:var(--ui-text);opacity:.85}
.library-button:disabled,.library-link:disabled{opacity:.4;cursor:not-allowed}
.library-button:focus-visible,.library-input:focus-visible,.library-link:focus-visible{outline:2px solid var(--ui-text-2);outline-offset:3px}
.library-link{font-size:.7rem;color:var(--ui-text-2);text-decoration:underline;text-underline-offset:3px}
.library-footer{padding:.2rem .1rem}.library-notice{font-size:.8rem;color:var(--ui-text-2)}
@media(max-width:900px){.library-grid{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){.library-button{transition:none}}
</style>
