<script setup lang="ts">
import type { FactorEntry } from '~/types/registry'

const props = defineProps<{ factor: FactorEntry }>()

const shortDesc = computed(() => {
  const d = String(props.factor.description || '').trim()
  if (!d) return '暂无简介'
  return d.length > 72 ? `${d.slice(0, 72)}…` : d
})

const usedCount = computed(() => props.factor.used_by?.length ?? 0)
</script>

<template>
  <article :id="factor.id" class="registry-scroll-target">
    <RegistryHoverCard>
      <template #compact>
        <header class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <h2 class="truncate text-base font-bold text-ui-text">{{ factor.name }}</h2>
            <p v-if="factor.category_label" class="mt-1 text-xs text-ui-text-3">{{ factor.category_label }}</p>
            <p class="mt-1 line-clamp-2 text-sm leading-relaxed text-ui-text-2">{{ shortDesc }}</p>
          </div>
          <span
            class="shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold"
            :class="factor.implemented ? 'bg-accent/15 text-accent' : 'bg-ui-fill-active text-ui-text-3'"
          >
            {{ factor.implemented ? '已实现' : '规划中' }}
          </span>
        </header>
        <div class="mt-2 text-sm">
          <span class="text-ui-text-2">挂载策略</span>
          <b v-if="usedCount">{{ usedCount }} 个</b>
          <b v-else class="text-accent">可挂 · 尚未绑定</b>
        </div>
      </template>

      <template #detail>
        <h3 class="text-base font-bold">{{ factor.name }}</h3>
        <p class="mt-1 text-xs text-ui-text-3"><code>{{ factor.id }}</code></p>
        <p v-if="factor.description" class="mt-2 text-sm leading-relaxed text-ui-text-2">{{ factor.description }}</p>

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
          <h4 class="text-sm font-semibold text-ui-text">挂载策略</h4>
          <ul class="mt-2 space-y-1 text-sm text-ui-text-2">
            <li v-for="s in factor.used_by ?? []" :key="`${s.id}-${s.role}`">
              <NuxtLink
                v-if="s.registry_kind !== 'hidden'"
                :to="`/strategies#${s.id}`"
                class="text-accent hover:underline"
              >{{ s.label }}</NuxtLink>
              <span v-else class="text-ui-text-2">{{ s.label }}（CLI）</span>
              · {{ s.role }}
              <span v-if="s.filter_desc">（{{ s.filter_desc }}）</span>
            </li>
          </ul>
        </div>
        <p v-else class="mt-4 text-xs leading-relaxed text-ui-text-3">
          尚未挂到 Web 策略。之后可在策略 <code>bindings.py</code> 里
          <code>bind_factor('{{ factor.id }}')</code>。
        </p>

        <div v-if="factor.rules_text" class="mt-4">
          <h4 class="text-sm font-semibold text-ui-text">规则摘要</h4>
          <pre class="mt-2 max-h-48 overflow-auto rounded-lg border border-ui-hairline bg-ui-ink/40 p-3 text-xs leading-relaxed whitespace-pre-wrap text-ui-text-2">{{ factor.rules_text }}</pre>
        </div>
      </template>
    </RegistryHoverCard>
  </article>
</template>
