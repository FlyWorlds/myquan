<script setup lang="ts">
defineProps<{
  items: { id: string; label?: string }[]
  ariaLabel?: string
}>()
</script>

<template>
  <nav
    v-if="items.length"
    class="registry-sticky-nav"
    :aria-label="ariaLabel ?? '页内导航'"
  >
    <a
      v-for="item in items"
      :key="item.id"
      :href="`#${item.id}`"
      class="tab-pill tab-pill-idle text-xs"
    >
      {{ item.label ?? item.id }}
    </a>
  </nav>
</template>
