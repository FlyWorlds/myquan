<script setup lang="ts">
import type { FactorEntry } from '~/types/registry'

defineProps<{ factor: FactorEntry }>()
</script>

<template>
  <article :id="factor.id" class="card registry-scroll-target p-4">
    <header class="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h2 class="text-lg font-bold">
          <code class="text-accent">{{ factor.id }}</code>
          · {{ factor.name }}
        </h2>
        <p v-if="factor.description" class="mt-1 text-sm text-ui-text-2">{{ factor.description }}</p>
      </div>
      <span
        class="rounded-full px-2 py-0.5 text-xs font-semibold"
        :class="factor.implemented ? 'bg-accent/15 text-accent' : 'bg-ui-fill-active text-ui-text-3'"
      >
        {{ factor.implemented ? '已实现' : '规划中' }}
      </span>
    </header>

    <div v-if="factor.meta && Object.keys(factor.meta).length" class="mt-3 flex flex-wrap gap-2">
      <span
        v-for="(val, key) in factor.meta"
        :key="String(key)"
        class="rounded-md border border-ui-hairline px-2 py-0.5 text-xs text-ui-text-2"
      >
        {{ key }}: {{ val }}
      </span>
    </div>

    <div v-if="factor.used_by?.length" class="mt-4">
      <h3 class="text-sm font-semibold text-ui-text">挂载策略</h3>
      <ul class="mt-2 space-y-1 text-sm text-ui-text-2">
        <li v-for="s in factor.used_by ?? []" :key="`${s.id}-${s.role}`">
          <NuxtLink :to="`/strategies#${s.id}`" class="text-accent hover:underline">{{ s.label }}</NuxtLink>
          · {{ s.role }}
          <span v-if="s.filter_desc">（{{ s.filter_desc }}）</span>
        </li>
      </ul>
    </div>

    <div v-if="factor.rules_text" class="mt-4">
      <h3 class="text-sm font-semibold text-ui-text">规则摘要</h3>
      <pre class="mt-2 max-h-96 overflow-auto rounded-lg border border-ui-hairline bg-ui-ink/40 p-3 text-xs leading-relaxed text-ui-text-2 whitespace-pre-wrap">{{ factor.rules_text }}</pre>
    </div>
  </article>
</template>
