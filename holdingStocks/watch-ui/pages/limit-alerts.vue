<script setup lang="ts">
import { baiduStockUrl } from '~/utils/stockLink'
import { fmtNum } from '~/utils/format'
const { data, loading, error, refresh } = useMarketRadar()
const query = ref('')
const pool = ref<'sealed' | 'broken'>('sealed')
const board = ref('全部')
const theme = ref('')
const sort = ref('height')
const summary = computed(() => data.value?.summary)
const sourceRows = computed(() => pool.value === 'sealed' ? data.value?.stocks || [] : data.value?.broken || [])
const rows = computed(() => sourceRows.value.filter(s => {
  const height = s.limit_days
  return (board.value === '全部' || board.value === '首板' && height === 1 || board.value === '连板' && height != null && height >= 2 || board.value.endsWith('板') && Number.parseInt(board.value) === height)
    && (!theme.value || s.themes?.includes(theme.value))
    && `${s.code} ${s.name} ${s.industry || ''} ${s.reason || ''} ${s.reason_detail || ''}`.toLowerCase().includes(query.value.trim().toLowerCase())
}).slice().sort((a,b) => sort.value === 'change' ? (b.pct ?? -Infinity)-(a.pct ?? -Infinity)
  : sort.value === 'time' ? (b.quote_at || '').localeCompare(a.quote_at || '')
  : (b.limit_days ?? 0)-(a.limit_days ?? 0) || (b.pct ?? 0)-(a.pct ?? 0)))
const leadingThemes = computed(() => (data.value?.themes || []).slice(0,8))
const hasMicrostructure = computed(() => rows.value.some(s => s.seal_fund_yi != null || s.first_seal != null || s.break_times != null))
const ladder = computed(() => {
  const groups = new Map<number, number>()
  for (const s of data.value?.stocks || []) if (s.limit_days != null) groups.set(s.limit_days, (groups.get(s.limit_days) || 0)+1)
  return [...groups.entries()].sort((a,b)=>b[0]-a[0])
})
function switchPool(value: 'sealed' | 'broken') { pool.value=value; board.value='全部'; theme.value='' }
useHead({ title: '涨停预警 · 持仓盯盘' })
</script>
<template>
  <main class="page-shell py-6">
    <header class="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div><p class="mb-1 text-xs font-semibold tracking-widest text-accent">MARKET RADAR</p><h1 class="text-2xl font-bold">涨停预警</h1><p class="mt-2 text-sm text-ui-text-2">看当日封板、连板梯队与涨停原因。</p></div>
      <button class="btn" :disabled="loading || data?.refreshing" @click="refresh(true)">{{ loading || data?.refreshing ? '更新中…' : '刷新数据' }}</button>
    </header>
    <MarketRadarStatus :data="data" :error="error" />
    <div class="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-6">
      <div v-for="item in [{label:'封板家数',value:summary?.sealed},{label:'炸板家数',value:summary?.broken},{label:'跌停家数',value:summary?.down},{label:'炸板率',value:summary?.break_rate == null ? null : summary.break_rate+'%'},{label:'最高连板',value:summary?.max_height == null ? null : summary.max_height+'板'},{label:'有题材标签',value:data?.reason_coverage}]" :key="item.label" class="card p-4">
        <p class="text-xs text-ui-text-2">{{ item.label }}</p><p class="mt-3 text-2xl font-semibold tabular-nums">{{ item.value ?? '—' }}</p>
      </div>
    </div>
    <div v-if="data?.stocks?.length" class="mb-5 grid gap-4 lg:grid-cols-2">
      <section class="card p-4"><div class="mb-3 flex items-center justify-between"><h2 class="text-sm font-semibold">连板梯队</h2><span class="text-xs text-ui-text-3">按当日封板池统计</span></div><div class="flex flex-wrap gap-2"><button v-for="[height,count] in ladder" :key="height" class="btn" @click="switchPool('sealed'); board=height === 1 ? '首板' : height+'板'"><b class="text-up">{{ height }}板</b><span class="ml-2 text-ui-text-2">{{ count }}只</span></button></div><p class="mt-3 text-xs text-ui-text-3">点击梯队查看对应高度的标的；高度以数据源口径为准。</p></section>
      <section class="card p-4"><div class="mb-3 flex items-center justify-between"><h2 class="text-sm font-semibold">热门涨停题材</h2><NuxtLink to="/theme-heat" class="text-xs text-accent">全部题材 ↗</NuxtLink></div><div class="flex flex-wrap gap-2"><button v-for="t in leadingThemes" :key="t.name" class="rounded-lg border border-ui-hairline px-3 py-2 text-xs" :class="theme === t.name ? 'text-accent bg-ui-fill-active' : 'text-ui-text-2'" @click="pool='sealed'; theme=theme === t.name ? '' : t.name">{{ t.name }} <b class="ml-1">{{ t.count }}</b></button></div></section>
    </div>
    <section class="card overflow-hidden">
      <div class="space-y-3 border-b border-ui-hairline p-4">
        <div class="flex flex-wrap items-center justify-between gap-3"><div class="flex gap-2"><button class="btn" :class="pool === 'sealed' ? 'text-accent' : ''" @click="switchPool('sealed')">已封板 {{ summary?.sealed ?? '—' }}</button><button class="btn" :class="pool === 'broken' ? 'text-accent' : ''" @click="switchPool('broken')">炸板跟踪 {{ summary?.broken ?? '—' }}</button></div><span class="text-xs text-ui-text-3">显示 {{ rows.length }} / {{ sourceRows.length }} 只</span></div>
        <div class="flex flex-wrap gap-2"><input v-model="query" class="min-w-60 flex-1 rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm" placeholder="搜索股票、题材或涨停原因" aria-label="搜索股票" /><select v-model="board" class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm" aria-label="连板筛选"><option>全部</option><option>首板</option><option>连板</option><option v-for="[height] in ladder.filter(([h])=>h > 1)" :key="height">{{ height }}板</option></select><select v-model="sort" class="rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm" aria-label="排序方式"><option value="height">连板高度优先</option><option value="change">涨幅优先</option><option value="time">源记录时间优先</option></select><button v-if="query || theme || board !== '全部'" class="btn text-ui-text-2" @click="query=''; theme=''; board='全部'">清除筛选{{ theme ? ' · '+theme : '' }}</button></div>
      </div>
      <div class="overflow-x-auto"><table class="w-full text-left text-sm">
        <thead class="border-b border-ui-hairline text-xs text-ui-text-2"><tr><th class="whitespace-nowrap p-4">标的 / 连板</th><th class="whitespace-nowrap p-3">现价 / 涨跌幅</th><th class="min-w-80 p-3">涨停题材与原因</th><th class="whitespace-nowrap p-3">源记录时间</th><th v-if="hasMicrostructure" class="whitespace-nowrap p-3">封单 / 首封 / 炸板</th></tr></thead>
        <tbody class="divide-y divide-ui-hairline"><tr v-for="s in rows" :key="s.code" class="align-top hover:bg-ui-fill-hover">
          <td class="whitespace-nowrap p-4"><a :href="baiduStockUrl(s.code,s.name)" target="_blank" rel="noopener" class="font-semibold hover:text-accent">{{ s.name }}</a><div class="mt-2 flex items-center gap-2"><span class="font-mono text-xs text-ui-text-3">{{ s.code }}</span><span v-if="s.limit_days" class="rounded border border-ui-hairline px-1.5 py-0.5 text-xs" :class="s.limit_days >= 2 ? 'text-up' : 'text-accent'">{{ s.limit_days === 1 ? '首板' : s.limit_days+'连板' }}</span><span v-else class="text-xs text-ui-text-3">连板未知</span></div></td>
          <td class="whitespace-nowrap p-3"><div class="font-semibold tabular-nums">{{ fmtNum(s.price,2) }}</div><div class="mt-2 text-xs"><ChgText :chg="s.pct">{{ s.pct == null ? '—' : (s.pct > 0 ? '+' : '')+fmtNum(s.pct,2)+'%' }}</ChgText></div></td>
          <td class="p-3"><div v-if="s.themes?.length" class="mb-2 flex flex-wrap gap-1.5"><button v-for="tag in s.themes" :key="tag" class="rounded border border-ui-hairline px-2 py-1 text-xs text-accent" @click="theme=theme === tag ? '' : tag">{{ tag }}</button></div><p v-else class="text-xs text-ui-text-3">数据源暂无题材标签</p><details v-if="s.reason_detail" class="mt-2 text-xs leading-6 text-ui-text-2"><summary class="cursor-pointer"><span class="ml-1">{{ s.reason_detail.slice(0,88) }}{{ s.reason_detail.length > 88 ? '…' : '' }}</span><span class="ml-2 text-accent">展开原因</span></summary><p class="mt-2 whitespace-pre-line rounded-lg bg-ui-page p-3">{{ s.reason_detail }}</p></details><p v-else class="mt-2 text-xs text-ui-text-3">暂无详细原因</p><p v-if="s.industry" class="mt-2 text-xs text-ui-text-3">行业 · {{ s.industry }}</p></td>
          <td class="whitespace-nowrap p-3 font-mono text-xs text-ui-text-2">{{ s.quote_at?.slice(11) || '—' }}</td>
          <td v-if="hasMicrostructure" class="whitespace-nowrap p-3 text-xs leading-6 text-ui-text-2"><p>封单 {{ fmtNum(s.seal_fund_yi,3) }} 亿</p><p>首封 {{ s.first_seal || '—' }}</p><p>炸板 {{ s.break_times ?? '—' }} 次</p></td>
        </tr></tbody>
      </table></div>
      <p v-if="!rows.length" class="px-4 py-12 text-center text-sm text-ui-text-2">{{ !data?.trade_date ? '实时数据暂不可用，正在尝试更新' : '当前筛选下暂无股票，可清除筛选查看完整列表' }}</p>
      <p class="border-t border-ui-hairline p-4 text-xs leading-relaxed text-ui-text-3">涨停原因来自行情提供方的归因说明，不代表已核实的唯一上涨原因。源记录时间不是首次封板时间；无封单、首封和炸板次数字段时自动隐藏相关列。炸板率＝炸板数÷（封板数＋炸板数）。每15秒轮询，实际变化延迟取决于上游。</p>
    </section>
  </main>
</template>
