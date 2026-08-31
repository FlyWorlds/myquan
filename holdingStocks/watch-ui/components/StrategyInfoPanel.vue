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
  <div :class="props.class">
    <StrategyRegistryCard :tab="entry" :anchor="false" />
  </div>
</template>
