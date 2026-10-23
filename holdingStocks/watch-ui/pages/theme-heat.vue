<script setup lang="ts">
import { baiduStockUrl } from '~/utils/stockLink'
import { fmtNum } from '~/utils/format'
const { data, loading, error, refresh } = useMarketRadar()
const mode = ref<'themes' | 'industries'>('themes')
const selected = ref('')
const search = ref('')
const groups = computed(() => (data.value?.[mode.value] || []).filter(t => t.name.includes(search.value.trim())))
const active = computed(() => groups.value.find(t => t.name === selected.value) || groups.value[0])
const maximum = computed(() => Math.max(1, ...groups.value.map(t => t.count)))
useHead({ title: '题材热度 · 持仓盯盘' })
</script>
<template>
  <main class="page-shell py-6">
    <header class="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p class="mb-1 text-xs font-semibold tracking-widest text-accent">THEME PULSE</p><h1 class="text-2xl font-bold">题材热度</h1><p class="mt-2 text-sm text-ui-text-2">从封板股票看资金关注方向，点击题材查看成员与连板高度。</p></div><button class="btn" :disabled="loading || data?.refreshing" @click="refresh(true)">{{ loading || data?.refreshing ? '更新中…' : '刷新数据' }}</button></header>
    <MarketRadarStatus :data="data" :error="error" />
    <div class="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4"><div class="card p-4"><p class="text-xs text-ui-text-2">覆盖封板股</p><p class="mt-3 text-2xl font-semibold">{{ data?.summary?.sealed ?? '—' }} <span class="text-sm font-normal text-ui-text-3">只</span></p></div><div class="card p-4"><p class="text-xs text-ui-text-2">取得题材标签</p><p class="mt-3 text-2xl font-semibold">{{ data?.reason_coverage ?? '—' }} <span class="text-sm font-normal text-ui-text-3">只</span></p></div><div class="card p-4"><p class="text-xs text-ui-text-2">题材数量</p><p class="mt-3 text-2xl font-semibold">{{ data?.themes?.length ?? '—' }}</p></div><div class="card p-4"><p class="text-xs text-ui-text-2">最热{{ mode === 'themes' ? '题材' : '行业' }}</p><p class="mt-3 text-xl font-semibold text-accent">{{ (data?.[mode] || [])[0]?.name || '—' }}</p></div></div>
    <div class="grid gap-5 lg:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.5fr)]">
      <section class="card p-4"><div class="mb-4 flex flex-wrap gap-2"><button class="btn" :class="mode === 'themes' ? 'text-accent' : ''" @click="mode='themes'; selected=''">题材排行</button><button class="btn" :class="mode === 'industries' ? 'text-accent' : ''" @click="mode='industries'; selected=''">行业分布</button><input v-model="search" placeholder="搜索题材 / 行业" aria-label="搜索题材或行业" class="w-full rounded-lg border border-ui-hairline bg-ui-page px-3 py-2 text-sm" /></div>
        <div class="space-y-1"><button v-for="(t,i) in groups" :key="t.name" class="block w-full rounded-lg px-3 py-3 text-left transition hover:bg-ui-fill-hover" :class="active?.name === t.name ? 'bg-ui-fill-active' : ''" @click="selected=t.name"><div class="mb-2 flex items-center gap-3 text-sm"><span class="w-5 font-mono text-xs text-ui-text-3">{{ String(i+1).padStart(2,'0') }}</span><span class="flex-1 font-semibold">{{ t.name }}</span><span class="tabular-nums text-accent">{{ t.count }}只</span></div><div class="ml-8 h-1.5 overflow-hidden rounded-full bg-ui-page"><div class="h-full rounded-full bg-accent opacity-60" :style="{width: (t.count/maximum*100)+'%'}" /></div></button></div>
        <p v-if="!groups.length" class="py-10 text-center text-sm text-ui-text-2">{{ mode === 'themes' && data?.trade_date ? '未取得题材标签，可切换行业分布查看' : data?.refreshing ? '正在拉取数据…' : '暂无匹配数据' }}</p>
      </section>
      <section class="card self-start overflow-hidden"><div class="border-b border-ui-hairline p-5"><p class="text-xs text-ui-text-3">{{ mode === 'themes' ? '题材成员' : '行业成员' }}</p><h2 class="mt-2 text-xl font-bold">{{ active?.name || '选择题材' }}</h2><div v-if="active" class="mt-3 flex flex-wrap gap-4 text-sm text-ui-text-2"><span>封板 <b class="text-ui-text">{{ active.count }}</b> 只</span><span>最高 <b class="text-up">{{ active.max_height }}</b> 板</span><span>封单合计 <b class="text-ui-text">{{ fmtNum(active.seal_fund_yi,3) }}</b> 亿</span></div></div>
        <div class="overflow-x-auto"><table class="w-full whitespace-nowrap text-left text-sm"><thead class="border-b border-ui-hairline text-xs text-ui-text-2"><tr><th class="p-4">标的</th><th class="p-3">连板高度</th><th class="p-3">封单 / 亿</th><th class="p-3">首次封板</th><th class="p-3">涨停题材</th></tr></thead><tbody class="divide-y divide-ui-hairline"><tr v-for="s in active?.stocks || []" :key="s.code" class="hover:bg-ui-fill-hover"><td class="p-4"><a :href="baiduStockUrl(s.code,s.name)" target="_blank" rel="noopener" class="font-semibold hover:text-accent">{{ s.name }}</a><div class="mt-1 font-mono text-xs text-ui-text-3">{{ s.code }}</div></td><td class="p-3 text-up">{{ s.limit_days || 1 }}板</td><td class="p-3">{{ fmtNum(s.seal_fund_yi,3) }}</td><td class="p-3 font-mono text-xs">{{ s.first_seal || '—' }}</td><td class="max-w-xs whitespace-normal p-3 text-xs leading-relaxed text-ui-text-2">{{ s.reason || '暂无题材标签' }}</td></tr></tbody></table></div>
        <p class="border-t border-ui-hairline p-4 text-xs leading-relaxed text-ui-text-3">热度＝该题材内去重后的封板股票数。每只股票可属于多个题材，题材数量不可相加为市场总数；行业与题材分别统计。仅关联同一份数据的涨停原因，不混用昨日标签与今日涨停池。</p>
      </section>
    </div>
  </main>
</template>
