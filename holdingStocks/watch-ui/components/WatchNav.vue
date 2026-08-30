<script setup lang="ts">
const route = useRoute()

function linkClass(path: string) {
  const active = route.path === path || (path !== '/' && route.path.startsWith(path))
  return active ? 'nav-link nav-link-active' : 'nav-link'
}
</script>

<template>
  <nav class="sticky top-0 z-30 border-b border-ui-hairline bg-ui-surface/90 backdrop-blur-md">
    <div class="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div class="flex flex-wrap items-center gap-1">
        <NuxtLink to="/" :class="linkClass('/')">持仓盯盘</NuxtLink>
        <NuxtLink to="/strategies" :class="linkClass('/strategies')">策略说明</NuxtLink>
        <NuxtLink to="/factors" :class="linkClass('/factors')">因子说明</NuxtLink>
      </div>
      <ThemeToggle />
    </div>
  </nav>
</template>
