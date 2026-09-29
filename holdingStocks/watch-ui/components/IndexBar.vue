<script setup lang="ts">
import type { IndexQuote } from '~/types/snapshot'
import { fmtNum, fmtSignedPct } from '~/utils/format'
import { baiduIndexUrl } from '~/utils/stockLink'

defineProps<{ indices: IndexQuote[] }>()
</script>

<template>
  <div class="grid gap-3 sm:grid-cols-2">
    <a
      v-for="ix in indices"
      :key="ix.code"
      :href="baiduIndexUrl(ix.code, ix.name)"
      target="_blank"
      rel="noopener"
      class="card block p-3 transition-colors hover:border-accent"
    >
      <div class="mb-2 flex items-center gap-2 text-sm">
        <span class="rounded-full border border-ui-hairline px-2 py-0.5 text-xs text-accent">{{ ix.market }}</span>
        <strong class="hover:text-accent hover:underline">{{ ix.name }}</strong>
        <code class="text-xs text-ui-text-3">{{ ix.code }}</code>
      </div>
      <p v-if="ix.error" class="text-sm text-up">{{ ix.error }}</p>
      <div v-else class="grid grid-cols-3 gap-2 text-sm">
        <div><span class="text-ui-text-2">点数</span><div class="sensitive font-semibold">{{ fmtNum(ix.price) }}</div></div>
        <div><span class="text-ui-text-2">涨跌点</span><div class="sensitive font-semibold"><ChgText :chg="ix.chgPoints" /></div></div>
        <div><span class="text-ui-text-2">涨跌幅</span><div class="sensitive font-semibold"><ChgText :chg="ix.chgPct">{{ fmtSignedPct(ix.chgPct) }}</ChgText></div></div>
      </div>
    </a>
  </div>
</template>
