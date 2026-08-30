<script setup lang="ts">
defineProps<{
  chg?: number | null
}>()

function cls(v?: number | null) {
  if (v == null || Number.isNaN(v)) return 'text-ui-text-3'
  if (v > 0) return 'text-up'
  if (v < 0) return 'text-down'
  return 'text-ui-text-3'
}

function fmt(v?: number | null, digits = 2, suffix = '') {
  if (v == null || Number.isNaN(v)) return '-'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}${suffix}`
}
</script>

<template>
  <span :class="cls(chg)"><slot>{{ fmt(chg) }}</slot></span>
</template>
