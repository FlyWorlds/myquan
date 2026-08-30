<script setup lang="ts">
import type { StrategyTab } from '~/types/snapshot'

defineProps<{ tab: StrategyTab }>()
</script>

<template>
  <div class="card p-4">
    <h2 class="flex flex-wrap items-center gap-2 text-lg font-bold">
      {{ tab.label }}
      <span v-if="tab.is_watch_default" class="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs font-bold text-accent">盯盘默认</span>
    </h2>
    <p v-if="tab.description" class="mt-2 text-sm text-ui-text-2">{{ tab.description }}</p>
    <p class="mt-2 text-sm text-ui-text-2">
      挂载因子：
      <span v-for="(f, i) in tab.factors" :key="f.id">
        <template v-if="i"> + </template>
        <code class="text-accent">{{ f.id }}</code>（{{ f.name }}）
      </span>
    </p>
    <div class="mt-3 overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead class="text-left text-ui-text-2">
          <tr>
            <th class="px-2 py-2">因子 ID</th>
            <th class="px-2 py-2">因子名称</th>
            <th class="px-2 py-2">角色</th>
            <th class="px-2 py-2">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in tab.factors" :key="f.id" class="border-t border-ui-hairline">
            <td class="px-2 py-2"><code>{{ f.id }}</code></td>
            <td class="px-2 py-2">{{ f.name }}</td>
            <td class="px-2 py-2">{{ f.role }}</td>
            <td class="max-w-lg px-2 py-2 text-xs text-ui-text-2">{{ f.filter_desc || f.description || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
