<script setup lang="ts">
import type { MarketRadar } from '~/types/marketRadar'
defineProps<{ data: MarketRadar | null; error?: string }>()
</script>
<template>
  <div class="card mb-5 space-y-2 px-4 py-3 text-xs text-ui-text-2" role="status">
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <span class="rounded-full border border-ui-hairline px-2 py-1 font-semibold" :class="data?.historical || data?.stale ? 'text-amber-500' : 'text-accent'">
        {{ data?.status === 'unavailable' ? '实时数据暂不可用' : !data?.trade_date ? '正在连接数据源' : data.historical ? '历史快照 · 非今日实时' : data.status === 'snapshot' ? '公开快照 · 非实时推送' : data.stale ? '缓存数据 · 待更新' : '当日接口数据' }}
      </span>
      <span>数据日 <b class="text-ui-text">{{ data?.trade_date || '—' }}</b></span>
      <span>来源 {{ data?.source || '东财 / 同花顺' }}</span>
      <span v-if="data?.source_at">源记录时间 {{ data.source_at }}</span>
      <span>最近拉取 {{ data?.fetched_at || '—' }}</span>
      <span v-if="data?.refreshing" class="text-accent">正在更新…</span>
    </div>
    <p v-if="data?.historical" class="text-amber-500">上游当日接口暂未取得，以下为 {{ data.trade_date }} 参考数据，不能用于判断今天是否封板。</p>
    <p v-if="error || data?.error" class="text-amber-500">{{ error || data?.error }}</p>
    <p v-if="data?.errors?.length">{{ data.errors.join('；') }}。每15秒更新一次。</p>
  </div>
</template>
