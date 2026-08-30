<script setup lang="ts">
const { isDark, toggleScheme } = useTheme()
</script>

<template>
  <button
    type="button"
    class="btn btn-ghost gap-1.5"
    :aria-label="isDark ? '切换浅色主题' : '切换深色主题'"
    @click="toggleScheme()"
  >
    <svg v-if="isDark" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
    <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
    <span class="hidden sm:inline">{{ isDark ? '浅色' : '深色' }}</span>
  </button>
</template>
