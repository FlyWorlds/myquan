<script setup lang="ts">
import type { StrategyTab } from '~/types/snapshot'
import type { StrategyEntry } from '~/types/registry'

const props = defineProps<{ tab: StrategyTab; class?: string }>()

const entry = computed(
  (): StrategyEntry => ({
    ...props.tab,
    backtest: (props.tab as StrategyEntry).backtest,
    reportPath: (props.tab as StrategyEntry).reportPath,
    picks: props.tab.picks,
  }),
)
</script>

<template>
  <details class="card" :class="props.class">
    <summary class="cursor-pointer px-4 py-3 text-sm font-semibold text-ui-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      {{ tab.name }}
    </summary>
    <div class="px-3 pb-3">
      <StrategyRegistryCard :tab="entry" :anchor="false" />
    </div>
  </details>
</template>
