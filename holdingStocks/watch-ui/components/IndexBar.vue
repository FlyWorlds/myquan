<script setup lang="ts">
import type { IndexQuote } from '~/types/snapshot'

defineProps<{ indices: IndexQuote[] }>()

function fmtNum(v?: number | null, d = 2) {
  if (v == null) return '-'
  return v.toFixed(d)
}
</script>

<template>
  <div class="grid gap-3 sm:grid-cols-2">
    <article v-for="ix in indices" :key="ix.code" class="card p-3">
      <div class="mb-2 flex items-center gap-2 text-sm">
        <span class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-accent">{{ ix.market }}</span>
        <strong>{{ ix.name }}</strong>
        <code class="text-xs text-ui-text-3">{{ ix.code }}</code>
      </div>
      <p v-if="ix.error" class="text-sm text-up">{{ ix.error }}</p>
      <div v-else class="grid grid-cols-3 gap-2 text-sm">
        <div><span class="text-ui-text-2">点数</span><div class="sensitive font-semibold">{{ fmtNum(ix.price) }}</div></div>
        <div><span class="text-ui-text-2">涨跌点</span><div class="sensitive font-semibold"><ChgText :chg="ix.chgPoints" /></div></div>
        <div><span class="text-ui-text-2">涨跌幅</span><div class="sensitive font-semibold"><ChgText :chg="ix.chgPct">{{ ix.chgPct == null ? '-' : `${ix.chgPct > 0 ? '+' : ''}${ix.chgPct.toFixed(2)}%` }}</ChgText></div></div>
      </div>
    </article>
  </div>
</template>
