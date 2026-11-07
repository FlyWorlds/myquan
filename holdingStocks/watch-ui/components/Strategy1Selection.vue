<script setup lang="ts">
interface Pick { code: string; name: string; thr: number; quality_pass: boolean; pl_ratio: number | null; data_end: string }
interface Draft { id: string; indices: string[]; period: string; picks: Pick[]; added: string[]; removed: string[]; warning: string; saved_at?: string; failed_candidates: string[] }
interface State { running: boolean; error?: string; progress?: { stage: string; completed: number; total: number }; draft?: Draft; active?: { selection_indices?: string[]; built_at?: string; n_picks?: number } }
const options = ['沪深300', '中证500', '中证1000', '中证1500']
const selected = ref([...options])
const state = ref<State>({ running: false })
const busy = ref(false)
const message = ref('')
const connected = ref(false)
const expanded = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const sameScope = computed(() => !!state.value.draft && [...selected.value].sort().join() === [...state.value.draft.indices].sort().join())

function toggleExpanded() {
  expanded.value = !expanded.value
  try {
    localStorage.setItem('strategy1_selection_expanded', String(expanded.value))
  } catch {}
}

async function request(path: string, body?: object) {
  const response = await fetch(`/api/strategy1/selection${path}`, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`)
  return data as State
}
async function poll() {
  try {
    const data = await request('')
    if (disposed) return
    if (!connected.value) selected.value = [...(data.draft?.indices || data.active?.selection_indices || options)]
    state.value = data
    connected.value = true
    message.value = ''
    if (data.running) expanded.value = true
  } catch (error) { if (!disposed) message.value = `${error}；正在重新查询状态` }
  if (!disposed) timer = setTimeout(poll, 3000)
}
async function act(action: 'run' | 'save') {
  busy.value = true
  message.value = ''
  clearTimeout(timer)
  if (action === 'run') {
    expanded.value = true
    try { localStorage.setItem('strategy1_selection_expanded', 'true') } catch {}
  }
  try {
    state.value = await request(`/${action}`, action === 'run' ? { indices: selected.value } : { draft_id: state.value.draft?.id })
  } catch (error) { message.value = String(error) }
  finally { busy.value = false; if (!disposed) timer = setTimeout(poll, 3000) }
}
onMounted(() => {
  try {
    const stored = localStorage.getItem('strategy1_selection_expanded')
    if (stored !== null) expanded.value = stored === 'true'
  } catch {}
  poll()
})
onBeforeUnmount(() => { disposed = true; clearTimeout(timer) })
</script>

<template>
  <section class="card my-3 p-4" aria-label="策略1重新选股">
    <div
      class="flex flex-wrap items-center justify-between gap-3 cursor-pointer select-none"
      @click="toggleExpanded"
    >
      <div class="flex items-center gap-2">
        <span class="text-xs text-ui-text-3 transition-transform inline-block w-3 text-center">
          {{ expanded ? '▼' : '▶' }}
        </span>
        <h3 class="text-sm font-bold text-ui-text">策略1选股 · 目标30只</h3>
        <span v-if="!expanded && state.active?.built_at" class="text-xs text-ui-text-3">
          （当前生效池：{{ state.active?.n_picks ?? 30 }}只 · 点击展开）
        </span>
        <span v-if="!expanded && state.draft && !state.draft.saved_at" class="text-xs text-amber-400">
          [候选已生成待保存]
        </span>
        <span v-if="state.running" class="ml-2 text-xs text-accent animate-pulse">
          {{ state.progress?.stage || '选股中' }} · {{ state.progress?.completed || 0 }}/{{ state.progress?.total || '30' }}
        </span>
      </div>
      <div class="flex items-center gap-2" @click.stop>
        <button
          class="tab-pill tab-pill-active disabled:opacity-40"
          :disabled="!connected || busy || state.running || !selected.length"
          @click="act('run')"
        >
          {{ state.running ? '选股中…' : '重新选股' }}
        </button>
        <button
          v-if="expanded || (state.draft && !state.draft.saved_at)"
          class="tab-pill tab-pill-active disabled:opacity-40"
          :disabled="!connected || busy || state.running || !sameScope || !state.draft || !!state.draft.saved_at"
          @click="act('save')"
        >
          保存并启用新股票池
        </button>
        <button
          type="button"
          class="text-xs text-ui-text-3 hover:text-ui-text ml-1 px-1.5 py-0.5 rounded border border-ui-hairline hover:border-ui-hairline-strong transition-colors"
          @click.stop="toggleExpanded"
        >
          {{ expanded ? '收起 ▲' : '展开 ▼' }}
        </button>
      </div>
    </div>

    <!-- 可折叠内容主体 -->
    <div v-show="expanded" class="border-t border-ui-hairline mt-3 pt-3">
      <fieldset class="flex flex-wrap gap-4" :disabled="busy || state.running">
        <legend class="mb-2 text-xs text-ui-text-2">候选范围（多选取并集）</legend>
        <label v-for="option in options" :key="option" class="flex items-center gap-1.5 text-sm"><input v-model="selected" type="checkbox" :value="option">{{ option }}</label>
      </fieldset>
      <p v-if="selected.includes('中证1500')" class="mt-2 text-xs text-amber-400">现有成分表“中证1500”标签含2000只，指数身份待核实；勾选时沿用该表范围。</p>
      <p class="mt-2 text-xs text-ui-text-3">30只 · 主板、非ST、股价低于100元 · 因子13A＋因子16 · 数量不足允许放宽质量带。重新选股只生成候选，保存后启用。</p>
      <p v-if="state.active?.built_at" class="mt-1 text-xs text-ui-text-3">当前生效池：{{ state.active.n_picks }}只 · 保存于 {{ state.active.built_at }}</p>
      <div v-if="state.running" class="mt-3 text-sm" role="status">
        {{ state.progress?.stage }} · {{ state.progress?.completed || 0 }}/{{ state.progress?.total || '待确定' }}
        <progress v-if="state.progress?.total" class="mt-2 h-2 w-full" :value="state.progress.completed" :max="state.progress.total" aria-label="选股回测进度" />
      </div>
      <p v-if="message || state.error" role="alert" class="mt-2 text-sm text-rose-400">{{ message || state.error }}</p>
      <div v-if="state.draft && !state.running" class="mt-3">
        <p class="text-sm text-accent">{{ state.draft.saved_at ? '已保存，新股票池已启用' : '候选已生成，尚未保存' }} · {{ state.draft.picks.length }}只 · 新增{{ state.draft.added.length }}只 / 移出{{ state.draft.removed.length }}只</p>
        <p class="mt-1 text-xs text-ui-text-3">{{ state.draft.period }}；数据截止日期见下表。</p>
        <p v-if="!sameScope" class="mt-1 text-xs text-amber-400">勾选范围已改变，请重新选股后再保存。</p>
        <p v-if="state.draft.failed_candidates.length" class="mt-1 text-xs text-amber-400">{{ state.draft.failed_candidates.length }}只股票数据不足或获取失败，未参与最终排序。</p>
        <div class="mt-2 max-h-96 overflow-auto">
          <table class="w-full text-left text-xs">
            <thead><tr><th class="p-2">股票</th><th>变更</th><th>质量带</th><th>盈亏比</th><th>买入阈值</th><th>日线截至</th></tr></thead>
            <tbody><tr v-for="pick in state.draft.picks" :key="pick.code" class="border-t border-ui-hairline"><td class="p-2">{{ pick.code }} {{ pick.name }}</td><td>{{ state.draft.added.includes(pick.code) ? '新增' : '保留' }}</td><td>{{ pick.quality_pass ? '通过' : '放宽补入' }}</td><td>{{ pick.pl_ratio?.toFixed(2) ?? '—' }}</td><td>{{ (pick.thr * 100).toFixed(1) }}%</td><td>{{ pick.data_end }}</td></tr></tbody>
          </table>
        </div>
        <p v-if="state.draft.removed.length" class="mt-2 text-xs text-ui-text-2">移出：{{ state.draft.removed.join('、') }}。已有持仓继续由持仓管理处理。</p>
      </div>
    </div>
  </section>
</template>
